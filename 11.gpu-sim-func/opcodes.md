# Extensiones ISA para ejecución GPU/SIMT

La GPU comparte la ISA base con la CPU. Las instrucciones aritméticas, lógicas, de memoria y de salto existentes se reutilizan sin cambios.

La ejecución GPU añade inicialmente tres instrucciones específicas para soportar el modelo SIMT:

- `SSY` — preparación de un punto de reconvergencia.
- `BAR` — barrera de sincronización.
- `EXIT` — finalización de los threads activos.

## Estado SIMT del warp

Cada warp contiene 8 threads (lanes) y mantiene, como mínimo:

```text
PC
active_mask
live_mask
state
SIMT_stack
```

Donde:

- `PC`: dirección de la siguiente instrucción del warp.
- `active_mask`: lanes que están ejecutando actualmente.
- `live_mask`: lanes que todavía no han ejecutado `EXIT`.
- `state`: estado actual del warp (`READY`, `WAIT_MEM`, `WAIT_MUL`, `WAIT_DIV`, `WAIT_BAR`, etc.).
- `SIMT_stack`: pila utilizada para gestionar divergencia y reconvergencia.

Una entrada de la pila SIMT contiene:

```text
reconv_pc
pending_pc
pending_mask
```

---

# `SSY` — Set Synchronization Point

## Objetivo

`SSY` indica el punto en el que deben reconverger los caminos de un branch potencialmente divergente.

```asm
SSY join
```

Por sí misma no realiza ningún salto ni modifica las máscaras.

Conceptualmente:

```text
reconv_pc = join
```

El siguiente branch divergente puede utilizar este valor para crear una entrada en la pila SIMT.

## Ejemplo

```asm
        SSY join
        BLT r1, r2, then

else:
        ADD r3, r3, 1
        BRA join

then:
        SUB r3, r3, 1

join:
        MUL r4, r4, r5
```

Supongamos:

```text
active_mask = 11111111

taken_mask       = 00001111
fallthrough_mask = 11110000
```

Al detectar divergencia, el hardware puede ejecutar un camino y guardar el otro:

```text
SIMT_stack.push {
    reconv_pc   = join
    pending_pc  = then
    pending_mask= 00001111
}
```

mientras continúa, por ejemplo, por el fall-through:

```text
PC          = PC + 1
active_mask = 11110000
```

Cuando el PC alcanza `join`, el hardware detecta:

```text
PC == SIMT_stack.top.reconv_pc
```

y ejecuta el camino pendiente antes de continuar desde `join` con las lanes reconvergidas.

## Branch sin `SSY`

Los branches existentes siguen siendo válidos sin `SSY`.

Si el branch es uniforme:

```text
taken_mask == 0
```

o:

```text
taken_mask == active_mask
```

no existe divergencia y no hace falta ninguna operación SIMT especial.

La política inicial propuesta es que un branch que resulte divergente sin un `SSY` válido produzca un error/trap GPU, salvo que posteriormente se defina otra semántica.

---

# `BAR` — Barrier

## Objetivo

`BAR` sincroniza los warps pertenecientes al mismo workgroup.

```asm
BAR
```

Cuando un warp llega a `BAR`:

```text
warp.state = WAIT_BAR
```

El scheduler deja de seleccionarlo.

Cuando todos los warps participantes del workgroup han llegado a la misma barrera:

```text
WAIT_BAR → READY
```

y pueden continuar su ejecución.

## Restricción de convergencia

En la primera implementación, `BAR` solo es válido cuando todas las lanes vivas del warp están convergidas:

```text
active_mask == live_mask
```

Ejemplo válido:

```text
live_mask   = 11111111
active_mask = 11111111

BAR → OK
```

Ejemplo inválido:

```text
live_mask   = 11111111
active_mask = 00001111

BAR → GPU exception
```

Esto evita tener que implementar barreras a nivel de lane y evita situaciones de deadlock provocadas por divergencia.

Una barrera pertenece al **workgroup**, no al SM completo ni a toda la GPU.

---

# `EXIT` — Finalización de threads

## Objetivo

`EXIT` finaliza las lanes que están activas en ese momento.

```asm
EXIT
```

Conceptualmente:

```text
live_mask = live_mask & ~active_mask
```

Ejemplo:

```text
live_mask   = 11111111
active_mask = 00001111
```

Después de `EXIT`:

```text
live_mask = 11110000
```

Las lanes 0–3 dejan definitivamente de participar en la ejecución del warp.

Cualquier máscara recuperada posteriormente de la pila SIMT debe filtrarse mediante `live_mask`:

```text
active_mask = pending_mask & live_mask
```

De esta forma una lane que haya ejecutado `EXIT` nunca puede reactivarse accidentalmente durante una reconvergencia.

Cuando:

```text
live_mask == 0
```

el warp ha terminado completamente y su slot residente puede liberarse.

---

# Resumen

| Opcode | Función                                                                 | Ámbito    |
|--------|-------------------------------------------------------------------------|-----------|
| `SSY`  | Define el PC de reconvergencia para un branch potencialmente divergente | Warp      |
| `BAR`  | Espera hasta que los warps del workgroup alcancen la barrera            | Workgroup |
| `EXIT` | Finaliza las lanes actualmente activas                                  | Lane/warp |

Estas instrucciones complementan las instrucciones normales de la ISA:

```text
ADD / SUB / MUL / MULFX / DIV / ...
LOAD / STORE
BLT / BGE / BEQ / BRA / ...
```

Las instrucciones normales se ejecutan simultáneamente sobre todas las lanes indicadas por `active_mask`.

Por tanto, la extensión GPU inicial de la ISA se limita a:

```text
ISA base CPU
    +
SSY
BAR
EXIT
```

mientras que la divergencia de los branches existentes se gestiona mediante `active_mask`, `live_mask` y la pila SIMT.
## Concreción en el simulador funcional

| Instrucción | Opcode (bits 31:26) | Bits 25:0                              |
|-------------|---------------------|----------------------------------------|
| SSY         | `0x31`              | offset signed26 en palabras desde PC+4 |
| BAR         | `0x32`              | cero                                   |
| EXIT        | `0x33`              | cero                                   |

Los PC son direcciones de bytes: avanzar una instrucción suma 4. El destino de
SSY debe estar dentro de memoria. Los campos reservados no nulos producen el
error de codificación existente (`0x05`).

SSY abre una entrada de pila que guarda también la máscara de entrada y si ya
se utilizó para una divergencia. Los saltos uniformes no consumen esta entrada.
La siguiente divergencia utiliza esa entrada y ejecuta primero el fall-through.
Cada divergencia adicional necesita su propio SSY, incluso dentro de un bucle.
Se admiten entradas anidadas. Al alcanzar el destino, antes de ejecutar su
instrucción, se ejecuta el camino pendiente y después se restaura la máscara
inicial filtrada por live_mask. Si EXIT vacía el camino activo, se hace la misma
transición sin esperar a alcanzar el destino. Las reconvergencias no cuentan
como instrucciones. Los programas deben usar regiones estructuradas: no saltar
fuera de una región sin pasar por su reconvergencia, salvo para finalizar lanes.

Una divergencia sin entrada disponible produce el fallo GPU `0x06`, sin commit.
HALT conserva la finalización de las lanes activas y se comporta como EXIT.

BAR identifica una barrera por `(PC, generación)` dentro de `workgroup_id`.
Cuenta una instrucción al llegar, conserva el PC mientras espera y avanza al
liberarse. Solo participan warps lanzados que aún tienen lanes vivas; un warp
terminado deja de participar. Todos usan workgroup 0 por defecto. La generación
se incrementa al liberar cada barrera, permitiendo repetirla en bucles.
Un BAR divergente o distinto del que esperan otros warps del mismo workgroup
produce `0x07` sin commit. Si otro warp sigue ejecutando sin llegar a BAR, se
aplica el límite normal de instrucciones del simulador.
