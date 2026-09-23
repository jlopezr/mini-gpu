"""Dónde ponen el framebuffer los programas de vídeo del repositorio.

Esto ya no lo escribe nadie: lo escribe cada programa. Las bases arrancan a
cero desde la fase 3.5 --cero no pretende ser una dirección útil, porque el
framebuffer es una decisión del programa y no una reserva que el hardware
impone-- y los once programas de vídeo del repositorio las ponen ellos al
arrancar, con `STORE` a `FB_FRONT` y `FB_BACK`.

Durante un tiempo las puso el arnés, y solo por dos casos: `band` y `bounce`
eran los únicos que las heredaban en vez de escribirlas. Preparar la máquina
desde fuera tapaba además un problema de verdad --solo el reset de la placa
reinicia las bases, así que un caso que dejara un número impar de intercambios
se las pasaba cruzadas al siguiente-- que desaparece solo en cuanto cada
programa escribe las suyas.

Lo que queda aquí son las dos direcciones que los programas usan de hecho, para
que las pruebas que necesitan mirar el framebuffer sepan dónde está sin
duplicar el número. Están separadas por 0x25800, justo un frame de 320x240 en
RGB565, y las dos alineadas a 16 como exige §9.2.

Si un programa elige otra dirección no pasa nada: los backends capturan el
frame leyendo `FB_FRONT` de la placa o del dispositivo, nunca una dirección
fija.
"""

FB_FRONT = 0x0100_0000
FB_BACK = 0x0102_5800
