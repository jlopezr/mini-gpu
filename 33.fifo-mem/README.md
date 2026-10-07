# FIFO de memoria con cuatro masters

La evolución propuesta para recuperar 100 MHz con seis puertos y admitir varias
peticiones pendientes o en vuelo está descrita en
[`propuesta-fabric6-pipeline.md`](propuesta-fabric6-pipeline.md).

Prototipo de diagnóstico en ULX3S para validar una arquitectura de memoria con
cuatro masters, cruces de dominio mediante FIFO asíncrona, arbitraje y un único
controlador SDRAM compartido.

## Arquitectura

El diseño tiene dos dominios de reloj:

- masters, monitor UART y registros MEMTEST a 25 MHz;
- `memory_fabric_fifo_4` y `sdram_controller_128` a 100 MHz.

Cada master conserva una interfaz `valid/ready`. Un `fabric_fifo_bridge`
proporciona por puerto una FIFO de requests hacia memoria y otra de responses
hacia el master. En `top_fabric6`, el fabric añade una cola global de ocho
comandos y otra de ocho respuestas. Puede aceptar y acumular varias peticiones
mientras el controlador ejecuta una; el controlador SDRAM todavía procesa una
única transacción interna cada vez.

Los puertos son:

| Puerto | Master | Región usada |
|---|---|---|
| p0 | `memory_traffic_gen` 0 | `0x00100000–0x001FFFFF` |
| p1 | `memory_traffic_gen` 1 | `0x00200000–0x002FFFFF` |
| p2 | `memory_traffic_gen` 2 | `0x00300000–0x003FFFFF` |
| p3 | monitor UART mediante `gpu_aux_adapter_128` | SDRAM fuera de esas regiones |

Cada generador escribe un patrón determinista de 128 bits, lo vuelve a leer y
comprueba la respuesta antes de avanzar a la siguiente línea de 16 bytes.

El fabric registra primero la petición concedida y la valida en el estado
`ST_CHECK` durante el ciclo siguiente. Esta etapa rompe el camino combinacional
que antes atravesaba el mux de 178 bits, la comprobación de dirección y la
actualización de estado en un solo ciclo.

## Construcción y timing

Desde esta carpeta:

```powershell
apio build
apio upload
```

El entorno por defecto sintetiza `top`, el sistema probado de cuatro masters.
También existe una variante de capacidad, no destinada todavía a la placa:

```powershell
apio build -e fabric6
```

`top_fabric6` usa `memory_fabric_fifo_6`, seis bridges CDC y dos generadores
adicionales en `0x00400000–0x004FFFFF` y `0x00500000–0x005FFFFF`. Ambos siguen
los bits enable/urgent de GEN2 para que sean clientes dinámicos y no se eliminen
durante síntesis. Esta variante
representa el espacio para dos futuros masters de GPU, no cambia el bitstream
por defecto ni se ha validado en placa.

`apio.ini` fija la semilla 12, solicita informe detallado de timing y conserva el
flujo de Yosys que omite `AUTONAME`, porque ese pase resulta impracticable en
este netlist.

Las etapas `ST_CAPTURE` y `ST_CHECK` separan arbitraje, mux del payload y
validación. Un barrido de 16 semillas sobre este RTL dio:

- objetivo de `sdram_clk`: 100,00 MHz;
- 2 de 16 semillas cumplen;
- mediana: 96,65 MHz;
- semilla 3: 102,05 MHz;
- semilla 12: 105,03 MHz, la mejor del barrido.

El cierre sigue dependiendo del placement, por lo que se fija la semilla 12.
El bitstream se puede
generar aunque falle timing porque Apio invoca NextPNR con
`--timing-allow-fail --force`; hay que leer siempre el resultado de Fmax.

El aviso de Yosys sobre soporte limitado de tri-state procede del bus
bidireccional de la SDRAM y es esperado.

Con esa misma semilla, la versión de seis puertos con router registrado y colas
globales de ocho comandos y ocho respuestas alcanza **105,83 MHz** en el dominio
de memoria. Usa 9785 `TRELLIS_COMB`, 6307 `TRELLIS_FF` y 548 `TRELLIS_RAMW`,
frente a 7398, 4556 y 312 en la construcción de cuatro puertos. El camino
crítico mide 9,45 ns y se encuentra ahora dentro de `sdram_controller_128`, desde
`timing_count`; el retorno/demultiplexado del fabric ha dejado de ser crítico.

El bitstream se validó en placa con los cinco generadores, el monitor bajo
contención, tráfico urgent, soak de 60 segundos y el bloque UART de 4 KiB, sin
errores ni mismatches.

## Test RTL del árbitro

`memory_fabric_fifo_4_tb.v` prueba de forma dirigida propiedades que los
contadores de placa no pueden observar:

- una petición urgente gana frente a peticiones normales simultáneas;
- varias peticiones urgentes respetan el puntero round-robin;
- sin urgentes se mantiene el round-robin normal;
- `ST_CHECK` conserva write, dirección, datos y máscara;
- la respuesta vuelve al puerto que originó la petición;
- direcciones desalineadas o fuera de SDRAM fallan localmente sin llegar al
  controlador.

Se ejecuta con el lanzador común:

```powershell
..\tools\test.ps1 --prototype 33
```

## Monitor UART

La UART funciona a 250000 baudios: reloj de 25 MHz y divisor 100.

El cliente propio del prototipo es `monitor.py`. Detecta automáticamente la
ULX3S si solo hay un adaptador FTDI conectado:

```powershell
python.exe .\monitor.py ping
python.exe .\monitor.py get-version
python.exe .\monitor.py write-word 0x00001000 0xA5C35A7E
python.exe .\monitor.py read-word 0x00001000
```

El cliente permite:

- `ping` y `get-version`;
- lectura y escritura de byte o palabra;
- lectura, escritura y verificación de bloques;
- acceso a SDRAM `0x00000000–0x01FFFFFF`;
- acceso a MEMTEST `0x81200000–0x8120FFFF`.

## Registros MEMTEST

Base: `0x81200000`.

### Control

`0x81200000`:

| Bit | Función |
|---:|---|
| 0 | GEN0 enable |
| 1 | GEN1 enable |
| 2 | GEN2 enable |
| 3 | GEN0 urgent |
| 4 | GEN1 urgent |
| 5 | GEN2 urgent |
| 8 | limpiar estadísticas, pulso |

El bit 8 siempre se lee como cero. Limpiar estadísticas no reinicia
`CURRENT_ADDRESS` ni `LOOPS`.

### Estadísticas

| Generador | Requests | Errors | Mismatches | Dirección | Loops |
|---|---:|---:|---:|---:|---:|
| GEN0 | `+0x04` | `+0x08` | `+0x0C` | `+0x10` | `+0x14` |
| GEN1 | `+0x20` | `+0x24` | `+0x28` | `+0x2C` | `+0x30` |
| GEN2 | `+0x40` | `+0x44` | `+0x48` | `+0x4C` | `+0x50` |
| GEN4 (`fabric6`) | — | `+0x64` bit 0 | `+0x64` bit 1 | `+0x60` | — |
| GEN5 (`fabric6`) | — | `+0x84` bit 0 | `+0x84` bit 1 | `+0x80` | — |

En el top normal, los registros de GEN4 y GEN5 existen pero leen cero. En
`top_fabric6` contienen la dirección de progreso y flags sticky de error; ambos
comparten los bits de enable y urgent de GEN2. Los flags se limpian con
`CLEAR_STATS`.

## Regresión de placa

Después de comprobar visualmente que la placa arranca, la secuencia funcional
completa se ejecuta con:

```powershell
.\validate.ps1
```

Valida, deteniéndose ante el primer fallo:

1. PING y versión 1.0.
2. Ventana MMIO MEMTEST.
3. Escritura y lectura SDRAM por p3.
4. GEN0 aislado.
5. GEN0 + GEN1.
6. Los tres generadores.
7. Acceso p3 bajo contención.
8. Camino `urgent` de GEN2.
9. Carga sostenida de 60 segundos.
10. Escritura y verificación de un bloque de 4 KiB por p3 bajo contención.

El validador conserva y restaura el valor inicial de CONTROL. También restaura
el contenido previo de las direcciones SDRAM que utiliza. Las duraciones son
configurables; para una pasada rápida:

```powershell
.\validate.ps1 --step-seconds 0.1 --soak-seconds 0.2
```

Una pasada rápida real completó todas las etapas sin errores ni mismatches.

Para el bitstream `fabric6`, la regresión equivalente añade la comprobación de
progreso, errores y mismatches de GEN4 y GEN5:

```powershell
.\validate_fabric6.ps1
# pasada rápida
.\validate_fabric6.ps1 --step-seconds 0.1 --soak-seconds 0.2
```

Si se ejecuta por error contra el top normal, falla porque los contadores extra
no progresan.

Durante la etapa urgent, GEN2 controla simultáneamente los puertos p2, p4 y p5.
Esos tres generadores pueden sostener peticiones urgentes continuamente, por lo
que el árbitro de prioridad estricta no garantiza progreso de los normales p0 y
p1 dentro de esa ventana. El validador exige progreso a p2 y después comprueba
p4/p5 mediante su telemetría; la etapa soak sin urgent vuelve a exigir progreso
a GEN0, GEN1 y GEN2.

La prueba de `urgent` confirma integridad y progreso con el bit activo, pero no
demuestra por contadores que el árbitro elija GEN2 cuando varias peticiones
llegan simultáneamente. Cada generador mantiene una sola transacción en vuelo y
espera la respuesta a través del CDC, por lo que no permanece siempre
encolado. La prioridad de latencia necesita un testbench dirigido o contadores
de concesiones/latencia.

## LEDs

| LED | Indicación |
|---:|---|
| 0 | PLL locked |
| 1 | SDRAM inicializada, sincronizada a 25 MHz |
| 2 | GEN0 habilitado |
| 3 | GEN1 habilitado |
| 4 | GEN2 habilitado |
| 5 | algún response error |
| 6 | algún mismatch |
| 7 | monitor ocupado |

Tras programar la placa, LED0 y LED1 deben estar encendidos. Durante una
regresión con tres generadores, LED2–4 deben estar encendidos y LED5/LED6
apagados. Los LEDs no son observables por software y requieren comprobación
visual.
