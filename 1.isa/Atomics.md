Atómicas y sincronización de memoria

Este documento propone tres instrucciones para soportar acceso concurrente a memoria entre CPU, GPU y otros posibles masters del sistema:

- "ATOMADD"
- "ATOMCAS"
- "FENCE"

Las operaciones atómicas se implementan en el subsistema de memoria compartido (memory fabric), ya que es el punto donde convergen los accesos de CPU, GPU y otros masters.

"FENCE", en cambio, es principalmente una operación del LSU/master que garantiza el orden y finalización de sus propias operaciones de memoria.

---

1. ATOMADD

Semántica

"ATOMADD" realiza atómicamente:

old = *addr;
*addr = old + value;
return old;

La lectura, suma y escritura forman una única operación indivisible respecto a otros accesos atómicos o conflictivos al mismo espacio de memoria.

Conceptualmente:

ATOMADD Rd, [Ra + imm], Rb

donde:

- "Ra + imm" determina la dirección.
- "Rb" contiene el valor que se suma.
- "Rd" recibe el valor que tenía la memoria antes de la suma.

Ejemplo

Si inicialmente:

counter = 10

CPU y GPU ejecutan simultáneamente:

CPU: ATOMADD counter, 1
GPU: ATOMADD counter, 1

el sistema serializa ambas operaciones:

CPU: 10 -> 11    devuelve 10
GPU: 11 -> 12    devuelve 11

o en el orden contrario.

En ambos casos:

counter = 12

No puede ocurrir el caso típico de un "LOAD" + "ADD" + "STORE" normal donde ambos agentes leen "10" y terminan escribiendo "11".

Usos

"ATOMADD" resulta especialmente útil para:

- Contadores compartidos.
- Reservar posiciones en una cola o array.
- Contabilizar resultados producidos por threads.
- Asignar identificadores únicos.
- Acumulaciones simples.

---

2. ATOMCAS

"ATOMCAS" (Atomic Compare-And-Swap) proporciona una primitiva atómica más general.

Semántica

Conceptualmente:

old = *addr;

if (old == expected)
    *addr = desired;

return old;

Toda la secuencia es indivisible.

Una posible representación sería:

ATOMCAS Rd, [Ra + imm], Rexpected, Rdesired

El encoding exacto deberá definirse teniendo en cuenta que la instrucción necesita:

- Dirección.
- Valor esperado.
- Nuevo valor.
- Registro donde devolver el valor anterior.

Ejemplo

Inicialmente:

lock = 0

Dos agentes intentan:

CAS(&lock, 0, 1)

El primero podría ejecutar:

READ lock       -> 0
COMPARE 0 == 0  -> true
WRITE lock      -> 1
RETURN          -> 0

El segundo encontraría:

READ lock       -> 1
COMPARE 1 == 0  -> false
NO WRITE
RETURN          -> 1

Por tanto, solamente uno consigue realizar la transición:

0 -> 1

Usos

"ATOMCAS" permite construir por software primitivas más complejas:

- Locks.
- Flags.
- Máquinas de estados concurrentes.
- Colas compartidas.
- Asignación condicional de recursos.
- Otras operaciones atómicas mediante bucles CAS.

CAS se considera atómico por definición en esta ISA. No se contempla una variante "CAS" no atómica.

---

3. Implementación de las operaciones atómicas

La atomicidad debe garantizarse en el punto donde convergen los distintos agentes:

CPU LSU --------+
                |
GPU LSU --------+---- Memory Fabric ---- Memory
                |
DMA ------------+

No es suficiente bloquear únicamente la LSU de la CPU o de la GPU, ya que otro master podría acceder a la memoria durante una operación read-modify-write.

Implementación inicial

Una implementación sencilla puede conceder acceso exclusivo al memory fabric durante toda la operación.

Para "ATOMADD":

acquire
   |
 READ
   |
  ADD
   |
 WRITE
   |
response
   |
release

Para "ATOMCAS":

acquire
   |
 READ
   |
COMPARE
   |
   +---- equal ----> WRITE desired
   |
   +---- different -> no write
   |
response old value
   |
release

Mientras una operación atómica está activa, los demás masters esperan.

Esta implementación bloquea inicialmente todo el acceso a la memoria durante la operación atómica. Es sencilla y garantiza correctamente la atomicidad.

Una implementación futura podría permitir accesos simultáneos a direcciones independientes.

Lógica en el Memory Fabric

El memory fabric puede implementar directamente las operaciones necesarias:

ATOMADD : sumador de 32 bits
ATOMCAS : comparador de 32 bits + selección de escritura

De esta forma CPU y GPU utilizan exactamente el mismo mecanismo de atomicidad y no necesitan implementar independientemente el read-modify-write.

---

4. FENCE

"FENCE" no es una operación atómica y no modifica memoria.

Su objetivo es establecer un punto de orden y finalización para los accesos de memoria del master que lo ejecuta.

Por ejemplo:

STORE [COMMAND_X],      R1
STORE [COMMAND_Y],      R2
STORE [COMMAND_BUFFER], R3

FENCE

STORE [READY],          R4

La intención es garantizar que las escrituras anteriores al "FENCE" se hayan completado antes de permitir que el master continúe con las operaciones posteriores.

Conceptualmente:

STORE X --------+
STORE Y --------+---- operaciones anteriores
STORE BUFFER ---+
                 |
               FENCE
                 |
                 v
           esperar hasta
         que hayan terminado
                 |
                 v
           STORE READY

Esto permite utilizar "READY", por ejemplo, como señal para indicar a otro agente que una estructura compartida ya está preparada.

Implementación

"FENCE" es principalmente responsabilidad del LSU/master.

Una implementación puede esperar hasta que:

outstanding_requests == 0
store_queue == empty
LSU / memory transactions completed

El memory fabric debe proporcionar las señales de finalización necesarias, pero no tiene por qué recibir una operación "FENCE" explícita.

---

5. FENCE en la implementación actual

Si una CPU es completamente bloqueante y cada "LOAD" o "STORE" termina únicamente cuando la operación de memoria se ha completado, el orden ya es:

STORE A -> completa
STORE B -> completa
FENCE
STORE C -> completa

En esta microarquitectura no existen operaciones pendientes cuando se alcanza "FENCE".

Por tanto, inicialmente:

FENCE = NOP

puede ser una implementación válida.

La instrucción sigue siendo útil a nivel de ISA porque permite introducir posteriormente:

- Write buffers.
- FIFOs.
- Cachés.
- Bursts.
- Varias operaciones de memoria pendientes.
- CPU y GPU concurrentes.
- DMA.

sin modificar el software existente.

---

6. Diferencia entre BAR y FENCE

"BAR" y "FENCE" resuelven problemas diferentes.

BAR

Sincroniza threads de un grupo/warp según el modelo de ejecución de la GPU.

Conceptualmente:

thread 0 ----+
thread 1 ----+
thread 2 ----+---- BAR ----> continúan
...          |
thread N ----+

Todos los threads participantes deben alcanzar la barrera antes de continuar.

FENCE

Ordena/finaliza operaciones de memoria de un master:

memory operations
       |
     FENCE
       |
later memory operations

Por tanto:

BAR   = sincronización entre threads
FENCE = orden/visibilidad de memoria

Una barrera no convierte accesos normales conflictivos en operaciones atómicas.

---

7. Stores normales con conflictos

Los "STORE" normales no proporcionan atomicidad.

Si diferentes lanes escriben simultáneamente valores diferentes sobre la misma dirección:

lane 0 -> [A] = 10
lane 1 -> [A] = 20
lane 2 -> [A] = 30

el software no debe depender de cuál de esos valores termina almacenado.

La ISA puede definir el resultado como no especificado.

Esto evita obligar al hardware a mantener un orden concreto entre lanes.

Cuando el programa necesite una modificación concurrente definida deberá utilizar una operación atómica.

---

8. Propuesta inicial para la ISA

Reservar:

ATOMADD
ATOMCAS
FENCE

con operaciones atómicas inicialmente limitadas a palabras de 32 bits.

Semántica propuesta:

ATOMADD:
    old = MEM32[address]
    MEM32[address] = old + value
    Rd = old

ATOMCAS:
    old = MEM32[address]

    if old == expected:
        MEM32[address] = desired

    Rd = old

FENCE:
    esperar a que las operaciones de memoria
    anteriores del master hayan completado antes
    de permitir operaciones posteriores

No es necesario añadir inicialmente:

ATOMAND
ATOMOR
ATOMXOR
ATOMMIN
ATOMMAX
ATOMXCHG

Estas operaciones pueden incorporarse posteriormente si aparecen casos de uso que justifiquen nuevos opcodes.

"ATOMCAS" proporciona la primitiva general, mientras que "ATOMADD" cubre eficientemente uno de los patrones concurrentes más habituales.
