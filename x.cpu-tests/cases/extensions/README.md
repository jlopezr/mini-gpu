# Extensiones de ISA posteriores a la v0.1

Los otros cuatro grupos de `cases/` prueban instrucciones que tiene **todo**
backend de CPU. Este prueba las extensiones que solo existen en algunos, y por
eso todos sus casos llevan `requires`:

| Subgrupo | Capacidad | Qué añade | Desde |
|---|---|---|---|
| [calls](calls/) | `calls` | `JAL`, `JALR`, `JR` (`0x2C–0x2E`) | 19 |
| [subword](subword/) | `subword_memory` | `LOADB`…`STOREH` (`0x18–0x1D`) | 19 |
| [serial](serial/) | `serial` | Puerto serie en `0x80000200` | 19 |
| [shift-immediate](shift-immediate/) | `shift_immediate` | `SHLI`, `SHRI`, `SARI` | 21 |
| [alu-extended](alu-extended/) | `alu_extended` | `MULHI`, `DIVU`, `REM`, `REMU` (`0x0B`, `0x0D–0x0F`) | 21 |
| [zero-register](zero-register/) | `zero_register` | `R0` cableado a cero | 21 |

Todas siguen el mapa de [`propuesta-v0.2.md`](../../../1.isa/propuesta-v0.2.md),
no el de la v0.3. Las tiene el simulador funcional; los bitstreams son
[`19.fpga-cpu-hdmi-ls`](../../../19.fpga-cpu-hdmi-ls/) (`--version subword`)
para las tres primeras y
[`21.fpga-cpu-hdmi-alu`](../../../21.fpga-cpu-hdmi-alu/) (`--version alu`) para
todas.

El `requires` no es decorativo. Sin él, estos casos no fallarían con un
diagnóstico útil en un bitstream anterior: pararían con **error `0x01`, opcode
inválido**, que es exactamente lo que produce un opcode mal ensamblado o un
salto a datos. Un `SKIP` dice «aquí no está implementado»; un `0x01` deja al que
lo lee preguntándose si ha roto el ensamblador.

Por qué una capacidad por extensión y no una sola: son independientes. El
backport a las versiones anteriores, si llega, no tiene por qué traerlas todas a
la vez, y un bitstream con una sola debe poder decirlo.

## Dos capacidades que no encajan en el molde

`shift_immediate` y `zero_register` rompen cada una una suposición distinta del
párrafo anterior, y conviene saberlo antes de escribir un caso nuevo.

**`shift_immediate` no se detecta por `0x01`.** No añade opcodes: es el bit 10
de `SHL`/`SHR`/`SAR`. En un bitstream sin ella ese bit sigue siendo reservado y
el programa para con **`0x05`, encoding inválido**, que es lo que produce un
ensamblador roto. El `SKIP` ahorra exactamente esa confusión.

**`zero_register` no es aditiva, es incompatible.** Un programa que use `R0`
como registro general no para con error en un backend sin ella: **da otro
resultado, en silencio**. Es la única capacidad de la lista de la que eso se
puede decir, y es la razón de que la 21 suba la versión del monitor aunque no
toque el protocolo.

## Lo que no tiene capacidad, y por qué

El camino rápido de `MULHI`/`REM`/`REMU` de la 21 **no tiene capacidad**. No es
un olvido: es invisible para la arquitectura. Acierto y fallo dan el mismo
número y solo cambian los ciclos, que el diferencial ya excluye. Un caso no
puede depender de algo que no puede observar.

Lo que sí existe es
[alu-extended/fast-path-sequences](alu-extended/fast-path-sequences/), que fija
el resultado correcto de las secuencias en las que el atajo **no** debe
acertar. No comprueba ciclos —no puede—; comprueba que los números son los que
serían sin atajo, y por eso vale igual contra el simulador, que no lo modela.

