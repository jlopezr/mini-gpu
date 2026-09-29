# Medida inicial: en qué se van los 258 ciclos por palabra

Paso 0 del plan de la carpeta 18, antes de escribir una línea de RTL. La
pregunta que decide el encargo es si esos ciclos son comandos de SDRAM —que es
lo único que una ráfaga BL8 puede abaratar— o handshake y estados de CPU, que
siguen ahí con ráfaga o sin ella.

La respuesta corta: **son comandos de SDRAM, el 55 %**, así que el plan se
sostiene. Pero la medida reordena las prioridades, y eso sí cambia el encargo.
Está al final, en «Lo que esto cambia».

## Cómo se mide

`perf_probe_tb.v` instancia seis sistemas completos —CPU real,
`sdram_system_adapter` real— que corren el mismo programa en paralelo. Lo único
que cambia entre los cuatro primeros es la **latencia del modelo de memoria**:
los ciclos desde que acepta la petición hasta que responde `done`. Eso separa
las dos partidas sin estimar ninguna:

```text
ciclos(L) = A + N_accesos × L
```

La pendiente es lo que la ráfaga puede abaratar; la ordenada `A` es el suelo de
handshake y de CPU. No hay que confiar en el ajuste: el banco **comprueba que la
recta es recta**, exigiendo que los puntos intermedios caigan exactos, y que la
pendiente sea exactamente el número de accesos contados.

El programa es el bucle interior real de `swap_demo_fast`, aislado en
[`../examples/perf_loop.asm`](../examples/perf_loop.asm), 160 iteraciones (una
línea de framebuffer):

```asm
draw_word:
    STORE R13, R6, 0
    ADDI  R6, R6, 4
    ADDI  R3, R3, 1
    BLT   R3, R25, draw_word
```

`L = 8` es el punto que reproduce la placa: es lo que cuesta una lectura en el
`sdram_controller` de la 16 a 100 MHz (IDLE + ACTIVE + 2 de tRCD + READ + 2 de
espera + captura). Una escritura cuesta 7.

El programa se precarga con `$readmemh` desde `perf_loop.hex`, que está
versionado a propósito para que el banco no dependa del ensamblador. Se
regenera desde el `.asm` con `../1.isa/mini_asm.py`.

## El barrido

Cada iteración son 4 instrucciones y una escritura: **645 búsquedas y 160
accesos de datos**, todos de 32 bits, que sobre un bus de 16 son **1 610 accesos
físicos**. El vídeo está en reposo en estos cuatro.

| | ciclos | por palabra | SDRAM | adaptador | CPU |
|---|---:|---:|---:|---:|---:|
| `L = 0`  | 10 465 |  65,4 | 15 % | 54 % | 31 % |
| `L = 4`  | 16 905 | 105,7 | 48 % | 33 % | 19 % |
| `L = 8`  | 23 345 | 145,9 | 62 % | 24 % | 14 % |
| `L = 16` | 36 225 | 226,4 | 76 % | 16 % |  9 % |

El ajuste sale exacto: `ciclos(L) = 10 465 + 1 610 × L`. Con el controlador
real, `L = 8`:

| | ciclos | |
|---|---:|---|
| Comandos de SDRAM | 12 880 | **55 %** — lo único que BL8 ataca |
| Handshake del adaptador | 7 245 | 31 % |
| CPU multiciclo | 3 220 | 14 % |

O sea: de los ~14,5 ciclos por acceso de 16 bits, **8 son la SDRAM y 6,5 son
suelo**. La ráfaga no ataca esos 6,5.

## Lo que la ráfaga no arregla, pero el búfer sí

Ese suelo de 6,5 ciclos por acceso parece intocable, y no lo es: **es suelo por
acceso, no por instrucción**. Si ocho accesos de 16 bits pasan a ser una sola
petición de 128 bits, el handshake se paga una vez en lugar de ocho. Por eso el
plan insiste en que BL8 sin búferes no mejora nada, y también en el sentido
contrario: el 45 % que la ráfaga no toca lo tocan los búferes.

El quinto sistema pone número a eso. Es idéntico al de `L = 8`, pero las
búsquedas de instrucción se sirven en un ciclo sin pasar por el adaptador ni por
la SDRAM: un búfer de instrucciones que nunca falla.

| | ciclos | por palabra | SDRAM | adaptador | CPU |
|---|---:|---:|---:|---:|---:|
| `L = 8` | 23 345 | 145,9 | 62 % | 24 % | 14 % |
| `L = 8`, imem ideal | 8 510 | **53,2** | 34 % | 13 % | 53 % |

**2,74× sin tocar el camino de datos**, y sin necesitar BL8 para nada. Es el
techo, no lo que dará un búfer real: uno de verdad falla al menos una vez por
línea, y hay que vaciarlo al arrancar la CPU.

Lo que más importa de esa tabla es la última columna. Con las búsquedas fuera,
**la CPU multiciclo pasa a ser la mayoría del tiempo**, el 53 %. Los 4 000
ciclos que quedan de memoria son todo lo que el punto 4 del plan —la combinación
de escrituras— puede llegar a recortar, y aun quitándolos enteros el resultado
no bajaría de ~28 ciclos por palabra.

Nota de lectura: en ese sistema la espera de un ciclo por búsqueda cae en la
columna de CPU, porque ya no pasa por el adaptador. No es que la CPU se haya
vuelto más lenta.

## El hueco con la placa, y de dónde sale

145,9 ciclos por palabra en simulación contra **258 medidos en placa**. Esa
diferencia no es error de medida: es que los cuatro sistemas del barrido tienen
el vídeo en reposo, y en la placa el scanout compite por la SDRAM.

El sexto sistema lo añade, con el ciclo de trabajo real del lector —320 accesos
de 16 bits por cada par de líneas de pantalla, 6 400 ciclos— y contra el árbitro
real, `VIDEO_RUN = 4` incluido:

| | ciclos | por palabra | SDRAM | adaptador | CPU |
|---|---:|---:|---:|---:|---:|
| `L = 8`, sin vídeo | 23 345 | 145,9 | 62 % | 24 % | 14 % |
| `L = 8`, con vídeo | 36 065 | **225,4** | 64 % | 26 % | 10 % |
| en placa | | 258 | | | |

De 145,9 a 225,4: **el scanout se lleva el 35 % del tiempo de la CPU**. Y el
modelo se queda a un 13 % de la cifra de placa, por debajo, que es el lado
correcto: aquí no se modelan el refresco ni la latencia asimétrica de escritura.
El banco exige que caiga en esa banda, así que si alguien cambia el árbitro y el
número se sale, salta.

Ese 35 % es el argumento más fuerte a favor del punto 2 del plan, y el plan lo
justifica por otro motivo —que un fallo de vídeo se ve en pantalla—. Los dos
valen, pero este es cuantitativo: **el vídeo es el segundo consumidor, no un
detalle**, y sus 320 accesos consecutivos por línea son el caso perfecto para
BL8: 40 ráfagas en vez de 320 accesos sueltos.

### Un aviso sobre el modelo de vídeo

El cliente sintético no termina el relleno a tiempo **3 veces** en las 160
iteraciones. En la placa `underflow` está a cero, así que eso es pesimismo del
modelo, no un fallo encontrado: el cliente pide palabra a palabra sin adelantar
trabajo y añade el ciclo de hueco de `video_req` en cada acceso. Se cuenta en
vez de colgar el banco, que es lo que hacía la primera versión.

## Las dos trampas que costó cada una un rato

- **La CPU sale del reset ya en `halted`.** Contar «hasta que `halted` suba» da
  cero ciclos en todos los sistemas, con un informe entero de ceros que parece
  un fallo de los contadores. Hay que ver primero que la CPU ha arrancado.
- **El árbitro exige ver bajar `video_req` entre concesiones.** `STATE_RELEASE`
  no vuelve a `IDLE` con `video_req` alto, así que un cliente de vídeo que
  mantenga el nivel —que es lo que parece razonable escribir— deja el adaptador
  atascado ahí para siempre. El lector real baja la petición al recibir su
  `ready` y la sube un ciclo después; el README de la 16 lo dice, y hay que
  reproducirlo.

## Lo que esto cambia

El plan sobrevive: los comandos de SDRAM son el 55 %, no el handshake, así que
la ráfaga tiene de dónde sacar. Pero el reparto medido reordena los pasos 2, 3
y 4:

1. **El búfer de instrucciones (paso 3) sigue siendo lo más grande, 2,74×, y no
   necesita BL8.** Podría hacerse sobre la 16 tal cual. BL8 lo mejora —rellenar
   una línea de 16 bytes pasa a ser una ráfaga en vez de ocho accesos— pero no
   es su requisito.
2. **El vídeo (paso 2) vale más de lo que el plan le atribuye.** No es solo el
   cliente más fácil de depurar: es el 35 % del tiempo de la CPU, y el que mejor
   encaja en una ráfaga.
3. **La combinación de escrituras (paso 4) es lo más pequeño**, tal como el plan
   sospechaba: 4 000 ciclos de 8 510 una vez hechos los otros dos, y con el
   riesgo de vaciado que el plan describe.
4. **Aparece un tope que no estaba en el plan.** Con los tres pasos hechos, la
   CPU multiciclo es la mayoría del tiempo restante. El punto 1 del `TODO.md`
   —«Optimizar LSU»— deja de ser una nota al pie y pasa a ser el siguiente
   cuello de botella real.

## Cómo repetir la medida

```powershell
..\.venv\Scripts\apio.exe test perf_probe_tb.v
```

Para regenerar `perf_loop.hex` tras tocar el `.asm`:

```powershell
..\.venv\Scripts\python.exe ..\1.isa\mini_asm.py examples\perf_loop.asm -o perf_loop.bin
```

y convertir el binario a medias palabras hexadecimales, una por línea.
