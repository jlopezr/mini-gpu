python minicpu_sim.py ../1.isa/mandelbrot.bin --dump 0x00100000 307200 framebuffer.raw
python raw_to_iter.py framebuffer.raw mandelbrot.iter