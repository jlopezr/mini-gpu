# FP32: comparaciones y conversiones

`FEQ`, `FLT`, `FLE`, `FTOI` e `ITOF`, capability `fp32`. Comprueba NaN (las
comparaciones dan 0 y `FTOI` da 0), `-0 == +0`, que las comparaciones no aplican
DAZ, el truncamiento y la saturación de `FTOI`, el redondeo de `ITOF`, `fbits`
(Q16.16 y otros), una dependencia `ITOF` → `FADD` → `FTOI` y R0.

```sh
tools/run-tests -- --backend sim-cpu cases-cpu/alu/fp32-cmp-cvt
tools/test-board -p 38 --family cpu -y t.tests/cases-cpu/alu/fp32-cmp-cvt
```
