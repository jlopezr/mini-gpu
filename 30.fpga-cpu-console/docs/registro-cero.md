# `R0` cableado a cero

Las escrituras a `R0` se descartan y las lecturas valen siempre cero. En el RTL
es **una línea**, en `register_file.v`:

```verilog
if (write_enable && write_address != 5'd0) begin
  registers[write_address] <= write_data;
end
```

## No se hace por área

Conviene decirlo primero porque es la razón que todo el mundo supone y es la
mala. Ahorra unos 32 flops de los 1024 del banco. En un ECP5-85F eso es ruido:
no cambia si el diseño cabe, no cambia el Fmax y no cambia nada que se pueda
medir. Si el argumento fuera el área, no valdría la pena un cambio
incompatible.

Las dos razones que sí valen:

**El opcode.** La familia de control `0x20–0x2F` está a **cero libres** después
de `propuesta-v0.2.md` §6: `BEQ`…`BGEU`, los seis branches con inmediato, `JAL`,
`JALR`, `JR` y `BRA` la llenan. Con `R0` a cero, `JR Ra` es exactamente
`JALR R0, Ra, 0` y `0x2E` vuelve al bote. El propio documento anota esta palanca
como «la más barata» en su línea 526.

**Los idiomas.** Cero sin gastar un `MOVI` ni un registro —`BEQ R5, R0, fin`,
`SUB R3, R0, R1`— y un destino de descarte para cuando solo interesan los
efectos de una operación.

## Por qué no se tocan las lecturas

El reset ya deja las 32 entradas a cero y ahora nadie escribe la 0, así que
`registers[0]` es cero **por construcción**. Yosys lo propaga como constante y
elimina por su cuenta los flops y la entrada del multiplexor.

Añadir un `(addr == 0) ? 0 : registers[addr]` explícito metería un multiplexor
extra en la ruta de lectura del banco, que es justo donde no se quiere: esa ruta
es combinacional y desemboca en `operand_a`/`operand_b`, y es la que obligó a
meter `STATE_DECODE` en su día. Ver [timing.md](timing.md).

## Qué NO hay que arreglar: el monitor

La pregunta obligada es si el monitor escribe registros por ese mismo puerto,
porque entonces un `SET_REGISTER R0` pasaría a ser un no-op silencioso y podría
haber casos de test armando estado por ahí.

**No lo hace.** El único acceso del monitor al banco es `READ_REGISTER` (`0x34`),
por el puerto de depuración, que es de solo lectura y de dos ciclos. No existe
ningún `SET_REGISTER` en `monitor.v` ni en `monitor.py`. No hay nada que
arreglar por ese lado.

## `JR` no se quita

`JR` (`0x2E`) queda **obsoleto**, no eliminado. Su hueco es *reclamable*, no
libre. Quitarlo hoy rompe todos los programas que usan `RET` —que es un alias de
`JR R31`— sin ganar absolutamente nada: el opcode no hace falta todavía. Cuando
haga falta, se recupera cambiando el alias del ensamblador y reensamblando.

## Qué se rompió, y la regla que lo hace reversible

Los programas que usan `R0` como registro general. Eran dos, `20.forth/forth.asm`
y `examples/bresenham_lines.asm`, y están **portados**; el detalle está en el
[README de esta carpeta](../README.md#qué-se-rompió-con-r0-a-cero-y-cómo-quedó).

La regla que conviene retener, porque decide qué se puede cambiar antes del
backport y qué no:

> **No escribir `R0` es compatible hacia atrás. Depender de que la escritura se
> descarte, no.**

Un programa que nunca escribe `R0` lee cero en cualquier versión: donde está
cableado por construcción, y donde no porque el reset deja el banco a cero y
nadie lo toca. Por eso los dos programas portados siguen corriendo en la 19, y
por eso los cinco casos de `x.tests` que comparan contra `R0` pasan en
todos los backends.

Lo que **solo** vale aquí es lo contrario: comprobar que una escritura a `R0` se
descarta. Eso es el caso `zero-register/discarded-writes`, y es el único que
lleva `requires: ["zero_register"]`.

De ahí sale la frontera práctica: los `MOVI Rn, 0` de los casos compartidos
podrían usar `R0` y ahorrarse una instrucción, pero en la 19 y anteriores eso
sería volver a apoyarse en la casualidad. Se cambian cuando `R0` esté cableado
en todas las versiones, no antes.
