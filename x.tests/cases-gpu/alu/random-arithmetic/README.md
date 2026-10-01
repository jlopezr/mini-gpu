# Aritmética aleatoria con semilla fija

## Objetivo

Recorre la ALU con operandos generados con `random.Random(1288)`: 33 operaciones (`ADD SUB MUL MULFX DIV AND OR XOR SHL SHR SAR`, tres vueltas) sobre registros de 0 a 9, más los casos límite de `DIV` (−2³¹ / −3 y −2³¹ / −1) y de `MULFX` con operandos extremos.

## Comportamiento esperado

- `R0` está cableado a cero: el `MOVI R0, -17` del principio se descarta y todo operando `R0` lee 0 (`R7 = MULFX R0, R3 = 0`; `R10 = R0 & 0xff = 0`; `R11 = R10 ^ 0xffff = 0xffff`).
- El divisor `R4` vale 1 y no se toca, así que no hay división por cero.
- Los resultados dependen del `tid` solo a través de `R1` (y de lo que lo lea).

## Qué comprueba el `test.json`

- `R0 = 0`, `R7 = 0` y `R10 = 0` en las lanes 0 y 7 de cada warp: ahí está la prueba de que `R0` no es escribible. Si lo fuera, `R11` valdría `0xff10`.
- Los demás registros no nulos de esas dos lanes y el contador de instrucciones.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Solo declara `mul_div`: `MULFX`, `SAR` y los desplazamientos son base; `DIV` y `MUL` no.

Contexto: [README de la categoría](../README.md).
