# Espacio de direcciones por versión

Documento transversal: compara qué direcciones existen, quién las valida y con
qué límites, en cada backend que `x.cpu-tests/run_gpu_tests.py` sabe ejecutar.

Las seis combinaciones de `--backend` / `--version`:

| Backend         | Versión   | Implementación                                                   |   Memoria arquitectónica | MMIO                        |
|-----------------|-----------|------------------------------------------------------------------|-------------------------:|-----------------------------|
| `cpu-simulator` | `current` | [2.cpu-sim-func/minicpu_sim.py](2.cpu-sim-func/minicpu_sim.py)   |         32 MiB continuos | —                           |
| `cpu-fpga`      | `ebr`     | [6.fpga-cpu/](6.fpga-cpu/)                                       | 2 × 16 KiB, no contiguos | —                           |
| `cpu-fpga`      | `sdram`   | [10.fpga-cpu-ram/](10.fpga-cpu-ram/)                             |         32 MiB continuos | —                           |
| `gpu-simulator` | `current` | [11.gpu-sim-func/minigpu_sim.py](11.gpu-sim-func/minigpu_sim.py) |         32 MiB continuos | —                           |
| `gpu-fpga`      | `bram`    | [12.fpga-gpu/](12.fpga-gpu/)                                     |        128 KiB continuos | 2 ventanas en `0x8000_xxxx` |
| `gpu-fpga`      | `sdram`   | [14.fpga-gpu-ram/](14.fpga-gpu-ram/)                             |         32 MiB continuos | 2 ventanas en `0x8000_xxxx` |

---

## 1. `cpu-simulator` — 32 MiB planos

```
0x00000000 ┌──────────────────────────────┐
           │  memoria (bytearray)         │  32 MiB
0x01FFFFFF └──────────────────────────────┘
0x02000000    fuera de rango → ERROR_MEMORY_ACCESS (0x02)
```

- El tamaño lo fija el backend, no el simulador:
  `memory_size = 32 * 1024 * 1024` en [simulator.py:15](x.cpu-tests/backends/simulator.py#L15).
- No hay huecos, ni bancos, ni MMIO. Todo el rango es legible y escribible, y el
  fetch puede ejecutar desde cualquier palabra alineada.
- La única comprobación es `address + 4 > len(memory)` o desalineación.

## 2. `cpu-fpga --version ebr` — dos bancos de 16 KiB con un hueco enorme

```
0x00000000 ┌──────────────────────────────┐
           │  EBR 0  (16 KiB)             │  convención: programa
0x00003FFF └──────────────────────────────┘
             ·········  hueco: error de bus  ·········
0x00100000 ┌──────────────────────────────┐
           │  EBR 1  (16 KiB)             │  convención: datos
0x00103FFF └──────────────────────────────┘
0x00104000    resto → error de bus
```

Es el único mapa **no contiguo** del repositorio. Detalles que importan:

- Los puertos `imem` y `dmem` alcanzan los dos bancos, así que un `LOAD` puede
  leer código y el fetch puede ejecutar desde el EBR 1. La separación
  programa/datos es convención, no hardware ([6.fpga-cpu/README.md:17](6.fpga-cpu/README.md#L17)).
- El cliente valida contra `MEMORY_REGIONS` con las dos regiones
  ([6.fpga-cpu/monitor.py:18-21](6.fpga-cpu/monitor.py#L18-L21)).
- El RTL valida algo **distinto y más débil**: solo que el bloque no cruce el
  límite de 16 KiB dentro de su banco, mirando `mem_address[13:0]`
  ([6.fpga-cpu/monitor.v:412](6.fpga-cpu/monitor.v#L412)). La existencia del
  banco la reporta la memoria como error de bus, no el validador.
- Es la **versión por defecto** de `cpu-fpga` (`DEFAULT_VERSION = "ebr"`).

## 3. `cpu-fpga --version sdram` — 32 MiB unificados

```
0x00000000 ┌──────────────────────────────┐
           │                              │  convención: programa
0x00100000 │  SDRAM  (32 MiB)             │  convención: datos
0x01000000 │                              │  convención: gráficos
0x01FFFFFF └──────────────────────────────┘
0x02000000    fuera de rango → rechazo
```

- Un solo espacio físico para `imem`, `dmem` y monitor, sin bases ni selección
  implícita de mitad ([10.fpga-cpu-ram/README.md:12](10.fpga-cpu-ram/README.md#L12)).
- Las tres zonas de la convención (programa / datos / gráficos) **no las impone
  el hardware**: son solo el reparto acordado.
- Cliente y RTL coinciden: `0x0200_0000` exclusivo en
  [monitor.py:19](10.fpga-cpu-ram/monitor.py#L19) y en
  [monitor.v:446](10.fpga-cpu-ram/monitor.v#L446).
- Accesos alineados a 4 bytes; cada palabra de CPU son dos operaciones SDRAM
  BL1 de 16 bits en little-endian.

## 4. `gpu-simulator` — 32 MiB planos, sin MMIO

```
0x00000000 ┌──────────────────────────────┐
           │  memoria compartida (32 MiB) │  todos los warps y lanes
0x01FFFFFF └──────────────────────────────┘
```

- `System(memory_size = 32 * 1024 * 1024, ...)` por defecto
  ([minigpu_sim.py:191](11.gpu-sim-func/minigpu_sim.py#L191)).
- **No existe ventana MMIO.** El PC, la máscara y el `workgroup_id` de cada
  warp son atributos de objetos Python; `configure_warps()` los escribe
  directamente y las observaciones del runner se leen del modelo.
- Esa es la diferencia estructural con `gpu-fpga`: en la FPGA ese mismo estado
  solo es alcanzable a través de direcciones MMIO.

## 5. `gpu-fpga` — memoria + dos ventanas MMIO

Los únicos mapas con espacio no arquitectónico. Las dos versiones comparten
comandos y ventanas MMIO; solo cambia el tamaño y la tecnología de la memoria:

| Versión | Memoria         | Monitor |
|---------|----------------:|---------|
| `bram`  | 128 KiB de BRAM | 2.1     |
| `sdram` | 32 MiB de SDRAM | 2.2     |

La versión del monitor es lo único que distingue los dos bitstreams por UART, y
por eso 14 responde **2.2** aunque no añada ningún comando: sin esa diferencia
`ensure_bitstream()` aceptaría uno creyendo que es el otro. Es la misma
convención que separa 1.5 de 1.6 en las dos revisiones de CPU.

### 5.1 Memoria arquitectónica

```
           bram                              sdram
0x00000000 ┌──────────────────┐   0x00000000 ┌──────────────────┐
           │  BRAM  (128 KiB) │              │  SDRAM  (32 MiB) │
0x0001FFFF └──────────────────┘   0x01FFFFFF └──────────────────┘
0x00020000   → ERROR_MEMORY_ACCESS 0x02000000   → ERROR_MEMORY_ACCESS
```

Compartida por los ocho warps, para código y datos. En `sdram` cada palabra son
dos accesos BL1 de 16 bits, sin caché ni coalescencia, así que el mismo caso
tarda más que en BRAM pero observa exactamente el mismo estado.

### 5.2 Ventana MMIO — solo monitor, solo con la GPU parada

Idéntica en las dos versiones. No forma parte de la memoria de la ISA: un
`LOAD`/`STORE` del programa no la ve. Palabras little-endian en el bus, pero la
dirección del comando UART va en big-endian
([monitor.py:132](12.fpga-gpu/monitor.py#L132)).

**Bloque A — configuración por warp, `0x80000000`–`0x8000007F`**
(16 bytes × 8 warps; `cfg_region` en [gpu_system.v:40](12.fpga-gpu/gpu_system.v#L40))

| Dirección           | Contenido                                                            | Acceso |
|---------------------|----------------------------------------------------------------------|--------|
| `0x80000000 + 16*w` | PC del warp                                                          | R/W    |
| `0x80000004 + 16*w` | `active[7:0]`, `live[15:8]`; escribir el byte bajo fija ambas        | R/W    |
| `0x80000008 + 16*w` | `workgroup_id`                                                       | R/W    |
| `0x8000000c + 16*w` | regiones `[7:0]`, caminos `[15:8]`, WAIT_MEM bit 16, WAIT_BAR bit 17 | R      |

Escribir en este bloque borra ambas pilas SIMT y el estado de barrera del warp,
y pone a cero su contador local.

**Bloque B — depuración global, `0x80000100`–`0x80000117`**
(`case` en [gpu_system.v:102-110](12.fpga-gpu/gpu_system.v#L102-L110))

| Dirección    | Contenido                                                        | Acceso |
|--------------|------------------------------------------------------------------|--------|
| `0x80000100` | Selección de contexto: `lane[2:0]`, `warp[5:3]`                  | R/W    |
| `0x80000104` | Slots LSU ocupados `[7:0]`                                       | R      |
| `0x80000108` | Instrucciones retiradas, contador global de 32 bits              | R      |
| `0x8000010c` | `lane[2:0]`, `warp[5:3]`, `lane_valid` bit 6, `error_code[15:8]` | R      |
| `0x80000110` | PC del primer error                                              | R      |
| `0x80000114` | Instrucciones retiradas del warp seleccionado en `0x80000100`    | R      |

`0x80000100` gobierna tanto la lectura de `0x80000114` como el comando
`READ_REG`, que devuelve los 32 registros del lane seleccionado. Cualquier otra
palabra dentro de `0x80000` activa `mmio_bad`.

---

## Comparativa rápida

Las columnas `ebr`/`sdram` son versiones de `cpu-fpga`; `bram`/`sdram` de
`gpu-fpga`.

|                       | cpu-sim |        ebr |  sdram | gpu-sim |          bram |     gpu sdram |
|-----------------------|--------:|-----------:|-------:|--------:|--------------:|--------------:|
| Tamaño arquitectónico |  32 MiB | 2 × 16 KiB | 32 MiB |  32 MiB |       128 KiB |        32 MiB |
| Contiguo              |      sí |     **no** |     sí |      sí |            sí |            sí |
| MMIO                  |       — |          — |      — |       — | `0x8000_0000` | `0x8000_0000` |
| Alineación a 4 bytes  |      sí |         sí |     sí |      sí |            sí |            sí |
| Límite de bloque UART |       — |      256 B |  256 B |       — |         256 B |         256 B |
| Monitor               |       — |        1.6 |    1.5 |       — |           2.1 |           2.2 |

---

## Dónde se valida cada rango

Un acceso pasa por cuatro filtros, cada uno con su responsabilidad:

1. **El caso de test** — [`load_case()`](x.cpu-tests/run_gpu_tests.py#L314)
   comprueba solo que el caso sea coherente consigo mismo y quepa en
   `ARCHITECTURAL_MEMORY_SIZE` (32 MiB). No sabe a qué backend va.
2. **El backend** — `incompatibility(case, version)` rechaza el caso contra el
   mapa concreto de esa versión, antes de abrir el puerto o cargar el
   bitstream. Lo publican [`fpga`](x.cpu-tests/backends/fpga.py#L40) y
   [`gpu_fpga`](x.cpu-tests/backends/gpu_fpga.py#L50); los simuladores no lo
   necesitan.
3. **El cliente del monitor** — `MEMORY_REGIONS` + `validate_transfer()` /
   `validate_block()` en cada `monitor.py`.
4. **El RTL** — `block_range_valid` o equivalente en cada `monitor.v`, más el
   decodificador de bus.

Los niveles 2 y 3 comparten fuente: **el mapa lo declara `ARCHITECTURAL_REGIONS`
en el `monitor.py` de cada versión**, que es quien lo implementa, y el backend lo
lee de ahí en vez de repetirlo. Por eso la comprobación es una lista de regiones
y no un tamaño: con `ebr`, un límite escalar no podría expresar el hueco.

### Desajustes corregidos

Los tres venían de escribir la misma verdad en varios sitios:

- **La ventana B se cortaba en `0x8000_0114`** en vez de `0x8000_0118` en el
  RTL, dejando fuera el último registro documentado. El cliente lo permitía y la
  FPGA respondía `RSP_ERROR`; se veía solo en casos con
  `expect.warps[*].instructions_executed`. Corregido en
  [monitor.v:151](12.fpga-gpu/monitor.v#L151) — **requiere re-sintetizar el
  bitstream**.
- **`cpu-fpga` no comprobaba rangos antes de hablar con la placa.** Ahora
  `fpga.incompatibility()` valida contra los bancos reales, así que un caso
  `ebr` con datos en `0x4000` o `0x200000` se rechaza en validación y con
  nombre, no contra el hardware.
- **El tope de 16 KiB para el programa CPU era global**, y se aplicaba también a
  `cpu-simulator` y a `sdram`, que tienen 32 MiB. `FPGA_MEMORY_SIZE` ya no
  existe: ese límite lo pone ahora el backend que corresponda.
