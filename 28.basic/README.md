# Mini BASIC bootstrap

This directory starts a tiny BASIC intended to run first over UART and later
behind a richer text console.

The first milestone is intentionally modest:

- numbered-line editing for a UART prompt;
- no dynamic allocation;
- one contiguous program buffer;
- a line format that stores compiled statement bytes;
- ordered iteration for `LIST` and `RUN`;
- a symbol table for variables, with `A`-`Z` preloaded as IDs `0..25`;
- expression bytecode compiled once and executed by a tiny stack VM;
- optional builtin function tables, with a default mini set in
  `basic_builtins.c`;
- shared keyword/operator tables for parsing and decompilation;
- a first executable statement set: `LET`, direct assignment, `PRINT`, `GOTO`,
  `IF ... THEN statement [ELSE statement]`, `GOSUB`, `RETURN`, `END`, `STOP`,
  `REM`, `WHILE`, `WEND`, `FOR`, and `NEXT`;
- UART-style line processing for `LIST`, `RUN`, `NEW`, numbered edits, and
  immediate statements;
- a callback-based REPL with prompt, echo, Enter, and backspace handling.

## Program storage

Each stored line is encoded as:

```text
u16 next_offset
u16 line_number
u16 payload_length
u8  payload[payload_length]
```

`next_offset == 0` marks the end of the program. Offset `0` is reserved, so
the first record is placed at offset `1`. Keeping `next_offset` in the record
means execution can walk the program without searching.

For the UART editor:

- `10 PRINT "HELLO"` stores or replaces line 10;
- `10` deletes line 10;
- `LIST` walks the records in order;
- `RUN` will later walk the same records and execute their payloads.

The payload is compiled statement bytecode. `LIST` reconstructs a canonical
source line from those bytes.

## Expression bytecode

Expressions are compiled when a line is entered, not during `RUN`. Variables are
resolved through the program's symbol table and stored in bytecode as direct
indices:

```text
A -> vars[0]
B -> vars[1]
...
Z -> vars[25]
COUNTER -> vars[26]
```

For example:

```basic
A + B * 2
```

becomes stack bytecode:

```text
PUSH_VAR A
PUSH_VAR B
PUSH_I32 2
MUL
ADD
END
```

This keeps the future interpreter simple: statement opcodes call the expression
VM and receive one integer result.

Operator spelling, opcode, and precedence are stored in one shared table. The
parser uses it to emit bytecode and `LIST` uses it to rebuild source text.

## Operators

From the tightest to the loosest:

| Level | Operators |
| --- | --- |
| power | `^` |
| unary | `-` |
| multiplicative | `*` `/` |
| integer division | `\` |
| modulo | `MOD` |
| additive | `+` `-` (`+` also joins strings) |
| shift | `<<` `>>` |
| comparison | `=` `<>` `<` `<=` `>` `>=` |
| `NOT` | `NOT x` |
| `AND` | `x AND y` |
| `OR` | `x OR y` |
| `XOR` | `x XOR y` |

They are left-associative, so `2 ^ 3 ^ 2` is 64, and the words are
case-insensitive and can touch a number or a parenthesis (`12AND 10`, `NOT(A)`)
but not a longer name (`ORANGE` is a variable). The order is the one of the
Amstrad and Microsoft BASICs: `^` binds tighter than the unary minus, so
`-2 ^ 2` is `-4`, and `MOD` is looser than `\`, which is looser than `*` and
`/`, so `10 MOD 3 * 2` is `10 MOD 6`. The shifts are not classic; they sit
between `+` and the comparisons, as in C.

- `/` and `\` are the same integer division, truncating towards zero, and
  `MOD` takes the sign of the dividend, so `-7 \ 2` is `-3` and `-7 MOD 3` is
  `-1`. Dividing by zero, or raising 0 to a negative power, is `?DIV ZERO`.
- `^` is an integer power that wraps like the other operations. A negative
  exponent gives the integer part: `2 ^ -1` is 0, and 1 and -1 stay put.
- `<<` shifts left. `>>` keeps the sign, so `-8 >> 1` is `-4`. A count of 32 or
  more shifts everything out, and a negative count is `?BAD ARG`.
As in the classic BASICs, **true is -1 and false is 0**, and `AND`, `OR`, `XOR`
and `NOT` work on all the bits of an integer. A comparison gives `-1` or `0`,
which makes the same operators serve for conditions and for masks:

```basic
PRINT 5 > 3               -1
PRINT NOT 0               -1
PRINT 12 AND 10           8
PRINT 1000 AND 255        232
IF A > 1 AND NOT B = 2 THEN PRINT "yes"
N = N - (A = B)           counts the times A equals B
```

`NOT` binds looser than the comparisons, so `NOT A = B` is `NOT (A = B)`.
`IF`, `WHILE` and the rest take any non-zero value as true. The logic operators
and `MOD` need integers; comparing two strings, in any of the six ways, gives an
integer, and mixing a string with a number is `?TYPE MISMATCH`.

Symbol names live with `MBProgram`; runtime values live in `MBRuntime`. That
keeps execution fast while allowing `LIST` to reconstruct names:

```basic
10 COUNTER = 1
20 LIMIT = 3
30 PRINT COUNTER
```

## Optional Builtins

Builtin functions are deliberately separated from the core interpreter. The
core stores calls as:

```text
CALL_BUILTIN id argc
```

The default optional table lives in `basic_builtins.c` and currently provides:

```basic
ABS(x)
MIN(a, b)
MAX(a, b)
```

Example:

```basic
10 A = ABS(-5)
20 PRINT MIN(A, 3)
30 PRINT MAX(A, 8)
```

`MBProgram` owns the active builtin table. A target build can provide another
table, or disable builtins with:

```c
mb_program_set_builtins(&program, 0, 0);
```

The default table also has the string functions (see [Strings](#strings)):

```basic
LEN(s$)             length
ASC(s$)             code of the first character (BAD ARG if empty)
VAL(s$)             leading integer of s$, 0 if there is none
CHR$(n)             one-character string, n in 0..255
STR$(n)             decimal text of n
LEFT$(s$, n)        first n characters (n larger than the length is clamped)
RIGHT$(s$, n)       last n characters
MID$(s$, i [, n])   from character i (1-based), n characters or to the end
INSTR(a$, b$)       1-based position of b$ in a$, 0 if absent (empty b$: found at 1)
INSTR(i, a$, b$)    same, starting the search at character i
UCASE$(s$)          upper case
LCASE$(s$)          lower case
SPACE$(n)           n spaces
FRE() / FRE(x)      bytes still free for strings and arrays (x is ignored)
```

`FRE` counts the strings nobody refers to any more as free, since the next
collection gives them back, and does not count the temporaries of the
expression it is part of.

`INSTR` is two entries with the same name and different argument counts; the
parser picks the entry once it knows how many arguments were written.

A builtin is a `MBBuiltin { name, min_args, max_args, fn, string_args,
string_result }`. `string_args` has bit `i` set when argument `i` is a string
and `string_result` is non-zero for a string result, so the parser type-checks
calls when the line is entered. `fn` receives the `MBRuntime`; the helpers
`mb_str_data`, `mb_str_slice`, `mb_str_make` and `mb_str_alloc` read a string
argument, take a zero-copy view of part of it, build a new one from text, or
reserve an empty one to fill in. `LEFT$`, `RIGHT$` and `MID$`
return views, so they allocate nothing.

`SIN` and `COS` are not included yet because this BASIC is currently integer
only. They can be added later once we choose a fixed-point convention.

## Strings

Variables whose name ends in `$` hold strings (`A$`, `NAME$`); everything else
stays an integer. Types are checked when the line is entered, so a mismatch is
reported at entry (`?TYPE MISMATCH`), not in the middle of a `RUN`.

```basic
10 A$ = "HELLO"
20 B$ = A$ + ", " + "WORLD"
30 PRINT B$
40 IF A$ = "HELLO" THEN PRINT "SAME" ELSE PRINT "DIFFERENT"
```

Supported today:

- literals `"..."` (no escape for the quote character, at most 255 bytes);
- `LET`/direct assignment, `PRINT`, and string expressions in `IF`/`WHILE`
  conditions;
- concatenation with `+`;
- comparison with `=`, `<>`, `<`, `<=`, `>` and `>=`, byte by byte (so `"Z" < "a"`),
  a prefix being smaller than the longer string;
- the string builtins listed under [Optional Builtins](#optional-builtins);
- an unassigned string variable is the empty string.

Mixing types (`A$ = 5`, `"a" + 1`, `-"a"`, `FOR A$ = ...`, string arguments to
a builtin) is `MB_ERR_TYPE_MISMATCH`.

Strings are stored without dynamic allocation in a fixed heap inside
`MBRuntime` (`MB_HEAP_SIZE` bytes, 2048 by default, shared with the arrays
described below). A string variable holds a
handle, `offset << 16 | length`, so the VM stack keeps carrying `mb_i32`
values and no opcode needs to know about strings except the four new ones:
`PUSH_STR`, `CONCAT`, `SEQ` and `SNE`.

The heap has two areas:

- `[0, str_used)` is persistent: the current value of each string variable;
- above it, the temporaries of the expression being evaluated (literals and
  partial concatenations). They are discarded when the next expression starts,
  so `IF A$ = "X" THEN ...` inside a loop does not leak.

An assignment copies the result down into the persistent area, which leaves the
previous value of the variable as garbage. When an expression cannot get the
space it needs and there is garbage, the runtime compacts the live strings and
evaluates the expression again. If it still does not fit the result is
`MB_ERR_STRING_TOO_LONG`. Because a string is copied on assignment, `B$ = A$`
needs room for a second copy.

`MBIO` gains `print_str(text, len, ctx)`, which `PRINT` calls for string
expressions; `mb_repl` already provides it.

## First runnable subset

This already runs:

```basic
10 LET A = 1
15 REM count to three
20 PRINT A
30 A = A + 1
40 IF A <= 3 THEN GOTO 20
50 END
```

Expected output:

```text
1
2
3
```

The current runner resolves `GOTO` targets by line number at runtime with a
linear lookup. That is simple and correct for now. A later `RUN` preparation
pass can cache line offsets or build a line index without changing the stored
statement bytecode.

`IF` stores an expression plus embedded statement bytecode for the `THEN` branch
and optional `ELSE` branch. For now those branches are single statements:

```basic
IF A = 0 THEN PRINT 10 ELSE PRINT 20
IF COUNTER <= LIMIT THEN GOTO 30 ELSE END
```

Multi-line `IF` blocks are also supported:

```basic
10 IF A = 0 THEN
20 PRINT 1
30 ELSE
40 PRINT 9
50 END IF
```

`RUN` performs a preparation pass before execution to pair each block `IF` with
its matching `ELSE`/`END IF`. Execution then uses cached offsets rather than
searching for the matching line at runtime.

`WHILE/WEND` use the same preparation pass:

```basic
10 A = 1
20 WHILE A <= 3
30 PRINT A
40 A = A + 1
50 WEND
```

The prepared jump table makes `WHILE` skip past `WEND` when false, and makes
`WEND` jump back to the matching `WHILE`.

`FOR/NEXT` is also supported, including optional `STEP`:

```basic
10 FOR I = 1 TO 3
20 PRINT I
30 NEXT I
40 FOR J = 6 TO 2 STEP -2
50 PRINT J
60 NEXT
```

`FOR` stores the loop variable, start, limit, and step as compiled bytecode.
At runtime a `FOR` frame keeps the active limit and step, so `NEXT` only has to
increment the variable and either jump back to the first body line or continue
after the loop.

`GOSUB` and `RETURN` use a generic control stack in `MBRuntime`. Today it stores
`GOSUB` return offsets and active `FOR` frames; later the same stack can grow
`SUB` or `FUNCTION` frame types.

## UART-facing command layer

`mb_console_process_line` accepts one complete input line:

```text
10 A = 1                 stores line 10
20 PRINT A               stores line 20
20                       deletes line 20
LIST                     decompiles and prints stored lines
RUN                      executes the stored bytecode
NEW                      clears program and variables
PRINT 2 + 3 * 4          immediate statement
```

## Arrays

```basic
10 DIM A(10)              11 elements, indices 0 to 10
20 DIM N$(5)              an array of strings
30 A(I) = A(I - 1) + 1
40 N$(2) = "hello"
50 PRINT A(3); N$(2)
60 ERASE A                gives the memory back
70 REDIM PRESERVE N$(9)   resizes, keeping the elements that still fit
```

Arrays have one dimension and hold integers, or strings when the name ends in
`$`. Elements start at zero (or empty).

- `DIM name(n)` creates an array with `n + 1` elements. `DIM` on an array that
  already exists is `?ARRAY EXISTS`, unless the size is the same: then it clears
  the array, which is what lets a program with a `DIM` at the top run twice.
- `REDIM name(n)` resizes and clears. `REDIM PRESERVE name(n)` resizes and keeps
  the elements common to both sizes; it needs room for both blocks at the same
  time, so it can be `?FULL` even when the new size would fit alone. `REDIM` of
  an array that does not exist creates it.
- `ERASE name` frees the array.
- `name(index)` is an array element unless a builtin has that name. Programs
  can be entered in any order, so a missing `DIM` is only found when the line
  runs: `?NO SUCH ARRAY`. An index outside `0..n` is `?SUBSCRIPT OUT OF RANGE`.
- Not there yet: several dimensions, a list in one `DIM`, and `INPUT` or `FOR`
  on an element.

Arrays live at the top of the heap, each block allocated below the previous
one, while strings grow from the bottom and their temporaries sit just above
them. Nothing keeps a pointer to a block, since every access goes through
`MBRuntime.arrays` (offset, element count, string or not for each name), so
`ERASE` and `REDIM` close the gap by sliding the other blocks up and updating
that table. This is separate from the string collection, which slides the
strings down; the elements of string arrays are roots for it. They only share
the free space between the two regions, and `?FULL` (arrays) or
`?STRING TOO LONG` (strings) is what running out of it looks like. `FRE()` tells
how much is left.

## PRINT lists

```basic
10 PRINT "Age: "; A        prints Age: 5
20 PRINT A; B$; "!"        no separator between items
30 PRINT "no newline";     a trailing ; keeps the cursor on the line
40 PRINT                   just a newline
```

`PRINT` takes any number of integer or string expressions separated by `;`.
Items are printed one after another with nothing in between (integers have no
leading space, unlike Locomotive BASIC), and a trailing `;` suppresses the
final newline. The comma separator of Locomotive BASIC, which jumps to the next
print zone, is not supported and is a syntax error.

A statement is stored as `PRINT flags { type expr }`; bit 0 of `flags` means
"no newline".

## Limits

All sizes and limits are together in the first enum of `basic.h`: variables,
control and expression stacks, the string heap, the source-text limits of an
expression, a `THEN`/`ELSE` branch and a statement's bytecode, and the
`LIST` and `INPUT` line buffers. Any one expression (a `PRINT` item, a
condition, the right side of an assignment...) may have at most
`MB_EXPR_TEXT_MAX - 1` (95) characters of source, not counting the blanks
around it; longer is `?FULL`. The buffers used to decompile are never
smaller than the ones used to compile, and `basic.c` refuses to build if a
change to them breaks that. That keeps every line the compiler accepts
listable, as long as it is written with the usual spacing: `LIST` prints
operators with spaces around them, so an expression typed without any
(`A+B+C+...`) can be longer once listed than when it was entered.

## INPUT

```basic
10 INPUT "Name: "; N$
20 INPUT AGE
30 PRINT "Hi " + N$ + " " + STR$(AGE + 1)
```

`INPUT [ "prompt" ; ] variable` reads one line into a single integer or string
variable. Without a prompt it prints a question mark and a space. A string variable takes the line as
typed, empty included, up to 127 characters. An integer variable accepts
optional spaces, a sign and digits; anything else prints `?REDO` and asks
again.

`RUN` blocks while it waits: `MBIO.read_line(buf, cap, ctx)` must return the
next line (without terminator) or a negative value when there is no more input,
which stops the program with `MB_ERR_NO_INPUT`. The same error comes back when
`read_line` is not set. `mb_repl` provides one that reads from its `get_char`,
with echo and backspace.

## Running in slices, and loading a whole program

`mb_program_run` does not return until the program ends. A host with something
else to do (a screen to redraw, a break key to look at) uses the sliced form:

```c
MBRun run;                                  /* the caller owns it */
mb_run_begin(&program, &runtime, &run);     /* prepares jumps, rewinds */
do {
    r = mb_run_step(&program, &runtime, &run, &io, 200);  /* up to 200 statements */
    /* ... poll keys, redraw ... */
} while (r == MB_RUNNING || r == MB_WAITING_INPUT);
```

`MB_OK` is the end of the program, a negative value an error. Abandoning a run
(a break key) is just not calling `mb_run_step` again. `mb_program_run` is built
on the same pieces, so both behave the same.

`INPUT` can wait without blocking: if `read_line` returns `MB_READ_WAIT` (-2),
`mb_run_step` returns `MB_WAITING_INPUT` and the statement is run again from its
start on the next call, without printing the prompt a second time. The caller
gathers the line meanwhile (a text box, say) and makes `read_line` deliver it.
Called through `mb_program_run`, which has nobody to wait for, `MB_READ_WAIT`
becomes `?NO INPUT`.

`mb_program_load_text(&program, text, len, &error_line)` stores a whole program
given as text, one numbered line per text line (`\n` or `\r\n`, blank lines
skipped, a bare number deletes the line). It does not clear the program first
(`mb_program_clear` does). On an error it returns it and `error_line` is the
1-based position of the offending text line, which is what an editor wants to
put its cursor on.

`mb_repl` wraps that command layer with character I/O callbacks:

```text
READY
> 10 A = 1
> 20 PRINT A
> RUN
1
```

On the target machine, `get_char` and `put_char` can be thin wrappers around
UART receive/transmit.

Stored program lines keep only the executable form:

```text
compiled statement bytecode
```

`LIST` decompiles that bytecode. It will not preserve exact original spacing or
redundant parentheses, but it saves RAM and keeps execution fast.
