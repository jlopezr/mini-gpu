# Camino de datos y máscaras

Casos funcionales que ejercitan `LOAD`/`STORE` con varios warps y comprueban el
resultado contra volcados de memoria.

| Caso | Qué valida |
|---|---|
| [memory-copy](memory-copy/) | Copia de 16 palabras con dos warps |
| [vecsum](vecsum/) | `C[i] = A[i] + B[i]` con 16 lanes |
| [vecsum-partial](vecsum-partial/) | Igual pero con un warp a `active_mask = 0x0F` |
