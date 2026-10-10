.text
.globl _start
_start:
LI R30, __stack+8192
JAL R31, main
HALT
.globl fib
.text
.align 4
fib:
ADDI R30, R30, -32
STORE R29, R30, 16
STORE R31, R30, 20
ADD R29, R1, R0
MOVI R15, 2
BGE R1, R15, L.2
ADD R1, R1, R0
BRA L.1
L.2:
ADDI R1, R1, -1
JAL R31, fib
STORE R1, R30, -4+32
ADDI R1, R29, -2
JAL R31, fib
LOAD R14, R30, -4+32
ADD R1, R14, R1
L.1:
LOAD R29, R30, 16
LOAD R31, R30, 20
ADDI R30, R30, 32
JR R31
.globl main
.align 4
main:
ADDI R30, R30, -32
STORE R31, R30, 16
MOVI R1, 8
JAL R31, fib
L.4:
LOAD R31, R30, 16
ADDI R30, R30, 32
JR R31
.bss
.comm __stack,8192
