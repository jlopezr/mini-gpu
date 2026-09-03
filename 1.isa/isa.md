00xxxx   ALU / CPU común
01xxxx   memoria
10xxxx   control de flujo
11xxxx   GPU / sistema / extensiones

---

000000  ADD
000001  SUB
000010  MULFX
000011  AND
000100  OR
...

010000  LOAD
010001  STORE

100000  BEQ
100001  BNE
100010  BLT
100011  BGE
100100  BRA

110000  GETTID
110001  GETLANE
110010  GETWARP
110011  SETMASK
110100  PUSHMASK
110101  POPMASK
110110  BAR
...

---

ISA:
    32 registros/thread
    R0 ... R31
    32 bits cada uno

MiniCPU física:
    32 × 32 bits

MiniGPU inicial:
    32 regs
    × 8 lanes
    × 8 warps
    × 32 bits

    = 65536 bits
    = 8 KiB

---

Instrucción:          32 bits
Registro:             32 bits
Registros/thread:     32 (R0-R31)
Opcode:               6 bits
Direcciones:          32 bits
ISA base:             CPU + kernel común
Espacio reservado:    extensiones SIMT/GPU

---

R0...R31
    =
registros arquitectónicos
    ≠
cantidad de registros físicos