# Contrato SM ↔ memoria

Todas las señales usan `clk`. Se acepta una transferencia en el flanco de subida
si `valid && ready`. El emisor mantiene `valid` y todo su payload estable hasta
esa aceptación. `ready` de petición significa **capturada**, nunca **completada**.
Reset vacía el protocolo y todos los participantes deben reiniciarse juntos.
No se presupone latencia fija ni se espera `ready` antes de afirmar `valid`.

## Petición vectorial

| Señal en `gpu_lsu` | Ancho | Significado |
|---|---:|---|
| `req_valid`, `req_ready` | 1 | Handshake del vector completo |
| `req_tag` | 3 | Warp, 0..7; no reutilizarlo hasta consumir su respuesta |
| `req_mask` | 8 | Un bit por lane activa |
| `req_write` | 1 | 0=LOAD, 1=STORE; común a todo el vector |
| `req_address` | 256 | Ocho direcciones de bytes de 32 bits |
| `req_data` | 256 | Ocho valores STORE de 32 bits |

Lane `l` ocupa `[32*l +: 32]`. Se aceptan direcciones arbitrarias por lane,
incluidas repeticiones y varios accesos al mismo banco. No existe asociación
fija lane↔banco. Las lanes fuera de máscara no producen accesos ni errores.
Una máscara cero es legal para la LSU y produce una respuesta sin accesos;
el SM normalmente no emite instrucciones de warps sin lanes activas.

Un solo handshake acepta todas las lanes: la implementación debe reservar
espacio suficiente antes de afirmar `req_ready`. La implementación BRAM tiene
exactamente un slot por tag. Solo puede entrar un vector por ciclo.
No hay operación por byte en esta frontera porque la ISA usa palabras completas.

## Respuesta vectorial

| Señal | Ancho | Significado |
|---|---:|---|
| `rsp_valid`, `rsp_ready` | 1 | Handshake de finalización |
| `rsp_tag` | 3 | Tag de la petición original |
| `rsp_data` | 256 | Ocho resultados LOAD, mismo orden de lanes |
| `rsp_error` | 8 | Error por lane activa |

Hay exactamente una respuesta por petición, también para STORE. No es necesario
conservar el orden de respuestas entre tags. Dentro de un tag solo hay una
petición en vuelo. Para STORE, la respuesta indica que todos los accesos han
terminado o fallado: no debe responder al mero encolado en un controlador externo.

Los datos de STORE, lanes inactivas y lanes con error no son significativos.
El SM guarda destino y máscara hasta recibir la respuesta; el backend no necesita
conocer números de registro, PC ni codificación de instrucciones.
La respuesta completa puede esperar con `rsp_ready=0`; el backend debe retenerla.
El SM acepta respuestas en las fronteras de ejecución para compartir el puerto
de escritura de los bancos de registros.

Un futuro controlador SDRAM puede descomponer el vector en ráfagas, combinar
lecturas o devolver los tags en otro orden sin cambiar el SM. Debe conservar
el orden de cada warp y la semántica de finalización de STORE para que BAR
funcione como sincronización de los accesos anteriores. No se exige rollback.
Si una operación falla, se responde igualmente y se indican las lanes afectadas.
Un backend que nunca responde impedirá drenar la GPU; el timeout, si se desea,
debe implementarlo ese backend como respuesta de error.

## Fetch

`imem_valid/imem_ready` transportan `imem_address` (32 bits, bytes).
`imem_rsp_valid/imem_rsp_ready` transportan una instrucción de 32 bits y
`imem_error`. Hay como máximo un fetch pendiente, por lo que no necesita tag.
El backend debe compartir el mismo espacio de direcciones con LOAD/STORE.

## Canales internos del backend BRAM

Cada uno de los ocho bancos recibe `bank_valid/ready`, `bank_row` de 12 bits,
`bank_data` de 32 bits y `bank_write`. Responde con sus propios
`bank_rsp_valid/ready`, datos y error. Solo hay una petición en vuelo por banco,
y la LSU guarda la lane de retorno. La ronda termina cuando todos los bancos
participantes responden. La latencia y la aceptación pueden ser diferentes en
cada banco; `gpu_lsu_tb.v` ejercita ambas posibilidades.

Estos canales describen bancos BRAM, no son el contrato que debe imponerse
a SDRAM. La compatibilidad futura se fija en el vector SM↔LSU descrito arriba.
