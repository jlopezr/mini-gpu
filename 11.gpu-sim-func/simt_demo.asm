; Dos caminos por warp, una reconvergencia y barrera de workgroup.
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY join
BLT R1, R2, low
MOVI R3, 20
BRA join
low:
MOVI R3, 10
join:
ADDI R3, R3, 1
BAR
EXIT
