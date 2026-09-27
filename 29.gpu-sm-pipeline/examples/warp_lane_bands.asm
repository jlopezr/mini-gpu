; ============================================================
; warp_lane_bands.asm - patron de diagnostico warp/lane para la MiniGPU
;
; Pinta 320x240 RGB565 en 0x01000000. Cada warp una banda horizontal de 30
; filas con su color base; dentro de la banda, cada lane un escalon de
; intensidad. El resultado hace visible de un vistazo que arrancaron los ocho
; warps, que participan las ocho lanes, y donde empieza y acaba cada uno.
;
; El kernel solo escribe RAM. No toca MMIO: el framebuffer y el scanout los
; configura la CPU o el monitor desde fuera (VIDEO vive en 0x80200000 segun
; mmio.md, y aqui no aparece ninguna direccion 0x8xxxxxxx).
;
; AVISO: `isa.md` dice que GETWARP y GETLANE no estan implementadas ni tienen
; opcode asignado. Se usan aqui por encargo explicito. El resto del programa es
; capability Base: no usa MULHI, DIVU, REM, REMU, SLT, SLTU, JAL, JALR, JR,
; los accesos sub-palabra ni la variante de desplazamiento inmediato.
;
; Reparto
; -------
;
;   warp w -> filas 30w .. 30w+29, o sea 19200 bytes consecutivos
;   lane l -> las words de indice l, l+8, l+16, ... dentro de esa region
;
; Una instruccion de store del warp genera ocho direcciones consecutivas
; separadas por 4 bytes, base+0 .. base+28: 32 bytes seguidos.
;
; El bucle unico
; --------------
;
; 640 bytes de stride y 32 bytes por iteracion dan 20 iteraciones por fila
; exactas, asi que al avanzar siempre 32 la lane cambia de fila sola y conserva
; su columna relativa. No hay correccion de stride ni bucle de filas:
;
;   600 iteraciones x 32 bytes = 19200 bytes = 30 filas
;
; El corte del bucle es la propia direccion comparada contra el final de la
; region, no un contador aparte. Asi el cuerpo son TRES instrucciones.
;
; Registros:
;   R1  warp id          R2  lane id          R3  direccion de escritura
;   R4  color base y luego el pixel RGB565    R5  packed de 32 bits
;   R7  temporal         R8  factor de intensidad (lane+1)
;   R9  rojo   R10 verde   R11 azul           R12 fin de la region
;   R20 constante 11     R21 constante 5      R22 constante 3
;   R23 constante 16     R0  cero, cableado
; ============================================================

start:
    GETWARP R1                  ; 0..7
    GETLANE R2                  ; 0..7

    MOVI  R20, 11               ; cantidades de desplazamiento, en registro:
    MOVI  R21, 5                ; SHL/SHR por registro son Base, la variante
    MOVI  R22, 3                ; inmediata (SHLI/SHRI) pide `shift_immediate`
    MOVI  R23, 16

    ; ---- color base del warp ----
    ; Cadena de comparaciones en vez de tabla en memoria: `isa.md` documenta
    ; instrucciones, no directivas de datos, y esto cuesta cero dentro del
    ; bucle. Los literales van con ORI sobre R0 porque el inmediato de MOVI es
    ; signed de 16 bits y no admite 0xF800.
    ORI   R4, R0, 0xF800        ; warp 0: rojo
    BEQ   R1, R0, color_listo

    MOVI  R7, 1
    BNE   R1, R7, no_w1
    ORI   R4, R0, 0x07E0        ; warp 1: verde
    BRA   color_listo
no_w1:
    MOVI  R7, 2
    BNE   R1, R7, no_w2
    ORI   R4, R0, 0x001F        ; warp 2: azul
    BRA   color_listo
no_w2:
    MOVI  R7, 3
    BNE   R1, R7, no_w3
    ORI   R4, R0, 0xFFE0        ; warp 3: amarillo
    BRA   color_listo
no_w3:
    MOVI  R7, 4
    BNE   R1, R7, no_w4
    ORI   R4, R0, 0x07FF        ; warp 4: cyan
    BRA   color_listo
no_w4:
    MOVI  R7, 5
    BNE   R1, R7, no_w5
    ORI   R4, R0, 0xF81F        ; warp 5: magenta
    BRA   color_listo
no_w5:
    MOVI  R7, 6
    BNE   R1, R7, no_w6
    ORI   R4, R0, 0xFC00        ; warp 6: naranja
    BRA   color_listo
no_w6:
    ORI   R4, R0, 0xFFFF        ; warp 7: blanco
color_listo:

    ; ---- intensidad por lane ----
    ; canal' = canal * (lane+1) / 8, por separado en los tres canales. El
    ; factor va de 1/8 a 8/8, asi que la lane 7 da el color base a plena
    ; intensidad y la lane 0 la version mas oscura. Escalar cada canal y no la
    ; palabra entera es lo que mantiene el tono: un AND sobre los 16 bits
    ; mezclaria los campos.
    ADDI  R8, R2, 1             ; factor de 1 a 8

    SHR   R9,  R4, R20          ; rojo5 = color >> 11
    ANDI  R9,  R9, 0x1F
    MUL   R9,  R9, R8
    SHR   R9,  R9, R22          ; /8, maximo 31*8/8 = 31

    SHR   R10, R4, R21          ; verde6 = (color >> 5) & 0x3F
    ANDI  R10, R10, 0x3F
    MUL   R10, R10, R8
    SHR   R10, R10, R22         ; maximo 63

    ANDI  R11, R4, 0x1F         ; azul5 = color & 0x1F
    MUL   R11, R11, R8
    SHR   R11, R11, R22         ; maximo 31

    SHL   R9,  R9, R20          ; recomponer RGB565
    SHL   R10, R10, R21
    OR    R4,  R9, R10
    OR    R4,  R4, R11

    ; ---- packed de 32 bits: el mismo pixel dos veces ----
    ; Un store de 32 bits pinta dos pixeles adyacentes de golpe. No se usa
    ; STOREH en ningun sitio: ademas de pedir `subword_memory`, duplicaria el
    ; numero de transacciones de la LSU.
    SHL   R5, R4, R23           ; pixel << 16
    OR    R5, R5, R4            ; | pixel

    ; ---- direccion inicial de la lane ----
    ;   FB_BASE + warp*19200 + lane*4
    ; 30 filas x 640 bytes = 19200, que entra en el inmediato signed de MOVI.
    MOVHI R3, 0x0100            ; FB_BASE = 0x01000000
    MOVI  R7, 19200
    MUL   R7, R1, R7
    ADD   R3, R3, R7            ; base de la banda del warp
    ADD   R7, R2, R2            ; lane*2
    ADD   R7, R7, R7            ; lane*4
    ADD   R3, R3, R7            ; columna de la lane dentro de la fila

    ; Fin de la region del warp, desplazado por la misma columna: la direccion
    ; llega EXACTAMENTE aqui tras 600 avances de 32, asi que la igualdad corta
    ; el bucle sin contador. 600*32 = 19200.
    MOVI  R12, 19200
    ADD   R12, R3, R12

    ; ---- bucle principal: tres instrucciones ----
loop:
    STORE R5, R3, 0             ; 8 lanes -> base+0..base+28, 32 bytes seguidos
    ADDI  R3, R3, 32
    BNE   R3, R12, loop

    EXIT
