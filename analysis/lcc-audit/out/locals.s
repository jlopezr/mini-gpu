.text
.globl _start
_start:
LI R30, __stack+8192
JAL R31, main
HALT
.globl locals
.text
.align 4
locals:
ADDI R30, R30, -16
STORE R28, R30, 0
STORE R29, R30, 4
ADD R15, R1, R0
ADDI R29, R15, 1
ADDI R28, R29, 2
ADDI R14, R28, 3
STORE R14, R30, -4+16
ADD R14, R29, R28
LOAD R13, R30, -4+16
ADD R1, R14, R13
L.1:
LOAD R28, R30, 0
LOAD R29, R30, 4
ADDI R30, R30, 16
JR R31
.globl main
.align 4
main:
ADDI R30, R30, -32
STORE R31, R30, 16
MOVI R1, 7
JAL R31, locals
ADD R15, R1, R0
L.2:
LOAD R31, R30, 16
ADDI R30, R30, 32
JR R31
.bss
.comm __stack,8192
