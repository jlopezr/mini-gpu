; Backend MiniABI de rop.h. R1 recibe el puntero al descriptor; R2-R15 son
; caller-saved, asi que estas rutinas hoja no necesitan pila ni salvar registros.
    .once
    .text

    .globl rop_submit_fill
rop_submit_fill:
    LOAD R2, R1, 0
    LOAD R3, R1, 4
    ROPSET P0, R2, P1, R3
    LOAD R2, R1, 8
    LOAD R3, R1, 12
    ROPSET P2, R2, P3, R3
    LOAD R2, R1, 16
    LOAD R3, R1, 20
    ROPSET P4, R2, PMODE, R3
    ROPSUBMIT FILL
    JR R31

    .globl rop_submit_copy
rop_submit_copy:
    LOAD R2, R1, 0
    LOAD R3, R1, 4
    ROPSET P0, R2, P1, R3
    LOAD R2, R1, 8
    LOAD R3, R1, 12
    ROPSET P2, R2, P3, R3
    LOAD R2, R1, 16
    LOAD R3, R1, 20
    ROPSET P4, R2, P5, R3
    LOAD R2, R1, 24
    ROPSET PMODE, R2
    ROPSUBMIT COPY
    JR R31

    .globl rop_submit_copy_fenced
rop_submit_copy_fenced:
    LOAD R2, R1, 0
    LOAD R3, R1, 4
    ROPSET P0, R2, P1, R3
    LOAD R2, R1, 8
    LOAD R3, R1, 12
    ROPSET P2, R2, P3, R3
    LOAD R2, R1, 16
    LOAD R3, R1, 20
    ROPSET P4, R2, P5, R3
    LOAD R2, R1, 24
    ROPSET PMODE, R2
    ROPSUBMIT.F COPY
    JR R31

    .globl rop_submit_generate
rop_submit_generate:
    LOAD R2, R1, 0
    LOAD R3, R1, 4
    ROPSET P0, R2, P1, R3
    LOAD R2, R1, 8
    LOAD R3, R1, 12
    ROPSET P2, R2, P3, R3
    LOAD R2, R1, 16
    LOAD R3, R1, 20
    ROPSET P4, R2, P5, R3
    LOAD R2, R1, 24
    LOAD R3, R1, 28
    ROPSET P6, R2, PMODE, R3
    ROPSUBMIT GENERATE
    JR R31

    .globl rop_submit_span
rop_submit_span:
    LOAD R2, R1, 0
    LOAD R3, R1, 4
    ROPSET P0, R2, P1, R3
    LOAD R2, R1, 8
    LOAD R3, R1, 12
    ROPSET P2, R2, P3, R3
    LOAD R2, R1, 16
    LOAD R3, R1, 20
    ROPSET P4, R2, P5, R3
    LOAD R2, R1, 24
    LOAD R3, R1, 28
    ROPSET P6, R2, P7, R3
    LOAD R2, R1, 32
    LOAD R3, R1, 36
    ROPSET P8, R2, P9, R3
    LOAD R2, R1, 40
    ROPSET PMODE, R2
    ROPSUBMIT SPAN
    JR R31

    .globl rop_submit_config
rop_submit_config:
    LOAD R2, R1, 0
    LOAD R3, R1, 4
    ROPSET P0, R2, P1, R3
    LOAD R2, R1, 8
    LOAD R3, R1, 12
    ROPSET P2, R2, P3, R3
    LOAD R2, R1, 16
    LOAD R3, R1, 20
    ROPSET P4, R2, P5, R3
    LOAD R2, R1, 24
    LOAD R3, R1, 28
    ROPSET P6, R2, P7, R3
    LOAD R2, R1, 32
    LOAD R3, R1, 36
    ROPSET P8, R2, PMODE, R3
    ROPSUBMIT CONFIG
    ROPSET P8, R0, P9, R0
    JR R31

    .globl rop_submit_config_fenced
rop_submit_config_fenced:
    LOAD R2, R1, 0
    LOAD R3, R1, 4
    ROPSET P0, R2, P1, R3
    LOAD R2, R1, 8
    LOAD R3, R1, 12
    ROPSET P2, R2, P3, R3
    LOAD R2, R1, 16
    LOAD R3, R1, 20
    ROPSET P4, R2, P5, R3
    LOAD R2, R1, 24
    LOAD R3, R1, 28
    ROPSET P6, R2, P7, R3
    LOAD R2, R1, 32
    LOAD R3, R1, 36
    ROPSET P8, R2, PMODE, R3
    ROPSUBMIT.F CONFIG
    ROPSET P8, R0, P9, R0
    JR R31

    .globl rop_submit_span_compact
rop_submit_span_compact:
    LOAD R2, R1, 0
    LOAD R3, R1, 4
    ROPSET P0, R2, P1, R3
    LOAD R2, R1, 8
    LOAD R3, R1, 12
    ROPSET P2, R2, P3, R3
    LOAD R2, R1, 16
    LOAD R3, R1, 20
    ROPSET P5, R2, PMODE, R3
    ROPSUBMIT SPAN
    JR R31

    .globl rop_wait
rop_wait:
    ROPWAIT
    JR R31

    .globl rop_wait_invalidate
rop_wait_invalidate:
    ROPWAIT INV
    JR R31

    .globl rop_status
rop_status:
    ROPSTATUS R1
    JR R31

    .globl rop_status_clear
rop_status_clear:
    ROPSTATUS R1, CLEAR
    JR R31
