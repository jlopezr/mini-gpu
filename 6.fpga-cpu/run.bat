python ..\1.isa\miniisa_asm.py fpga_smoke_test.asm -o fpga_smoke_test.bin
apio build
apio upload
python monitor.py --port COM3 ping
python monitor.py --port COM3 get-version
python monitor.py --port COM3 write-block 0 fpga_smoke_test.bin
python monitor.py --port COM3 verify 0 fpga_smoke_test.bin
python monitor.py --port COM3 status
python monitor.py --port COM3 run
python monitor.py --port COM3 status
python monitor.py --port COM3 read-register 5
python monitor.py --port COM3 read-block 0x00100010 4 result.bin
