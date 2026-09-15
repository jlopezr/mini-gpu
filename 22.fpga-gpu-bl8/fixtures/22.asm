GETTID R1
ANDI R1, R1, 7
MOVI R2, 2
SSY done
BLT R1, R2, low
MOVI R2, 5
BLT R1, R2, middle
MOVI R3, 30
BRA done
low:
MOVI R3, 10
BRA done
middle:
MOVI R3, 20
done:
ADDI R3, R3, 1
EXIT
