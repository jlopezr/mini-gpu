# Casos compartidos CPU/GPU

Casos con `"architecture": ["cpu", "gpu"]`: **el mismo binario** y la misma
expectativa corren en las dos familias. Son la prueba de que el mapa MMIO
unificado es un contrato y no dos mapas parecidos: si la CPU y la GPU no
respondieran igual a las mismas escrituras, un caso fallaría en una de las dos.

| Grupo | Caso | Qué fija |
|---|---|---|
| `mmio` | [absent-load](mmio/absent-load/) | Leer un bloque sin dispositivo da error, no cero |
| `mmio` | [absent-store](mmio/absent-store/) | Escribirlo tampoco se descarta en silencio |
| `mmio` | [sysid-reserved](mmio/sysid-reserved/) | Un offset reservado dentro de un bloque que sí existe es error |
| `mmio` | [sysid-write](mmio/sysid-write/) | Las siete palabras de `SYSTEM` son de solo lectura |
| `video` | [double-buffer](video/double-buffer/) | El contrato de doble buffer, igual en CPU y GPU |
| `video` | [fb-desalineada](video/fb-desalineada/) | Una base de framebuffer desalineada es error, no se trunca |
| `compare` | [slt-sltu](compare/slt-sltu/) | `SLT` y `SLTU` sobre dieciséis pares de borde |
| `alu-extended` | [mulhi-div-rem](alu-extended/mulhi-div-rem/) | `MULHI`, `DIV`, `DIVU`, `REM` y `REMU`, con `-2^31 / -1` y divisores por encima de 2^31 |
| `alu-extended` | `divu-by-zero`, `rem-by-zero`, `remu-by-zero` | Dividir entre cero para con `0x04` |
| `calls` | [call-return](calls/call-return/) | `JAL`, `JALR` y `JR`, incluido `Rd = Ra` y un destino con los bits bajos sucios |

Como la GPU reparte trabajo con `GETTID` entre 64 hilos y eso no existe en la CPU,
los casos usan un `warps.json` con **un solo hilo activo** (`active_mask: 1`): así
no hace falta ninguna guarda dentro del programa y el código es literalmente el
mismo.
