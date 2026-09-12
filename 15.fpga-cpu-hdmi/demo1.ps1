python make_framebuffer.py gradient fb_gradient.bin
python monitor.py write-block 0x01025800 fb_gradient.bin
python monitor.py write-byte 0x80000008 1
