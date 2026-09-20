# Migración de la 18 a MMIO v2

Log de trabajo, escrito **durante** la migración. El orden de las secciones es
el orden real, no el del plan.

Contrato de referencia: [`../../1.isa/mmio.md`](../../1.isa/mmio.md).

**Este fichero es el tercero y sólo escribe la diferencia.** Los dos anteriores
son [la bitácora de la 21](../../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md) —el
camino completo— y [la de la 19](../../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md)
—la que mide lo que cuesta cada trozo—. No se repite aquí nada que ya digan.

**Alcance de cada decisión**, con la misma marca que las otras dos:

- `[TODAS]` vale para las diez carpetas.
- `[CPU]` vale para la familia CPU (6, 10, 16, 18, 19, 21).
- `[18]` es específico de esta carpeta.

---

## Fase 0 — Verificación del punto de partida

El encargo se declara a sí mismo una hipótesis y pide verificar cada dato antes
de actuar sobre él. Se hizo, **sin modificar nada**. La estructura del encargo
se sostiene y el atajo es real; lo que no cuadra son cinco cosas, y dos de ellas
cambian el estado del repo, no sólo el plan.

### Los números base

| Comando | Resultado | ¿Lo que decía el encargo? |
|---|---|---|
| `tools/test --prototype 18` | **SUCCESS**, 42,13 s, 21 bancos | sí, clavado |
| `tools/lint --prototype 18` | **40 `%Warning-PINMISSING`, 0 de anchura** (exit 1) | sí, y el reparto es de un solo tipo |
| `run_tests.py --backend cpusim` | 53 casos, 0 fallos, 34 omitidos, 17,3 s | — |
| `unittest` de `x.tests` | **278 OK** | — |
| `unittest` de `1.isa` / `2.cpu-sim-func` / `11.gpu-sim-func` | 61 / 44 / 62 OK | — |
| `check-links.py` | 628 enlaces en 180 `.md`, ninguno roto | — |
| `generate-mmio --check` | al día, los cuatro destinos | — |
| `generate-docs --check` | **ROJO** (ver abajo) | **no**: se daba por al día |
| `test_top_wiring.py` | 6 tests OK | sí, verde con la deuda anotada |

El número a no empeorar es **40 PINMISSING / 0 de anchura**, mirando el reparto
por tipo.

### El inventario se confirma entero

- **8 `.asm`** en `examples/`, y **6 tocan MMIO**: los que no son
  `fpga_smoke_test.asm` ni `perf_loop.asm`. Exacto.
- **21 bancos** `*_tb.v`. Exacto.
- `apio.ini`: semilla **4**, `default-testbench = cpu_sdram_system_tb.v`. Exacto.
- `video_registers.v` implementa **siete** registros —índices 0 a 6, o sea
  bitmap `0x7f`— así que el `VIDEO_REGISTERS(64'h7f)` de `top.v:555` es
  **correcto hoy**. Exacto.
- `monitor.py:39` tiene `MONITOR_REGIONS` con **una sola** ventana,
  `(0x8000_0000, 0x8000_1000)`. Exacto.
- Los siete ficheros generados de la raíz están los siete, y **no existe
  `fullframe_tb.asm`**. Exacto.
- `video_registers.v:241` usa `>=` con el comentario que lo declara defensa
  deliberada. **La corrección que el encargo le hace al log de la 21 es
  correcta**: no hay ningún bug de `==` que arreglar aquí.

### El atajo es real, y medido con `git hash-object`

Seis de los ocho ficheros RTL de MMIO de la 18 son byte a byte idénticos a los
de la 19 **en `HEAD`**, o sea antes de migrarla:

| Fichero | 18 == 19 pre-migración |
|---|---|
| `mmio_decoder.v`, `mmio_mux.v`, `sysid.v` | **sí** |
| `video_registers.v`, `cpu_perf_counters.v`, `monitor_mem_adapter_128.v` | **sí** |
| `cpu_dmem_adapter.v`, `top.v` | no |

Se copian ya migrados. Confirmado también que `monitor.v` es idéntico en 18, 19
y 21 **hoy**, o sea que la migración no lo ha tocado en ninguna.

### Lo que no cuadró

**1. El árbol no está limpio: la 19 y la 21 están migradas pero SIN COMMITEAR.**
`git status --porcelain` da **109 ficheros modificados**:

| Carpeta | Ficheros |
|---|---:|
| `21.fpga-cpu-hdmi-alu` | 35 |
| `19.fpga-cpu-hdmi-ls` | 33 |
| `x.tests` | 23 |
| `tools` | 8 |
| resto (`1.isa`, `11.gpu-sim-func`, `18`, `2.cpu-sim-func`, `20.forth`, `25`, `docs`, `TODO.md`) | 10 |

O sea que `HEAD` es el árbol **pre-migración de todo**, y las dos bitácoras
anteriores describen trabajo que sólo existe en el directorio de trabajo. Tiene
una consecuencia práctica inmediata y una de riesgo:

- **Práctica, y a favor:** `git ls-tree HEAD 19.../fichero` da gratis la versión
  **pre-migración** de la 19, que es justo contra lo que hay que comparar la 18
  para decidir si un fichero es copiable. Sin eso habría que fiarse del diff de
  texto, que engaña por los finales de línea (el repo es CRLF en disco y LF en
  el índice: `git diff` lo avisa en cada invocación).
- **De riesgo:** tres migraciones sin un solo punto de restauración. Si algo de
  esta tercera rompe una pieza compartida —y toca `x.tests`, `tools` y `1.isa`,
  que es donde vive todo lo compartido— no hay a dónde volver que no se lleve
  por delante las otras dos. `[TODAS]`

**2. `generate-docs --check` está rojo antes de tocar nada**, y dice que
cambiarían `docs/synthesis-report.md` y `docs/resumen-prototipos.md`. No es
cosmético: lo que la regeneración escribiría es esto.

```text
-| 21.fpga-cpu-hdmi-alu | build | $glbnet$sdram_clk... | 89.67 / 80.00 | PASS |
+| 21.fpga-cpu-hdmi-alu | build | $glbnet$sdram_clk... | 79.90 / 80.00 | FAIL |
```

**3. La 21 SÍ se ha sintetizado desde su migración, y no cumple.** El encargo
dice que la 19 y la 21 «están sin sintetizar desde su migración»; para la 19 es
cierto, para la 21 no. `reports/20260920-101323-955327-build` es de hoy a las
08:13 UTC, `exit_code: 1`:

```text
nextpnr-ecp5 ... --seed 13
Max frequency for clock '$glbnet$sdram_clk$TRELLIS_IO_OUT': 79.90 MHz (FAIL at 80.00 MHz)
```

Es exactamente lo que la bitácora de la 19 predijo —«la semilla 13 ya no vale»—
sólo que ya está medido: **se queda un 0,1 % corta**. Y el `resumen-prototipos.md`
también registraría la subida de área de la 21, de 10 867/5 066 a **11 590/5 236**
LUT/FF, que es un 6,7 % más de LUT por la migración.

> Un `--check` de documentación generada no compara texto contra texto: compara
> texto contra **el estado real del árbol de builds**. Que se ponga rojo sin que
> nadie toque un `.md` significa que alguien sintetizó, no que alguien editó.
> `[TODAS]`

No se ha regenerado. Los dos ficheros se dejaron exactamente como estaban
—`docs/synthesis-report.md` sin modificar, `docs/resumen-prototipos.md` con la
única modificación que ya traía— porque la decisión de anotar en la
documentación un barrido fallido del 0,1 % no es de esta fase.

**4. «11 bancos idénticos» son 10.** La lista de los **once que difieren** es
correcta, clavada y sin sobrantes; lo que está mal es la otra mitad de la
cuenta, porque 21 = 10 + 11. Los diez copiables son `instruction_buffer_tb`,
`memory_fabric_tb`, `mmio_monitor_tb`, `sdram_controller_128_tb`,
`sdram_controller_tb`, `sdram_system_adapter_tb`, `video_burst_tb`,
`video_frame_tb`, `video_mode_switch_tb` y `video_scanout_tb`. **Ningún banco es
exclusivo de la 18.**

**5. `perf_probe_tb.v` no es «copia idéntica» en las tres carpetas.** Lo dice el
comentario de `DEUDA_EN_BANCOS` en `test_top_wiring.py:313` y lo repite el
encargo. El de la 18 tiene **ocho líneas menos** que el de la 19 y el de la 21,
y son ocho líneas de **comentario**: el bloque que explica que este banco monta
`sdram_system_adapter` a propósito, porque su cifra de 145,9 ciclos por palabra
es la línea base contra la que se mide el camino de ráfagas.

La sustancia de la deuda se sostiene —el desajuste es el mismo y es ajeno a
MMIO, y las líneas `179/180/195` frente a `187/188/203` cuadran exactamente con
el desfase de ocho—, así que las tres entradas de la 18 se quedan como dice el
encargo. Lo que hay que corregir es la palabra «idéntica» del comentario, que
invita a copiar un fichero que perdería esa explicación. Es la trampa que la 19
documentó con `monitor_tb.v`, en pequeño. `[TODAS]`

### Y el «trozo ciego» no es el que dice el encargo `[18]`

El encargo dedica un apartado a que «`sdram_system_adapter.v` sigue en su
`top.v`» y que la 19 lo sacó. **`sdram_system_adapter` no está instanciado en
ningún `top.v`**, ni en el de la 18, ni en el de la 19, ni en el de la 21. En
los tres aparece dos veces y las dos son comentarios, idénticos, explicando que
era el bloque único de la 16. El propio `apio.ini` de la 19 lo dice con todas
las letras: «el bloque unico de la 16, **que ya no esta en top.v**».

Lo que la 19 sí hizo, y la 18 no, es **cambiar su banco por defecto**:

```ini
# 19/apio.ini
# El banco por defecto tiene que montar el camino que se sintetiza. Era
# cpu_sdram_system_tb.v, que monta `sdram_system_adapter` [...] y cuya ventana
# MMIO es de 16 bytes en vez de 32. `apio sim` sin argumentos ensenaba el
# diseno anterior.
default-testbench = cpu_burst_system_tb.v
```

La 18 sigue con `cpu_sdram_system_tb.v` por defecto.

O sea que hay un trozo ciego, pero es **otro**, y es más pequeño y más concreto:

| | 18 | 19 | 21 |
|---|---|---|---|
| Instancia `sdram_system_adapter` en `top.v` | no | no | no |
| Bancos que lo instancian | **5** | 4 | 4 |
| El de más | **`cpu_video_tb.v`** | — | — |
| `default-testbench` | `cpu_sdram_system_tb.v` | `cpu_burst_system_tb.v` | — |

El único fichero que de verdad ejercita ese camino en la 18 y no en las otras
dos es **`cpu_video_tb.v`**, que además está en la lista de los once que
difieren. Y `sdram_system_adapter_tb.v` es de los **idénticos**, así que su
versión ya migrada de la 19 sirve: el encargo le atribuye «9 apariciones de
direcciones MMIO» y las que tiene son **cinco líneas con `0x8000`, de las cuales
sólo tres son direcciones** (`32'h8000_0004`, `32'h8000_0006`, `32'h8000_0007`);
las otras dos son comentarios.

> Dos logs seguidos dan por hecho que la 18 monta en `top.v` un bloque que no
> monta, y el encargo lo hereda. La comprobación cuesta un `Select-String`. Un
> dato que viaja de bitácora en bitácora sin volver a medirse **envejece igual
> que el código**, y es más difícil de auditar porque suena a conclusión.
> `[TODAS]`

### Estado

Verificación hecha, **nada modificado**. Ni RTL, ni `.asm`, ni tests, ni
documentación generada. La semilla 4 de `apio.ini` sigue siendo válida porque no
se ha tocado un bit.

### Las dos decisiones que cerraron la fase

Consultadas, porque ninguna era mía:

1. **Checkpoint commiteado** (`5fc229f`), con las migraciones de la 19 y la 21
   tal cual estaban. Ahora hay a dónde volver.
2. **Documentación generada regenerada**, o sea que el FAIL de temporización de
   la 21 queda escrito en `docs/synthesis-report.md` y su área nueva en
   `docs/resumen-prototipos.md`. El barrido de semillas no se paga aquí.

Comprobado que `generate-docs` sólo tocó lo que hay entre los marcadores
`BEGIN/END GENERATED` —las líneas 46 y 48, dentro de `cpu-matrix`—; el resto del
diff de `resumen-prototipos.md` ya venía de la migración de la 19. Tras esto,
`generate-docs --check` sale **verde**, que es la línea base real a partir de la
cual se mide si la 18 empeora algo.

---

## Fase 1 — los seis programas, que fueron una copia `[18]`

El encargo estima este paso como «los `.asm`, contra `mmio_v1.inc` primero, sin
mover ninguna dirección», y la 19 lo midió en media hora. **Aquí fueron seis
copias y una sustitución de una palabra**, y es el hallazgo barato de esta
migración.

### La guarda primero, y saltó como debía

Antes de tocar un `.asm` se añadió `18.fpga-cpu-hdmi-bl8/examples` a `CARPETAS`
en `test_mmio_map.py`. Falló al instante nombrando **los seis ficheros**, ni uno
más ni uno menos, lo que confirma de paso el inventario de la fase 0:

```text
18\examples\fullframe.asm:34:       MOVHI R20, 0x8000
18\examples\swap_demo.asm:32:       MOVHI R20, 0x8000   ; registros de video en 0x80000000
18\examples\swap_demo_fast.asm:55:  MOVHI R20, 0x8000
18\examples\swap_smoke.asm:21:      MOVHI R20, 0x8000
18\examples\tear_demo.asm:32:       MOVHI R20, 0x8000
18\examples\tear_demo_fast.asm:50:  MOVHI R20, 0x8000
```

Es todavía **más homogéneo que la 19**: una sola base (`R20`), un solo
dispositivo (VIDEO) y cuatro offsets (`0`, `4`, `8`, `24`). Ni un programa toca
SERIAL, PERF ni SYSID — lo cual encaja con que la 18 no tiene puerto serie
(`HAS_SERIAL(0)` en su `top.v`).

### El atajo llega más lejos de lo que dice el encargo

El encargo aplica el atajo de la copia a seis ficheros RTL. Medido, **también
cubre los `.asm`: los ocho de `examples/` son byte a byte idénticos a los de la
19 antes de migrarla**, incluidos los dos que no tocan MMIO. Y esos dos la 19 no
los tocó, así que la 18 tampoco.

O sea que la migración de los seis no fue una edición sino **copiar la versión
ya migrada de la 19 y cambiarle `mmio.inc` por `mmio_v1.inc`**, para quedarse en
el punto intermedio que la fase 1 de la 19 existía para construir.

La comprobación de la 19 —«compara en las dos direcciones antes de copiar»— aquí
sale gratis: si los ficheros eran **byte a byte idénticos** antes, no hay nada
propio de la 18 que la copia pueda borrar. Es el único caso en el que copiar no
necesita más justificación que el hash.

> Antes de estimar el coste de los `.asm` de una carpeta, compara sus
> `examples/` con los de una carpeta ya migrada **en el commit anterior a su
> migración**. Si salen idénticos, el paso entero es un `Copy-Item`. Y los
> hashes hay que sacarlos de `git`, no de un diff de texto: este repo tiene LF
> en el índice y CRLF en disco, así que cualquier comparación textual miente en
> todas las líneas. `[TODAS]`

### Lo que la copia trajo de propina, y hay que quedárselo

`fullframe.asm` no creció +1 como los otros cinco, sino **+2**, y el verificador
lo cazó. No era un error: la 19, al arreglar su fixture, sacó además **las dos
bases del framebuffer** a `.equ` para que su `examples/fullframe.asm` y su
`fullframe_tb.asm` sólo se diferencien en ese bloque —que es justo lo que
`test_fullframe_fixture.py` exige—.

Eso llega a la 18 con la copia, y es deseable, porque la 18 va a necesitar su
propio `fullframe_tb.asm`. Pero deja el fichero **hablando de un hermano que
todavía no existe**: el comentario nuevo dice «la unica diferencia con
`../fullframe_tb.asm`». Queda pendiente para la fase de la fixture.

### La validación: el binario no puede cambiar

Cada programa se ensambló tres veces —el original, el migrado, y un «esperado»
construido del original fusionando cada `MOVHI`(+`ORI`) en el `LI` equivalente
**con el número cableado**— y se comparó **palabra a palabra**. Eso aísla la
simbolización del crecimiento de `LI`.

| Programa | Palabras | Crecimiento | Veredicto |
|---|---:|---:|---|
| `swap_demo_fast` | 75 | +1 | idéntico |
| `tear_demo_fast` | 62 | +1 | idéntico |
| `fullframe` | 57 | **+2** | idéntico |
| `swap_demo` | 42 | +1 | idéntico |
| `tear_demo` | 37 | +1 | idéntico |
| `swap_smoke` | 19 | +1 | idéntico |

La regla de la 21 se confirma por tercera vez: crecen los que cargaban la base
con un `MOVHI` suelto, que aquí son los seis. El `+2` de `fullframe` son la base
MMIO más la de `FB_FRONT`, que también iba en un `MOVHI` solo; la de `FB_BACK`
ya hacía `MOVHI` + `ORI` y no creció.

**Ningún caso de `x.tests` fija un `pc` contra estos programas**, igual que en la
19 y por la misma razón: ningún `test.json` apunta a los `examples` de la 18.

### El control negativo, y sale clavado el de la 19

| Mutación | Resultado | Palabras |
|---|---|---:|
| `SWAP` simbolizado como `FB_BACK` | **DIFIERE en 2 palabras** | 42 |
| base de VIDEO cambiada por la de SERIAL | **DIFIERE en 1 palabra** | 42 |

La columna que importa es la tercera: el programa sigue midiendo **42 palabras**
en los dos casos. Una comprobación de tamaño, o de `pc` final, habría pasado las
dos. El sustituidor lleva su propia guarda de «la mutación no aplicó», que es lo
que la 21 aprendió con los finales de línea.

### Lo que se rompió

Nada.

| Qué | Antes | Ahora |
|---|---|---|
| `unittest` de `x.tests` | 278 OK | **278 OK** (la guarda ya no salta) |
| `run_tests --backend cpusim` | 53 casos, 0 fallos | 53 casos, 0 fallos |

### Estado

**Sigue sin moverse ninguna dirección.** Los seis programas van por símbolo
contra el mapa de hoy. RTL sin tocar, semilla 4 válida.

### Coste

Diez minutos, y ocho de ellos en el verificador. La 19 lo midió en media hora y
avisaba de que su homogeneidad «no se repite»; se repitió, y más. **Este es el
trozo donde el encargo más sobreestima**, y la razón es concreta: la 18 y la 19
comparten los ocho `examples` byte a byte.

---

## Fase 2 — el RTL, que también fue casi todo copia `[18]`

### Los seis, copiados, y quedan byte a byte los de la 19 y la 21

Sin sorpresas. Tras la copia, `mmio_decoder.v`, `mmio_mux.v`, `sysid.v`,
`video_registers.v`, `cpu_perf_counters.v` y `monitor_mem_adapter_128.v` son
byte a byte los de las otras dos, que es el estado en el que el test de copias
los quiere.

### `cpu_dmem_adapter.v`: una línea propia, y no es de mapa

El diff con la versión pre-migración de la 19 es **un solo hunk**, y no tiene
nada que ver con MMIO:

```verilog
// 19 (con STOREB/LOADB)
wire address_in_sdram = ((dmem_address & ADDR_RANGE_MASK) == 32'd0);
// 18 (sin accesos sub-palabra)
wire address_in_sdram = ((dmem_address & ADDR_RANGE_MASK) == 32'd0) &&
                        (dmem_address[1:0] == 2'b00);
```

Así que se copió la versión migrada de la 19 y se restauró esa línea, con un
comentario que dice por qué está ahí. **La migración a v2 no la toca**: es una
diferencia de ISA, no de mapa, y conviene que quede escrito para que la próxima
copia no la borre por parecer un resto.

### `top.v`, y los cinco parámetros que hay que repasar uno a uno

La trampa 1 del encargo se aplicó tal cual. Los valores propios de la 18:

| Parámetro | Valor | Por qué no es el de la 19 |
|---|---|---|
| `FOLDER` | `8'd18` | — |
| `HAS_SERIAL` | **`0`** | la 18 no tiene puerto serie |
| `VIDEO_REGISTERS` | `64'h3ff` | era `0x7f`; diez registros en v2 |
| `ISA_PROFILE` | `32'h3` | MUL y DIV, sin subpalabra |
| `DEVICES` | **`32'h225`** | `0x235` **sin el bit 4**, que es SERIAL |
| `MEM_BASE`/`MEM_SIZE` | `0` / `0x0200_0000` | — |
| `MONITOR_VERSION` | **`32'h0312`** | 3.18, no 4.19 |

Y las ventanas del monitor son **tres**, no cuatro: SYSTEM, VIDEO y CPU PERF.
No hay ventana de SERIAL porque abrirla sólo dejaría pasar accesos que el
decodificador va a rechazar.

> La 18 es la **primera carpeta sin puerto serie** que se migra, y eso convierte
> `HAS_SERIAL` en una tercera cosa que hay que propagar a mano: al bit 4 de
> `DEVICES`, a la lista de ventanas del monitor, a `MONITOR_REGIONS` del host y
> al banco de errores. Ninguna de esas cuatro se deduce de las otras, y sólo dos
> tienen test. Las carpetas que quedan sin serie son la **6**, la **10** y las
> de GPU, así que esto se repite. `[TODAS]`

`MONITOR_VERSION` no se deduce de nada: es `(mayor << 8) | menor` con los mismos
números que el `monitor #(...)` de al lado, y aquí el monitor es **3.18**, no
4.19. Copiar el `0x0413` de la 19 habría hecho que el bloque SYSTEM declarara un
juego de comandos que esta carpeta no implementa, y ningún test lo habría dicho:
es un número perfectamente válido, exactamente como el `0x7f` del bitmap.

---

## Fase 3 — los bancos, y aquí sí se fue el tiempo

De los 21, **diez son copia directa** de la 19 ya migrada y once hubo que
mirarlos. El reparto real, que no es el que se esperaba:

| Qué se hizo | Bancos |
|---|---|
| Copia limpia de la 19 migrada | `video_fullframe_tb`, `video_registers_tb`, `write_combine_tb`, `video_mode_switch_tb` |
| Copia + parche de identidad | `cpu_mmio_error_tb`, `cpu_video_tb` |
| A mano | `cpu_burst_system_tb`, `monitor_tb` |
| **No tocados**, y es correcto | `cpu_sdram_system_tb`, `cpu_tb`, `perf_probe_tb`, `video_sdram_tb` y los seis restantes |

### El que faltaba en la lista del encargo `[18]`

`video_mode_switch_tb.v` está en el grupo de los **idénticos** —así que el
encargo no lo nombra— pero **la 19 sí lo migró**. Trabajar sólo desde la lista
de «los que difieren» se lo salta.

No lo cazó ningún test: lo cazó **el lint**, con dos `PINMISSING` de puertos
nuevos de `video_registers` sin conectar.

> Al migrar una carpeta, la lista de trabajo no es «los bancos que difieren de
> la gemela», es **la unión de ésos con los que la gemela tocó al migrar**. Un
> banco puede ser idéntico hoy y aun así necesitar el cambio. `[TODAS]`

### `cpu_video_tb.v`: el trozo ciego, y hubo que decidir

Es el único banco donde la 18 no se parece a nadie: 199 líneas contra 512, y
monta `sdram_system_adapter` —el bloque de la 16, con una ventana MMIO de
**dieciséis bytes** y una dirección de **cuatro bits**— en vez del camino que se
sintetiza.

Y no se podía migrar tal cual: **el bloque de vídeo de v2 llega hasta +0x24 y no
cabe en dieciséis bytes.** Las opciones eran ensanchar `sdram_system_adapter.v`
o cambiar de banco.

Se cambió de banco: ahora es el `cpu_video_tb.v` de la 19, con
`mmio_decoder #(.HAS_SERIAL(0))` y sin `serial_port` —fichero que esta carpeta
no tiene—. Las razones, en orden:

1. **`sdram_system_adapter.v` no está en ningún `top.v`.** Migrarlo sería migrar
   algo que no se sintetiza.
2. **`perf_probe_tb.v` prohíbe migrarlo**, y lo dice en su cabecera: su cifra de
   145,9 ciclos por palabra es la línea base contra la que se mide el camino de
   ráfagas, y migrarlo destruiría la comparación.
3. Es el mismo criterio que la 19 aplicó a su `default-testbench`: **el banco
   tiene que montar el camino que se sintetiza.**

Lo que se gana es cobertura que el banco viejo no tenía: `HALT_AT`, `HALT_TARGET`
y la parada sola de la CPU. Lo que se pierde es «la CPU contra el adaptador
viejo», que no es el diseño. `sdram_system_adapter_tb.v` sigue cubriendo el
adaptador en sí, y se queda en v1 como en la 19 y la 21.

**Queda una asimetría sin resolver, y es deuda anotada:** la 18 sigue teniendo
`default-testbench = cpu_sdram_system_tb.v`, que monta el adaptador viejo,
mientras la 19 lo cambió a `cpu_burst_system_tb.v` por esa misma razón. No se ha
tocado porque cambiar el banco por defecto no es parte de migrar el mapa, pero
está en la misma clase de problema.

### `cpu_burst_system_tb.v` y `monitor_tb.v`: a mano, y poco

El primero no monta decodificador —conecta `mmio_select` directo a
`video_registers`—, así que copiar el de la 19 habría traído un decodificador y
un `serial_port`. Se migró a mano: tres anchuras, los puertos `error`/`running`
nuevos, y los tres accesos del monitor de `0x8000_0000`/`0x8000_0008` a
`0x8020_0004`/`0x8020_000C`, el último además como palabra entera.

`monitor_tb.v` fueron **dos ediciones**: las ventanas y un comentario. Aquí la
lección de la 19 —comparar en las dos direcciones antes de copiar— se aplicó y
salvó lo mismo: su `monitor_tb.v` tiene 321 líneas y el de la 19, 567.

### Los cuatro que no se tocan, y por qué eso es una respuesta y no un olvido

`cpu_sdram_system_tb`, `cpu_tb`, `perf_probe_tb` y `video_sdram_tb` difieren de
la 19 pero **la 19 no los migró**. Sus direcciones `0x8000_xxxx` no son del mapa
nuevo: son del adaptador viejo (`sdram_system_adapter`), que sigue en v1 en las
tres carpetas. Lo mismo vale para `mmio_monitor_tb.v` y su `0x80000f00`.

> Que un banco contenga `0x8000_0000` no significa que esté sin migrar. En este
> repo conviven dos mapas a propósito: el de `top.v`, que es v2, y el del
> adaptador de la 16, que se queda en v1 porque mide el diseño anterior. **Antes
> de migrar una dirección, mira qué módulo la decodifica.** `[TODAS]`

---

## Fase 4 — los `.asm` a v2, la fixture y el lado host

### La línea por fichero, por fin

Con el RTL en v2, los seis programas pasaron de `mmio_v1.inc` a `mmio.inc`.
**Una línea por fichero**, que es exactamente lo que el andamio compra.

### La fixture: `fullframe_tb.asm` creado, y el `.hex` coincide con los otros dos

El banco ya migrado falló con «la CPU paró con error 05 en pc=00000004»: el
`fullframe.hex` versionado seguía siendo el de v1. Se aplicaron las tres piezas:
`fullframe_tb.asm` copiado de la 19 (los cuerpos son idénticos, sólo cambian las
dos `.equ`), el `.hex` regenerado **desde ahí** con la orden escrita en la
cabecera del banco, y el README corregido.

**El `.hex` regenerado sale byte a byte igual al de la 19 y al de la 21.** Es la
tercera migración independiente que converge al mismo fichero.

Y `test_fullframe_fixture.py` **descubrió sola la 18** en cuanto existió el trío,
sin tocar el test — que es exactamente lo que la 19 dijo que pasaría.

> Detalle de método: el ensamblador emite siempre un `.bin` junto al `--hex`, y
> ninguna de las tres carpetas lo versiona. Hay que borrarlo tras regenerar. `[TODAS]`

### El lado host, y son los dos últimos rojos otra vez

Exactamente como en la 19: los dos únicos fallos de `x.tests` al final fueron
`MONITOR_REGIONS` de `monitor.py`, que seguía con la ventana única. Lo cazaron
sus dos gemelas (`test_monitor_port` y `test_monitor_protocol`).

Tres regiones, no cuatro. Se escriben a mano y literales, por la razón que la 21
dejó anotada: `tools/prototype_report.py` lee esa asignación del **texto** del
fichero, y un `tuple(... for ...)` lo deja ciego.

---

## Lint: el único sitio donde la migración empeoró algo, y se arregló

La línea base eran **40 `PINMISSING` y 0 de anchura**. A mitad de camino salió
**43**, o sea peor, y el reparto por tipo fue lo que lo dijo — el total habría
servido igual aquí, pero por casualidad.

Para saber **cuáles** eran los nuevos se sacó el lint del punto de partida en un
worktree del checkpoint y se compararon las listas, no los números:

| | Aviso |
|---|---|
| nuevos | `video_fullframe_tb.v`: `error` y `running` sin conectar |
| desaparecido | `video_registers_tb.v`: `video_mode` |

Los dos nuevos venían del banco copiado, **byte a byte igual en las tres
carpetas**, así que arreglarlo en la 18 sola habría roto el test que exige que
sean idénticos. Se ataron `.error()` y `.running(1'b1)` **en las tres**.

Resultado: **39 `PINMISSING`, 0 de anchura**. Mejora sobre la base.

> Un aviso de lint que llega dentro de un fichero copiado no es tuyo, pero es
> tuyo arreglarlo, y hay que hacerlo **en todas las copias a la vez** o se rompe
> la invariante que hacía barata la copia. `[TODAS]`

Y un aviso de método que costó una pasada: el texto del comentario se insertó
con un here-string `@"..."@` de PowerShell, donde **el backtick es carácter de
escape**. `` `running`` se convirtió en un retorno de carro suelto dentro del
comentario, iverilog cortó ahí la línea y el resto pasó a ser código: «syntax
error» en una línea que a la vista era un comentario. Con `@'...'@` no pasa.

---

## Controles negativos

Se rompió la referencia a propósito tres veces, borrando `__pycache__` entre
pasadas, y las tres veces falló **el test que toca y por el motivo correcto**:

| Mutación | Qué falla | Qué dice |
|---|---|---|
| M1 `fullframe.hex` regenerado desde el programa de la **placa** | `test_el_hex_sale_del_fuente_del_banco` | nombra la carpeta y da la orden exacta |
| M2 `mmio_address` de `top.v` estrechada de 32 a 12 bits | `AnchosDePuertoTest` | `top.v:384: mmio_mux.address espera 32 bit(s) y recibe mmio_address de 12` |
| M3 `VIDEO_REGISTERS` devuelto a `0x7f` | `test_el_top_no_estrecha_el_bitmap_de_video` | «faltan los índices [7, 8, 9]; esos registros darán error de acceso en la placa aunque el RTL los tenga» |

Y los dos de la fase 1, sobre la simbolización, que salieron con el mismo número
de palabras que el original.

M2 y M3 son los dos fallos históricos de esta carpeta y de la 21 reproducidos a
propósito: los dos se cazan ahora en un test que tarda menos de un segundo.

---

## Verificación al cerrar

| Qué | Base | Ahora |
|---|---|---|
| `tools/test --prototype 18` | SUCCESS, 42 s, 21 bancos | **SUCCESS, 123 s**, 21 bancos |
| `tools/lint --prototype 18` | 40 PINMISSING, 0 anchura | **39 PINMISSING, 0 anchura** |
| `unittest` de `x.tests` | 278 OK | 278 OK |
| `run_tests --backend cpusim` | 53 casos, 0 fallos | 53 casos, 0 fallos |
| `unittest` de `1.isa` / `2.cpu-sim-func` / `11.gpu-sim-func` | 61 / 44 / 62 | 61 / 44 / 62 OK |
| `check-links` | 628 en 180 `.md` | 639 en 181, ninguno roto |
| `generate-mmio --check` | al día | al día |
| `generate-docs --check` | **rojo** | **al día** |
| `tools/test --prototype 19` | — | **SUCCESS, 127 s** |
| `tools/test --prototype 21` | — | **SUCCESS, 130 s** |

**No se ha sintetizado.** La semilla 4 de `apio.ini` está invalidada.

---

## Lo que esta migración le hizo a la 19 y a la 21

| Qué | Cómo apareció |
|---|---|
| **La 21 no cumple temporización**: 79,90 MHz contra 80,00 con la semilla 13, y 11 590/5 236 LUT/FF frente a 10 867/5 066 | `generate-docs --check` estaba rojo en la fase 0 |
| `video_fullframe_tb.v` deja `error` y `running` al aire en las tres carpetas | al comparar el lint contra el del checkpoint |
| El comentario de `DEUDA_EN_BANCOS` llama «copia idéntica» a `perf_probe_tb.v`, que no lo es | al verificar el encargo |
| Dos logs seguidos dan por hecho que la 18 monta `sdram_system_adapter` en su `top.v`, y no lo monta nadie | al verificar el encargo |
| Las migraciones de la 19 y la 21 estaban **sin commitear** | al ir a comparar contra `HEAD` |

Los dos primeros están arreglados; los tres siguientes, corregidos por escrito.
La 19 lo avisó: **la carpeta anterior no está terminada hasta que la siguiente
ha pasado por encima**, y esta vez lo que salió fue de placa otra vez.

---

## Qué salió más barato y qué más caro

**Más barato de lo estimado, y mucho:**

- **Los `.asm`.** Estimados como una fase; fueron un `Copy-Item`, porque los
  ocho son byte a byte los de la 19 pre-migración.
- **El RTL.** Los seis del atajo salieron limpios los seis, y
  `cpu_dmem_adapter.v` fue copia más una línea restaurada.
- **La fixture.** La 19 la describe como un rojo caro; aquí fue copiar un
  fichero y ejecutar una orden ya escrita, y el resultado coincidió byte a byte.

**Más caro de lo estimado:**

- **Los bancos**, que siguen siendo donde se va el tiempo, y por un motivo que
  el encargo no anticipa: el banco que había que rehacer no era uno de los que
  «difieren», era el que la 18 tiene distinto **de todas** (`cpu_video_tb`).
- **`HAS_SERIAL(0)`**, que no aparece en ninguno de los dos logs porque la 19 y
  la 21 tienen puerto serie. Toca cuatro sitios y sólo dos tienen test.
- **Lint**, por tener que medir el punto de partida en un worktree para saber
  qué avisos eran míos.
- **Verificar el encargo**, que devolvió cinco correcciones, dos de ellas de
  estado del repo.

**Lo que costó cero, y conviene decirlo:** el mapa de transición, el generador,
`.equ`, el test de anchuras, el de fixtures y los periféricos del simulador. Es
la mitad del trabajo de la 21 y no se ha vuelto a pagar.

---

## Qué cuesta la 17, corregido

La 19 dejó la estimación y sigue siendo buena en su estructura: **la 17 es otro
mapa, no una carpeta más pequeña**. Lo que esta migración añade:

1. **El atajo de copiar no le sirve.** Aquí fue la mitad del trabajo, y sólo
   funciona entre carpetas gemelas de la misma familia. La 17 no tiene
   `mmio_decoder.v`: decodifica *inline* en `gpu_system.v`. Lo único que se
   copia ya migrado es `sysid.v`.
2. **La regla nueva de la lista de trabajo sí le sirve**, y le sirve más: la
   unión de «los que difieren» con «los que la gemela tocó». En la 17, donde
   casi nada es gemelo, esa lista hay que construirla mirando **qué módulo
   decodifica cada dirección**, que es la otra regla de esta migración.
3. **Lo de `HAS_SERIAL(0)` se repite y se multiplica.** La 17 no tiene vídeo, ni
   serie, ni contadores de CPU, ni GPU CORE. O sea cuatro bloques ausentes en
   vez de uno, y por cada uno hay que propagar a mano el bit de `DEVICES`, la
   ventana del monitor, `MONITOR_REGIONS` y el banco de errores. **Ese es el
   trabajo de la 17 que ninguna de las tres bitácoras había medido todavía.**

Y sigue en pie lo que la 19 apuntó: `retired_count` intercalado entre los
registros SIMT, `mmio_map_v1.vh` sin un solo nombre de GPU, excluir `_build` al
añadir la 17 a la guarda, y los `0x80000000` de `gpu_control_tb.v` que son
codificaciones de instrucción y no direcciones.

---

## Fase 5 — pendiente: síntesis, barrido y placa

Nada de esto se ha pagado, y hace falta permiso explícito:

- **Barrido de semillas de las tres** (`build-sweep --seeds 1..8`). La 18 tiene
  la 4 invalidada, la 19 la suya, y la 21 **ya sabemos que la 13 no cumple**:
  79,90 MHz contra 80,00. O sea que el de la 21 no es precautorio.
- **Placa**, que es lo único que confirma dos cosas que ninguna simulación ve:
  que `HALT_TARGET` y `VIDEO_TX` responden de verdad, y que las **tres** ventanas
  del monitor de esta carpeta dejan pasar lo que deben.

### Deuda anotada y no pagada

- `default-testbench = cpu_sdram_system_tb.v` en el `apio.ini` de la 18 monta el
  adaptador viejo. La 19 lo cambió por esa razón; aquí no se ha tocado.
- Escrituras sub-palabra a MMIO (§4.1 y §16.2), que es la deuda que la 21 dejó
  y que hay que pagar en el host y en los bancos a la vez.
- Los tres desajustes de `perf_probe_tb.v` en `DEUDA_EN_BANCOS`, ajenos a MMIO y
  compartidos por las tres carpetas.
