# Programas de integración

Programas completos y largos, útiles como prueba de regresión global. No aíslan
una regla concreta: si fallan, conviene mirar antes los grupos específicos.

| Caso | Qué valida |
|---|---|
| [mandelbrot](mandelbrot/) | Imagen Q16.16 de 320×240 con ocho warps |
| [mandelbrot-packed](mandelbrot-packed/) | Variante empaquetada, con regiones reutilizables |

Con `--trace` conviene usar siempre `--trace-limit`: una ejecución completa
produce millones de eventos.
