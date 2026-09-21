# Migración de la 14 a MMIO v2

Esta bitácora es corta a propósito. El diseño, las trampas y los hallazgos
están en [la de la 17](../../17.fpga-gpu-ram-v2/docs/migracion-v2.md), que fue
la primera de la familia. Aquí sólo va **si el atajo funcionó**, que es lo que
el encargo pedía medir en esta carpeta.

## Funcionó, y el número es diez de diez

El encargo decía: «la 14 después, que es su gemela de una línea. Debería salir
casi gratis, y **si no sale casi gratis, eso es el hallazgo**».

Salió casi gratis. De los diez ficheros que la migración de la 17 tocó, **seis
eran byte a byte idénticos** entre las dos antes de empezar:

| Fichero | Antes de migrar | Cómo se migró |
|---|---|---|
| `sysid.v` | idéntico | copia |
| `monitor.py` | idéntico | copia |
| `test_monitor.py` | idéntico | copia |
| `gpu_control_tb.v` | idéntico | copia |
| `gpu_regions_tb.v` | idéntico | copia |
| `gpu_mmio_error_tb.v` | idéntico | copia |
| `gpu_system.v` | 1 línea (`FOLDER`) | copia + `FOLDER` y `MONITOR_VERSION` |
| `top.v` | comentario + `VERSION_MINOR` | copia + los dos |
| `gpu_uart_tb.v` | una assertion de versión | copia + la assertion |
| `gpu_system_tb.v` | un `$display` de más en la 17 | editado en sitio |

**`./tools/test --prototype 14` pasó a la primera**, nueve bancos y 8 tests
Python, sin una sola corrección. La migración de la 14 fue media hora de
propagar, no un día de diseñar.

O sea que la corrección grande del encargo —«`gpu_system.v` es de hecho un
fichero compartido parametrizado por el número de carpeta»— se sostiene con el
trabajo hecho encima, no sólo con el `git hash-object`.

## Lo único que cambió del enunciado

**Ahora son dos líneas, no una.** `gpu_system.v` de la 14 y de la 17 difieren
en `FOLDER` **y** en `MONITOR_VERSION`, porque el `sysid.v` de v2 recibe la
versión del monitor como parámetro y la de v1 no. Es una línea más de
divergencia por carpeta, introducida por esta migración.

No es gratis del todo: cada cosa que el bloque SYSTEM de v2 declara —`DEVICES`,
`MEM_BASE`, `MEM_SIZE`, `MONITOR_VERSION`— es un parámetro que **tiene que ser
distinto por carpeta**, y por tanto una línea que el atajo de copiar no puede
resolver sola. En la 14 y la 17 coinciden todos menos dos. En la 12 no
coinciden ni `DEVICES` ni `MEM_SIZE`.

> El atajo de copiar escala con lo que las carpetas comparten, y v2 añade
> declaraciones **por carpeta** que v1 no tenía. Cuenta los parámetros nuevos
> antes de prometer que la siguiente sale gratis. `[TODAS]`

## Temporización: v2 sale ganando, y eso también es ruido

| | Fmax | Margen sobre 25 MHz | Camino crítico |
|---|---:|---:|---|
| 14 v1 | 31,15 | +24,6 % | `gpu.lsu.pending[3][2]` → `gpu.lsu.pick[2]` |
| **14 v2** | **34,25** | **+37,0 %** | `gpu.lsu.pending[3][5]` → `gpu.lsu.pick[1]` |

**El mismo sitio, dentro de la LSU**, y +3,10 MHz. La 17 perdió un 4,1 % y esta
gana un 10,0 %: las dos son la misma migración sobre el mismo diseño, así que
el signo lo pone el emplazamiento, no el mapa. Es la mejor prueba de que el
coste estructural de la 16 no existe aquí — si lo hubiera, no cambiaría de
signo entre dos carpetas que difieren en dos líneas.

Y la trampa de la doble temporización, otra vez y aún más grande que en v1:

```text
estimacion pre-rutado:  25,68 MHz
la buena:               34,25 MHz
```

Ocho megahercios y medio de diferencia. En v1 esta misma carpeta daba
`22,92 FAIL` contra `31,15 PASS`.

## Verificación

- `./tools/test --prototype 14`: nueve bancos RTL y 8 tests Python, a la
  primera.
- `sysid.v` de la 14 ya es byte a byte el de las seis de CPU. Quedan **dos** en
  el grupo de v1 (la 12 —migrada después de escribir esto— y la 22).
- Los otros cinco ficheros compartidos siguen idénticos en las cuatro.
- `x.tests`: 285 tests, sólo falla la guarda de `.asm` de la 22.
- Semilla: **no se fija**, y se conserva el párrafo que lo argumenta. Ver
  [la bitácora de la 17](../../17.fpga-gpu-ram-v2/docs/migracion-v2.md).
