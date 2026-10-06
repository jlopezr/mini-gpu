# Extensiones de ISA en la GPU

Casos de las extensiones de `1.isa` que la GPU implementa de forma opcional y
que cada caso declara en `requires`: un RTL que no las tiene los omite en vez de
fallar con un error de opcode.

| Grupo | Caso | Capacidad | Qué fija |
|---|---|---|---|
| `gpu-ids` | [getid-family](gpu-ids/getid-family/) | `gpu_ids` | `GETTID`, `GETLANE`, `GETWARP`, `GETLWARP` y `GETARG`, con `warp_size = 4` (solo simulador) |
| `gpu-ids` | [getid-8warps](gpu-ids/getid-8warps/) | `gpu_ids` | Lo mismo con 8 lanes y cuatro warps no contiguos; **diferencial de RTL** |
| `gpu-ids` | [getid-reserved-type](gpu-ids/getid-reserved-type/) | `gpu_ids` | Un `type` mayor que 4 es `ERROR_INVALID_ENCODING` |
| `subword` | [lane-bytes-halves](subword/lane-bytes-halves/) | `subword_memory` | Los seis accesos de 8 y 16 bits con 64 hilos y varias lanes por palabra; **diferencial de RTL** |
| `subword` | [misaligned-halfword](subword/misaligned-halfword/) | `subword_memory` | Una media palabra impar es un fallo; un byte impar no |
| `subword` | [mmio-byte](subword/mmio-byte/) | `subword_memory` | Un acceso de 8 bits a MMIO es un fallo (`mmio.md` §4.1) |

Los dos de fallo de memoria declaran `fault.address`, que el monitor no expone,
así que la placa los omite; los cubre el banco directo de la LSU
(`29.fpga-gpu-sm-pipeline/gpu_lsu2_tb.v`).
