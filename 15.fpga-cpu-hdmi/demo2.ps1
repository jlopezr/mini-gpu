..\.venv\Scripts\python.exe ..\1.isa\miniisa_asm.py examples\swap_demo.asm -o examples\swap_demo.bin
..\.venv\Scripts\python.exe monitor.py reset --port COM3
..\.venv\Scripts\python.exe monitor.py write-block 0 examples\swap_demo.bin --port COM3
..\.venv\Scripts\python.exe monitor.py run --port COM3
