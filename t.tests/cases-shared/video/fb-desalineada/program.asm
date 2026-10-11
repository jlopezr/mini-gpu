; Una base de framebuffer desalineada es ERROR, no se trunca (mmio.md §9.2).
;
; Este caso existe porque la comprobacion se le cayo a dos casos a la vez. En
; v1, `video-registers` y `shared-double-buffer` escribian FB_BACK con los dos
; bits bajos a uno y comprobaban que el hardware los ignoraba. v2 convirtio esa
; escritura en un fallo de acceso, y un programa no puede comprobar su propio
; fallo: al quitarla de los dos, el alineamiento se quedaba sin probar.
;
; Y merece caso propio, porque el truncamiento silencioso NO era el mismo en
; las dos familias --cuatro bytes en la CPU, dieciseis en la GPU-- asi que el
; mismo programa dibujaba bien en una placa y torcido en la otra sin que nada
; lo dijera. De ahi que corra en las dos.
.include "mmio.inc"

    LI    R1, MMIO_VIDEO_BASE
    MOVHI R2, 0x0110
    ORI   R2, R2, 0x0004       ; alineado a 4, NO a 16: justo la diferencia
                               ; que v1 se tragaba en la CPU y la GPU no
    STORE R2, R1, MMIO_VIDEO_FB_BACK_OFF
    HALT
