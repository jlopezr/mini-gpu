; live_mask -> 0 con estado SIMT abierto.
; Todas las lanes mueren dentro de la REGION: el warp termina y las pilas
; REGION y PATH deben quedar vacias sin llegar a ejecutar el EXIT del join.

        GETTID R1
        MOVI   R2, 4

        SSY    join
        BGE    R1, R2, path_b         ; PATH = lanes 4..7

        EXIT                          ; mueren las lanes 0..3

path_b:
        EXIT                          ; mueren las lanes 4..7

join:
        EXIT                          ; no deberia ejecutarse
