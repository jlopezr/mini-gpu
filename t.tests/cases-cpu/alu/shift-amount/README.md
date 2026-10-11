# `shift-amount`

## Objetivo

Para `SHL`, `SHR` y `SAR` la cantidad de desplazamiento son los **cinco bits
bajos** de `Rb` (`1.isa/isa.md`), y `SAR` replica el signo mientras que `SHR`
mete ceros.

## Comportamiento esperado

Con `R1 = 0x80000000`:

- Desplazar 4: `SAR` da `0xF8000000` y `SHR` da `0x08000000`.
- Desplazar 32 (`32 & 31 = 0`): `SAR` y `SHL` dejan `0x80000000` sin cambios.
- Desplazar 33 (`33 & 31 = 1`): `1 << 33` da `2` y `SHR` da `0x40000000`.
- Desplazar 31: `SAR` da `0xFFFFFFFF` y `SHR` da `1`.

## Qué comprueba el `test.json`

- Los registros `R3`, `R4`, `R6`, `R7`, `R10`, `R11`, `R13` y `R14`, y parada
  limpia en `pc = 0x3C`.
- Los valores 32 y 33 son los puntos donde "usar `Rb` entero" y "usar sus cinco
  bits bajos" divergen.
