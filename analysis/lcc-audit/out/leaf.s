.text
.globl _start
_start:
LI R30, __stack+8192
JAL R31, main
HALT
.globl leaf
.text
.align 4
leaf:
ADD R15, R1, R0
ADD R14, R2, R0
ADD R13, R3, R0
ADD R12, R15, R14
MUL R12, R12, R13
SUB R1, R12, R15
L.1:
JR R31
.globl main
.align 4
main:
ADDI R30, R30, -32
STORE R31, R30, 16
MOVI R1, 3
MOVI R2, 4
MOVI R3, 5
JAL R31, leaf
ADD R15, R1, R0
L.2:
LOAD R31, R30, 16
ADDI R30, R30, 32
JR R31
.bss
.comm __stack,8192
