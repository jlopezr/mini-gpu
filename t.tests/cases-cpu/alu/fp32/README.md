# FP32

`FADD`, `FSUB`, `FMUL` y `FDIV`, capability `fp32`. Comprueba dependencias
FP→FP, FP→STORE y LOAD→FP, R0, cancelación, ceros con signo, NaN, infinito,
DAZ/FTZ, desbordamiento y redondeo de 1/3. Los registros contienen patrones
binary32; el programa no necesita soporte `float` del compilador C.

```sh
tools/run-tests -- --backend sim-cpu cases-cpu/alu/fp32
tools/test-board -p 38 --family cpu -y t.tests/cases-cpu/alu/fp32
```
