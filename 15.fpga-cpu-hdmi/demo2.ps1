..\.venv\Scripts\python.exe ..\1.isa\miniisa_asm.py swap_demo.asm -o swap_demo.bin
..\.venv\Scripts\python.exe monitor.py reset --port COM3
..\.venv\Scripts\python.exe monitor.py write-block 0 swap_demo.bin --port COM3
..\.venv\Scripts\python.exe monitor.py run --port COM3
