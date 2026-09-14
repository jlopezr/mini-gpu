# MiniABI v0.2 draft

This document describes the C ABI for MiniISA and the conventions required to
support 64-bit integer types on a 32-bit MiniISA implementation.

MiniABI is intentionally small and reflects the current experimental MiniISA
toolchain. Some areas remain provisional, but the integer calling convention,
register preservation rules, stack organization, and 64-bit integer
representation described here define the intended ABI.

---

## 1. Scope

- Architecture: scalar MiniCPU, MiniISA.
- Data model:
  - 8-bit `char`
  - 16-bit `short`
  - 32-bit `int`
  - 32-bit `long`
  - 64-bit `long long`
  - 32-bit pointers
- Endianness: little-endian.
- Memory: byte-addressed.
- Native integer register width: 32 bits.
- Native aligned word access: 32 bits.
- Stack: grows downward.
- Entry point: `_start` at address `0x00000000`.

Floating point, varargs, some bitfield details, and some aggregate conventions
are not yet considered ABI-stable.

---

## 2. Register Roles

| Register | Role | Preservation |
|---|---|---|
| `R0` | hard-wired zero | special |
| `R1`-`R4` | argument / return registers | caller-saved |
| `R5`-`R15` | temporaries | caller-saved |
| `R16`-`R28` | preserved general-purpose registers | callee-saved |
| `R29` | preserved register / optional frame pointer | callee-saved |
| `R30` | stack pointer | special |
| `R31` | link register / return address | overwritten by calls |

### 2.1 Caller-saved registers

`R1`-`R15` are volatile across calls.

A caller that needs the value of one of these registers after a function call
must preserve it before making the call.

`R1`-`R4` additionally form the argument and return register area.

### 2.2 Callee-saved registers

`R16`-`R29` are callee-saved.

A function that modifies one of these registers must restore its incoming value
before returning.

Callee-saved registers only need to be saved if the function actually modifies
them.

### 2.3 Special registers

`R0` is permanently zero.

`R30` is the stack pointer and is not available to the general-purpose register
allocator.

`R31` contains the link / return address. Calls normally overwrite it.

A leaf function may return directly through its incoming `R31`.

A non-leaf function that performs another call must preserve its incoming
`R31` if it still needs that return address.

`R29` has an additional optional role as frame pointer, described below.

---

## 3. Program Startup

The current backend emits a simple `_start` before user functions:

```asm
_start:
    MOVHI R30, 0x0001
    ORI   R30, R30, 0x0000
    JAL   R31, main
    HALT
```

The initial stack top is therefore:

```text
0x00010000
```

A future runtime should move this startup sequence into a separate `crt0`
object or configurable runtime file.

---

## 4. Calls and Returns

A direct call uses:

```asm
JAL R31, function
```

An indirect call uses:

```asm
JALR R31, Rn, 0
```

A return uses:

```asm
JR R31
```

### 4.1 32-bit scalar returns

Integer and pointer return values of up to 32 bits are returned in:

```text
R1
```

### 4.2 64-bit integer returns

A `long long` or `unsigned long long` return value uses:

```text
R1 = bits 31:0
R2 = bits 63:32
```

Conceptually:

```text
R2:R1
high:low
```

`R1` and `R2` are caller-saved registers, so using both as return registers
does not conflict with the preservation convention.

Signed and unsigned 64-bit integers use exactly the same calling convention.
Signedness affects operations performed on the value, not its representation
or transport across function boundaries.

### 4.3 Aggregate returns

Struct returns are currently handled by lcc's lowering and have been tested
for small structs.

The aggregate return convention should still be considered provisional until
it is explicitly specified and stabilized.

---

## 5. Argument Passing

`R1`-`R4` provide four 32-bit argument slots.

Arguments are assigned to these slots in source order.

### 5.1 32-bit arguments

Integer and pointer arguments of up to 32 bits consume one argument slot.

For example:

```c
f(int a, int b, void *p)
```

uses:

```text
R1 = a
R2 = b
R3 = p
```

### 5.2 64-bit integer arguments

A 64-bit integer consumes two consecutive 32-bit argument slots.

The low word is assigned first, followed by the high word.

For:

```c
f(long long a, long long b)
```

the convention is:

```text
R1 = a.low
R2 = a.high
R3 = b.low
R4 = b.high
```

A 64-bit argument does not need to begin in an even-numbered register.

For example:

```c
f(int a, long long b)
```

uses:

```text
R1 = a
R2 = b.low
R3 = b.high
```

No register slot is skipped merely to align a register pair.

### 5.3 Register/stack boundary

A scalar 64-bit argument is never split between argument registers and the
stack.

If fewer than two argument registers remain when a 64-bit scalar argument is
encountered, the complete 64-bit value is placed in the outgoing stack
argument area.

Once argument allocation has moved to the stack because an argument cannot fit
completely in the remaining argument registers, subsequent arguments are also
passed on the stack.

The ABI therefore never returns to unused argument registers after crossing
the register/stack boundary.

For example:

```c
f(int a, int b, int c, long long d, int e)
```

uses:

```text
R1 = a
R2 = b
R3 = c
```

`R4` remains unused, and the remaining arguments are passed on the stack:

```text
stack + 0  = d.low
stack + 4  = d.high
stack + 8  = e
```

This rule avoids split scalar values and keeps argument allocation
deterministic.

### 5.4 Stack arguments

Stack argument slots are aligned to 4 bytes.

A 64-bit integer occupies two consecutive 32-bit slots:

```text
lower address     low 32 bits
higher address    high 32 bits
```

No 8-byte alignment is required for 64-bit integers.

### 5.5 Struct arguments

The existing aggregate convention is retained for now.

Struct arguments passed by value are copied as consecutive 32-bit words.

The first words that fit in the four register argument slots are placed in
`R1`-`R4`; later words are placed in the stack argument area.

Unlike scalar 64-bit integer arguments, an aggregate may therefore span the
register/stack boundary.

This behavior is retained because it is already implemented and tested, but
the complete aggregate calling convention remains provisional.

The callee may store incoming argument registers into its stack frame when it
needs addressable parameter storage.

---

## 6. 64-bit Integer Representation

MiniISA registers are 32 bits wide.

A 64-bit integer is represented internally by two 32-bit values:

```text
value = (high << 32) | low
```

Conceptually:

```text
low  = value[31:0]
high = value[63:32]
```

The compiler may use any two available general-purpose registers for these
halves.

They do not need to:

- be consecutive;
- form a predefined pair;
- start at an even register;
- have any architectural relationship.

For example, all of these are valid internal representations:

```text
R5  = low     R6  = high
R8  = low     R17 = high
R23 = low     R4  = high
```

provided that the compiler tracks which register contains each half.

MiniISA does not expose a 64-bit register type or architectural register-pair
concept.

Register pairing exists only in compiler state and in the specific ABI rules
for argument and return registers.

---

## 7. Data Layout

| C type | Size | Alignment |
|---|---:|---:|
| `char` / `unsigned char` | 1 | 1 |
| `short` / `unsigned short` | 2 | 2 |
| `int` / `unsigned int` | 4 | 4 |
| `long` / `unsigned long` | 4 | 4 |
| `long long` / `unsigned long long` | 8 | 4 |
| pointer | 4 | 4 |
| struct | member-dependent | maximum member alignment |

A `long long` therefore occupies 8 bytes but requires only 4-byte alignment.

This matches the native MiniISA memory interface: a 64-bit object is accessed
as two aligned 32-bit words rather than through a native 64-bit load/store.

---

## 8. 64-bit Values in Memory

MiniISA is little-endian.

For a 64-bit value stored at address `p`:

```text
p + 0 : bits 31:0
p + 4 : bits 63:32
```

A 64-bit load is lowered to two ordinary 32-bit loads:

```asm
LOAD Rlow,  Rbase, 0
LOAD Rhigh, Rbase, 4
```

A 64-bit store is similarly:

```asm
STORE Rlow,  Rbase, 0
STORE Rhigh, Rbase, 4
```

MiniISA does not require `LOAD64` or `STORE64` instructions.

---

## 9. Stack Frame

The stack grows downward from `R30`.

The current frame layout, from lower addresses upward, is:

```text
lower addresses

R30 + 0
+------------------------------+
| outgoing argument area       |
+------------------------------+
| saved registers / saved R31  |
+------------------------------+
| local variables and spills   |
+------------------------------+
| ...                          |
+------------------------------+
R30 + framesize
caller stack pointer

higher addresses
```

The exact ordering of saved registers, locals, and spills within the frame is a
backend implementation detail unless explicitly specified elsewhere by the
ABI.

The backend rounds stack frames to 16 bytes.

This is stronger than the 4-byte alignment required by 64-bit integer objects
and stack argument slots.

`R31` is saved only by functions that need to preserve their incoming return
address across another call.

Callee-saved registers are saved only when used.

---

## 10. Optional Frame Pointer

`R29` is the designated optional frame pointer register.

The ABI does not require every function to maintain a frame pointer.

### 10.1 Functions without a frame pointer

When a function does not require a frame pointer, `R29` remains an ordinary
callee-saved general-purpose register and may be used by the register
allocator.

For example, a simple function may operate only with `R30`:

```asm
ADDI R30, R30, -framesize

...

ADDI R30, R30, framesize
JR   R31
```

In this case, `R29` remains available as a normal preserved register.

### 10.2 Functions using a frame pointer

When a function uses a frame pointer, `R29` is removed from the
general-purpose allocation pool for that function.

`R29` points to the caller's stack pointer, which is also the upper boundary of
the current stack frame:

```text
lower addresses

R30 --> +------------------------------+
        | outgoing argument area       |
        +------------------------------+
        | saved registers              |
        +------------------------------+
        | locals / spills              |
        +------------------------------+
R29 --> +------------------------------+
        | caller's stack frame         |
        +------------------------------+

higher addresses
```

Therefore:

```text
R29 = caller SP
R30 = base of current frame
```

and, for a fixed-size frame:

```text
R29 = R30 + framesize
```

This gives the function a stable reference point even if `R30` is adjusted
temporarily.

Because `R29` is callee-saved, a function using it as a frame pointer must
preserve the caller's incoming `R29`.

Conceptually, a frame-pointer prologue performs:

```text
save old R29
allocate frame
R29 = caller SP
```

and the epilogue restores the previous `R29`.

The exact instruction sequence and location used to save the previous `R29`
are backend implementation details, provided that the externally visible ABI
semantics are preserved.

### 10.3 Frame pointer omission

Compilers are encouraged to omit the frame pointer when it is unnecessary.

This allows `R29` to remain available as an additional callee-saved register
and avoids unnecessary prologue/epilogue instructions.

A frame pointer may be useful for:

- debugging and stack inspection;
- functions with dynamically changing stack usage;
- future variable-length array support;
- future `alloca`-style operations;
- simpler unoptimized code generation.

---

## 11. 64-bit Arithmetic Without FLAGS

MiniISA does not expose architectural FLAGS or a carry flag.

Multiword arithmetic therefore materializes carry and borrow explicitly.

### 11.1 Addition

For:

```text
A = Ahi:Alo
B = Bhi:Blo
```

first compute:

```text
Rlo = Alo + Blo
```

A carry occurred exactly when:

```text
unsigned(Rlo) < unsigned(Alo)
```

Therefore:

```text
carry = unsigned(Rlo < Alo) ? 1 : 0
Rhi   = Ahi + Bhi + carry
```

With `SLTU`:

```asm
ADD  Rlo, Alo, Blo
SLTU Rt, Rlo, Alo
ADD  Rhi, Ahi, Bhi
ADD  Rhi, Rhi, Rt
```

This requires no branch and no architectural carry flag.

`SLTU` is used for carry detection even when implementing signed `long long`.

Carry between machine words is a property of the underlying binary addition,
not the signed interpretation of the complete 64-bit value.

### 11.2 Subtraction

For:

```text
R = A - B
```

the borrow from the low word is:

```text
borrow = unsigned(Alo < Blo)
```

Therefore:

```asm
SLTU Rt,  Alo, Blo
SUB  Rlo, Alo, Blo
SUB  Rhi, Ahi, Bhi
SUB  Rhi, Rhi, Rt
```

Again, no FLAGS or data-dependent branch is required.

---

## 12. Materialized Comparisons

MiniISA provides:

```asm
SLT  Rd, Ra, Rb
SLTU Rd, Ra, Rb
```

with semantics:

```text
SLT:
    Rd = signed32(Ra) < signed32(Rb) ? 1 : 0

SLTU:
    Rd = unsigned32(Ra) < unsigned32(Rb) ? 1 : 0
```

Both instructions always produce exactly `0` or `1`.

They do not modify FLAGS and have no control-flow side effects.

`SLT` and `SLTU` provide the primitive materialized less-than comparisons
needed by the compiler.

Other relations can generally be synthesized.

For example, signed:

```text
a >= b
```

can be materialized as:

```asm
SLT  Rd, Ra, Rb
XORI Rd, Rd, 1
```

and unsigned:

```asm
SLTU Rd, Ra, Rb
XORI Rd, Rd, 1
```

Because `R0` is hard-wired to zero:

```asm
SLT Rd, Ra, R0
```

tests whether `Ra` is negative, while:

```asm
SLTU Rd, R0, Ra
```

materializes:

```text
Ra != 0
```

Additional materialized comparison instructions such as `SLE`, `SGE`, `SEQ`,
or `SNE` are not currently required.

---

## 13. MiniISA v0.1 Encoding

MiniISA v0.1 uses individual primary opcodes.

The comparison/control region contains:

```text
0x20 BEQ
0x21 BNE
0x22 BLT
0x23 BGE
0x24 BLTU
0x25 BGEU
0x26 SLT
0x27 SLTU
0x28-0x2B reserved
0x2C JAL
0x2D JALR
0x2E JR
0x2F BRA
```

`SLT` and `SLTU` use the normal R-Type format:

```text
 31          26 25    21 20    16 15    11 10                0
+-------------+--------+--------+--------+--------------------+
|   opcode    |   Rd   |   Ra   |   Rb   |        0          |
+-------------+--------+--------+--------+--------------------+
```

Semantics:

```text
0x26 SLT  Rd, Ra, Rb
     Rd = signed32(Ra) < signed32(Rb) ? 1 : 0

0x27 SLTU Rd, Ra, Rb
     Rd = unsigned32(Ra) < unsigned32(Rb) ? 1 : 0
```

Although physically located in the `0x20-0x2F` region, they can be considered
part of a conceptual "comparison and control flow" family.

MiniISA v0.1 is not reorganized solely to accommodate these instructions.

---

## 14. MiniISA v0.3 Encoding

MiniISA v0.3 supports operation families selected through `func6`.

The existing `MINMAX` family at primary opcode `0x0C` is generalized into a
`COMPARE` family:

| `func6` | Mnemonic | Operands | Semantics |
|---:|---|---|---|
| `0x00` | `MIN` | `Rd, Ra, Rb` | signed minimum |
| `0x01` | `MAX` | `Rd, Ra, Rb` | signed maximum |
| `0x02` | `MINU` | `Rd, Ra, Rb` | unsigned minimum |
| `0x03` | `MAXU` | `Rd, Ra, Rb` | unsigned maximum |
| `0x04` | `SLT` | `Rd, Ra, Rb` | signed less-than, producing 0/1 |
| `0x05` | `SLTU` | `Rd, Ra, Rb` | unsigned less-than, producing 0/1 |

For these operations:

```text
Rc = 0
```

The register-with-suboperation encoding is:

```text
 31       26 25   21 20   16 15   11 10    6 5          0
+----------+-------+-------+-------+-------+------------+
|   0x0C   |  Rd   |  Ra   |  Rb   |   0   |   func6    |
+----------+-------+-------+-------+-------+------------+
```

This organization allows:

- `MIN`, `MAX`, and `SLT` to share signed comparison logic;
- `MINU`, `MAXU`, and `SLTU` to share unsigned comparison logic;
- materialized comparisons to remain in the ALU block;
- the control-flow opcode block to remain dedicated to control flow;
- no additional primary opcode to be consumed.

Further materialized comparison operations should only be added if compiler
measurements justify them.

---

## 15. MiniGPU

`SLT` and `SLTU` retain ordinary per-lane ALU semantics when executed by
MiniGPU.

Each active lane independently computes:

```text
predicate[lane] = comparison(...) ? 1 : 0
```

SIMT instructions may subsequently consume these boolean values.

For example:

```asm
SLTU   R5, R1, R2
BALLOT R6, R5
```

`SLTU` first produces one boolean per lane.

`BALLOT` then aggregates those booleans into a lane mask.

The responsibilities remain separate:

```text
SLT / SLTU     per-lane comparison
BALLOT         SIMT aggregation
ACTIVEMASK     active-lane mask
```

For the current 8-lane MiniGPU, the low 8 bits of the 32-bit ballot result are
used.

The 32-bit representation leaves room for implementations with up to 32 lanes
without changing the ballot result representation.

---

## 16. Object Layout

The assembler currently emits a flat image rather than a relocatable object
file.

Pseudo-sections are laid out in this order:

```text
.text
.rodata
.data
.bss
```

Labels resolve to absolute addresses in the flat image.

There is currently no linker, symbol relocation, or multi-object linking.

---

## 17. Current Test Coverage

The `mini-tst` suite currently covers:

- integer arithmetic, branches, loops, and recursion;
- signed and unsigned comparisons;
- byte and halfword loads/stores;
- globals, arrays, strings, structs, and local arrays;
- global initializers for arrays, structs, and symbol-address pointers;
- nested global aggregate initializers;
- pointer tables;
- pointers to array elements;
- global string arrays;
- local array initializers;
- automatic aggregate initializers;
- nested structs;
- arrays of structs;
- string-backed char arrays;
- unions;
- partial aggregate initializers;
- pointer-to-pointer access;
- larger global arrays;
- multidimensional arrays as globals, locals, and function parameters;
- memory-dump checks for buffers, arrays, and structs;
- `void *`;
- casts between object pointer types;
- casts between pointers and integer/unsigned values;
- byte-wise pointer arithmetic casts;
- `void *` returns;
- function pointer casts;
- `typedef` aliases for struct pointers and function pointers;
- enum constants, including negative values and constant expressions;
- `sizeof` for scalar types, pointers, arrays, structs, and unions;
- numeric conversions among `char`, `short`, unsigned narrow types, and `int`;
- `goto` and labels;
- increment/decrement;
- compound assignment;
- comma operator;
- basic unsigned bitfields;
- function pointers and indirect calls;
- static local arrays and structs with initializers;
- global `const char *` string literal pointers;
- deeper nested call chains;
- common small C routines such as `strlen`, `strcmp`, overlapping `memmove`,
  decimal `atoi`, table lookup, and string separator scanning;
- structs by assignment, by value, and by return;
- mixed-size struct fields;
- simple `memset`/`memcpy`-style routines;
- generated manifests with register expectations and memory dumps.

The current v0.1 baseline is:

```sh
python3 run-mini-tst.py --simulate
```

with expected result:

```text
116/116 compiled+simulated (+4 xfail)
```

The test suite should be extended with dedicated 64-bit tests as the new
lowering is implemented.

---

## 18. Known Gaps

The following areas remain incomplete or provisional:

- no real linker or relocatable object format;
- no external symbol resolution;
- no formal libc/runtime beyond `_start`;
- limited treatment of large addresses beyond `LI` pseudoinstruction
  expansion;
- varargs are not supported;
- 64-bit integer lowering is not yet fully implemented and tested;
- 64-bit multiplication, division, remainder, shifts, comparisons, and
  conversions still require compiler lowering and/or runtime-helper decisions;
- repeated reads of same-width bitfields can currently clobber a shared mask
  register;
- C99 designated initializers are not parsed by the current lcc front-end;
- floating point is not a stable ABI feature;
- aggregate calling and return conventions remain partly provisional;
- register allocation and prologue/epilogue generation are conservative and
  not yet optimized.

---

## 19. ABI Summary

MiniABI uses the following register convention:

```text
R0       hard-wired zero

R1-R4    arguments / returns
         caller-saved

R5-R15   temporaries
         caller-saved

R16-R28  preserved general-purpose registers
         callee-saved

R29      preserved register / optional frame pointer
         callee-saved

R30      stack pointer

R31      link register / return address
```

`R29` is available as a normal callee-saved register when frame-pointer
omission is used.

When used as a frame pointer:

```text
R29 = caller SP / upper boundary of current frame
R30 = base of current frame
```

For 64-bit integers:

```text
sizeof(long long)  = 8
alignof(long long) = 4
```

Memory representation:

```text
lower address      low32
higher address     high32
```

Return convention:

```text
R1 = low32
R2 = high32
```

Argument convention:

- a 32-bit scalar consumes one argument slot;
- a 64-bit scalar consumes two argument slots;
- no even-register alignment is required;
- a 64-bit scalar is never split between registers and stack;
- once argument allocation moves to the stack, subsequent arguments also use
  the stack;
- stack arguments are 4-byte aligned;
- aggregates retain the existing word-wise convention and may cross the
  register/stack boundary.

Internally, the compiler may represent a 64-bit integer using any two available
general-purpose registers.

There is no architectural concept of a 64-bit register pair.

MiniISA does not introduce FLAGS for multiword arithmetic.

`SLT` and `SLTU` materialize comparisons as `0` or `1`, with `SLTU` providing
the carry/borrow primitive required for efficient 64-bit addition and
subtraction.

For MiniISA v0.1:

```text
0x26 SLT
0x27 SLTU
```

For MiniISA v0.3, both operations belong to the `COMPARE` family at opcode
`0x0C`:

```text
func6=0x04 SLT
func6=0x05 SLTU
```