; ============================================================
; async-error.asm - un trabajo que el ROP rechaza para la CPU en ROPWAIT
;
; Un SPAN con ancho 0 es un descriptor invalido. No se puede detectar al
; enviarlo (la validez de un compacto depende de la configuracion vigente
; cuando se ejecuta), asi que ROPSUBMIT acepta y el ROP marca el error
; pegajoso. ROPSTATUS lo ve sin parar; ROPWAIT para con ERROR_ROP (0x07) en
; su PC.
;
; Registros al parar:
;   R1  ROPSTATUS antes del error: nada pendiente, 16 huecos (0x1000)
; ============================================================

start:
    ROPSTATUS R1
    ROPSET P2, R0, P3, R0          ; ancho 0, filas 0
    LI    R2, 0x0063               ; LT, escribe Z y color
    ROPSUBMIT SPAN, PMODE, R2
    ROPWAIT                        ; aqui para, ERROR_ROP
    MOVI  R3, 1                    ; no se ejecuta: el PC del error lo dice
    HALT
