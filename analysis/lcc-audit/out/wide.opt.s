.text
.globl _start
_start:
LI R30, __stack+8192
JAL R31, main
HALT
.globl wide
.text
.align 4
wide:
MULHI R5, R1, R2
SARI R6, R1, 31
AND R6, R6, R2
ADD R5, R5, R6
SARI R6, R2, 31
AND R6, R6, R1
ADD R5, R5, R6
MUL R12, R1, R2
ADD R13, R5, R0
ADDI R1, R12, 2
SLTU R5, R1, R12
ADDI R2, R13, 1
ADD R2, R2, R5
L.1:
JR R31
.globl main
.align 4
main:
ADDI R30, R30, -32
STORE R31, R30, 16
MOVI R1, 7
MOVI R2, 9
JAL R31, wide
ADD R1, R1, R0
L.2:
LOAD R31, R30, 16
ADDI R30, R30, 32
JR R31
.bss
.comm __stack,8192
