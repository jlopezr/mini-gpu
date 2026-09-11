# Optimización de temporización: 16 frente a 14

Copia de `14.fpga-gpu-ram` para subir la frecuencia máxima. Objetivo declarado:
acercarse a 100 MHz. La constraint del proyecto sigue en 25 MHz; lo que se mide
en cada paso es el `achieved` del informe de `nextpnr`, no un cambio de reloj.

Método: **un cambio por iteración**, con `check.ps1 Tests`, `check.ps1 Lint` y
`check.ps1 Build` después de cada uno, anotando fmax, camino crítico y recursos.

```powershell
./16.fpga-gpu-ram-v2/check.ps1 Tests
./16.fpga-gpu-ram-v2/check.ps1 Lint
./16.fpga-gpu-ram-v2/check.ps1 Build
./16.fpga-gpu-ram-v2/timing.ps1   # camino crítico y recursos de esta pasada
./16.fpga-gpu-ram-v2/sweep.ps1    # fmax sobre varias semillas
```

> **El fmax de una sola semilla no sirve para comparar.** Medido sobre el mismo
> netlist, `nextpnr` da 31,18 / 35,02 / 36,60 MHz según la semilla de
> emplazamiento: **17 % de dispersión**. Cualquier diferencia por debajo de eso
> es ruido. Por eso el fmax se anota como mediana de varias semillas, y el
> recuento de LUT —que sale de Yosys y es determinista— vale como señal
> secundaria libre de ruido.
>
> Los pasos 1 y 2 se midieron con una sola semilla antes de descubrirlo, así que
> sus cifras están marcadas como no comparables.

## Medidas

| Paso | fmax | camino crítico | LUT | FF |
| --- | --- | --- | --- | --- |
| Base (RTL de 14) | 33,57 MHz ¹ | `gpu.lsu.pending` → `gpu.lsu.pick` (29,79 ns) | 30744 | 9016 |
| 1. Arbitraje y direccionamiento en ciclos distintos | 34,48 MHz ¹ | `gpu.sm.push_index` → `gpu.sm.top_index` (29,01 ns) | 30749 | 9020 |
| 2. `has_pending` fuera de la cadena de prioridad | 35,96 MHz ¹ | `gpu.sm.push_index` → `gpu.sm.top_index` (27,81 ns) | 30467 | 9025 |
| 3. Liberación de barrera de uno en uno | 31,18 / 35,02 / 36,60 MHz ² | `gpu.sm.stack_count` → `top_index` → `pc$wrmux` (32,07 ns) | **29422** | 9033 |

¹ Una sola semilla: no comparable entre sí (véase el aviso de arriba).
² Semillas 1/2/3; mediana 35,02 MHz.

La base reproduce exactamente la cifra de `14/salida-sintesis.json`, así que al
menos la comparación base↔14 es entre medidas equivalentes.

El único indicador limpio en toda la tabla es el área: **30744 → 29422 LUT**,
un 4,3 % menos, sin ruido de emplazamiento.

## Paso 1: separar el arbitraje del direccionamiento

**Problema.** El estado `IDLE` resolvía en un único ciclo combinacional toda la
cadena de selección: prioridad rotatoria sobre ocho warps, prioridad sobre ocho
lanes dependiente del resultado anterior, y **dos multiplexores de 2048 bits a
32** (`addresses[pick][lane_pick*32 +: 32]` y el equivalente sobre `values`)
indexados por ambas prioridades encadenadas, más la validación de rango y la
transición de estado encima. El informe de la base lo confirmaba: el camino
crítico nacía en `gpu.lsu.pending[7][0]` y pasaba por `gpu.lsu.pick[2]`.

Los retardos eran de enrutado, no de lógica: saltos de 3,11 ns, 3,28 ns y
2,29 ns entre celdas situadas en (76,72), (92,38), (95,38) y (103,38). Un mux de
ese tamaño no se empaqueta junto, así que el emplazador lo reparte por el chip.

**Cambio.** Se añade el estado `SELECT` (código 7, el único libre de los tres
bits). `IDLE` ahora solo arbitra y registra `selected`/`selected_lane`; `SELECT`
lee la dirección y el dato con esos índices **ya registrados** y decide entre
error de rango y `SEND_LOW`. Los muxes siguen existiendo, pero dejan de estar
encadenados detrás de la lógica de prioridad.

Los códigos de `SEND_LOW`..`WAIT_HIGH` se conservan porque `gpu_lsu_tb` recorre
`dut.state==1..4` para cancelar en cada fase de la transferencia.

**Coste.** Un ciclo más por palabra de lane. Es irrelevante: cada palabra de 32
bits ya son dos accesos BL1 a SDRAM con decenas de ciclos de espera. En área,
+5 LUT y +4 FF.

**Resultado.** 33,57 → 34,48 MHz, y sobre todo **el camino crítico sale de la
LSU**: ahora el peor camino está en la pila de divergencia del SM
(`push_index` → `top_index`). La sospecha inicial era correcta, pero la LSU solo
era el primero de varios caminos casi igual de largos.

## Paso 2: sacar `pending` de la cadena de prioridad

**Problema.** La condición de la prioridad rotatoria era
`busy[candidate] && (pending[candidate]!=0 || !rsp_valid)`. Ese
`pending[candidate]!=0` obliga a multiplexar los **64 bits** de `pending` por un
índice que la propia cadena va calculando, y a reducirlos con un OR, ocho veces
en serie. Es lógica ancha dentro del lazo de prioridad, que es justo donde más
cara sale.

**Cambio.** Se añade el registro `has_pending[7:0]`, un bit por slot que refleja
`|pending[i]`. La prioridad consulta un único bit por candidato. El registro se
mantiene en los cuatro puntos que tocan `pending`: reset, aceptación de petición
(`|req_mask`), y los dos cierres de lane en `SELECT` y `WAIT_HIGH`, ambos con el
mismo `pending_after_lane`.

El cálculo ancho no desaparece, pero se traslada a `SELECT`/`WAIT_HIGH`, donde
se indexa con `selected` (ya registrado) y no está en el lazo de prioridad.

No hay riesgo de doble asignación entre la aceptación de petición y los cierres:
`req_ready` exige `!busy[req_tag]` y el slot seleccionado está ocupado hasta que
se consume su respuesta, así que `req_tag` nunca coincide con `selected`.

**Resultado.** 34,48 → 35,96 MHz, y esta vez **también baja el área**: 30749 →
30467 LUT, porque los ocho comparadores de 8 bits desaparecen. Solo +5 FF. El
camino crítico sigue en el SM, ahora con 27,81 ns.

## Lectura de los tres primeros pasos

Las ganancias que parecían darse en los pasos 1 y 2 (+2,7 % y +4,3 %) están por
debajo del ruido de emplazamiento, así que no demuestran nada por sí solas. Lo
que sí es sólido:

- Los tres cambios son correctos y **reducen área**: 30744 → 29422 LUT.
- El camino crítico **se ha desplazado** de la LSU al SM y se ha ido concretando
  a cada paso, hasta señalar una estructura precisa. Eso es señal real: el
  análisis estático de qué encadena cada camino no depende de la semilla.
- Las estructuras que se han quitado —cadena de prioridad con `pending` ancho,
  ocho puertos de escritura sobre `pc`— eran caras por construcción.

Para el resto del recorrido conviene medir el fmax como mediana de varias
semillas y apoyarse en el área y en la lectura del camino crítico, que son las
señales que no fluctúan.

## Paso 3: liberar la barrera de uno en uno

**Problema.** `pc[0:7]` acumulaba **más de trece puertos de escritura**
inferidos: cuatro del acceso por bytes de configuración, uno de
`pc[lsu_rsp_tag]`, los de `pc[current]` en `RECON`/`DECODE`/`FINISH`, y sobre
todo **ocho** de un único sitio:

```verilog
for(w=0;w<8;w=w+1) if(release_bar[w]) begin
    wait_bar[w]<=0; pc[w]<=pc[w]+4; generation[w]<=generation[w]+1'b1;
end
```

Escribir los ocho warps en el mismo ciclo obliga a Yosys a construir ocho
puertos sobre `pc`, `generation` y `wait_bar`. De ahí los árboles
`memory\gpu.sm.pc$wrmux[...]` que dominaban toda la cola por encima de 20 ns.

**Cambio.** El conjunto de warps con la barrera ya satisfecha se captura entero
en el registro `releasing`, y se drena **un warp por ciclo**. Hay que capturarlo
de golpe porque `release_bar` deja de ser válido en cuanto se libera el primero:
la condición exige que *todos* los warps vivos del grupo estén esperando, así
que liberar uno la anula para el resto y los demás no saldrían nunca.

`fault` descarta `releasing`, porque antes un error simplemente impedía que la
liberación atómica llegara a ocurrir; y la escritura de configuración limpia el
bit junto con `wait_bar`. La liberación tarda ahora hasta ocho ciclos en lugar
de uno, sin efecto sobre `retired_count`: liberar una barrera es una transición
de control, no una instrucción retirada.

**Resultado.** **30467 → 29422 LUT**, mil LUT menos, y desaparecen los ocho
puertos. En fmax no se puede concluir nada: 31,18 / 35,02 / 36,60 MHz según
semilla. Fue precisamente la semilla mala de este paso la que destapó que las
medidas anteriores no eran comparables.

El camino crítico se mantiene en la misma zona y ahora se lee más claro:
`sp[current]` → `top_index` → mux sobre `join_pc[0:8*DEPTH-1]` → comparación de
32 bits → valor de escritura de `pc`, todo en un ciclo. Ese es el objetivo
siguiente.

## ¿Cuántos caminos hay que arreglar?

El informe que guarda apio solo trae el peor camino por dominio de reloj. Para
ver el reparto completo hay que relanzar `nextpnr` **sin `-q`**, que imprime un
histograma de slack por endpoint, y con `--detailed-timing-report`, que añade al
JSON el tiempo de llegada de cada net:

```powershell
$root = "$env:USERPROFILE\.apio\packages\oss-cad-suite"
$env:PATH = "$root\bin;$root\lib;$root\py3bin;" + $env:PATH
cd 16.fpga-gpu-ram-v2
nextpnr-ecp5 --85k --package CABGA381 --speed 6 --json _build/default/hardware.json `
  --report detallado.pnr --lpf ulx3s_v20.lpf --timing-allow-fail `
  --detailed-timing-report --force
```

El histograma se mide contra la constraint vigente (25 MHz, 40 ns), así que el
retardo de cada endpoint es `40 ns − slack`. Sobre los 67.175 endpoints del
diseño tras el paso 2:

| Objetivo | Periodo | Endpoints por encima | % |
| --- | --- | --- | --- |
| 50 MHz | 20,0 ns | 5.465 | 8 % |
| 66 MHz | 15,2 ns | 8.576 | 13 % |
| 75 MHz | 13,3 ns | 11.338 | 17 % |
| 85 MHz | 11,8 ns | 15.687 | 23 % |
| 100 MHz | 10,0 ns | 24.315 | 36 % |

La masa del diseño está en 7,6–9,0 ns, es decir ya en torno a 110–130 MHz. Lo
que sobra es una cola larga.

**Pero endpoints no son problemas independientes.** Agrupando los nets con
nombre por módulo, la cola se concentra en muy pocas estructuras:

| Módulo | nets | >10 ns | >15 ns | >20 ns | peor |
| --- | --- | --- | --- | --- | --- |
| write-mux de arrays del SM | 7336 | 1832 | 1197 | 748 | 27,81 ns |
| `gpu.sm` (resto) | 2369 | 709 | 305 | 0 | 19,89 ns |
| `gpu.lsu` | 1618 | 266 | 3 | 0 | 18,72 ns |
| `gpu` | 309 | 1 | 0 | 0 | 13,25 ns |
| `controller` | 18 | 0 | 0 | 0 | 5,01 ns |
| `uart_i` | 6 | 0 | 0 | 0 | 2,38 ns |

Los veinte nets más tardíos son todos del mismo tipo:
`memory\gpu.sm.pc$wrmux[...]` y `memory\gpu.sm.warp_retired_count$wrmux[...]`.
Son los árboles de multiplexores de escritura que Yosys construye para los
arrays `pc[0:7]` y `warp_retired_count[0:7]`, escritos desde más de una docena de
sitios (`current`, `lsu_rsp_tag`, `w`, `cfg_word[4:2]`) con valores que dependen
de decodificación profunda (`join_pc[top_index]`, `pending_pc[path_top]` y sus
comparaciones).

O sea: **cientos de endpoints, un puñado de causas**. La cola >20 ns es
esencialmente una sola estructura. El controlador SDRAM y la UART no aparecen.

## Pendiente

En cabeza, y siguiente paso: **guardar la cima de la pila SIMT en registros por
warp**. Hoy `RECON` calcula `top_index` desde `sp[current]`, indexa con él
`join_pc[0:8*DEPTH-1]`, compara 32 bits contra `pc[current]` y de ahí sale el
valor y el permiso de escritura de `pc`, todo encadenado en un ciclo. Con copias
`join_pc_top[0:7]`, `ssy_pc_top[0:7]`, `entry_mask_top[0:7]` y
`path_base_top[0:7]` mantenidas en push y pop, la comparación pasa a ser un mux
de ocho entradas sin aritmética de índice delante.

Quedan además los puertos de escritura de `pc` que no ha tocado el paso 3: los
cuatro del acceso por bytes de configuración podrían unificarse en uno solo.

Sobre la LSU, del plan inicial quedan:

- Sacar `pending` de la cadena de prioridad con un bit `has_pending` por slot,
  en vez de comparar `pending[candidate]!=0` sobre 64 bits.
- Rotar una máscara one-hot por `cursor` en lugar de ocho sumadores `cursor+k`
  con ocho comparadores encadenados.
- Mover `addresses`/`values` a memoria distribuida leída por índice registrado,
  en vez de un array de biestables con mux 2048→32. Son 2×2048 bits.

Todo lo que se consolide aquí es candidato a backport a `12.fpga-gpu`, cuya
lógica de `found`/`pick`/`cursor` es casi idéntica.
