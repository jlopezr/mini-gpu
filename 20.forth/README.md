# MiniForth: un Forth sobre la consola serie

Un Forth que corre en la MiniCPU y se usa por la consola del monitor, con
intérprete y compilador. Es el primer programa del repositorio que **hace algo
distinto según lo que escribas** y el primero que **aprende palabras nuevas**;
existe porque la [19](../19.fpga-cpu-hdmi-ls) le dio a la CPU dos cosas que
hacían falta: un puerto serie y las llamadas indirectas.

```text
MiniForth
ok> 2 3 + .
5
ok> : cuad dup * ;
ok> : cuarta cuad cuad ;
ok> 3 cuarta .
81
ok> words
CUAR CUAD BYE ; : WORD CR ! @ > < = .S . NEG OVER SWAP DROP DUP / * - +
ok> bye
adios
```

## Las dos mitades

Un Forth son un intérprete de texto y un compilador, y aquí están las dos. Lo
interesante es que **son el mismo bucle**: la única diferencia es una variable,
`STATE`, que dice si la palabra encontrada se ejecuta o se anota.

```asm
found:
    LOAD  R14, R11, 12          ; flags
    ANDI  R15, R14, 1           ; ¿inmediata?
    BNE   R15, R0, execute_it
    BEQ   R2, R0, execute_it    ; STATE = 0: ejecutar
    STORE R11, R16, 0           ; compilar: anotar la entrada
```

Esas cinco instrucciones son todo el compilador. El resto —`:`, `;`, `LIT`— son
tres palabras cortas.

**Y sigue siendo un intérprete.** Lo que `:` produce no es código máquina: es
una lista de punteros a entradas del diccionario, y hace falta un segundo
intérprete —el *interno*, en `run_colon`— para recorrerla. Por eso Forth se
llama interpretado aunque tenga compilador, y por eso «compilar» aquí significa
algo mucho más modesto que en C: la palabra estándar es literalmente
`COMPILE,`, y lo único que hace es añadir una referencia.

**El control de flujo sale del mismo mecanismo**, y eso es lo bonito: `IF`,
`THEN`, `BEGIN`… no son sintaxis. Son palabras inmediatas que, al ejecutarse en
modo compilación, emiten saltos. El intérprete no sabe que existen.

Un salto hacia adelante no conoce su destino cuando se emite, así que `IF` deja
un **hueco** y apunta su dirección; `THEN` lo rellena con donde hemos llegado.
Las direcciones pendientes se guardan en la **pila de datos**, como en Forth de
verdad — por eso dejar basura en la pila dentro de una definición descuadra el
control de flujo, que es un clásico del lenguaje.

```text
ok> : signo dup 0 < if drop -1 else 0 > if 1 else 0 then then . ;
ok> -7 signo
-1
ok> : fact 1 1052672 ! begin dup 1 > while dup 1052672 @ * 1052672 ! 1 - repeat drop 1052672 @ . ;
ok> 10 fact
3628800
```

| Palabra | Efecto |
|---|---|
| `:` `;` | Definen una palabra nueva |
| `IF` `ELSE` `THEN` | Condicional |
| `BEGIN` `UNTIL` | Bucle que sale cuando la condición es cierta |
| `BEGIN` `WHILE` `REPEAT` | Bucle con salida por el medio |
| `BEGIN` `AGAIN` | Bucle sin salida |
| `CREATE` `DOES>` | Definen palabras que definen palabras |
| `,` `ALLOT` `CELLS` | Reservan y rellenan la zona de datos |
| `WORDS` | Lista el diccionario, de lo más nuevo a lo más viejo |
| `+` `-` `*` `/` | Aritmética sobre los dos de arriba |
| `DUP` `DROP` `SWAP` `OVER` | Manipulación de pila |
| `NEG` | Cambia el signo del de arriba |
| `.` | Saca el de arriba y lo imprime |
| `.S` | Enseña la pila entera sin tocarla |
| `=` `<` `>` | Comparan y dejan −1 (cierto) o 0 (falso) |
| `@` `!` | `dir @` lee memoria; `valor dir !` escribe |
| `CR` | Salto de línea |
| `BYE` | Para la CPU |

Mayúsculas y minúsculas dan igual: `dup` y `DUP` son la misma palabra.

## Las tres decisiones que dan forma al programa

**Los nombres caben en cuatro caracteres y se guardan empaquetados en una
palabra de 32 bits.** `DUP` es `0x00505544`. Así buscar una palabra es comparar
enteros —siete instrucciones— en vez de recorrer cadenas, y el diccionario son
dos palabras por entrada. Es una limitación de verdad: `NEGATE` no cabe, y por
eso la palabra se llama `NEG`.

Tiene una trampa que costó un bug: como el empaquetado se queda con los cuatro
primeros caracteres, **`dropit` coincidía con `DROP`** y ejecutaba una palabra
que nadie había escrito. El intérprete compara ahora también la longitud.

**`JALR` es lo que hace posible el programa.** El intérprete no puede saber a
qué código saltar hasta que ha buscado la palabra: el destino sale de una tabla
en memoria. Sin salto indirecto habría que poner una cadena de comparaciones,
una por palabra, y el diccionario dejaría de ser datos para convertirse en
código. Es el primer programa del repositorio que *necesita*
[las llamadas de la 19](../19.fpga-cpu-hdmi-ls/docs/llamadas.md).

**La división por cero se comprueba antes de dividir.** En esta CPU `DIV` con
divisor cero es un error terminal: para la máquina con código `0x04`. Un
intérprete que lo permitiera se mataría a sí mismo con un `1 0 /`, y la sesión
se acabaría ahí. Lo mismo con la pila: cada palabra comprueba que hay bastante
antes de tocar nada, porque un `+` con la pila vacía leería memoria de cualquier
sitio y el error aparecería mucho más tarde y en otro lado.

## Las dos pilas

**La de datos** es la de Forth: la que `DUP` duplica y `+` consume. Vive en
`0x00100000`.

**La de retorno** vive en `0x00103000` y guarda punteros del intérprete interno.
Hace falta exactamente en un sitio —`inner_call`— y por una razón concreta: una
definición llama a otras que llaman a otras, y **la profundidad depende de lo
que escriba el usuario**, no de lo que escribiera quien programó el intérprete.
Con `: b a a ;` y `: c b b ;` ya no se puede repartir un registro por nivel.

Las rutinas nativas, en cambio, siguen devolviendo por registros de enlace
repartidos a mano, y llegan a cuatro niveles:

```text
main (R31) -> palabra (R28) -> print_num (R29) -> emit (R30)
```

Eso funciona porque esa profundidad sí se conoce al escribir el programa. Pero
obliga a que quien llama conozca los registros que usa el llamado, y ya costó un
fallo: `.S` llevaba su cursor en R11, que es un temporal de `print_num`, así que
la primera cifra impresa lo destruía y el bucle se quedaba recorriendo memoria
para siempre. Ver
[`docs/llamadas.md`](../19.fpga-cpu-hdmi-ls/docs/llamadas.md) de la 19.

### `R0` es el cero, y `R3` es `BASE`

Era al revés: `R0` guardaba `BASE` y había que reservar `R3` y un `MOVI` para
tener un cero con el que comparar, porque en la MiniISA v0.1 `R0` es un registro
general. Desde que
[`21.fpga-cpu-hdmi-alu`](../21.fpga-cpu-hdmi-alu) lo cablea a cero, el cero sale
gratis y los dos registros se intercambian. Son 58 usos de `R0` como cero y 8 de
`R3` como `BASE`, y el `MOVI` sobra.

**El programa sigue corriendo en la 19**, que es donde está el bitstream con
puerto serie. No depende de que las escrituras a `R0` se descarten: depende de
no escribirlo nunca, y eso vale en cualquier versión, porque el reset deja el
banco a cero. Es la diferencia entre una disciplina compatible hacia atrás y una
dependencia de la ISA nueva.

## Qué pasa cuando algo falla dentro de un `:`

Se deshace la definición a medias: `HERE` vuelve al principio de la cabecera y
`HEAD` al enlace anterior. Sin eso quedaría en la lista una entrada cuyo cuerpo
**no termina en cero**, y la próxima vez que alguien la invocara el intérprete
interno se iría a recorrer memoria. Es el `SMUDGE` de los Forth de verdad, en
versión pobre.

**Otros límites conocidos**: la pila de datos no comprueba desbordamiento
—mil palabras y empieza a pisar el buffer de entrada—, la línea son 128 bytes, y
no hay `MOD` porque `DIV` solo da el cociente.

## Palabras que definen palabras

`CREATE` hace una cabecera con el nombre que viene detrás; la palabra resultante
apila la dirección de su zona de datos, que empieza justo detrás. Con `,` se
meten valores ahí y con `ALLOT` se reserva sitio.

`DOES>` es lo que lo convierte en un mecanismo. Va dentro de una definición y la
parte en dos:

```forth
: CONSTANT  CREATE , DOES> @ ;
\           ^^^^^^^^        lo que pasa al DEFINIR
\                      ^^   lo que hace la palabra DEFINIDA
```

**Y eso significa que `CONSTANT` y `VARIABLE` no son parte de este programa: se
escriben en Forth, desde la consola.**

```text
ok> : constant create , does> @ ;
ok> 5 constant cinco
ok> cinco cinco + .
10
ok> : variable create 0 , ;
ok> variable v
ok> 7 v ! v @ .
7
ok> : array create cells allot does> swap cells + ;
ok> 5 array v
ok> 11 0 v !  22 1 v !
ok> 0 v @ . 1 v @ .
11
22
```

En casi cualquier otro lenguaje, `def`, `const` o `class` son palabras que el
compilador conoce y tú no puedes añadir. Aquí el mecanismo de definir está
abierto.

La implementación tiene un detalle bonito: **`DOES>` no es inmediata**, se
compila como una palabra normal. Cuando `CONSTANT` se ejecuta y llega a ella, el
puntero del intérprete interno apunta ya a lo que la sigue —el `@`—, así que
basta con guardarlo en el campo de código de la palabra recién creada y terminar
la definición ahí. Cuatro instrucciones.

## Qué le falta para ser un Forth de verdad

Por orden de cuánto se echa en falta:

**Palabras de pila.** `ROT`, `-ROT`, `PICK`, `ROLL`, `2DUP`, `TUCK`, `NIP`. Con
solo `DUP DROP SWAP OVER` no se llega al tercer elemento, y eso obliga a usar
memoria donde bastaría la pila: se ve en el factorial de arriba, que guarda el
acumulador en `0x00102000` porque no le queda otra. Es lo primero que añadiría.

**`>R` `R@` `R>`.** Acceso a la pila de retorno desde el programa. Aquí es
delicado porque esa pila la usa el intérprete interno para sus punteros, y
mezclarlas requiere cuidado — aunque es exactamente lo que hace Forth.

**`DO` `LOOP` `I`.** El bucle contado, que guarda índice y límite en la pila de
retorno. Depende de lo anterior.

**Texto.** `." mensaje"`, `S"`, `TYPE`, `EMIT`, `KEY`, `CHAR`. Ahora mismo un
programa no puede imprimir nada que no sea un número.

**Bases.** `BASE`, `HEX`, `DECIMAL`. Solo hay decimal.

**Aritmética completa.** `MOD`, `/MOD`, `*/`, `ABS`, `MIN`, `MAX`, y los
operadores lógicos `AND` `OR` `XOR` `INVERT`. `MOD` no está porque `DIV` solo da
cociente, pero se calcula con `n - (n/m)*m`.

**Y lo estructural**: `EXIT` y `RECURSE`, `POSTPONE`, `[` `]` `LITERAL` para
controlar la compilación desde el propio Forth, `IMMEDIATE` como palabra de
usuario, `FORGET`/`MARKER` para deshacer el diccionario, `CATCH`/`THROW` para
excepciones, y `EVALUATE` para interpretar una cadena.

Con `CREATE`/`DOES>` dentro, **ya nada de eso pide cambios estructurales**: son
palabras que se añaden sin tocar el intérprete, y unas cuantas se pueden
escribir en el propio Forth.

## Mapa de memoria

| Dirección | Qué |
|---|---|
| `0x00000000` | El programa, con el diccionario y los mensajes dentro |
| `0x00100000` | Pila de datos, hacia arriba |
| `0x00101000` | Buffer de la línea de entrada, 128 bytes |
| `0x00102000` | Memoria libre, para jugar con `@` y `!` |
| `0x00103000` | Pila de retorno del intérprete interno |
| `0x00104000` | Diccionario en RAM: aquí añade `:` |
| `0x80000200` | Puerto serie: `+0` DATA, `+4` STATUS |

Como `@` y `!` alcanzan los 32 MiB enteros, desde el propio Forth se puede leer
y escribir el framebuffer. `0x01000000` es el buffer frontal.

## Ejecutar

Necesita el bitstream de la [19](../19.fpga-cpu-hdmi-ls), que es el único con
puerto serie:

```powershell
cd ..\19.fpga-cpu-hdmi-ls
.\run-demo.ps1 ..\20.forth\forth.asm
..\.venv\Scripts\python.exe monitor.py console --port COM3
```

Se sale de la consola con Ctrl+]. Sin terminal, desde un script:

```powershell
..\.venv\Scripts\python.exe monitor.py send "2 3 + .`n" --port COM3
```

## Verificación

```powershell
..\.venv\Scripts\python.exe -m unittest test_forth -v
```

Sesenta y una pruebas que ejecutan el intérprete **de verdad** sobre el simulador
funcional, metiéndole líneas por la cola de entrada y comprobando lo que
contesta. No hay placa de por medio: `SerialDevice` de
[`2.cpu-sim-func`](../2.cpu-sim-func) es el mismo dispositivo que
`serial_port.v`, así que lo que se prueba es el programa.

Las pruebas cubren lo que se rompe de verdad: el orden de los operandos
(`10 3 -` es 7, no −7), el cero —que no pasa por el bucle de dígitos y tiene su
propio camino—, que `.S` no toca la pila, que la línea se abandona entera tras
un error, y que una división por cero no mata la sesión.

Trece son de `CREATE`/`DOES>`, doce del control de flujo --IF/ELSE/THEN anidados, los tres bucles, y que
un THEN sin IF avise en vez de escribir en una direccion cualquiera-- y quince
del compilador: que una definición no se ejecuta al
definirla, que los números van con LIT, el anidamiento de tres niveles, que
redefinir tapa a la anterior pero **no** cambia las palabras que ya la usaban
—se compiló un puntero, no una búsqueda por nombre—, y que un error dentro de
un : deshace la definición.

**Tres de las pruebas empezaron mal escritas**, y merece la pena saberlo: daba
por hecho que `1 2 swap drop` deja 1 —deja 2—, que un `-` suelto sería «palabra
desconocida» —es la resta, con la pila vacía— y que el error imprimiría el
nombre en mayúscula. Las tres eran expectativas equivocadas mías, no fallos del
intérprete; las otras tres sí eran bugs.
