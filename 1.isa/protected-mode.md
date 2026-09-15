Sistema mínimo de privilegios, traps e interrupciones

1. Objetivo

El objetivo es extender la CPU con un mecanismo mínimo pero suficientemente general para soportar:

- ejecución separada de kernel y aplicaciones;
- excepciones;
- interrupciones;
- llamadas al sistema;
- temporizador y dispositivos externos;
- y, en el futuro, una MMU y memoria virtual.

La idea fundamental es disponer de un único mecanismo de trap. Una syscall, una instrucción ilegal, un page fault o una interrupción de timer son eventos distintos, pero todos provocan la misma transición controlada hacia el kernel.

Esto permite empezar con un sistema muy pequeño y ampliar posteriormente la arquitectura sin cambiar el mecanismo básico.

---

2. Modos de ejecución

Se definen inicialmente dos niveles de privilegio:

USER        Ejecución de aplicaciones
SUPERVISOR  Ejecución del kernel

Después de un reset:

MODE = SUPERVISOR

En modo "USER" no se permite:

- modificar los registros de control privilegiados;
- modificar la configuración de interrupciones;
- ejecutar "ERET";
- configurar la futura MMU;
- realizar otras operaciones reservadas al kernel.

El acceso a cualquiera de estas operaciones desde "USER" genera una excepción de instrucción privilegiada/ilegal.

No es necesario introducir más niveles de privilegio inicialmente.

---

3. El mecanismo de TRAP

Un trap es cualquier transferencia automática de control desde el código que se está ejecutando hacia el kernel debido a un evento excepcional.

Puede originarse por diferentes motivos:

                    TRAP
                      ▲
                      │
        ┌─────────────┼─────────────┐
        │             │             │
     software     excepción     interrupción
        │             │             │
      TRAP        illegal         timer
                  access          UART
                  page fault      GPU
                  ...

Todos utilizan el mismo mecanismo hardware.

Al producirse un trap, la CPU:

EPC     <- PC de retorno
CAUSE   <- causa
PMODE   <- MODE
PIE     <- IE

MODE    <- SUPERVISOR
IE      <- 0

PC      <- dirección del handler

La única diferencia entre los distintos eventos es la información almacenada en "CAUSE", "BADADDR" cuando corresponda, y el vector seleccionado.

---

4. Registros de sistema

Los registros de sistema se mantienen separados de los registros generales "R0..R31".

Una primera implementación podría contener:

STATUS
EPC
CAUSE
TVEC
BADADDR

Posteriormente pueden añadirse:

IRQ_PENDING
IRQ_ENABLE
PTBASE
TLB control
...

Conviene reservar desde el principio un espacio razonablemente grande para system registers.

Por ejemplo:

SR00    STATUS
SR01    EPC
SR02    CAUSE
SR03    TVEC
SR04    BADADDR

SR05... reservados

4.1 STATUS

Contiene el estado relacionado con privilegios e interrupciones.

Una implementación inicial podría tener:

bit 0   IE       Interrupt Enable
bit 1   PIE      Previous Interrupt Enable
bit 2   MODE     Current Mode
bit 3   PMODE    Previous Mode

"PIE" y "PMODE" permiten restaurar automáticamente el estado mediante "ERET".

4.2 EPC

"EPC" contiene el PC necesario para continuar la ejecución después del trap.

Su semántica debe estar claramente definida para cada excepción.

Por ejemplo:

Illegal instruction:

    EPC = PC de la instrucción ilegal


Access fault:

    EPC = PC de LOAD/STORE que falló


TRAP software:

    EPC = PC de la siguiente instrucción

Esto permite que "ERET" tenga una semántica sencilla:

PC <- EPC

4.3 CAUSE

Indica por qué se produjo el trap.

Puede utilizarse un bit para distinguir interrupciones de excepciones:

31      INTERRUPT
30:0    CAUSE

Por ejemplo:

0x00000000    software TRAP
0x00000001    illegal instruction
0x00000002    alignment fault
0x00000003    access fault

0x80000001    timer interrupt
0x80000002    external interrupt
...

Los valores concretos forman parte de la definición de la ISA y deben permanecer estables.

4.4 BADADDR

Contiene la dirección asociada a un fallo de memoria.

Por ejemplo:

LOAD R5, [R7 + 12]

si la dirección no es válida:

EPC     = PC del LOAD
CAUSE   = ACCESS_FAULT
BADADDR = R7 + 12

Aunque inicialmente no exista MMU, merece la pena incorporar "BADADDR", porque posteriormente puede utilizarse también para:

page fault
TLB miss
permission fault
alignment fault

4.5 TVEC

"TVEC" determina dónde comienza el código de tratamiento de traps.

Además de almacenar una dirección base, permite seleccionar entre dos modos:

DIRECT
VECTORED

Conceptualmente:

TVEC:

31........................2  1:0
+--------------------------+----+
|           BASE           |MODE|
+--------------------------+----+

Una posible codificación es:

MODE = 00    DIRECT
MODE = 01    VECTORED
MODE = 10    reservado
MODE = 11    reservado

La dirección base debe estar alineada según lo requerido por la arquitectura.

---

5. Modo DIRECT

En modo "DIRECT", todos los traps entran por la misma dirección:

PC <- TVEC.BASE

Por tanto:

            syscall
               │
        illegal instruction
               │
          page fault
               │
             timer
               │
              GPU
               │
               ▼
          +-----------+
          | TVEC.BASE |
          +-----------+
               │
               ▼
         leer CAUSE
               │
               ▼
           dispatch

El kernel consulta "CAUSE" y decide qué handler debe ejecutar.

Este modo resulta especialmente útil durante el desarrollo inicial porque requiere muy poco hardware y permite implementar un kernel muy sencillo.

---

6. Modo VECTORED

En modo "VECTORED", cada tipo de trap puede entrar directamente por una posición diferente:

PC <- TVEC.BASE + VECTOR * 4

Suponiendo instrucciones de 32 bits:

VECTOR 0  -> BASE + 0x00
VECTOR 1  -> BASE + 0x04
VECTOR 2  -> BASE + 0x08
VECTOR 3  -> BASE + 0x0C
...

La tabla puede contener instrucciones de salto:

vectors:

    BRA software_trap_handler
    BRA illegal_handler
    BRA alignment_handler
    BRA access_fault_handler
    BRA timer_handler
    BRA external_irq_handler

Por tanto, no es necesario que el hardware lea una tabla de punteros.

Simplemente calcula:

BASE + VECTOR * 4

y empieza a ejecutar allí.

El coste hardware adicional respecto al modo directo es pequeño:

DIRECT:

    trap_target = BASE


VECTORED:

    trap_target = BASE + (VECTOR << 2)

El desplazamiento "<< 2" es esencialmente cableado, por lo que la diferencia fundamental es un pequeño sumador/multiplexor en la selección del nuevo PC.

---

7. VECTOR y CAUSE

Aunque inicialmente podrían tener el mismo valor, conceptualmente conviene distinguir:

VECTOR
CAUSE

"VECTOR" responde a:

«¿A qué handler debo saltar?»

"CAUSE" responde a:

«¿Qué ha ocurrido exactamente?»

"VECTOR" ni siquiera necesita ser un registro visible. Puede ser una señal interna del controlador de traps.

Esto permite en el futuro tener, por ejemplo:

VECTOR = EXTERNAL_IRQ
CAUSE  = GPU_IRQ

De esta forma varias fuentes pueden compartir un vector sin perder información sobre la causa concreta.

También permite mantener pequeña la tabla de vectores.

---

8. Instrucciones de sistema

La extensión mínima de la ISA puede ser muy pequeña.

8.1 TRAP

Provoca voluntariamente una excepción síncrona.

TRAP

El hardware realiza la entrada normal de trap:

CAUSE = SOFTWARE_TRAP
EPC   = PC + tamaño_instrucción

guardar estado
MODE  = SUPERVISOR
IE    = 0

PC    = trap_target

Esta instrucción puede utilizarse para implementar system calls.

Por ejemplo, una ABI podría establecer:

R0    número de syscall
R1    argumento 0
R2    argumento 1
R3    argumento 2
R4    argumento 3

y:

TRAP

El kernel examina "R0" y realiza la operación correspondiente.

Por tanto, SYSCALL no necesita ser una instrucción diferente.

Una syscall es simplemente uno de los posibles usos de un "TRAP" software.

---

9. ERET

"ERET" retorna de una excepción o interrupción.

Conceptualmente:

PC   <- EPC
MODE <- PMODE
IE   <- PIE

Sólo puede ejecutarse en modo "SUPERVISOR".

Si se intenta ejecutar desde "USER", genera una excepción.

Esto proporciona una secuencia completa:

USER
 │
 │ timer IRQ
 ▼
TRAP
 │
 ├─ EPC   <- PC
 ├─ CAUSE <- TIMER
 ├─ PMODE <- USER
 ├─ MODE  <- SUPERVISOR
 └─ PC    <- handler
             │
             ▼
           kernel
             │
             ▼
            ERET
             │
             ├─ MODE <- USER
             └─ PC   <- EPC
                       │
                       ▼
                     USER

---

10. Acceso a registros de sistema

Se pueden introducir dos instrucciones genéricas:

MFSR Rd, SR
MTSR SR, Rs

Por ejemplo:

MFSR R4, CAUSE
MFSR R5, EPC

MTSR TVEC, R6

Esto evita dedicar opcodes diferentes a cada registro de control.

En general, "MTSR" debe ser privilegiada.

Para "MFSR" puede definirse individualmente qué registros son visibles desde "USER".

---

11. Interrupciones

Las interrupciones externas utilizan exactamente el mismo mecanismo de traps.

Por ejemplo:

Timer ───┐
UART ────┤
GPU ─────┤
         ▼
   IRQ controller
         │
         ▼
   trap controller
         │
         ├── EPC
         ├── CAUSE
         └── VECTOR
              │
              ▼
       DIRECT / VECTORED
              │
              ▼
             PC

Inicialmente puede existir simplemente:

IE = interrupt enable global

Posteriormente pueden añadirse:

IRQ_ENABLE
IRQ_PENDING

para habilitar/deshabilitar fuentes individualmente.

---

12. Excepciones precisas

Una característica especialmente importante para soportar un sistema operativo es que las excepciones sean precisas.

Supongamos:

I0    ADD
I1    LOAD       ; falla
I2    STORE
I3    ADD

Cuando "I1" genera una excepción:

I0    debe haber terminado

I1    no debe dejar efectos parciales

I2    no debe modificar memoria

I3    no debe modificar registros

y:

EPC = dirección de I1

El estado arquitectónico debe corresponder exactamente al momento anterior a ejecutar la instrucción que produjo el fallo.

En una CPU sencilla, escalar e in-order esto es relativamente manejable, pero debe tenerse en cuenta al diseñar el pipeline y especialmente la LSU y su interacción con el memory fabric.

---

13. Evolución hacia una MMU

Una ventaja importante de este diseño es que la futura MMU utiliza exactamente el mismo mecanismo.

Posteriormente pueden añadirse registros como:

PTBASE
MMU_CONTROL
TLB_CONTROL

y nuevas causas:

LOAD_PAGE_FAULT
STORE_PAGE_FAULT
EXEC_PAGE_FAULT
TLB_MISS
PERMISSION_FAULT

El flujo sigue siendo:

             LOAD
               │
               ▼
              MMU
               │
            ¿válido?
           /         \
         sí           no
         │             │
         ▼             ▼
      memoria        TRAP
                      │
                 ┌────┼─────┐
                 ▼    ▼     ▼
                EPC CAUSE BADADDR
                      │
                      ▼
              DIRECT/VECTORED
                      │
                      ▼
                    kernel

Por tanto, añadir la MMU no requiere rediseñar la arquitectura de excepciones.

---

14. ISA mínima propuesta

Las únicas instrucciones nuevas estrictamente necesarias para este subsistema serían:

TRAP

ERET

MFSR Rd, SR
MTSR SR, Rs

Los primeros registros de sistema serían:

STATUS
EPC
CAUSE
TVEC
BADADDR

Y existirían dos modos:

USER
SUPERVISOR

"TVEC" soportaría:

DIRECT
VECTORED

---

15. Orden de implementación recomendado

Una evolución razonable de la CPU sería:

1. USER / SUPERVISOR

2. Registros:
      STATUS
      EPC
      CAUSE
      TVEC
      BADADDR

3. Entrada común de TRAP

4. TRAP software

5. ERET

6. MFSR / MTSR

7. TVEC DIRECT

8. Excepciones:
      illegal instruction
      privileged instruction
      alignment/access fault

9. Interrupción de timer

10. Interrupciones externas

11. TVEC VECTORED

12. Kernel mínimo + syscalls

13. Scheduler / multitarea

14. MMU + TLB

15. Memoria virtual / procesos

Esto permite validar cada etapa independientemente.

---

16. Resumen de arquitectura

El resultado final de esta primera extensión sería:

                    CPU
                     │
          ┌──────────┴──────────┐
          │                     │
        USER               SUPERVISOR
          │                     │
          └──────────┬──────────┘
                     │
               ejecución normal
                     │
         ┌───────────┼────────────┐
         │           │            │
       TRAP       excepción      IRQ
         │           │            │
         └───────────┼────────────┘
                     ▼
              TRAP CONTROLLER
                     │
            ┌────────┼─────────┐
            ▼        ▼         ▼
           EPC     CAUSE    BADADDR
                     │
                     ▼
                    TVEC
                     │
              ┌──────┴──────┐
              │             │
           DIRECT        VECTORED
              │             │
            BASE      BASE + VECTOR*4
              │             │
              └──────┬──────┘
                     ▼
                   kernel
                     │
                    ERET
                     │
                     ▼
             programa anterior

La característica fundamental es que syscalls, excepciones, interrupciones y futuros fallos de MMU no son mecanismos diferentes.

Todos son distintas causas de un mismo mecanismo arquitectónico de trap.

Esto mantiene pequeña la ISA, simplifica el hardware y proporciona una base suficientemente extensible para evolucionar desde ejecución bare-metal hacia un sistema operativo con separación user/kernel, multitarea y, posteriormente, memoria virtual.
