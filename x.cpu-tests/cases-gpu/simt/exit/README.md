# Terminación de lanes dentro de una REGION

Qué ocurre cuando una lane ejecuta `EXIT` con estado SIMT abierto. La regla común
es que las lanes muertas salen de `live_mask` y no pueden reaparecer al restaurar
la máscara de una REGION.

| Caso | Qué valida |
|---|---|
| [ssy-exit-with-pending](ssy-exit-with-pending/) | `EXIT` en el camino activo, con un `PATH` pendiente |
| [ssy-exit-pending-path](ssy-exit-pending-path/) | `EXIT` desde el `PATH` ya seleccionado |
| [ssy-exit-nested](ssy-exit-nested/) | `EXIT` dentro de una REGION interior |
| [ssy-exit-all](ssy-exit-all/) | `live_mask` llega a cero: termina el warp |
