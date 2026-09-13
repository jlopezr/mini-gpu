# Llamadas y saltos indirectos: `JAL`, `JALR` y `JR`

Hasta la 18 esta CPU solo sabía saltar a una etiqueta. Podía hacer bucles, pero
no funciones: no había forma de guardar la dirección de retorno ni de volver a
una dirección calculada. Estas tres instrucciones cierran ese hueco y son lo
mínimo para tener una convención de llamada.

## Qué se ha adoptado

El mapa es el de [`../../1.isa/propuesta-v0.2.md`](../../1.isa/propuesta-v0.2.md)
§3.2, igual que los accesos sub-palabra de esta misma carpeta:

| Opcode | Mnemónico | Formato | Operandos       | Semántica                          |
|--------|-----------|---------|-----------------|------------------------------------|
| `0x2C` | `JAL`     | I-Type  | `Rd, label`     | `Rd = PC + 4`; salto relativo      |
| `0x2D` | `JALR`    | I-Type  | `Rd, Ra, imm16` | `Rd = PC + 4`; salto a `Ra + imm`  |
| `0x2E` | `JR`      | I-Type  | `Ra`            | Salto a `Ra`, sin guardar enlace   |

Codificación, con los mismos campos `X`/`Y`/`imm16` que el resto de las I-Type:

```text
JAL   X = Rd,  Y = 0,   imm16 = offset relativo en palabras
JALR  X = Rd,  Y = Ra,  imm16 = desplazamiento en palabras
JR    X = 0,   Y = Ra,  imm16 = 0
```

`RET` no es un opcode: el ensamblador lo traduce a `JR R31`.

**No es la v0.3.** La v0.3 cablea `R0` a cero, mueve `JAL`/`JALR` a `0x23`/`0x24`
y elimina `JR`, que pasa a ser el alias `JALR R0, Ra, 0`. Cablear `R0` rompería
todos los programas de esta familia que lo usan como registro general —
`cpu_tb.v` comprueba explícitamente que `R0` es normal— así que aquí se paga un
opcode por `JR`. Es reversible: el día que `R0` valga cero, `JR` se convierte en
un alias del ensamblador y `0x2E` queda libre.

## Por qué el desplazamiento va en palabras

Porque todo el control de flujo de esta ISA ya va en palabras: los branches
condicionales y `BRA` cuentan instrucciones, no bytes. Ser coherente dentro de la
propia ISA vale más que parecerse a RISC-V, donde `jalr` va en bytes. En el RTL
es el mismo campo y el mismo desplazamiento:

```verilog
wire [31:0] jump_offset = {{14{instruction[15]}}, instruction[15:0], 2'b00};
```

Los 16 bits con signo dan ±32 768 palabras, o sea ±128 KiB de alcance para
`JAL`. Los programas que caben en esta máquina están muy por debajo.

## Qué cuesta en hardware

Nada de máquina de estados: las tres reutilizan `STATE_BRANCH_COMMIT`, que ya
existía para los branches. En `STATE_EXECUTE` fijan `branch_taken` a uno —son
incondicionales— y registran el destino en `branch_target`; el ciclo siguiente
lo escribe en `pc`. Son **siete ciclos**, exactamente lo que cuesta `BRA`.

El enlace se escribe en el mismo `STATE_EXECUTE`, como hace `MOVI`, y el valor es
directamente `pc`: el fetch ya lo había adelantado a la instrucción siguiente, que
es justo lo que la ISA pide guardar. No hace falta ningún sumador extra para el
enlace.

Lo único nuevo en el camino de datos es el sumador de `operand_a + jump_offset`
de `JALR`, que es el mismo patrón que `effective_address` de `LOAD`/`STORE`, y
una entrada más en el multiplexor de `register_write_data`.

## Destinos desalineados

En `JAL` el destino es `PC + offset*4` y sale alineado por construcción, como en
los branches. En `JALR` y `JR` sale de un registro, y un programa puede dejarlo
en cualquier byte. Aquí **se descartan los dos bits bajos** en vez de añadir una
quinta ruta de error:

```verilog
branch_target <= operand_a & ~32'd3;
```

El motivo es de coste, no de doctrina. Las cuatro rutas de error que ya existen
—opcode inválido, encoding inválido, acceso a memoria, división por cero— cada
una acaba en `pc_restore` y en `STATE_HALTED`, y el comentario de `cpu.v` sobre
el cono de datos del `pc` explica por qué esas rutas son caras. Enmascarar dos
bits es gratis y mantiene el fetch siempre alineado. El coste es que un salto a
una dirección basura salta a la palabra que la contiene en lugar de parar; para
una máquina de enseñanza sin excepciones, parece el trato correcto.

`cpu_tb.v` lo comprueba: `JR` con `0x0a` en el registro salta a `0x08`.

## Encodings inválidos

`JAL` no tiene registro fuente y `JR` no tiene ni destino ni inmediato, así que
esos campos van validados como los del resto de instrucciones con campos
reservados:

- `JAL` exige `instruction[20:16] == 0`.
- `JR` exige `instruction[25:21] == 0` y `instruction[15:0] == 0`.

Un `JR` con campo de destino distinto de cero para con `ERROR_INVALID_ENCODING`
(`0x05`), igual que un `NOP` con bits reservados puestos.

## Convención de llamada

No forma parte de la ISA, pero el ensamblador y estos ejemplos la dan por
sentada:

| Registro | Uso |
|---|---|
| `R31` | Dirección de retorno (`link`) |
| `R30` | Puntero de pila, cuando exista |

```asm
        JAL  R31, funcion
        ...
funcion:
        ...
        RET              ; = JR R31
```

Las llamadas anidadas exigen salvar `R31` a mano: no hay pila en hardware, y
`LOAD`/`STORE` de palabra bastan para montarla.

## Aviso para cuando esto sea una GPU

En una máquina SIMT, `JALR` y `JR` pueden producir tantos destinos distintos como
lanes activas, y la maquinaria de divergencia de `SSY` está pensada para dos
caminos, no para ocho. Cuando esta ISA crezca a warps habrá que exigir que el
destino de un salto indirecto sea **uniforme entre las lanes activas**. En esta
CPU escalar el problema no existe todavía, pero conviene que quede escrito antes
de que aparezca código que dependa de lo contrario.
