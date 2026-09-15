# `SLT` con el campo reservado sucio

`program.hex` contiene una sola instrucción:

```text
98221801   SLT R1, R2, R3, extra = 0x001
```

`SLT` y `SLTU` son R-Type, igual que `ADD`: su campo reservado es `extra`
entero, `instruction[10:0]`. Con cualquier bit puesto ahí, la instrucción debe
parar con `ERROR_INVALID_ENCODING` (`0x05`) y el PC en `0x00000000`.

Va como `.hex` y no como `.asm` por lo de siempre: el ensamblador no emite
encodings inválidos.

Lo que este caso protege: sin él, quitar la comprobación de `extra[10:0]`
para `SLT`/`SLTU` no rompería nada, porque
[`signed-unsigned`](../signed-unsigned/) solo ejercita encodings válidos.
