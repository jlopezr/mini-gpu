# MiniGL V0 directo + Processing (C89)

- `minigl.h/.c`: estado y rasterizador CPU sobre RGB565.
- `processing.h/.c`: capa Processing con wrappers finos.
- `example.c`: escena de prueba; la plataforma debe llamar `setup()` y `draw()`.

Integracion: llamar `mg_bind(backbuffer, width, height, stride_en_pixeles)` al seleccionar el destino. La plataforma gestiona el doble buffer, vblank y `present`; esta libreria no presupone MMIO ni direcciones fisicas. El modo directo dibuja inmediatamente y no utiliza command buffer.

Reglas provisionales: coordenadas enteras, `rect` con ancho/alto positivos, `circle` con radio, sprite opaco RGB565, clipping al destino, sin alpha ni antialiasing. El relleno se dibuja antes que el contorno. El triangulo utiliza muestreo en coordenadas enteras y bordes inclusivos (puede producir doble pintado en triangulos adyacentes). Las primitivas se dibujan en orden de llamada.

Limitaciones de esta primera version: el calculo de geometria presupone dimensiones/coordenadas moderadas (los productos de `long` deben caber en el entero de la plataforma); las lineas se recortan por pixel, no geometricamente, de modo que lineas con extremos muy alejados pueden ser lentas. `strokeWeight` utiliza pincel cuadrado y el contorno circular no garantiza un grosor perfectamente uniforme.

Prueba en host: `cc -std=c89 -Wall -Wextra -pedantic -c minigl.c processing.c example.c`.
