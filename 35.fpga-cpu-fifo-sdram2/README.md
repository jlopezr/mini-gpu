# CPU a 80 MHz sobre fabric FIFO con SDRAM de cuatro bancos en paralelo

Prototipo derivado de `34.fpga-cpu-fifo`. Los masters, los puertos del fabric, los
dominios de reloj y los LED son los mismos; lo que cambia es el camino entre las
colas del fabric y los pines de la SDRAM. Es la fase 3 de
[`propuesta-fabric6-pipeline.md`](propuesta-fabric6-pipeline.md): varias operaciones
realmente en vuelo dentro del controlador.

## Qué cambia respecto a la 34

El controlador secuencial hacía `ACTIVE`, esperar tRCD, `READ`/`WRITE`, ráfaga y
esperar tRP antes de aceptar nada más: unos 16 ciclos por petición de 16 bytes, con
el bus de datos útil solo en 8.

`sdram_controller_128.v` tiene ahora un **slot de petición por banco** y una
temporización independiente por banco. Mientras un banco espera tRCD o su
precarga automática, otro recibe su `ACTIVE` o saca su ráfaga. Solo se serializa
lo que es físicamente único:

- el bus de comandos (un comando por ciclo);
- el bus de datos (una ráfaga BL8 cada vez, con 1 ciclo de guardia al pasar de
  leer a escribir);
- tRRD entre dos `ACTIVE`.

Política:

- **página cerrada**, como la 34: cada acceso es `ACTIVE` + `READ`/`WRITE` con
  auto-precarga;
- los `ACTIVE` se **adelantan**: un slot cuyo banco está libre recibe su `ACTIVE`
  sin esperar turno, el más antiguo primero;
- los `READ`/`WRITE` salen **en orden de llegada**, de modo que las respuestas
  salen en el orden de las peticiones sin buffers de reordenación;
- las salidas hacia la SDRAM son **registros** (la 34 las generaba combinacionalmente
  desde el estado) y las escrituras copian su dato a un buffer común, de modo que
  el slot queda libre en cuanto sale el comando;
- refresco: con el temporizador vencido deja de aceptar peticiones, deja que se
  vacíen los slots, comprueba los cuatro bancos precargados y emite `REFRESH`.
  `MAX_ACCESS_CYCLES` pasa de 32 a 64 para cubrir ese vaciado.

El banco se decodifica del bit 10:9 de la dirección de palabra, es decir, cambia
cada 1 KiB. Un recorrido secuencial largo de un solo master se queda en un banco; el
paralelismo se ve cuando varios masters (CPU, scanout, monitor, generadores)
atacan regiones distintas.

### Interfaz con el fabric

La interfaz de señales no cambia, la semántica sí:

- `req_ready` depende de la dirección: es el slot de su banco el que debe estar libre;
- puede haber hasta cuatro peticiones aceptadas más las que esperan `done`;
- `done` es un pulso **por petición aceptada, en orden**; `rdata` es válida en ese
  ciclo (en una escritura no significa nada).

`memory_fabric_fifo_6.v` sustituye el backend secuencial por una etapa de emisión,
una FIFO de destinos (`meta`) que se empuja al aceptar el controlador y se
vacía con cada `done`, y un contador de créditos: solo se emite si
`meta + cola de respuestas < 8`. Así cada `done` encuentra hueco en la cola global
de respuestas y el controlador no necesita contrapresión de salida. Una dirección
inválida no llega al controlador, pero viaja marcada como error por la misma FIFO
para no adelantar a las anteriores.

## Rendimiento en simulación

Lecturas de 16 bytes contra el modelo JEDEC, 100 MHz, ciclos por petición:

| Patrón | 34 (secuencial) | 35 |
|---|---:|---:|
| alternando los cuatro bancos | 17,21 | 8,19 |
| siempre el mismo banco | 17,21 | 12,32 |
| lecturas y escrituras alternadas, cuatro bancos | 16,71 | 9,19 |

Medido con `sdram_bank_parallel_tb.v` contra el controlador de cada carpeta (el
de la 33 y el de la 34 son idénticos). A 100 MHz, 16 B por petición:
93 MB/s en la 34 y 195 MB/s en la 35 en el mejor caso, sobre un pico de 200 MB/s.

8 ciclos es el límite del bus de datos con ráfagas BL8. El mismo banco queda
limitado por el ciclo de fila (`ACTIVE` → precarga → `ACTIVE`).

## Timing

Build con semilla 12 (la de la 34, sin cambiar): memoria 102,8 MHz para 100,
CPU 84,95 MHz para 80, píxel y TMDS con margen; 19.194 LUT, 11.465 FF, 10 EBR.
Es una semilla afortunada: un barrido de las semillas 1 a 8 no cierra ninguna
(memoria 89 a 99 MHz, CPU 66 a 78 MHz). Cualquier cambio de RTL puede perder el
cierre y exige re-barrer.

Caminos críticos del build con semilla 12:

- reloj de CPU: decodificador MMIO (`mmio_address` → comparador de `palabra`
  contra `PERF_SLOTS`), heredado de la 34;
- reloj de memoria: lógica de decisión del controlador desde `ref_state`.

## Validación

- `sdram_bank_parallel_tb.v` (nuevo): peticiones sin esperar respuesta contra el
  modelo de SDRAM, con marcador de referencia, vigilante de tRRD y del bus de
  datos, tráfico aleatorio con pausas durante decenas de refrescos y medida de
  ciclos por petición. Corre con `READ_DELAY_CYCLES` 0 y 1. Se comprobó que
  detecta tres mutaciones del controlador (guardia de cambio de sentido, tRP tras
  lectura y tWR tras escritura);
- `sdram_controller_128_tb.v` (de la 30): el banco secuencial, intacto;
- `memory_fabric_fifo_6_tb.v`: controlador simulado en tubería; añade errores
  que conservan su sitio en el orden y el límite de créditos con todos los
  destinos bloqueados;
- el resto, como en la 34.

## Placa

En ULX3S 85K, con los dos generadores de tráfico activos (7 de octubre de 2026):
monitor 5.35, 28 casos de CPU (basics, alu, errores, vídeo, programas) y después
tres rondas de los 62 casos de `cases-cpu` y `cases-shared` (sin `input`, que
esta placa no tiene): 186 ejecuciones, 0 fallos, unos 164 s seguidos. El vídeo
mantiene unos 58 FPS en pacman. Esto cubre la calibración de `READ_DELAY_CYCLES`
a 100 MHz con lecturas encadenadas sin hueco.

No se pudieron mirar los LED de mismatch y de error de respuesta de los
generadores (pegajosos), así que lo comprobado es el comportamiento de CPU y
vídeo, no esos dos indicadores.

## Pendiente
- Reutilizar filas abiertas (página abierta) para que el recorrido secuencial de
  un solo master también gane.

La identificación de placa es monitor `5.35`.
