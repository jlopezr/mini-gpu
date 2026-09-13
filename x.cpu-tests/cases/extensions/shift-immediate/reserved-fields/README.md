# `SHL` con el campo reservado sucio

`program.hex` contiene una sola instrucción:

```text
1C221C01   SHL R1, R2, R3, extra = 0x401
```

El bit 10 puesto es legítimo: es el modo inmediato. El bit 0 no lo es. Para
`SHL`, `SHR` y `SAR` el campo reservado dejó de ser `extra` entero y pasó a ser
`extra[9:0]`, así que esta instrucción tiene que parar con
`ERROR_INVALID_ENCODING` (`0x05`) y el PC en `0x00000000`.

Va como `.hex` y no como `.asm` por lo de siempre: el ensamblador no emite
encodings inválidos.

Lo que este caso protege es la **mitad negativa** del cambio. La positiva —que
`extra[10]` solo sea válido— la cubre
[bounds](../bounds/), que ejecuta quince desplazamientos inmediatos sin error.
Sin este caso, quitar la comprobación de `extra[9:0]` entera no rompería nada:
el campo reservado dejaría de comprobarse y las dieciséis suites seguirían en
verde.
