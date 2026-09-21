# Migración de la 12 a MMIO v2

El diseño está en [la bitácora de la 17](../../17.fpga-gpu-ram-v2/docs/migracion-v2.md)
y el resultado del atajo de copiar, en [la de la 14](../../14.fpga-gpu-ram/docs/migracion-v2.md).
Aquí va sólo lo que esta carpeta tiene de distinto, que es más de lo que el
encargo suponía.

## El atajo de copiar NO sirve aquí, y el encargo decía lo contrario a medias

El encargo dice de la 12: «su `gpu_system.v` difiere por la memoria. **Nada de
MMIO**». Eso es cierto de `gpu_system.v` y **sólo** de `gpu_system.v`.

Medido antes de tocar nada, de los diez ficheros que la migración toca:

| | 14 vs 17 | 12 vs 14 |
|---|---:|---:|
| idénticos antes de migrar | **6 de 10** | **1 de 10** (`sysid.v`) |

Los otros nueve difieren, y no por MMIO: difieren porque **128 KiB de EBR no
son 32 MiB de SDRAM**, y ese número aparece en los bancos, en los tests, en las
ventanas del monitor y en las regiones del host. Diferencias pequeñas —entre 1
y 25 líneas cada una— pero suficientes para que copiar el fichero entero
destruya lo específico de la carpeta.

O sea que la 12 se migró **fichero a fichero, aplicando los mismos cambios**, no
copiando. Costó lo que la 17, menos el diseño.

> «Difiere sólo por la memoria» y «se puede copiar» no son la misma frase. El
> tamaño de la memoria está cableado en nueve sitios de esta carpeta. `[TODAS]`

Aun así **pasó a la primera**: `./tools/test --prototype 12`, nueve bancos y 7
tests Python, sin una corrección. El diseño ya estaba resuelto.

## El hallazgo: `MMIO_MEM_SIZE_EBR` no describe a esta carpeta

Al declarar `MEM_SIZE` del bloque SYSTEM (§5.5) hubo que mirar cuánta memoria
tiene la 12 de verdad. Y el contrato y el hardware no dicen lo mismo:

| Fuente | Tamaño |
|---|---|
| `top.v` de la 12 (`RAM_END`) | `0x0002_0000` = **128 KiB** |
| `monitor.py` de la 12 (`ARCHITECTURAL_REGIONS`) | **128 KiB** |
| `1.isa/mmio_map.vh`, `MMIO_MEM_SIZE_EBR` | `0x0000_8000` = **32 KiB** |
| `1.isa/mmio.md` §3.1, «Prototipos con EBR» | `0000_0000 - 0000_7FFF`, **32 KiB** |

No es que el RTL esté mal: el `6.fpga-cpu` sí tiene 32 KiB, y esa constante es
suya. Lo que está mal es el **alcance** de §3.1, que generaliza a «los
prototipos sin SDRAM» a partir de un único caso. Hay dos prototipos sin SDRAM
—la 6 y la 12— y tienen memorias distintas, una cuádruple de la otra.

**Aquí se declara la verdad**, `MEM_SIZE = 0x0002_0000`, porque para eso existe
el registro; y hay un caso nuevo en `gpu_mmio_error_tb.v` que lo comprueba y
dice por qué. Lo que **no** se ha hecho es añadir una constante al mapa v2:
está congelado y eso es una decisión de contrato, no de migración.

> Una constante llamada `_EBR` parece describir una tecnología y describe una
> carpeta. Antes de usar una constante del mapa como si fuera universal,
> comprueba contra cuántos prototipos se escribió. `[TODAS]`

**Queda pendiente**, y es para quien cierre el contrato: o §3.1 admite dos
tamaños de EBR, o `MMIO_MEM_SIZE_EBR` se renombra a algo que diga de quién es.

## El caso negativo que había que mover para que siguiera siendo negativo

`test_transfer_boundaries` comprobaba que `0x80000000` **no** es ninguna
ventana, con este comentario:

> «0x80000000 ya no es ninguna ventana — la primera página queda para
> periféricos compartidos, que la 12 no tiene.»

En v2 `0x80000000` **es** el bloque SYSTEM. Si se deja tal cual, el test no
falla: deja de probar nada y pasa por el motivo equivocado. Se cambió el caso a
`0x82000000` (GPU CORE, no implementado), que es la forma actual de «una
dirección que este bitstream rechaza».

Es exactamente el aviso de la ronda de la familia CPU —«un control negativo
anclado en un caso real caduca cuando el caso real se arregla»— con el mapa en
vez de una capacidad. Y la contramedida también: lo que se ancla es la
**forma** («un bloque ausente»), no el número.

## Temporización: tres de tres, y el crítico ni se inmuta

| | Fmax | Margen | Camino crítico |
|---|---:|---:|---|
| 12 v1 | 33,93 | +35,7 % | `gpu.sm.push_index[0]` → `gpu.sm.top_index[1]` |
| **12 v2** | **35,06** | **+40,2 %** | `gpu.sm.push_index[0]` → `gpu.sm.top_index[1]` |

**El mismo camino, red por red.** Y con el resto de la familia:

| | v1 | v2 | Δ | Dónde está el crítico |
|---|---:|---:|---:|---|
| 12 | 33,93 | 35,06 | **+3,3 %** | pila de reconvergencia (`gpu.sm`) |
| 14 | 31,15 | 34,25 | **+10,0 %** | LSU (`gpu.lsu.pending` → `pick`) |
| 17 | 46,73 | 44,83 | **−4,1 %** | LSU (`gpu.lsu.req_mask` → `lsu_mask`) |

Tres carpetas, tres deltas con dos signos, y **el camino crítico nunca se
mueve**. MMIO no aparece en ninguno de los seis informes. El lazo estructural
de la 16 no existe en esta familia, y la razón está explicada en la bitácora de
la 17: la máquina de estados de `gpu_system.v` no mira nunca la respuesta del
dispositivo para decidir a dónde va.

La 12 es además la única cuyo crítico **no** está en la LSU sino en la pila de
reconvergencia SIMT, lo cual encaja: sin SDRAM detrás, la LSU no es el cuello.

## Verificación

- `./tools/test --prototype 12`: nueve bancos RTL y 7 tests Python, a la
  primera.
- `sysid.v` de la 12 ya es byte a byte el de las seis de CPU. **Queda una** en
  el grupo de v1: la 22.
- Semilla: no se fija, y se conserva el párrafo que lo argumenta.
