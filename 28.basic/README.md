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

`SIN` and `COS` are not included yet because this BASIC is currently integer
only. They can be added later once we choose a fixed-point convention.

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
