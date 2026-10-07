# CPU a 80 MHz sobre fabric FIFO de seis puertos

Prototipo derivado de `33.fifo-mem` que integra progresivamente la CPU y el
scanout de `30.fpga-cpu-console` sin retirar la carga de diagnóstico.

## Dominios de reloj

- CPU, monitor, periféricos y generadores: 80 MHz;
- fabric FIFO y controlador SDRAM: 100 MHz;
- vídeo: 25 MHz de píxel y 125 MHz TMDS.

Todos los masters cruzan al dominio de memoria mediante `fabric_fifo_bridge`.
El fabric mantiene sus colas globales de ocho comandos y ocho respuestas.

## Puertos del fabric

| Puerto | Cliente |
|---|---|
| p0 | CPU datos |
| p1 | CPU instrucciones |
| p2 | scanout, con `urgent` |
| p3 | monitor UART |
| p4 | generador de tráfico, región `0x01D00000` |
| p5 | generador de tráfico, región `0x01E00000` |

La CPU conserva puertos separados para instrucciones y datos, como en la 30.
Esto permite encolar ambos tipos de petición simultáneamente y evita que una
operación de datos bloquee artificialmente el siguiente miss de instrucciones.
Una futura integración de GPU probablemente justificará ampliar otra vez el
número de puertos.

Los dos generadores arrancan habilitados y sin prioridad urgent. De este modo
el prototipo prueba desde el arranque CPU y vídeo bajo contención sostenida.
Ocupan dos MiB al final de SDRAM para no pisar programas, resultados de
tests ni los framebuffers que comienzan en `0x01000000`.

## Indicadores LED

De `led[7]` a `led[0]`: error de CPU, mismatch de los generadores, error de
respuesta de los generadores, SDRAM inicializada, SDRAM ocupada, monitor
ocupado, CPU detenida y underflow de vídeo. Los dos indicadores de los
generadores son pegajosos hasta reset.

## Validación

- `cpu_tb.v`: CPU mínima;
- `video_scanout_tb.v`: scanout y cruce de dominios de vídeo;
- `memory_fabric_fifo_6_tb.v`: colas, arbitraje y respuestas del fabric.

La identificación de placa es monitor `5.34`. La validación en hardware debe
hacerse con los generadores activos: los LED de mismatch y error de respuesta
han de permanecer apagados mientras la CPU y el scanout progresan.

Con semilla 12, el build validado cierra todos los dominios: CPU a 81,38 MHz
para un objetivo de 80 MHz, SDRAM a 110,82 MHz para 100 MHz, píxel a 59,82 MHz
para 25 MHz y TMDS a 354,48 MHz para 125 MHz. Ocupa 18.761 LUT, 10.814 FF,
10 EBR y 6 multiplicadores.

En ULX3S 85K se comprobaron el monitor 5.34, los casos CPU `smoke` y
`zero-register`, y `video-band` (11 refrescos y 4 swaps), todos con los dos
generadores activos.
