# string_test

Prueba CPU-only de la biblioteca C mínima: las cabeceras están en
[`runtime/include`](../../../../runtime/include/string.h) y la implementación en
[`runtime/src`](../../../../runtime/src/string.c).

```text
build-c t.tests/cases-cpu/libc/string_test/string_test.c     # -> _build/c/string_test.bin
sim-sys _build/c/string_test.bin
```

`main` devuelve un bit por cada comprobación que falla; `test.json` exige `R1 = 0`.
