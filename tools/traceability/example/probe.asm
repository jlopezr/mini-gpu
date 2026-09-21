; @artifact IMPL-DEVICE-PROBE type=implementation
; @implements SPEC-DEVICE@identity
start:
    LOAD R1, R0, 0

; read-identity @implements SPEC-DEVICE#identity-register
read_identity:
    LOAD R2, R1, 0
