.text
.globl _start
_start:
LI R30, __stack+8192
JAL R31, main
HALT
.globl control
.text
.align 4
control:
ADDI R30, R30, -16
STORE R28, R30, 0
STORE R29, R30, 4
ADD R28, R0, R0
ADD R29, R0, R0
BRA L.5
L.2:
ANDI R14, R29, 1
BEQ R14, R0, L.6
ADD R28, R28, R29
BRA L.7
L.6:
SUB R28, R28, R29
L.7:
L.3:
ADDI R29, R29, 1
L.5:
BLT R29, R1, L.2
ADD R1, R28, R0
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
MOVI R1, 10
JAL R31, control
L.8:
LOAD R31, R30, 16
ADDI R30, R30, 32
JR R31
.bss
.comm __stack,8192
