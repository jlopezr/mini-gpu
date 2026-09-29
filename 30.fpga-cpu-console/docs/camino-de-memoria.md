# El camino de memoria en ráfagas

Cómo queda `top.v` después de sustituir el camino de 16 bits de la 16 por uno de
128, y qué costó que cerrara temporización.

## La forma cambia, no solo el ancho

La 16 tenía **un solo bloque**, `sdram_system_adapter`, que arbitraba monitor,
CPU y vídeo contra un controlador de 16 bits, y de paso decodificaba la ventana
de registros de vídeo. Aquí cada cliente tiene su propio adaptador y su propio
puerto del árbitro:

```text
                     ┌── p0  cpu_dmem_adapter        ── dmem 32 bits + MMIO
 sdram_controller_128┤── p1  instruction_buffer      ── imem 32 bits
         ▲           ├── p2  video_line_source_burst    (nativo, urgent)
         │           └── p3  monitor_mem_adapter_128  ── monitor, byte a byte
   memory_fabric_4
```

El puerto 1 está pensado en `pruebas/sdram` para una GPU; aquí lo ocupa el búfer
de instrucciones, que es el cliente de solo lectura que más tráfico mueve. Cuando
llegue la GPU habrá que ensanchar el árbitro, y esa conversación es mejor tenerla
con el reparto ya medido.

## Escribir sin leer antes

El detalle que hace que esto no sea más lento de lo que parece: **una escritura
de 32 bits dentro de una línea de 16 bytes no necesita leer la línea antes**. La
máscara de byte del controlador —16 bits, uno por byte— deja intactos los otros
doce. Lo mismo vale para el byte suelto del monitor, que solo activa uno de los
dieciséis.

Sin esa máscara, cada `STORE` sería lectura-modificación-escritura y el camino
nuevo sería peor que el viejo. Es la razón de que la interfaz del controlador
lleve `req_wmask[15:0]` y no un simple `write`.

## Lo que aparece al partir el adaptador en cuatro

La ventana de registros de vídeo tiene **un solo puerto** y ahora tiene **dos
clientes**: el adaptador de datos de la CPU y el del monitor. En la 16 no hacía
falta arbitrar porque la máquina de estados única ya los serializaba.

[`mmio_mux.v`](../mmio_mux.v) los reparte. Un acceso MMIO se resuelve en un
ciclo, así que basta con atender a uno y que el otro espere; no hace falta cola.
El monitor va primero porque sus peticiones son raras y las de la CPU son un
bucle que puede esperar, y así un `SWAP` escrito desde el PC no se queda detrás
de un programa que dibuja a toda velocidad.

Tiene una trampa que costó encontrar al escribirlo: al confirmar no vale volver a
mirar `a_req`. Si se concedió a B y A pide en ese mismo ciclo, se confirmaría al
que no era. Hay que recordar a quién se concedió.

## Temporización: de 84 a 100 MHz

La primera integración que funcionaba en simulación se quedó en **84,42 MHz**
contra una restricción de 100. Conviene insistir en que `apio build` usa
`--timing-allow-fail` y **genera bitstream igualmente**: si no se lee la
frecuencia alcanzada, esto se lleva a la placa sin enterarse.

Dos causas, y la segunda no era la que parecía:

**Comparadores de magnitud de 32 bits.** Al escribir los adaptadores nuevos puse
`address < SDRAM_SIZE_BYTES`, que es una resta de 32 bits, donde la 16 comparaba
siete bits (`address[31:25] == 0`). Estaban en los tres adaptadores y cuatro
veces más en el árbitro, todos dentro de conos de decisión. Se cambió por una
máscara de los bits altos, que vale porque el tamaño es potencia de dos y no ata
el módulo a los 32 MiB.

**`urgent` combinacional, que era el de verdad.** Arreglar lo anterior dejó la
frecuencia en **77,98 MHz**, o sea peor. El camino crítico había cambiado de
sitio: `late_count` del lector de vídeo → comparador de 16 bits → `urgent` → la
concesión del árbitro → todo lo demás, porque de la concesión cuelga el sistema
entero. Registrar `urgent` lo sube a **100,21 MHz**. Un ciclo de retraso en «voy
con retraso» no cambia nada, porque el umbral son miles de ciclos.

La lección es la de siempre y volvió a costar un build: **arreglar el camino
crítico no mejora nada si el siguiente está igual de mal**. El primer arreglo era
correcto y por sí solo empeoró el número.

### Y aun así, 100 MHz no sale

Con una semilla suelta llegó a dar 100,21 MHz, que parecía suficiente. El barrido
completo dijo otra cosa: **1 de 8 semillas**, y por un 0,2 %. Eso no es cumplir,
es tener suerte.

Se probaron dos cosas más:

- **Registrar la concesión del árbitro**, para que `req_ready` dejara de ser
  combinacional desde `req_valid`. Es correcto, sale **gratis** —el ciclo extra
  se solapa con la espera de la respuesta, el bucle sigue en 7 951 ciclos— y de
  paso elimina la trampa de handshake. Se queda.
- **Partir la búsqueda del búfer en dos ciclos**, con la comparación arrancando
  de un registro local en vez del `imem_address` de la CPU. Costaba un 8 % de
  rendimiento y **no compró ni una semilla**: seguía cerrando 1 de 8. Se
  deshizo, y queda anotado en el propio módulo para que nadie lo reintente.

Barrido final con la restricción en 100: entre **83,91 y 91,79 MHz, mediana
86,4, ninguna semilla cumple**. En ese punto el camino es de routing casi puro
—8,75 ns de 11,2— y cruza `urgent` → concesión → adaptadores → controlador, que
son cuatro bloques repartidos por el dado. Eso no se arregla acortando lógica,
porque las celdas están físicamente lejos. Es el mismo techo que el README de la
16 describe para el camino del monitor.

### Se baja el reloj a 80 MHz, como hizo la 16

| | 16 | 18 con 100 MHz | 18 con 80 MHz |
|---|---:|---:|---:|
| Semillas que cumplen | 8 de 8 | **0 de 8** | **8 de 8** |
| Rango alcanzado | 106,5–114,6 | 83,9–91,8 | 88,8–98,1 |

El criterio es el de la 16, y por el mismo motivo: **la lotería de semillas deja
de decidir si el diseño funciona**.

80 MHz no es una frecuencia redonda elegida al azar. Tenía que cumplir tres
cosas a la vez:

1. **Quedar por debajo de la peor semilla** (83,91), para que cumplan las ocho.
2. **Ser alcanzable con el PLL desde 25 MHz.** Con `fref = 5 MHz`,
   `CLKFB_DIV = 16` da 80 MHz y `CLKOP_DIV = 8` deja el VCO en 640 MHz, dentro
   de rango.
3. **Conservar el baudio**, que es lo que más agradece no tocar. El divisor de
   UART tiene que ser múltiplo de cuatro y dar un baudio que el FTDI genere
   exacto: **divisor 80 → 1 Mbaud**, que es 3/3, y 80 es múltiplo de cuatro. No
   hay que tocar `monitor.py` ni los scripts.

Otras frecuencias fallaban alguna de las tres. 88,89 MHz (VCO 800/9) daba un
baudio exacto de 888 889 con divisor 100, pero solo cumplían dos semillas. 87,5
y 83,33 MHz cumplían más semillas pero no admiten ningún divisor múltiplo de
cuatro con baudio exacto por encima de 166 kbaud.

**El coste**: la CPU va un 20 % más lenta. Sobre una mejora de 2,94×, el
resultado neto en tiempo real es **2,35×** respecto a la 16. Y la versión del
monitor sube a **1.11**, porque un bitstream con otro reloj es otro bitstream.

## Lo que se conserva sin instanciar

`sdram_controller` (BL1) y `sdram_system_adapter` siguen en la carpeta y sus
bancos siguen pasando, aunque `top.v` ya no los use. No es descuido: son la
**línea base** contra la que se compara este camino, y `perf_probe_tb.v` los mide
para producir los 145,9 ciclos por palabra con los que se compara todo lo demás.
Es el mismo criterio por el que la 16 conserva `video_line_source_pattern.v`.
