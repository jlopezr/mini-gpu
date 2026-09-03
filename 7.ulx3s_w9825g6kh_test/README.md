# Test de SDRAM W9825G6KH-6 para ULX3S

Proyecto mínimo para comprobar la SDR SDRAM de 32 MiB montada en ULX3S v2.x/v3.x. Usa directamente `clk_25mhz`, sin PLL. El controlador trabaja con palabras de 16 bits, burst length 1, CAS latency 2 y auto-precharge en cada acceso.

## Qué prueba

Por defecto se recorren las primeras 65 536 palabras (128 KiB) cuatro veces. Para cada patrón se escribe todo el bloque y después se lee y compara:

1. `0000`
2. `FFFF`
3. dirección XOR `A5A5`
4. `55AA` / `AA55` alternado

El test se detiene permanentemente al primer error y conserva internamente dirección, valor esperado y valor leído para depuración con analizador lógico/SignalTap equivalente. Pulsar `BTN_PWRn` reinicia todo el proceso.

## LEDs

| LED | Significado                       |
|-----|-----------------------------------|
| 0   | Inicialización SDRAM terminada    |
| 1   | Fase de escritura                 |
| 2   | Fase de lectura/comparación       |
| 3   | PASS final                        |
| 4   | FAIL; detenido en el primer error |
| 7:5 | Progreso dentro del bloque actual |

## Temporizaciones a 25 MHz

Un ciclo dura 40 ns. La inicialización espera más de 200 us (5001 ciclos), hace PRECHARGE ALL, ocho AUTO REFRESH y carga el modo BL1/CL2. Los espacios usados son conservadores: 40 ns para tRP y tRCD, 80 ns para tRFC y dos ciclos tras WRITE. El refresco se solicita cada 190 ciclos (7,6 us), por debajo del máximo medio de 7,8125 us para 8192 refrescos en 64 ms.

## Ampliar el área probada

En `top.v`, cambie `TEST_ADDR_BITS(16)`. Por ejemplo, 20 prueba 1 048 576 palabras (2 MiB). El máximo es 24 para los 32 MiB completos; a costa de un tiempo de ejecución mucho mayor.

## Notas de bring-up

- El LPF usa los nombres y pines del fichero oficial `ulx3s_v20.lpf` para placas v2.x/v3.x.
- La dirección del puerto es una dirección de palabra, no de byte: fila `[23:11]`, banco `[10:9]`, columna `[8:0]`.
- El reloj SDRAM es el mismo reloj de 25 MHz. Esta elección es deliberada para el primer bring-up; al subir frecuencia habrá que introducir PLL, fase de reloj y revisar todos los tiempos.
- El diseño presupone W9825G6KH y ULX3S v2.x/v3.x. Revise el esquema/constraints si su placa es una revisión distinta.

Fuentes de referencia: [constraints oficiales ULX3S](https://github.com/emard/ulx3s/blob/master/doc/constraints/ulx3s_v20.lpf) y [datasheet W9825G6KH](https://evelta.com/content/datasheets/153-W9825G6KH-6.pdf).
