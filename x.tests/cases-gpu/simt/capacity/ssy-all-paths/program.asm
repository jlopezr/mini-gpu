        GETTID R1          ; R1 = lane id: 0..7
        SSY    join

        ; Separa lane 7
        MOVI   R2, 7
        BGE    R1, R2, path7

        ; activas: lanes 0..6
        ; PATH: [lane7]

        ; Separa lane 6
        MOVI   R2, 6
        BGE    R1, R2, path6

        ; activas: lanes 0..5
        ; PATH: [lane7, lane6]

        ; Separa lane 5
        MOVI   R2, 5
        BGE    R1, R2, path5

        ; activas: lanes 0..4
        ; PATH: [lane7, lane6, lane5]

        MOVI   R2, 4
        BGE    R1, R2, path4

        ; activas: lanes 0..3
        ; PATH count = 4

        MOVI   R2, 3
        BGE    R1, R2, path3

        ; activas: lanes 0..2
        ; PATH count = 5

        MOVI   R2, 2
        BGE    R1, R2, path2

        ; activas: lanes 0..1
        ; PATH count = 6

        MOVI   R2, 1
        BGE    R1, R2, path1

        ; --------------------------------
        ; Aquí:
        ;
        ; active_mask = 00000001  (lane 0)
        ; path_count  = 7
        ;
        ; PATH:
        ;   lane 7
        ;   lane 6
        ;   lane 5
        ;   lane 4
        ;   lane 3
        ;   lane 2
        ;   lane 1
        ; --------------------------------

        BRA    join

path1:
        NOP
        BRA    join

path2:
        NOP
        BRA    join

path3:
        NOP
        BRA    join

path4:
        NOP
        BRA    join

path5:
        NOP
        BRA    join

path6:
        NOP
        BRA    join

path7:
        NOP
        BRA    join

join:
        EXIT