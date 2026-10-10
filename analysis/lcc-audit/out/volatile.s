.text
.globl _start
_start:
LI R30, __stack+8192
JAL R31, main
HALT
.globl probe
.text
.align 4
probe:
ADDI R30, R30, -16
LI R15, mmio
LOAD R15, R15, 0
STORE R15, R30, -4+16
LI R15, mmio
LOAD R14, R30, -4+16
MOVI R13, 1
ADD R14, R14, R13
STORE R14, R15, 0
LOAD R15, R15, 0
ADD R1, R15, R0
L.1:
ADDI R30, R30, 16
JR R31
.globl main
.align 4
main:
ADDI R30, R30, -32
STORE R31, R30, 16
LI R15, mmio
MOVI R14, 4
STORE R14, R15, 0
JAL R31, probe
ADD R15, R1, R0
L.2:
LOAD R31, R30, 16
ADDI R30, R30, 32
JR R31
.bss
.globl mmio
.comm mmio,4
.bss
.comm __stack,8192
