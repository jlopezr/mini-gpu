# MiniGPU scheduler v0.1 — prototipo C

Scheduler cooperativo de 128 jobs, 8 slots GPU, prioridad estricta RENDER > COMPUTE, dependencias múltiples hacia jobs existentes, listas inversas, y cancelación recursiva transaccional antes del lanzamiento.

## Integración

Implementar los tres callbacks de `gpu_hw_ops`: `pop_done`, `slot_available`, `launch`. `pop_done` debe devolver cada terminación **una sola vez**, conservarla hasta su consumo y no reutilizar un slot antes de consumirla. `launch` recibe el `shader_pc` y el `logical_warp` que corresponde a `warp_user_id`/`GETWID` si esa extensión se incorpora. La propuesta de ISA aún no asigna MMIO a `warp_user_id`: este archivo no presupone direcciones ni registros concretos.

Llamar a `gpu_scheduler_poll()` periódicamente desde la CPU. `gpu_submit()` admite una lista de dependencias existentes; un job ya DONE cuenta como dependencia satisfecha. Los IDs tienen 7 bits de índice y 9 de generación. No se deben mantener IDs obsoletos más allá de 512 reutilizaciones del mismo slot. No llamar concurrentemente a las funciones sin exclusión mutua.

`gpu_cancel()` solo admite READY/BLOCKED sin warps lanzados y cancela toda su descendencia si también es cancelable. `gpu_release()` requiere DONE/CANCELLED y que no queden enlaces inversos pendientes. Las colas READY se implementan como selección circular sobre la tabla de 128 jobs, evitando memoria y sincronización adicionales.

## Límites del prototipo

- Máximo 512 aristas de dependencia vivas (no 512 jobs); se comprueba capacidad antes de modificar estado.
- Las terminaciones de hardware deben conservar su asociación física al slot. No se soporta reutilización del slot antes de `pop_done`.
- No hay política de fallo de GPU, timeout ni preempción.
- Los callbacks no deben reentrar al scheduler.
- La generación de 9 bits puede reciclarse: para protección permanente contra referencias obsoletas, usar handles más anchos.
- `base_warp_id + next_warp` opera en aritmética de 32 bits; el llamador debe evitar desbordamientos no deseados.

Compilar con: `cc -std=c11 -Wall -Wextra -Werror -c scheduler_v01.c`.

## Ejemplo ejecutable

Compilar: `cc -std=c11 -Wall -Wextra -Werror scheduler_v01.c example.c -o example`
Ejecutar: `./example`

`example.c` usa una GPU simulada de 8 slots y latencia fija de 3 ticks por warp. Lanza CLEAR, DRAW dependiente de CLEAR, COMPUTE independiente y PRESENT dependiente de DRAW y COMPUTE. Comprueba que no se violan las dependencias.
