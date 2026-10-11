; Un destino indirecto desalineado no para la CPU.
;
; `JALR` y `JR` toman el destino de un registro, que el programa puede haber
; dejado en cualquier byte. La CPU descarta los dos bits bajos en vez de abrir
; una quinta ruta de error: el fetch queda siempre alineado sin ensanchar el
; mapa de códigos de error. Aquí 0x0E salta a la palabra 0x0C.
;
; El MOVI de 0x08 es el testigo: si el salto fuera a parar a otro sitio, o si
; no saltara, R2 acabaría escrito.

        MOVI R1, 0x0E
        JR   R1
        MOVI R2, 0x7EAD           ; 0x08: no debe ejecutarse
        MOVI R3, 0x00C0           ; 0x0C: destino real
        HALT
