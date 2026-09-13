# Extensiones de ISA posteriores a la v0.1

Los otros cuatro grupos de `cases/` prueban instrucciones que tiene **todo**
backend de CPU. Este prueba las dos extensiones que solo existen en algunos, y
por eso todos sus casos llevan `requires`:

| Subgrupo | Capacidad | Qué añade | Opcodes |
|---|---|---|---|
| [calls](calls/) | `calls` | `JAL`, `JALR`, `JR` | `0x2C–0x2E` |
| [subword](subword/) | `subword_memory` | `LOADB`, `LOADUB`, `STOREB`, `LOADH`, `LOADUH`, `STOREH` | `0x18–0x1D` |

Ambas siguen el mapa de [`propuesta-v0.2.md`](../../../1.isa/propuesta-v0.2.md),
no el de la v0.3. Las tiene el simulador funcional y el bitstream de
[`19.fpga-cpu-hdmi-ls`](../../../19.fpga-cpu-hdmi-ls/) (`--version subword`).

El `requires` no es decorativo. Sin él, estos casos no fallarían con un
diagnóstico útil en un bitstream anterior: pararían con **error `0x01`, opcode
inválido**, que es exactamente lo que produce un opcode mal ensamblado o un
salto a datos. Un `SKIP` dice «aquí no está implementado»; un `0x01` deja al que
lo lee preguntándose si ha roto el ensamblador.

Por qué dos capacidades y no una: son extensiones independientes. El backport a
las versiones anteriores, si llega, no tiene por qué traer las dos a la vez, y
un bitstream con una sola debe poder decirlo.
