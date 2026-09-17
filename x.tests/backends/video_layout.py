"""Dónde pone el arnés el framebuffer, y por qué lo tiene que poner él.

Hasta la fase 3.5 las bases venían cableadas en el reset del hardware
(`0x01000000` y `0x01025800`), y un caso que dibujara las heredaba sin
escribirlas. Ya no: `video_registers.v` arranca con las dos a cero, porque cero
no pretende ser una dirección útil --el framebuffer es una decisión del
programa, no una reserva que el hardware impone-- y porque `0x01000000` ni
siquiera es válida en todos los mapas.

La consecuencia para las pruebas es que *alguien* tiene que elegir la dirección
antes de que el caso arranque. Dos casos de `cases/video` --`band` y
`bounce`-- leen FB_BACK y dibujan donde les digan, así que sin esto dibujarían
sobre el propio programa, en la dirección cero.

Ese alguien es el arnés y no el caso, por la misma razón por la que el arnés
enciende SCANOUT: el caso declara lo que espera, no cómo dejar la máquina
preparada.

Y vive aquí, en un solo sitio, porque lo usan los tres backends que corren
vídeo --placa, simulador de CPU y simulador de GPU-- y `test_differential`
compara el framebuffer del simulador contra el de la placa byte a byte. Si las
copias se separaran, la comparación fallaría por una diferencia que no está en
lo que se prueba.
"""

# 320*240*2 bytes de separación entre los dos buffers: el frontal justo encima
# del área que usan los programas de prueba, y el trasero a un frame de él.
FB_FRONT = 0x0100_0000
FB_BACK = 0x0102_5800
