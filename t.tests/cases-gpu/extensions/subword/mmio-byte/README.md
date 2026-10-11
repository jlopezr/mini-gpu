# Un byte de MMIO es un error

## Objetivo

Los registros de dispositivo son de palabras completas (`mmio.md` §4.1). Un acceso
de 8 o 16 bits a MMIO no se trunca ni se parte: es un error, y un fallo no puede
dejar rastro en el dispositivo.

## Comportamiento esperado

- `LOAD` de `0x80000000` (el bloque SYSTEM, presente en toda GPU) es legal.
- `LOADB` del mismo registro detiene la GPU con `ERROR_MEMORY_ACCESS` (`0x02`).

## Qué comprueba el `test.json`

`error_code = 2`, fallo en `pc = 12`, `warp 0`, `lane 0`, dirección `0x80000000`.
No se comprueba `R2` porque `SYSTEM_ID` es distinto en cada prototipo.

## Notas

**En la placa (29) este caso no discrimina**: el decodificador del RTL no deja a un
warp llegar al bloque SYSTEM (`mmio.md` §15 dice que sí), así que el `LOAD` de
palabra ya falla en el PC 8 antes de llegar al `LOADB`. Por eso se comprobó
además contra VIDEO a mano en la placa (nota N10 de
`32.cpu-gpu-func-sim/docs/necesidades-detectadas.md`). Contra los simuladores sí
discrimina, y el caso se omite en la placa de todos modos.

Con una sola lane activa (`mmio.md` §4.2). Declara `fault.address`: la placa
omite el caso. La LSU de la 29 lo cubre en su banco directo (`gpu_lsu2_tb.v`,
prueba 15), que además comprueba que un `STOREH` a MMIO no llega al bus.
