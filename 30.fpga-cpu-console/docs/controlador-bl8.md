# Verificación del controlador BL8

El paso 1 del plan: `pruebas/sdram/sdram_controller.v` son 24 KB de Verilog sin
un solo banco de pruebas, y un controlador de SDRAM es el peor sitio donde
descubrir errores en la placa. Aquí está verificado, y **tenía dos fallos**.

## Lo que hacía falta antes de poder probar nada

El banco heredado de la 16, `sdram_controller_tb.v`, comprueba que los
**comandos** salen con la temporización JEDEC. Lo que no puede comprobar, porque
no hay memoria al otro lado, es que los **datos** acaben donde deben. Con BL1 eso
casi da igual: una palabra, un comando. Con ráfagas de ocho hay ocho
oportunidades de equivocarse de ciclo, y una sola basta para leer la palabra del
vecino.

Así que primero hay un modelo: [`sdram_model.v`](../sdram_model.v), conductual,
del W9825G6KH. Guarda y devuelve datos con la latencia CAS y la secuencia de
ráfaga que diga el registro de modo, verifica la secuencia de arranque —nada
antes del retardo de encendido, precarga general, ocho refrescos, MRS, en ese
orden— y cuenta las violaciones de tRCD, tRP, tRAS, tRC, tRFC y tMRD.

Un detalle del modelo que es una decisión y no un descuido: son 4 bancos × 32
filas × 512 columnas, y **protesta si se activa una fila fuera de rango** en vez
de aliasear en silencio. Aliasear taparía justo un error de decodificación de
fila, que es de los que hay que cazar aquí.

## Fallo 1: el fichero no elaboraba

```verilog
$error(
    "sdram_controller_128: "
    "req_addr must be aligned to 8 SDRAM words / 16 bytes"
);
```

Dos literales pegados no son Verilog, aunque en C lo sean. `iverilog` lo rechaza
con `Malformed statement`. Nadie se había enterado porque el fichero no estaba
en ningún proyecto: sin un banco, nunca se había compilado.

## Fallo 2: la ráfaga salía corrida un beat

Éste es el de verdad.

Con CL2 la SDRAM presenta D0 dos ciclos después del comando READ, y el
controlador BL8 muestrea exactamente ahí:

```text
ST_READ_CMD (T)  ->  ST_READ_LATENCY (T+1)  ->  ST_READ_BURST (T+2, captura)
```

Sobre el papel es correcto. En la placa no, y el propio repositorio tenía la
prueba: el `sdram_controller` BL1 de la 16, que lleva meses funcionando, captura
**un ciclo más tarde**:

```text
ST_READ (T) -> ST_READ_WAIT0 -> ST_READ_WAIT1 -> ST_READ_CAPTURE (T+3)
```

No es margen de sobra. Entre que la FPGA emite el comando y ve el dato de vuelta
están el camino de salida, el pin, la pista, el pin de vuelta y el camino de
entrada, y a 100 MHz eso pasa de un ciclo.

El modelo lo reproduce con `READ_DELAY_CYCLES`: 0 es JEDEC sobre el papel, 1 es
esta placa. Con 1, la lectura de la ráfaga sale así:

```text
leído    0edd 0dcc 0cbb 0baa 0a99 0988 0877 zzzz
esperado 0fee 0edd 0dcc 0cbb 0baa 0a99 0988 0877
```

Los ocho beats corridos una posición, y el beat 0 capturando alta impedancia.
Es el aspecto exacto de un off-by-one de muestreo, y en la placa se habría visto
como memoria que devuelve basura sin ningún patrón obvio.

El arreglo es un parámetro nuevo, `READ_DELAY_CYCLES`, con valor por defecto
**1**, que alarga `ST_READ_LATENCY` un ciclo. Es parámetro y no una constante
para que el punto de muestreo sea algo que se declara y se prueba, no algo que se
deduce contando estados.

## Cómo está montado el banco

[`sdram_controller_128_tb.v`](../sdram_controller_128_tb.v) instancia **tres**
sistemas completos, cada uno con su propio modelo de memoria:

| | controlador | modelo | qué demuestra |
|---|---|---|---|
| `ctrl_ideal` | sin margen | sin retardo | que el parámetro a 0 sigue siendo coherente |
| `ctrl_placa` | margen 1 | retardo 1 | **el que manda**: coincide con hardware que funciona |
| `ctrl_malo` | sin margen | retardo 1 | el control negativo, que **tiene** que fallar |

El tercero es el que convierte esto en una prueba. Sin él, el banco aprobaría
igual aunque alguien devolviera `READ_DELAY_CYCLES` a cero, que es exactamente
el fallo que este fichero existe para haber encontrado. El banco comprueba que
lee mal, y lo imprime.

Los casos, sobre `ctrl_placa`:

1. **Ida y vuelta de una ráfaga entera**, con un valor distinto y reconocible en
   cada beat, para que un error de ciclo se vea y se sepa de cuánto es.
2. **Otra dirección, en otro banco y otra fila**, para que un error de
   decodificación no se esconda detrás de la dirección cero; y se comprueba que
   la primera ráfaga sigue intacta.
3. **Máscara de byte**, escribiendo solo el byte bajo del beat 0 y el alto del
   beat 7 sobre un fondo conocido. Es lo que permite al monitor escribir un byte
   sin destruir los otros quince.
4. **Máscara a cero**, que no debe cambiar nada.
5. **Sobrevivir a un refresco.**

Y al final se leen los contadores de violaciones JEDEC de los dos modelos.

## Lo que este banco todavía no cubre

- **Solicitudes mal alineadas.** El controlador tiene un `$error` para
  `req_addr[2:0] != 0`, pero comprobar que salta exigiría que el banco provocara
  un `$error` a propósito, y `apio test` lo trataría como fallo.
- **tRAS y tRC con la fila abierta entre ráfagas.** Hoy no aplica porque cada
  ráfaga lleva auto-precarga, pero es el escalón siguiente que el plan menciona,
  y el modelo ya tiene las comprobaciones puestas para cuando llegue.
- **CKE bajo.** El modelo protesta si llega un comando con CKE bajo; este
  controlador nunca lo baja, así que la comprobación está esperando a que alguien
  añada un modo de bajo consumo.
