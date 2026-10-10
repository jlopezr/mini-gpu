.text
.globl _start
_start:
LI R30, __stack+8192
JAL R31, main
HALT
.globl use
.text
.align 4
use:
ADD R15, R1, R0
LOAD R14, R15, 0
LOAD R13, R15, 4
ADD R14, R14, R13
LOAD R13, R15, 8
ADD R14, R14, R13
LOAD R13, R15, 12
ADD R1, R14, R13
L.1:
JR R31
.rodata
.align 4
L.3:
.word 0x1
.word 0x2
.word 0x3
.word 0x4
.globl arrays
.text
.align 4
arrays:
ADDI R30, R30, -48
STORE R31, R30, 16
ADDI R15, R30, -16+48
LI R14, L.3
LOAD R5, R14, 0
STORE R5, R15, 0
LOAD R5, R14, 4
STORE R5, R15, 4
LOAD R5, R14, 8
STORE R5, R15, 8
LOAD R5, R14, 12
STORE R5, R15, 12
ADDI R1, R30, -16+48
JAL R31, use
ADD R15, R1, R0
L.2:
LOAD R31, R30, 16
ADDI R30, R30, 48
JR R31
.globl main
.align 4
main:
ADDI R30, R30, -32
STORE R31, R30, 16
JAL R31, arrays
ADD R15, R1, R0
L.4:
LOAD R31, R30, 16
ADDI R30, R30, 32
JR R31
.bss
.comm __stack,8192
