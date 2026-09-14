; Reaches the join on every iteration. The synchronization entry must be
; popped before the following loop iteration.

MOVI R1, 0
MOVI R2, 9

loop:
SSY join
BRA join

join:
ADDI R1, R1, 1
BLT R1, R2, loop
EXIT
