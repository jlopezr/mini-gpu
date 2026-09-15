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
| 6 (hoy) | 975 693 | 6,42 | 2,7× |
| 5 | 828 621 | 5,46 | 3,2× |
| 4 (sin su fetch) | 681 549 | 4,49 | **3,9×** |
| 3 | 534 481 | 3,52 | 5,0× |

Referencia: 2 678 274 ciclos medidos en RTL para el mismo frame.

### El hallazgo: la lane hace un fetch que no necesita

Desde `step_request`, `gpu_lane.v` recorre seis estados:

```text
HALTED → FETCH_REQUEST → FETCH_WAIT → DECODE → EXECUTE → RETIRE
```

**Dos de ellos son un fetch propio** que no hace falta: el SM ya le entrega la
instrucción, y su `imem_ready` está atado a su propio `imem_valid`, así que no
espera a nadie — simplemente gasta los estados. Son un resto de cuando la lane
era una CPU completa.

Quitarlos vale:

- **1,43× sobre el cauce segmentado** (6,42 → 4,49 ciclos por instrucción);
- **y un 18% HOY, sin segmentar nada**: el modelo de coste da 2 185 888 ciclos
  contra los 2 678 274 medidos, o sea 17,63 → 14,39 ciclos por instrucción.

Ese segundo número es el interesante: es un cambio **local a un módulo**, del
mismo tipo que acortar el handshake de `gpu_imem_buffer` (que dio −12,5%), y no
depende de segmentar el SM. Se puede hacer ya, medir en placa con `profile.py`,
y seguir.

## Cómo leer estos números

Los dos modelos coinciden entre sí (975 693 contra 990 086, 1,5%), lo cual está
bien pero no demuestra nada sobre el RTL: comparten calibración. Lo que sí
respalda al conjunto es que 23 reproduce el diseño actual con `retired` y
`lsu_tx` exactos y los ciclos a −7,4%.

**Ese −7,4% es un sesgo optimista**, así que los 3,9× hay que leerlos como
"algo menos de 3,9×". Y el modelo no sabe nada de Fmax: si el cauce segmentado
baja el reloj, parte de la ganancia se va por ahí. Eso solo lo dice la síntesis.