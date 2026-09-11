# Optimización de temporización: 16 frente a 14

Copia de `14.fpga-gpu-ram` para subir la frecuencia máxima. Objetivo declarado:
acercarse a 100 MHz. La constraint del proyecto sigue en 25 MHz; lo que se mide
en cada paso es el `achieved` del informe de `nextpnr`, no un cambio de reloj.

Método: **un cambio por iteración**, con `check.ps1 Tests`, `check.ps1 Lint` y
`check.ps1 Build` después de cada uno, anotando fmax, camino crítico y recursos.
`timing.ps1` resume el informe para que las medidas sean comparables.

```powershell
./16.fpga-gpu-ram-v2/check.ps1 Tests
./16.fpga-gpu-ram-v2/check.ps1 Lint
./16.fpga-gpu-ram-v2/check.ps1 Build
./16.fpga-gpu-ram-v2/timing.ps1
```

## Medidas

| Paso | fmax | camino crítico | LUT | FF |
| --- | --- | --- | --- | --- |
| Base (RTL de 14) | 33,57 MHz | `gpu.lsu.pending` → `gpu.lsu.pick` (29,79 ns) | 30744 | 9016 |
| 1. Arbitraje y direccionamiento en ciclos distintos | 34,48 MHz | `gpu.sm.push_index` → `gpu.sm.top_index` (29,01 ns) | 30749 | 9020 |

La base reproduce exactamente la cifra de `14/salida-sintesis.json`, así que las
comparaciones posteriores son contra una medida equivalente y no contra otra
síntesis distinta.

## Paso 1: separar el arbitraje del direccionamiento

**Problema.** El estado `IDLE` resolvía en un único ciclo combinacional toda la
cadena de selección: prioridad rotatoria sobre ocho warps, prioridad sobre ocho
lanes dependiente del resultado anterior, y **dos multiplexores de 2048 bits a
32** (`addresses[pick][lane_pick*32 +: 32]` y el equivalente sobre `values`)
indexados por ambas prioridades encadenadas, más la validación de rango y la
transición de estado encima. El informe de la base lo confirmaba: el camino
crítico nacía en `gpu.lsu.pending[7][0]` y pasaba por `gpu.lsu.pick[2]`.

Los retardos eran de enrutado, no de lógica: saltos de 3,11 ns, 3,28 ns y
2,29 ns entre celdas situadas en (76,72), (92,38), (95,38) y (103,38). Un mux de
ese tamaño no se empaqueta junto, así que el emplazador lo reparte por el chip.

**Cambio.** Se añade el estado `SELECT` (código 7, el único libre de los tres
bits). `IDLE` ahora solo arbitra y registra `selected`/`selected_lane`; `SELECT`
lee la dirección y el dato con esos índices **ya registrados** y decide entre
error de rango y `SEND_LOW`. Los muxes siguen existiendo, pero dejan de estar
encadenados detrás de la lógica de prioridad.

Los códigos de `SEND_LOW`..`WAIT_HIGH` se conservan porque `gpu_lsu_tb` recorre
`dut.state==1..4` para cancelar en cada fase de la transferencia.

**Coste.** Un ciclo más por palabra de lane. Es irrelevante: cada palabra de 32
bits ya son dos accesos BL1 a SDRAM con decenas de ciclos de espera. En área,
+5 LUT y +4 FF.

**Resultado.** 33,57 → 34,48 MHz, y sobre todo **el camino crítico sale de la
LSU**: ahora el peor camino está en la pila de divergencia del SM
(`push_index` → `top_index`). La sospecha inicial era correcta, pero la LSU solo
era el primero de varios caminos casi igual de largos.

## Lectura del primer paso

La ganancia en frecuencia es pequeña (+2,7 %) porque el segundo camino estaba a
menos de un nanosegundo del primero: 29,01 ns frente a 29,79 ns. No hay un único
cuello de botella que quitar, sino un conjunto de caminos largos parecidos.

Llegar a 100 MHz exige bajar de 29 ns a 10 ns, un factor de tres, sobre **todos**
ellos. No se consigue con un retoque; hace falta seguir troceando en etapas
registradas cada bloque que aparezca arriba, LSU y SM incluidos. El método de un
cambio por iteración sigue siendo el adecuado, pero conviene contar con varias
iteraciones y con que la mejora por paso sea modesta hasta que se nivelen.

## Pendiente

Sobre la LSU, del plan inicial quedan:

- Sacar `pending` de la cadena de prioridad con un bit `has_pending` por slot,
  en vez de comparar `pending[candidate]!=0` sobre 64 bits.
- Rotar una máscara one-hot por `cursor` en lugar de ocho sumadores `cursor+k`
  con ocho comparadores encadenados.
- Mover `addresses`/`values` a memoria distribuida leída por índice registrado,
  en vez de un array de biestables con mux 2048→32. Son 2×2048 bits.

Y, ahora en cabeza, la pila de divergencia del SM.

Todo lo que se consolide aquí es candidato a backport a `12.fpga-gpu`, cuya
lógica de `found`/`pick`/`cursor` es casi idéntica.
