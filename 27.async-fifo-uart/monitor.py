import serial

PORT = "COM3"
BAUD = 115200

with serial.Serial(PORT, BAUD, timeout=1) as ser:
    while True:
        line = ser.readline().decode(errors="replace").strip()

        if not line:
            continue

        print(line)

        if "ERR=1" in line:
            print("!!! ERROR EN LA FIFO !!!")

        if "PASS=1" in line:
            print("FIFO OK")