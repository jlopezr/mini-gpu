; Un `type` de GETID mayor que 4 esta reservado: ERROR_INVALID_ENCODING (0x05).
;
; No hay mnemonico para esto, a proposito: se escribe la palabra a mano.
;   0x30 << 26 | rd = 1 << 21 | type = 5 << 16  ->  0xC0250000
; El `type` valido mas alto (4, GETARG) se ejecuta justo antes, para que el caso
; separe «el 4 vale» de «el 5 no».
    NOP
    GETARG R2
    .word 0xC0250000
    HALT
