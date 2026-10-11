# Fallos de ejecución

Cada caso provoca un fallo distinto y comprueba que el diagnóstico es exacto
(`error_code`, `fault.pc`, `fault.core_id`, `fault.address`) y que **no hay
efectos parciales**: el PC no avanza, la máscara no cambia y ninguna lane
escribe registros ni memoria.

| Caso | Código | Qué valida |
|---|---:|---|
| [division-by-zero](division-by-zero/) | 4 | `DIV` por cero en una sola lane |
| [load-out-of-bounds](load-out-of-bounds/) | 2 | `LOAD` fuera del mapa |
| [store-out-of-bounds](store-out-of-bounds/) | 2 | `STORE` fuera del mapa, memoria intacta |
| [trap-global](trap-global/) | 3 | `TRAP` detiene todos los warps |
