# La familia ALU completa, y el medio resultado que la CPU tiraba

Dos cosas distintas que conviene no mezclar al leerlas:

1. **`MULHI`, `DIVU`, `REM` y `REMU`**, las cuatro reservadas de `0x00–0x0F`.
   Es una ampliación del juego de instrucciones, y es visible.
2. **El camino rápido**, que deja que un `MULHI` o un `REM` reutilicen la mitad
   del resultado que su `MUL` o su `DIV` ya habían calculado. Es una
   optimización de microarquitectura, y es **invisible**: no cambia ningún
   número, solo ciclos.

La segunda va encima de la primera, pero no la necesita: con el camino rápido
desarmado (`ALU_FAST_PATH = 0`) la CPU sigue dando exactamente los mismos
resultados y tarda más.

---

## 1. `MULHI` es con signo, y eso cuesta

La ISA v0.1 dejaba `0x0B` reservado sin decir si era la mitad alta signed o la
unsigned. Hay que elegir, porque solo hay un opcode y la familia ALU está llena:
no cabe un `MULHU` al lado.

**Se elige signed**, por tres razones:

- Es la convención de `MULH` en RISC-V, que es de donde va a venir cualquiera
  que lea esto.
- Es coherente con `MULFX`, la otra multiplicación de esta ISA, que es signed.
- `MUL` + `MULHI` forman así el producto signed de 64 bits completo, que es la
  operación que de verdad falta. Los 32 bits bajos no dependen del signo, así
  que `MUL` sirve igual para unsigned; los altos sí.

Quien necesite el alto unsigned lo reconstruye sumando la corrección:

```text
alto_unsigned = MULHI(a, b) + (a[31] ? b : 0) + (b[31] ? a : 0)
```

### La trampa

El RTL heredado de la 19 construye `multiply_unsigned_product`, un producto de
64 bits **sin signo**, a partir de cuatro parciales de 16×16 (`MULFX` necesita
los bits centrales). Es tentador cablear `[63:32]` a la salida y dar `MULHI` por
hecho. **No funciona**, y no funciona en silencio: con operandos positivos el
resultado es correcto.

La mitad alta signed es la unsigned menos la misma corrección de antes:

```text
alto_signed = producto_unsigned[63:32] - (a[31] ? b : 0) - (b[31] ? a : 0)
```

con `a` y `b` los operandos **originales**. En el RTL eso son dos estados:
`STATE_MULHI_FIX` suma los dos términos en `mulhi_correction` y
`STATE_MUL_SIGN` hace una sola resta. Están separados por lo mismo que existe
`STATE_ALU_WRITE`: encadenar dos sumadores de 32 bits antes del multiplexor de
escritura del banco era el camino crítico de `6.fpga-cpu`.

El discriminante más limpio, y el que hay que mirar si algo de esto se rompe,
es `-1 × -1`: signed da 1, o sea parte alta `0x00000000`; unsigned daría
`0xFFFFFFFE`.

### El multiplicador ahora calcula siempre los 64 bits

En la 19, `MUL` se ahorraba el parcial alto porque módulo 2³² no aporta nada. En
la 21 no: `MUL` construye el producto entero igual que `MULFX`. Hace falta para
`MULHI`, y **hace falta para que el camino rápido sirva de algo**: si `MUL` no
dejara la mitad alta escrita, la etiqueta apuntaría a un valor que no existe.

Cuesta un bloque 16×16 más y un sumador más ancho. No cuesta un ciclo: los
parciales ya iban en paralelo.

---

## 2. El resto y su signo

El divisor de la 19 es por restas con restauración, sobre magnitudes: niega los operandos
negativos, divide sin signo en 32 iteraciones y le pone el signo al cociente al
final. `divide_remainder` queda con el resto de las magnitudes.

Las cuatro instrucciones comparten ese camino y solo cambian en dos cosas:

| Instrucción | Operandos | Qué se escribe | Signo |
|---|---|---|---|
| `DIV` | magnitudes | cociente | `a[31] ^ b[31]` |
| `DIVU` | crudos | cociente | — |
| `REM` | magnitudes | resto | `a[31]` |
| `REMU` | crudos | resto | — |

La fila de `REM` es la que hay que leer dos veces. El resto acompaña a una
división truncada hacia cero, así que lleva el signo del **dividendo**, no el
del cociente, que es el que ya había registrado. Por eso hay dos flops de signo
y no uno: `divide_negative` y `divide_dividend_negative`. Los dos casos que
separan esta regla de la otra convención posible —el módulo matemático, con el
signo del divisor— son `-7 rem 2 = -1` y `7 rem -2 = 1`.

División por cero: trap en las cuatro. `REM` no tiene más definición que la
división que lo acompaña, así que no hay nada que devolver.

---

## 3. El camino rápido

### La observación

Las dos mitades que faltan ya están calculadas. El divisor mantiene
`divide_remainder` durante las 32 iteraciones; el multiplicador construye los 64
bits enteros. De cada operación se tira la mitad que nadie pidió.

Un `REM` que venga detrás de su `DIV` puede leer el resto en vez de rehacer una
división de **32 ciclos**. Medido en `alu_fast_path_tb.v`: 87 ciclos en lugar de
119. Un `MULHI` detrás de su `MUL` se ahorra tres.

**En la placa son 31,99 ciclos por acierto**, medidos con los contadores de
rendimiento sobre `examples/fastpath_hit.asm` y `fastpath_miss.asm`: 63 108
frente a 95 093 ciclos para las mismas 4 005 instrucciones, o sea 31 985 en
1 000 vueltas, y un CPI que baja de 23,74 a 15,76. Los dos programas son el
mismo fichero con un carácter distinto —el `REM` lee `R2` o `R3`, que valen lo
mismo—, así que la resta es el ahorro y no hay nada que descontar. El detalle
está en [`cycles.md`](cycles.md).

### La condición, y por qué es tan estricta

**Estrictamente la instrucción inmediatamente anterior.** Nada de «algún `MUL`
en algún momento».

Esa restricción no es prudencia, es lo que hace barata la idea. Si no hay
instrucción intermedia, nada puede haber cambiado los operandos, y entonces
basta con comparar **números de registro de 5 bits** en vez de valores de 32:

| Qué se guarda | flops |
|---|---:|
| número de Ra, número de Rb | 10 |
| tipo de operación | 2 |
| válido | 1 |
| **etiqueta** | **13** |

Trece flops y comparadores de 5 bits. Un esquema más generoso —«recuerda el
último producto y compara valores»— necesitaría dos comparadores de 32 bits en
la ruta de decisión, que es exactamente lo que no se quiere para el Fmax, a
cambio de acertar en secuencias que el código no escribe: el compilador y el
programador emiten siempre `MULHI` pegado a su `MUL`.

### Las reglas, y qué protege cada una

- **Se arma al completar**, en `STATE_MUL_WRITE`, no al empezar en
  `STATE_EXECUTE`. Una división por cero se va a `STATE_HALTED` desde
  `STATE_DIV_STEP` y por tanto no deja etiqueta. Si se armara al empezar, un
  `REM` posterior se creería un resto que nunca se calculó.
- **No se arma si `rd == ra || rd == rb`.** La operación pisa una de sus propias
  fuentes, así que los números de registro siguen coincidiendo pero los valores
  ya no. Es el único caso en el que la comparación de 5 bits no basta por sí
  sola, y por eso está a mano.
- **Se etiqueta con los registros de la instrucción**, no con lo que entra al
  operador. `MULFX` y `DIV` pasan el valor absoluto y guardan el signo aparte;
  etiquetar con eso sería etiquetar con otra cosa.
- **`MULFX` no arma.** Multiplica magnitudes, así que su producto de 64 bits no
  es `a × b` sin signo. Un `MULHI` que se lo creyera daría el alto del valor
  absoluto.
- **`DIV` y `DIVU` arman tipos distintos.** El más sutil de los tres cruces:
  `DIV` trabaja en magnitudes y `DIVU` en crudo, así que con un dividendo
  negativo el resto que dejan no es el mismo. Si fueran un solo tipo, un `REMU`
  detrás de un `DIV` daría un número plausible y equivocado.
- **Se invalida en cualquier otra instrucción**, en reset y en `RESET_CPU` (que
  pulsa ese mismo reset). El borrado está escrito como una línea incondicional
  al entrar en `STATE_EXECUTE`, no como una lista de opcodes: la lista es justo
  lo que se olvida de actualizar cuando se añade un opcode.
- **Al fallar se recalcula.** Nunca se devuelve un valor rancio.

### Invisible para la arquitectura, sin excepciones

`MULHI`, `REM` y `REMU` dan exactamente el mismo número haya acierto o no. Lo
único que cambia es el número de ciclos. No existe ningún «error por usar
`MULHI` sin `MUL` previo», ni ninguna instrucción para leer ese registro, ni
ninguna capacidad que declarar en `x.tests`: un caso no puede depender de
algo que no puede observar.

El simulador funcional no modela nada de esto, y no debe. `x.tests` ya
excluye `cycles` de la comparación diferencial, así que `--backend both` sigue
valiendo tal cual.

### Cómo está probado, y por qué así

El riesgo que justifica tanto detalle: un acierto indebido no da un fallo
ruidoso. Da un número plausible y equivocado **solo en ciertas secuencias**.

`alu_fast_path_tb.v` no compara contra una tabla de valores esperados, porque
una tabla solo encuentra lo que a uno se le ocurrió tabular. Instancia **dos
CPUs**, una con `ALU_FAST_PATH = 1` y otra con `ALU_FAST_PATH = 0`, ejecuta el
mismo programa en las dos y compara los treinta y dos registros, el PC y el
estado de error. El contrato es literal —«no debe cambiar ni un resultado, solo
los ciclos»— y eso es lo que se comprueba.

Los ciclos se comprueban en los dos sentidos, que es lo que hace útil el
testbench:

- En las secuencias de acierto, la CPU rápida tiene que tardar **menos**. Sin
  esto, un camino rápido que no se activara nunca pasaría el testbench entero.
- En las de fallo, **exactamente lo mismo**. Así se ve que el atajo no se cuela
  donde no debe, incluso cuando por casualidad el número saliera bien.

Las secuencias de fallo son el grueso de la lista: operandos distintos,
instrucción intercalada, tipo cruzado, signo cruzado, `rd` pisando a `ra` y a
`rb`, `MULFX` delante, división por cero delante y arranque en frío.

Nueve mutaciones del RTL —incluidas «no invalidar la etiqueta», «no excluir
`rd == ra`» y «`TAG_DIVU` igual que `TAG_DIV`»— se probaron a propósito y las
tres suites nuevas las detectan todas.
