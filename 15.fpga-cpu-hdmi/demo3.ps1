..\.venv\Scripts\python.exe ..\1.isa\miniisa_asm.py examples\swap_demo_fast.asm -o examples\swap_demo_fast.bin
..\.venv\Scripts\python.exe monitor.py reset --port COM3
..\.venv\Scripts\python.exe monitor.py write-block 0 examples\swap_demo_fast.bin --port COM3
..\.venv\Scripts\python.exe monitor.py run --port COM3
