# Camino de datos y máscaras

Casos funcionales que ejercitan `LOAD`/`STORE` con varios warps y comprueban el
resultado contra volcados de memoria.

| Caso | Qué valida |
|---|---|
| [memory-copy](memory-copy/) | Copia de 16 palabras con dos warps |
| [vecsum](vecsum/) | `C[i] = A[i] + B[i]` con 16 lanes |
| [vecsum-partial](vecsum-partial/) | Igual pero con un warp a `active_mask = 0x0F` |
| [barrier-visibility](barrier-visibility/) | Lo escrito antes de `BAR` lo ve otro warp después |
| [bank-conflicts](bank-conflicts/) | Stride de 32 bytes: ninguna coalescencia |
| [top-of-bram-word](top-of-bram-word/) | Escritura y lectura en `0x1FFFC` (límite de 128 KiB) |
| [unified-code](unified-code/) | Un `STORE` sobre el código cambia lo que se ejecuta |
| [negative-offset](negative-offset/) | `LOAD`/`STORE` con desplazamiento negativo: el acarreo de una lane no pasa a la siguiente |
