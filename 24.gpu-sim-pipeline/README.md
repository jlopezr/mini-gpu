# Modelo por ciclos del cauce del SM

Modelo **estructural**: avanza un ciclo cada vez y cada etapa tiene su registro
con la instrucción que lleva dentro. Sirve para *mirar* el cauce y depurar un
riesgo mal resuelto antes de escribirlo en Verilog.

Carpeta aparte de `23.gpu-sim-uarch`, que se queda como está:

| | 23, modelo de coste | 24, modelo por ciclos |
| --- | --- | --- |
| Cómo avanza | calcula cuándo acaba y salta el reloj | un ciclo cada vez |
| Qué se puede mirar | agregados | el contenido de cada etapa, ciclo a ciclo |
| Velocidad | rápido | lento |
| Para qué | decidir parámetros | depurar el diseño |

**La calibración no se duplica**: `Config`, el canal de memoria y las
constantes derivadas del RTL se importan de 23. Costó sacarlas contando estados
en `gpu_lane.v` y midiendo en `sdram_bandwidth_tb.v`; tenerlas en dos sitios
sería garantizar que un día divergen.

## Uso

```bash
python pipeline.py                              # agregados
python pipeline.py --trace-from 2000 --trace-len 20    # diagrama de etapas
python pipeline.py --exec-base 4                # y si la lane tardara 4 ciclos
```

## Lo primero que enseñó el diagrama

```text
    ciclo  S     F     I     D     X     W
     2000  w3*   w2*   w1*   w0*   w7*   --
     2004  w3*   w2*   w1*   w0*   w7*   --
     2005  w4    w3    w2    w1    w0    w7     <- todo avanza un paso
     2006  w4*   w3*   w2*   w1*   w0*   --
```

(`wN*` = esa etapa no pudo avanzar ese ciclo.)

**Las seis etapas llenas, las seis paradas, y cada 6 ciclos todo avanza un
paso.** La cadena es: `X` retiene la instrucción 6 ciclos, así que `D` no puede
entregarle la suya, así que `I` no pasa a `D`, ni `F` a `I`, ni `S` a `F`. Una
cinta que se mueve al ritmo de su eslabón más lento.

Y lo que no es obvio: **esto es el cauce funcionando bien, no mal.**
`stall_no_warp` son 316 ciclos de 975 698, un 0,03%. Los 8 warps mantienen las
seis etapas llenas todo el tiempo: ni burbujas, ni riesgos, ni huecos. La
segmentación hace exactamente su trabajo.

Lo que revela es que, una vez lleno el cauce, **no queda nada que ganar en el
front-end**: el único límite es `X`. Por eso el barrido de abajo sale
perfectamente lineal.

> **Corrección.** La primera versión de este documento decía que "`S` está
> siempre vacía" y lo leía como que el cauce no segmentaba. Era un fallo del
> modelo, no del diseño: el código metía el paquete directamente en `F` y nunca
> ocupaba `S`. Arreglado; los agregados no cambiaron (975 698 contra 975 693),
> porque una etapa más añade latencia, no caudal. La conclusión de fondo —que
> `X` domina— se sostiene, pero venía del barrido y de la ocupación del 99,5%,
> no de aquella columna vacía.

## Lo que sale del barrido

Con `X` al 99%, el tiempo total **es** el tiempo de la lane, así que la
relación es exactamente lineal:

| Ciclos de la lane | Ciclos/frame | CPI | vs. el diseño de hoy |
| --- | --- | --- | --- |
| 6 (antes de quitar su fetch) | 1 001 463 | 6,59 | 2,4× |
| 5 | 854 429 | 5,63 | 2,8× |
| **4 (hoy, `EXTERNAL_FETCH`)** | **707 404** | **4,66** | **3,3×** |
| 3 | 560 433 | 3,69 | 4,2× |
| 2 (colapsando `HALTED` y `RETIRE`) | 413 373 | 2,72 | **5,7×** |

Referencia: **15,6 ciclos por instrucción medidos en placa** (`profile.py`, ver
`22.fpga-gpu-bl8/profiling.md`); 2 378 037 ciclos en RTL para este frame.

Los 6 ciclos ya no son "hoy": el fetch redundante de la lane está quitado y hoy
son 4. La fila de 2 es la siguiente parada, y está razonada en
`sm-pipeline.md` — `HALTED` es un handshake y `RETIRE` lo duplica `W`.

El modelo de coste de 23 da 4,75 para la misma configuración; éste, 4,66. Un
1,9% de diferencia entre dos modelos construidos por separado, que es
exactamente para lo que sirve tener dos.

### El hallazgo: la lane hace un fetch que no necesita

Desde `step_request`, `gpu_lane.v` recorre seis estados:

```text
HALTED → FETCH_REQUEST → FETCH_WAIT → DECODE → EXECUTE → RETIRE
```

**Dos de ellos son un fetch propio** que no hace falta: el SM ya le entrega la
instrucción, y su `imem_ready` está atado a su propio `imem_valid`, así que no
espera a nadie — simplemente gasta los estados. Son un resto de cuando la lane
era una CPU completa.

**Hecho, y esto es lo que salió.** El cambio fue local a un módulo
(`gpu_lane #(.EXTERNAL_FETCH(1))`), del mismo tipo que acortar el handshake de
`gpu_imem_buffer`, y no dependía de segmentar el SM:

| | Predicho por el modelo | Medido en RTL |
| --- | --- | --- |
| Ganancia sin segmentar nada | −11,9% | **−11,2%** |

Es la razón de ser de esta carpeta: la predicción se hizo antes de tocar el
Verilog y acertó dentro de un punto porcentual.

## Cómo leer estos números

Los dos modelos coinciden entre sí (707 404 contra 721 750, un 2,0%), lo cual
está bien pero **no demuestra nada sobre el RTL**: comparten calibración.

Lo que sí respalda al conjunto son dos contrastes externos:

- 23 reproduce el diseño actual con `retired`, `lane_ops` y `lsu_tx` exactos y
  los ciclos a −7,0%;
- y sobre todo, **el CPI medido en la placa es 15,6 y el modelo predijo 15,66**
  (ver `22.fpga-gpu-bl8/profiling.md`). Esa es la única validación que no es
  circular, porque el hardware no comparte nada con el modelo.

La parte segmentada sigue siendo **predicción**. El modelo reproduce lo que
existe, que es la única razón para creerle sobre lo que no existe.

**Ese −7,4% es un sesgo optimista**, así que los 3,9× hay que leerlos como
"algo menos de 3,9×". Y el modelo no sabe nada de Fmax: si el cauce segmentado
baja el reloj, parte de la ganancia se va por ahí. Eso solo lo dice la síntesis.