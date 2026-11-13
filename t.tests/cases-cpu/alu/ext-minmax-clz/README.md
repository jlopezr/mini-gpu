# EXT: MIN/MAX y CLZ

`MIN`, `MAX`, `MINU`, `MAXU` (capability `minmax`) y `CLZ` (capability `clz`),
en el opcode `EXT` (`0x1E`). Comprueba signed frente a unsigned, `CLZ(0) = 32`,
dependencias entre ellas y R0.

```sh
tools/run-tests -- --backend sim-cpu cases-cpu/alu/ext-minmax-clz
tools/test-board -p 38 --family cpu -y t.tests/cases-cpu/alu/ext-minmax-clz
```
