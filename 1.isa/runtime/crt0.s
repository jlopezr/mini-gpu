; crt0 de la CPU (MiniABI, abi.md seccion 3): el arranque que antes emitia mini-lcc
; en cada .s. Se usa con `mini-lcc --no-crt`:
;
;     .include "crt0.s"        ; primero: `_start` tiene que quedar en la direccion 0
;     .include "programa.s"    ; el .s de mini-lcc, con `main`
;
; `.include "crt0.s"` desde una carpeta distinta pide `-I 1.isa/runtime`.
;
; Pone la pila al final de `__stack`, llama a `main` y para cuando vuelve. La pila
; va en .bss, despues de todo lo demas; cambiar `CRT_STACK_SIZE` cambia el tamano
; (8 KiB como el arranque del compilador; 32 KiB de RAM en total en el prototipo
; 6, 32 MiB en los que tienen SDRAM).
    .once
    .equ CRT_STACK_SIZE, 8192
    .text
    .globl _start
_start:
    LI   R30, __stack+CRT_STACK_SIZE
    JAL  R31, main
    HALT
    .bss
    .comm __stack, 8192             ; el tamano de .comm no admite .equ: igual que arriba
