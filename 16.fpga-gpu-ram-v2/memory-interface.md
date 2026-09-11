# Contrato SM â†” memoria

Todas las seÃ±ales usan `clk`. Se acepta una transferencia en el flanco de subida
si `valid && ready`. El emisor mantiene `valid` y todo su payload estable hasta
esa aceptaciÃ³n. `ready` de peticiÃ³n significa **capturada**, nunca **completada**.
Reset vacÃ­a el protocolo y todos los participantes deben reiniciarse juntos.
No se presupone latencia fija ni se espera `ready` antes de afirmar `valid`.

## PeticiÃ³n vectorial

| SeÃ±al en `gpu_lsu` | Ancho | Significado |
|---|---:|---|
| `req_valid`, `req_ready` | 1 | Handshake del vector completo |
| `req_tag` | 3 | Warp, 0..7; no reutilizarlo hasta consumir su respuesta |
| `req_mask` | 8 | Un bit por lane activa |
| `req_write` | 1 | 0=LOAD, 1=STORE; comÃºn a todo el vector |
| `req_address` | 256 | Ocho direcciones de bytes de 32 bits |
| `req_data` | 256 | Ocho valores STORE de 32 bits |

Lane `l` ocupa `[32*l +: 32]`. Se aceptan direcciones arbitrarias por lane,
incluidas repeticiones y varios accesos al mismo banco. No existe asociaciÃ³n
fija laneâ†”banco. Las lanes fuera de mÃ¡scara no producen accesos ni errores.
Una mÃ¡scara cero es legal para la LSU y produce una respuesta sin accesos;
el SM normalmente no emite instrucciones de warps sin lanes activas.

Un solo handshake acepta todas las lanes: la implementaciÃ³n debe reservar
espacio suficiente antes de afirmar `req_ready`. La implementaciÃ³n BRAM tiene
exactamente un slot por tag. Solo puede entrar un vector por ciclo.
No hay operaciÃ³n por byte en esta frontera porque la ISA usa palabras completas.

## Respuesta vectorial

| SeÃ±al | Ancho | Significado |
|---|---:|---|
| `rsp_valid`, `rsp_ready` | 1 | Handshake de finalizaciÃ³n |
| `rsp_tag` | 3 | Tag de la peticiÃ³n original |
| `rsp_data` | 256 | Ocho resultados LOAD, mismo orden de lanes |
| `rsp_error` | 8 | Error por lane activa |

Hay exactamente una respuesta por peticiÃ³n, tambiÃ©n para STORE. No es necesario
conservar el orden de respuestas entre tags. Dentro de un tag solo hay una
peticiÃ³n en vuelo. Para STORE, la respuesta indica que todos los accesos han
terminado o fallado: no debe responder al mero encolado en un controlador externo.

Los datos de STORE, lanes inactivas y lanes con error no son significativos.
El SM guarda destino y mÃ¡scara hasta recibir la respuesta; el backend no necesita
conocer nÃºmeros de registro, PC ni codificaciÃ³n de instrucciones.
La respuesta completa puede esperar con `rsp_ready=0`; el backend debe retenerla.
El SM acepta respuestas en las fronteras de ejecuciÃ³n para compartir el puerto
de escritura de los bancos de registros.

Un controlador SDRAM puede descomponer el vector en rÃ¡fagas, combinar
lecturas o devolver los tags en otro orden sin cambiar el SM. Debe conservar
el orden de cada warp y la semÃ¡ntica de finalizaciÃ³n de STORE para que BAR
funcione como sincronizaciÃ³n de los accesos anteriores. No se exige rollback.
Si una operaciÃ³n falla, se responde igualmente y se indican las lanes afectadas.
Un backend que nunca responde impedirÃ¡ drenar la GPU; el timeout, si se desea,
debe implementarlo ese backend como respuesta de error.

## Fetch

`imem_valid/imem_ready` transportan `imem_address` (32 bits, bytes).
`imem_rsp_valid/imem_rsp_ready` transportan una instrucciÃ³n de 32 bits y
`imem_error`. Hay como mÃ¡ximo un fetch pendiente, por lo que no necesita tag.
El backend debe compartir el mismo espacio de direcciones con LOAD/STORE.

## Backend SDRAM de esta versión

`gpu_lsu` arbitra vectores y un puerto auxiliar de palabras con strobes por byte.
El puerto auxiliar recibe fetch durante ejecución y monitor con GPU detenida.
El rango válido se amplía a 32 MiB. Cada palabra se convierte en dos peticiones
`mem_req_*` de 16 bits al controlador; `mem_req_addr` cuenta medias palabras.
`mem_req_wmask` indica los bytes habilitados y el controlador invierte a DQM.
`mem_req_valid && mem_req_ready` acepta; `mem_done` termina, sin backpressure
en esta última señal. Solo hay una transferencia física pendiente.

La respuesta vectorial tiene un registro independiente del secuenciador SDRAM:
puede mantenerse con `rsp_ready=0` mientras progresa el fetch y otras lanes.
Los slots solo se liberan al consumir la respuesta. El arbitraje rota por lane
entre tags y alterna con el auxiliar. No se combinan accesos repetidos.
