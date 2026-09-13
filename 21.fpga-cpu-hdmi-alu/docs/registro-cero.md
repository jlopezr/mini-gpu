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

## Qué se rompe

Los programas que usan `R0` como registro general. Están listados en el
[README de esta carpeta](../README.md#qué-se-rompe-con-r0-a-cero), con lo que
hace cada uno y por qué. **No se han portado**: esa decisión es aparte.

Los que solo *leen* `R0` esperando cero —que son la mayoría, incluidos cinco
casos de `x.cpu-tests`— siguen funcionando igual, y de hecho pasan a funcionar
por construcción en vez de por casualidad.
