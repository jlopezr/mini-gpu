# Combinación de escrituras

Paso 4 del plan, y el que este avisaba de que era el más delicado. No por la
combinación, que es fácil, sino por los **vaciados**.

## Qué hace

[`cpu_dmem_adapter.v`](../cpu_dmem_adapter.v) guarda **una línea de 16 bytes**
con su máscara de byte. Mientras la CPU siga escribiendo dentro de esa línea, las
escrituras se funden ahí y se contestan **en un ciclo**, sin tocar la memoria. Al
salirse de la línea, se vuelca de una sola ráfaga.

Cuatro `STORE` consecutivos con `+4` —que es exactamente el bucle interior de
[`swap_demo_fast`](../examples/swap_demo_fast.asm)— caben en una línea. Así que
las 160 escrituras de una línea de framebuffer pasan de **160 ráfagas a 40**, y
la CPU deja de esperar a la memoria en tres de cada cuatro.

| | ciclos por palabra | ráfagas |
|---|---:|---:|
| La 16 | 145,9 | (1 610 accesos de 16 bits) |
| Camino de ráfagas | 49,7 | 163 |
| **Con combinación** | **35,2** | **42** |

**4,15× sobre la 16**, o 3,32× netos contando que el reloj es un 20 % más lento.

## Por qué no es una caché

El motivo no es el coste: es que **el subsistema de vídeo lee el framebuffer de
la SDRAM por su cuenta**. Una caché con escritura diferida guardaría píxeles que
el barrido no puede ver, y saldría la imagen a medias sin que el programa haya
hecho nada mal.

Un búfer de combinación acaba escribiéndolo todo, solo que a tandas. Lo que pide
a cambio son tres vaciados forzados.

## Los tres vaciados, y cómo se prueban

[`write_combine_tb.v`](../write_combine_tb.v) dedica la mitad de su extensión a
esto, y cada vaciado tiene **control negativo comprobado**: se quitó del RTL y se
verificó que el banco falla.

### 1. Cualquier acceso MMIO

Cubre el caso importante, que es escribir el registro `SWAP`. Y aquí está la
parte fina: **comprobar «después del SWAP la memoria tiene los píxeles» no prueba
nada**, porque el vaciado podría haber ocurrido justo después y en la placa se
vería un frame a medias igual. Lo que hay que comprobar es el **orden**.

El banco lleva un vigilante permanente que baja `orden_ok` si `mmio_req` sube
alguna vez con el búfer sucio, en cualquier ciclo del banco entero. Quitando el
vaciado:

```
FALLO: `mmio_req` subio con el bufer todavia sucio: el SWAP
       podria adelantar a los pixeles del frame
```

### 2. Al parar la CPU

Para que el monitor lea memoria de verdad. Y **no basta con empezar el vaciado**:
el monitor no puede tocar la SDRAM hasta que termine.

Aquí el banco encontró un fallo real. La primera versión sacaba
`wb_dirty = wb_valid`, y `wb_valid` se limpia al **arrancar** el volcado, no al
terminarlo. O sea que la señal bajaba antes de que el dato estuviera en memoria y
la carrera que existía para cerrar seguía abierta: la CPU para, el PC lee
inmediatamente y ve el frame anterior. La señal es ahora
`wb_valid || wb_flushing`, y el banco comprueba que al bajar, la memoria **ya**
tiene el dato:

```
FALLO rafagas provocadas por el halt: 0, esperado 1
FALLO: al bajar wb_dirty la memoria tiene 00000000000000000000000000000000
```

Del otro lado, [`monitor_mem_adapter_128.v`](../monitor_mem_adapter_128.v) tiene
un estado nuevo, `ST_WAIT_FLUSH`, que espera a que `wb_dirty` baje antes de pedir
nada a la SDRAM. La petición ya está capturada para entonces, así que el pulso de
un ciclo del monitor no se pierde por esperar.

### 3. Una lectura que caiga en la línea guardada

Devolvería el dato viejo de la SDRAM. Se vuelca y luego se lee.

Y su control negativo es al revés: **una lectura a otra línea no vacía nada**. Si
vaciara siempre, la combinación no serviría en un bucle que mezclara `LOAD` y
`STORE`. El banco comprueba las dos direcciones del caso.

## Escribir sin leer antes

El volcado **no** necesita leer la línea primero: la máscara de byte del
controlador, de 16 bits, deja intactos los bytes que nadie escribió. Sin esa
máscara habría que hacer lectura-modificación-escritura y la combinación no
compensaría —cada volcado costaría dos ráfagas en vez de una—.

El banco lo comprueba con máscaras parciales: dos escrituras de media palabra en
la misma línea, sobre un fondo de `0xff`, y solo pueden cambiar los cuatro bytes
marcados.

## Lo que cuesta

| | antes | después |
|---|---:|---:|
| LUT | 8 624 | 8 733 |
| FF | 4 713 | 4 456 |
| Semillas que cierran a 80 MHz | 8 de 8 | **8 de 8**, 83,1 a 93,2 MHz |

Los biestables bajan porque el camino de datos deja de necesitar parte del
secuenciado anterior; los 128 bits de la línea y sus 16 de máscara se compensan
con creces.

## Lo que este paso NO resuelve

**Sigue habiendo una ventana en la que el vídeo puede leer píxeles a medias**, y
es inherente al diseño: entre que la CPU escribe la primera palabra de una línea
y que el búfer se vuelca, esos 16 bytes no están en la SDRAM. Lo que garantiza el
vaciado por MMIO es que **al llegar el `SWAP` el frame está entero**, que es lo
que hace falta con doble búfer. Un programa que dibuje sobre el framebuffer
visible —los `tear_demo`— verá un desgarro ligeramente distinto al de la 16, y
eso es esperable.

**La combinación es de una sola línea.** Un bucle que alterne entre dos zonas de
memoria separadas volcará en cada alternancia y no ganará nada. Para el
framebuffer, que se recorre en orden, es el caso bueno.
