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
| Base (RTL de 14) | **30,85 MHz** ⁵ | `gpu.lsu.pending` → `gpu.lsu.pick` (29,79 ns) | 30744 | 9016 |
| 1. Arbitraje y direccionamiento en ciclos distintos | 34,48 MHz ¹ | `gpu.sm.push_index` → `gpu.sm.top_index` (29,01 ns) | 30749 | 9020 |
| 2. `has_pending` fuera de la cadena de prioridad | 35,96 MHz ¹ | `gpu.sm.push_index` → `gpu.sm.top_index` (27,81 ns) | 30467 | 9025 |
| 3. Liberación de barrera de uno en uno | 35,02 MHz ² | `gpu.sm.stack_count` → `top_index` → `pc$wrmux` (32,07 ns, 59 seg.) | **29422** | 9033 |
| 4. Cima de la pila SIMT en registros | **37,78 MHz** ³ | `gpu.sm.pc` → `gpu.fetch_address` → `pc$wrmux` (26,87 ns, **39 seg.**) | **29103** | 9961 |

¹ Una sola semilla: no comparable entre sí (véase el aviso de arriba).
² Mediana de las semillas 1/2/3: 31,18 / 35,02 / 36,60 MHz.
| ~~5. Puerto único de escritura de `pc`~~ | ~~35,22 MHz~~ ⁴ | ~~91 seg.~~ | ~~27220~~ | ~~9961~~ |

⁴ **Descartado y revertido**: ganaba 1883 LUT pero perdía 6,8 % de fmax.
El paso 5 se revirtió al paso 4; la nueva iteración vigente es el paso 6,
documentado al final (todavía sin barrido de semillas).
⁵ Medido a posteriori sobre el RTL intacto de `14.fpga-gpu-ram`, con el mismo
barrido de cinco semillas: 35,31 / 27,21 / 30,85 / 34,87 / 30,70 MHz.

**Balance: 30,85 → 37,78 MHz de mediana, un 22 % más**, con 30744 → 29103 LUT.
Ambos extremos medidos con el mismo método, así que la cifra se sostiene.

Un detalle revelador: la dispersión entre semillas cae del **30 % al 9 %**. La
base no solo era más lenta de mediana, era mucho más impredecible: según la
semilla daba entre 27,21 y 35,31 MHz. Un diseño con caminos largos y congestión
depende del azar del emplazador; a medida que se acortan, el resultado se
vuelve repetible. Esa caída de varianza es, por sí sola, una mejora práctica:
una síntesis cualquiera ya no se va a 27 MHz.

También explica por qué la primera medida de la base (33,57 MHz, una semilla)
resultó optimista: estaba en la parte alta de una distribución muy ancha.

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
debajo del ruido de emplazamiento, así que no demuestran nada **individualmente**
—aunque el balance global medido después, 30,85 → 37,78 MHz, sí recoge su
efecto acumulado. Lo que es sólido:

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

## Paso 4: guardar la cima de la pila SIMT en registros

**Problema.** El camino que quedó en cabeza tras el paso 3 era, dentro de un
solo ciclo de `RECON`: leer `sp[current]` (mux de ocho), calcular
`top_index = current*SIMT_REGION_DEPTH + sp-1` (multiplicación y suma de 32
bits), indexar con él `join_pc[0:8*SIMT_REGION_DEPTH-1]`, comparar 32 bits
contra `pc[current]` y, del resultado, sacar el valor **y** el permiso de
escritura de `pc`. Cinco niveles anchos encadenados.

Peor aún, la condición de normalización lo hacía **ocho veces en paralelo**, una
por warp, cada una con su propio índice `a*DEPTH+sp[a]-1`:

```verilog
(sp[a]!=0 && pc[a]==join_pc[a*SIMT_REGION_DEPTH+{{(32-SP_BITS){1'b0}},sp[a]}-1])
```

**Cambio.** Se añade una copia de la cima de cada pila, una entrada por warp:
`join_pc_top`, `ssy_pc_top`, `entry_mask_top`, `path_base_top` para la pila de
regiones, y `pending_pc_top`, `pending_mask_top` para la de caminos. Todas las
lecturas pasan a ser `..._top[current]` (o `..._top[a]`): un mux de ocho
entradas, sin aritmética de índice delante.

Mantenerlas es asimétrico. En un **push** la nueva cima es el valor que se está
escribiendo, así que basta con copiarlo. En un **pop** la nueva cima es el nivel
de debajo, que sí hay que releer del array con `pop_index`. Esa lectura sigue
siendo un mux grande, pero ahora alimenta **solo un registro**, no la cadena de
comparación y escritura de `pc`: el camino queda partido en dos.

Las copias solo son válidas mientras `sp`/`pp` no sean cero, que es exactamente
la condición bajo la que se leen. Los sitios que ponen las pilas a cero
(reset, configuración, y la muerte de todas las lanes en `6'h33`/`6'h3f`) las
dejan obsoletas sin consecuencia. `top_index` y `path_top` desaparecen.

**Resultado.** El camino crítico pasa de **59 a 39 segmentos** y de 32,07 a
26,87 ns, y cambia de forma: ya no nace en la pila sino en `pc` → `fetch_address`.
Área 29422 → 29103 LUT; a cambio +928 biestables, que son justo las copias
(8 warps × 116 bits).

El recuento de segmentos es, junto al área, otro indicador poco sensible a la
semilla: mide cuántos niveles de lógica encadena el peor camino.

En fmax, mediana de cinco semillas **35,02 → 37,78 MHz**, con las cinco por
encima de la mediana del paso 3. Es el primer paso cuya mejora sobrevive al
ruido. La dispersión además baja del 17 % al 9 %, lo que encaja con un diseño
menos congestionado.

## Paso 5: puerto único de escritura de `pc` — **descartado**

**Hipótesis.** Tras el paso 3 quedaban todavía varios puertos de escritura sobre
`pc`: los cuatro por bytes de la ventana de configuración y los de `pc[current]`
repartidos por `RECON`, `DECODE` y `FINISH`. Unificarlos en un solo puerto con
máscara de bytes debería reducir el árbol `pc$wrmux` que seguía cerrando el
camino crítico.

**Implementación.** Cada rama declaraba su intención con asignaciones
bloqueantes (`pc_write`, `pc_index`, `pc_value`, `pc_strobe`) y la escritura se
resolvía una sola vez al final del ciclo. Un `pc_increment` calculaba
`pc[pc_index]+4` después del índice, para no repetir el mux de lectura y el
sumador en las tres ramas que solo avanzan una instrucción. La escritura de
configuración se resolvía **detrás** del `case`, porque el orden original la
ponía antes y con asignaciones no bloqueantes ganaba el `case`.

Funcionó: pruebas, lint y síntesis correctas, y **1883 LUT menos**
(29103 → 27220, −6,5 %).

**Pero el fmax empeoró.** Mediana de cinco semillas **37,78 → 35,22 MHz**
(rango 33,78–35,85), con todas las semillas por debajo de la mediana del paso 4.
El camino crítico pasó de 39 a **91 segmentos**.

**Por qué.** Es el intercambio clásico de compartir un recurso. Al forzar todas
las fuentes por un único puerto, dejan de calcularse en paralelo y pasan a
compartir una cadena de prioridad; y `pc_increment` agrava el efecto poniendo la
lectura de `pc` y el sumador *detrás* de la resolución del índice, que a su vez
depende de toda la decodificación del `case`.

**Decisión: revertido.** El diseño ocupa un 33 % del dispositivo, así que el
área no es el recurso escaso; el objetivo es el fmax. Cambiar 6,5 % de LUT por
6,8 % de frecuencia va en la dirección contraria. El comentario en `gpu_sm.v`
deja constancia para que nadie vuelva a intentarlo sin saberlo.

Queda una variante sin probar: puerto único **sin** `pc_increment`, calculando
el valor en cada rama en paralelo. Recuperaría parte del área sin serializar la
lectura detrás del índice, aunque la cadena de prioridad seguiría ahí.

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

El camino crítico sigue terminando en el árbol de escritura de `pc`, pero ahora
nace en el propio `pc` y pasa por `gpu.fetch_address`. Dos frentes:

- **Reducir todavía más los puertos de escritura de `pc`.** Quedan los cuatro
  del acceso por bytes de configuración, que podrían unificarse en uno solo, y
  los varios de `pc[current]` en `RECON`/`DECODE`/`FINISH`, que podrían
  colapsarse calculando un único `pc_next` con su permiso de escritura.
- **`gpu.fetch_address`**, que sale de `pc[current]` hacia la LSU y vuelve a
  entrar en la decisión de escritura.

Después habría que repetir el histograma de slack: la cola por encima de 20 ns
era propiedad de los `wrmux` del SM, y conviene ver cómo ha quedado el reparto.

Sobre la LSU, del plan inicial quedan:

- `has_pending` por slot ya está implementado en el paso 2.
- Rotar una máscara one-hot por `cursor` en lugar de ocho sumadores `cursor+k`
  con ocho comparadores encadenados.
- Mover `addresses`/`values` a memoria distribuida leída por índice registrado,
  en vez de un array de biestables con mux 2048→32. Son 2×2048 bits.

Todo lo que se consolide aquí es candidato a backport a `12.fpga-gpu`, cuya
lógica de `found`/`pick`/`cursor` es casi idéntica.

## Paso 6: PC del contexto y destinos registrados (12 septiembre 2026)

Se conserva la ejecución multiciclo. `PICK` selecciona el warp y el nuevo estado
`CONTEXT` captura `pc[current]` antes de evaluar `RECON`/`NORMALIZE`. Cada pop
vuelve a `CONTEXT` para capturar el PC que acaba de escribirse, antes de evaluar
la siguiente región. Así no se utiliza una copia obsoleta en pops consecutivos.

El fetch y las lanes reciben `context_pc`. `FETCH` registra `sequential_pc=PC+4`
y `RF_WAIT` registra los dos destinos de salto; estos cálculos aprovechan ciclos
ya existentes. Las comparaciones y escrituras de `DECODE`/`FINISH` usan esos
registros. Las actualizaciones de otros warps por LSU, barrera o configuración
siguen escribiendo el array arquitectónico.

### Primera medida, no mediana

| Magnitud | Paso 4, informe guardado | Paso 6 |
| --- | ---: | ---: |
| fmax | 37,22 MHz | 47,14 MHz |
| Camino crítico | 26,870 ns | 21,215 ns |
| Segmentos | 39 | 31 |
| Routing en el camino | 22,127 ns | 17,391 ns |
| Lógica en el camino | 4,218 ns | 3,299 ns |
| TRELLIS_COMB | 29103 | 29245 |
| TRELLIS_FF | 9961 | 10089 |
| EBR / DSP | 16 / 32 | 16 / 32 |

La primera construcción completa tardó 422,3 s, incluidos 227,6 s de routing.
El nuevo peor camino pasa por `gpu.lsu_mask[5]` (alias de la selección de máscara
activa) y termina en **CE de `warp_retired_count[6][12]`**, identificado enlazando
la celda final del informe con el netlist. Que aparezca `lsu_mask` no demuestra
un recorrido dentro de la LSU: la misma máscara se utiliza en el control del SM.
El siguiente candidato es separar las decisiones de máscara/divergencia de los
permisos de retirada y escritura del estado. No se ha implementado ese paso aún.

El incremento de frecuencia de esta pareja de informes es 26,66 %, pero no se
presenta como ganancia de mediana: falta el barrido de semillas del nuevo RTL.
El reloj físico y las constraints siguen en 25 MHz; no se ha programado la placa.

### Corrección y coste en ciclos

Pasan los 8 tests Python del monitor, los 6 testbenches RTL (incluidos los 32
casos diferenciales) y lint. Los tests del script verifican extracción de tablas,
conservación de extremos/retardos, rechazo de timing insuficiente, archivos ZIP
sin interferir con Apio y rechazo de informes antiguos tras un build fallido.

Se simularon además los mismos 32 programas sobre las fuentes anteriores y las
actuales, en directorios aislados. El contador se imprime inmediatamente después
de acabar la ejecución, antes de que las lecturas de comprobación del monitor lo
reutilicen. Suma de ciclos: **131196 → 135933 (+3,61 %)**; coste por caso entre
0,70 % y 8,23 %. Este coste exige ganar frecuencia, no basta con añadir etapas.
No es una medida de rendimiento físico a 47 MHz: el modelo SDRAM y sus parámetros
siguen correspondiendo a 25 MHz.

Informes y logs de la primera medida:
`reports/20260912-092103-728457-context-pc/`.
Incluye `before.log`, `after.log` y `cycles.json` con las medidas por programa.
El informe antiguo está en `reports/20260912-091931-835060-before-context/`;
se archivó desde los outputs existentes, no se reconstruyó esa versión.

### Herramienta de build

`build.ps1 -Label <nombre>` ejecuta Apio con progreso PNR, captura el log en vivo,
extrae histogramas de slack y tabla de routing y conserva JSON detallado, fuentes
en ZIP, hashes y bitstream en `reports/`. No realiza una segunda pasada para
obtener el detalle. Véase el README para `-Incremental` y `-ArchiveOnly`: en Apio
1.5.1 pedir `--verbose-pnr` fuerza una pasada de routing aunque no cambie el RTL.
