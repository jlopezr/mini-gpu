# MiniGPU scheduler v0.1 — prototipo C

Scheduler cooperativo de 128 jobs, 8 slots GPU, prioridad estricta RENDER > COMPUTE, dependencias múltiples hacia jobs existentes, listas inversas, y cancelación en cascada transaccional antes del lanzamiento.

## Integración

Implementar los tres callbacks de `gpu_hw_ops`: `pop_done`, `slot_available`, `launch`. `pop_done` debe devolver cada terminación **una sola vez**, conservarla hasta su consumo y no reutilizar un slot antes de consumirla. `launch` recibe el `shader_pc` y el `logical_warp` que corresponde a `warp_user_id`/`GETWID` si esa extensión se incorpora. La propuesta de ISA aún no asigna MMIO a `warp_user_id`: este archivo no presupone direcciones ni registros concretos.

Llamar a `gpu_scheduler_poll()` periódicamente desde la CPU. `gpu_submit()` admite una lista de dependencias existentes; un job ya DONE cuenta como dependencia satisfecha. Los IDs tienen 7 bits de índice y 9 de generación, y nunca valen `GPU_INVALID_JOB`: el job 127 se salta la generación 511. No se deben mantener IDs obsoletos más allá de 512 reutilizaciones del mismo slot. No llamar concurrentemente a las funciones sin exclusión mutua.

`gpu_cancel()` solo admite READY/BLOCKED sin warps lanzados y cancela toda su descendencia si también es cancelable. Recorre la descendencia en anchura y visita cada job una sola vez, así que cuesta O(jobs + aristas) aunque haya diamantes, y no usa recursión. `gpu_release()` requiere DONE/CANCELLED y que no queden enlaces inversos pendientes. Las colas READY se implementan como selección circular sobre la tabla de 128 jobs, evitando memoria y sincronización adicionales.

## Límites del prototipo

- Máximo 512 aristas de dependencia vivas (no 512 jobs); se comprueba capacidad antes de modificar estado.
- Las terminaciones de hardware deben conservar su asociación física al slot. No se soporta reutilización del slot antes de `pop_done`.
- No hay política de fallo de GPU, timeout ni preempción.
- Los callbacks no deben reentrar al scheduler.
- La generación de 9 bits puede reciclarse: para protección permanente contra referencias obsoletas, usar handles más anchos.
- `base_warp_id + next_warp` opera en aritmética de 32 bits; el llamador debe evitar desbordamientos no deseados.

## Compilar

El código es C89, que es lo que acepta `mini-lcc`. `make` hace dos cosas:

- **`make host`**: compila con `cc -std=c89 -pedantic -Wno-long-long -Werror`, usando las cabeceras de `t.tests/inc`.
- **`make lcc`**: pasa el código por `mini-lcc --no-crt`, `mini-opt` y `mini-asm`.

Todo lo que genera va a `_build/c/gpu-scheduler/`. El `.bin` sirve solo para comprobar que el `.s` ensambla: es una biblioteca sin `main` y no se ejecuta por sí sola.
`stdint.h` y `stdbool.h` salen de `t.tests/inc`, porque la librería de lcc no las trae. Allí `bool` es un `int`.
No hay libc, así que el código no llama a `memset` ni a ninguna otra función de biblioteca.

## Ejemplo y pruebas: `test-scheduler.c`

[`test-scheduler.c`](test-scheduler.c) sirve de ejemplo de uso y de batería de pruebas. Trae una GPU simulada (`fake_gpu`) que implementa los tres callbacks con el contrato de arriba. `example_frame()` es el ejemplo: encadena tres jobs (física, escena y post-proceso), espera a que acaben y libera sus entradas. Las demás funciones prueban la prioridad, el reparto de slots, las dependencias, los jobs vacíos, los errores de `gpu_submit`, la capacidad de aristas, la cancelación (en árbol, todo o nada, y con 63 capas de diamantes), la reutilización de IDs y los fallos del hardware.

- **`make test`**: lo ejecuta en el anfitrión, en C99 con ASan y UBSan. Imprime cada `CHECK` que falla.
- **`make sim`**: lo compila para MiniISA (`build-c test-scheduler.c scheduler.c`) y lo ejecuta en `sim-sys`. `main` deja en `R1` un 0 si todo pasa, o la línea del primer fallo. Son unos 6,4 millones de instrucciones.
- **`test.json`**: el mismo caso para `run_tests.py --backend sim-sys`. Está marcado como `slow`.
