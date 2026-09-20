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
