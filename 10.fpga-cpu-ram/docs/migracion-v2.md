# Migración de la 10 a MMIO v2

Log de trabajo, escrito **durante** la migración.

Contrato de referencia: [`../../1.isa/mmio.md`](../../1.isa/mmio.md).

**Este fichero es el más corto de los cinco, y eso es el resultado.** La
[bitácora de la 6](../../6.fpga-cpu/docs/migracion-v2.md) es la gemela de ésta
y lleva **la fase 0 de las tres carpetas** de este encargo, la decisión de
diseño de las siete palabras y los dos analizadores compartidos que hubo que
arreglar. Aquí sólo se escribe lo que en la 10 no salió igual.

Antes de ésas están [la 21](../../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md),
[la 19](../../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md),
[la 18](../../18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md) y
[la validación en placa](../../docs/validacion-mmio-v2-placa.md).

---

## La predicción del encargo, y se cumple

> «La 10 después, que es su gemela y debería salir casi gratis. Si no sale casi
> gratis, eso es el hallazgo y hay que escribirlo.»

**Salió casi gratis.** El RTL, los bancos y la ventana del monitor son la misma
edición que la 6 con otros números, y se hicieron en una pasada sin una sola
sorpresa. Los ficheros tocados son los mismos cinco, con los mismos cambios:

| Fichero | Qué le pasa | ¿Igual que en la 6? |
|---|---|---|
| `sysid.v` | copiado ya migrado de la 21 | sí, byte a byte |
| `top.v` | selección, parámetros, ventana | sí, con otros valores |
| `sysid_host_tb.v` | las siete palabras y el final del bloque | sí |
| `monitor_tb.v` | una línea | sí |
| `monitor.py` | **no**, y es lo único que no es gemelo (abajo) |

Los valores propios, que son los únicos que hay que repasar uno a uno:

| Parámetro | 6 | 10 | Por qué |
|---|---|---|---|
| `FOLDER` | 6 | 10 | — |
| `ISA_PROFILE` | `0x3` | **`0x0`** | a esta CPU le faltan MUL y DIV |
| `DEVICES` | `0x009` | **`0x005`** | bit 0 SYSTEM + bit 2 **SDRAM**, no EBR |
| `MEM_SIZE` | `0x8000` | **`0x0200_0000`** | 32 MiB, no 32 KiB |
| `MONITOR_VERSION` | `0x0306` | **`0x030A`** | 3.10 |

Ninguno de los cinco se deduce de otro, y `MONITOR_VERSION` no se deduce de
nada: copiar el de la carpeta de al lado es un número perfectamente válido que
hace que el bloque SYSTEM declare un juego de comandos que esta carpeta no
implementa, y no lo dice ningún test. Es la trampa que la 18 documentó y que
sigue viva.

### La única diferencia de RTL que importa, y va a favor

En la 6 la selección cuelga del bus crudo:

```verilog
wire sysid_selected = (mem_address[31:5] == 27'h400_0000) && ...
```

En la 10 cuelga de la dirección **ya registrada**, porque este `top.v` registra
las dos direcciones del puerto del monitor antes del adaptador:

```verilog
wire sysid_selected = (adapter_monitor_address[31:5] == 27'h400_0000) && ...
```

O sea que aquí el camino es registro → comparación → registro y **no toca el
crítico**, mientras que en la 6 sale del pin del bus y sí lo toca. Las dos
carpetas parecen la misma edición y la consecuencia de temporización es
distinta; en la 6 hubo que medirla con un control entero y aquí no.

> Dos carpetas gemelas pueden tener el mismo diff y distinto riesgo. Lo que
> decide no es qué línea cambias, es **de qué cuelga**. `[TODAS]`

---

## Lo único que no fue gemelo: el CLI no llegaba a su propio bloque `[10]`

Y es el hallazgo de esta carpeta.

La 6 y la 10 comparten que su `monitor.py` **no tiene `parse_address`**: validan
con `MAX_ADDRESS` a secas. Pero el valor no es el mismo:

| | `MAX_ADDRESS` | ¿Cubre `0x8000_0000`? |
|---|---|---|
| 6 | `0xFFFF_FFFF` | sí, los 32 bits enteros |
| **10** | **`0x01FF_FFFF`** | **no**: son los 32 MiB de SDRAM |

O sea que en la 10 `monitor.py read-word 0x80000000` se rechaza **en el host,
sin llegar al cable**. Y no es una regresión de esta migración: pasaba
exactamente igual en v1 con `0x80000f00`. **El bloque de identificación de la 10
llevaba desde que existe sin ser alcanzable desde la línea de órdenes**, que es
lo único que esa carpeta tiene fuera de la memoria.

Por qué no lo había visto nadie, y son las tres razones de la fase 7 de la
validación de placa, calcadas:

1. `MONITOR_REGIONS` **sí** declaraba la ventana, y es lo que los tests
   contrastan. Este otro camino no lo miraba nada.
2. Sólo se usa desde el **CLI**. La suite de placa va por `MonitorClient` y no
   pasa por la validación de la línea de órdenes.
3. **El síntoma es idéntico al éxito que se busca.** `exit=1` con un `Error:`
   es lo que se espera de una dirección que la placa rechaza.

Lo destapó `test_la_ventana_del_cli_cubre_los_bloques_que_decodifica` en cuanto
la carpeta entró en su alcance, o sea en cuanto su `sysid.v` llevó el magic de
v2, y lo dijo con el comando delante:

```text
10.fpga-cpu-ram: la ventana del CLI [0x00000000, 0x01ffffff] no cubre la
región [0x80000000, 0x8000ffff] que declara MONITOR_REGIONS. El síntoma es que
`monitor.py read-word 0x80000000` falla en el HOST, sin llegar a la placa.
```

Arreglado con la forma que ya tienen la 16, la 18, la 19 y la 21: un
`parse_address` que acepta la SDRAM **o** la ventana de SYSTEM, más el par
`MMIO_BASE`/`MMIO_LIMIT` que lo alimenta, y las ocho llamadas del CLI pasando
por él.

> La 6 no lleva ese par y la 10 sí, y la diferencia no es de estilo: la 6 no
> filtra direcciones en el host y la 10 sí. Declarar constantes que nadie lee
> es como sobrevivió el `SERIAL_BASE` de la 19; no declararlas donde hacen
> falta es como sobrevivió esto. `[TODAS]`

---

## Temporización: el barrido que no hacía falta y se hizo igual

Con la semilla 2 de siempre, la síntesis post-migración da **106,44 MHz, PASS**.
O sea que la migración no invalidó nada y se podía parar ahí.

Se barrió igual, porque «la semilla es propiedad de un netlist» y porque la
comparación sólo significa algo contra **el mismo juego de ocho semillas**:

| | v1, según su `apio.ini` | v2, hoy |
|---|---|---|
| Cumplen | 7 de 8 | **8 de 8** |
| Rango | 99,96 – 115,55 | **106,44 – 115,17** |
| Mediana | 107,36 | **111,37** |
| Mejor | 115,55 (s2, +15,6 %) | 115,17 (s6, +15,2 %) |

**v2 no cuesta frecuencia en la 10**: el suelo sube seis MHz y medio, la mediana
cuatro, y el techo se mueve cuatro décimas. Se fija la **6**, +15,2 %, con su
párrafo en el `apio.ini`.

Esto es la cuarta carpeta que dice lo mismo y ya no es una sorpresa: lo que v2
se lleva, cuando se lleva algo, es el techo, y lo que no se mueve es cuántas
semillas cumplen.

---

## Verificación al cerrar

| Qué | Base (fase 0) | Ahora |
|---|---|---|
| `tools/test --prototype 10` | SUCCESS, 7 bancos | **SUCCESS**, 7 bancos |
| `tools/lint --prototype 10` | 20 `PINMISSING`, 21 `WIDTHEXPAND` | **igual, por tipo** |
| `unittest` de `x.tests` | 284 OK | **284 OK** |
| `run_tests --backend cpusim` | 53 casos, 0 fallos | 53 casos, 0 fallos |
| `unittest` de `1.isa` / `2` / `11` | 61 / 44 / 62 | 61 / 44 / 62 OK |
| `generate-mmio --check` | al día | al día |
| Barrido | 7 de 8 | **8 de 8**, semilla 6 fijada con su párrafo |

Control negativo del banco, idéntico al de la 6: devuelta la selección a
`[31:5]` a secas, falla **exactamente** en `8000001c` con `err 0` y nada más.

---

## Qué salió más barato y qué más caro `[10]`

**Más barato:** todo el RTL y los bancos, que fueron la edición de la 6 con
otros números. Si la 6 costó una tarde por los analizadores compartidos, la 10
costó veinte minutos porque esos ya estaban arreglados. **El orden 6 → 10 es el
correcto y por la razón que da el encargo.**

**Más caro:** el `monitor.py`, que era el fichero que parecía más gemelo y
resultó ser el único que no lo era, y que además escondía un fallo anterior a
esta migración.

> Al migrar la gemela de una carpeta ya hecha, el fichero donde hay que mirar
> con lupa es el que **no** es RTL. El RTL lo protege un test de copias byte a
> byte; el lado host no tiene quien lo iguale, y cada `monitor.py` es una copia
> divergente desde hace trece carpetas. `[TODAS]`
