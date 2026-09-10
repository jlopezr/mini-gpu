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

`SSY join` abre una región de reconvergencia, guardando el PC del SSY,
el join, la máscara activa de entrada y la profundidad de caminos pendientes.
Si el PC del SSY coincide con el de la región más interna, la reutiliza sin
reiniciar su máscara ni sus pendientes. Un destino distinto al guardado en
esa reutilización produce error SIMT.

Los branches uniformes no consumen la región. Varias divergencias pueden
compartirla. Una salida directa al join aparca sus lanes sin guardar PATH;
si ambos caminos tienen trabajo anterior al join, se guarda un PATH y se
ejecuta primero el fall-through.

El simulador implementa esta semántica con dos pilas independientes. El RTL
actual de `12.fpga-gpu` conserva la semántica anterior y todavía no es
conforme con esta revisión. Véase [el diseño](ssy-reusable-regions-design.md).

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

En este ejemplo ambos caminos tienen trabajo. El simulador guarda el tomado:

```text
path_stack.push {
    pending_pc  = then
    pending_mask= 00001111
}
```

mientras continúa, por ejemplo, por el fall-through:

```text
PC          = PC + 4
active_mask = 11110000
```

Cuando el PC alcanza `join`, el simulador detecta:

```text
PC == region_stack.top.join_pc
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

Un branch divergente sin región abierta produce el error GPU `0x06`, sin commit.

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

SSY abre o reutiliza la región más interna según su PC de apertura. Compartir
join con otro SSY no implica reutilización. Cada región admite varias
divergencias; no existe un indicador `used`.

El simulador mantiene `region_stack` y `path_stack`, con ocho posiciones cada
una por defecto. La API `System(..., simt_region_depth=8, simt_path_depth=8)`
permite dimensionarlas independientemente. Una REGION guarda `ssy_pc`,
`join_pc`, `entry_mask` y `path_base`; un PATH, `pending_pc` y `pending_mask`.

Antes de ejecutar el join, si quedan PATH por encima de `path_base`, se retira
el superior y se ejecuta. Si no quedan, se retira la REGION y se restaura
`entry_mask & live_mask`. Se repite para cierres coincidentes o máscaras vacías.
EXIT también activa esta normalización al vaciar el camino actual. Si no quedan
lanes vivas, se vacían ambas pilas y se conserva el PC siguiente de EXIT/HALT.
Las reconvergencias no cuentan como instrucciones.

Una reserva que exceda su capacidad produce `0x06` sin commit. Reutilizar una
región llena o salir directamente al join con la pila de caminos llena no
requiere reserva y sigue siendo válido. Los programas deben respetar cierres
estructurados: no saltarse una región interior para salir de una exterior,
salvo al finalizar las lanes. HALT de la ISA se comporta como EXIT.

BAR identifica una barrera por `(PC, generación)` dentro de `workgroup_id`.
Cuenta una instrucción al llegar, conserva el PC mientras espera y avanza al
liberarse. Solo participan warps lanzados que aún tienen lanes vivas; un warp
terminado deja de participar. Todos usan workgroup 0 por defecto. La generación
se incrementa al liberar cada barrera, permitiendo repetirla en bucles.
Un BAR divergente o distinto del que esperan otros warps del mismo workgroup
produce `0x07` sin commit. Si otro warp sigue ejecutando sin llegar a BAR, se
aplica el límite normal de instrucciones del simulador.
