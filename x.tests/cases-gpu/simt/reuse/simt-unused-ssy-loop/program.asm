; Re-executes an unused SSY for the same join in a uniform loop. There is no
; divergent path pending, so the redundant synchronization entry should be
; reused/replaced instead of consuming another physical stack entry.

MOVI R1, 0
MOVI R2, 9

loop:
SSY done
ADDI R1, R1, 1
BLT R1, R2, loop

done:
EXIT
