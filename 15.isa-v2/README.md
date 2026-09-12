# Diseño de la GPU educativa (ISA v2)

Carpeta **solo de documentación**: no hay RTL, ni simulador, ni programas. Es el
diseño que guía las carpetas siguientes, escrito antes de implementarlas.

Por eso no tiene `docs/` ni `examples/` como las carpetas de RTL: aquí los `.md`
no son material de apoyo de un código, son el contenido.

| Documento | Qué es |
|---|---|
| [`planning.md`](planning.md) | La escalera de fases, cada una con algo visible por HDMI y una prueba pequeña antes de pasar a la siguiente. |
| [`gpu_educativa_arquitectura.md`](gpu_educativa_arquitectura.md) | Arquitectura SIMT, modos de vídeo, formatos de framebuffer, uso de SDRAM y kernels. |
| [`integracion_3d.md`](integracion_3d.md) | Cómo montar un pipeline 3D sobre el núcleo SIMT de 8 warps × 8 lanes, con hardware fijo solo donde compensa. |

## Qué se ha ejecutado ya

- La **fase 0** es «Optimizar LSU», que sigue siendo el punto 1 del
  [`TODO.md`](../TODO.md) del repositorio.
- Las **fases 1 y 2** están hechas en
  [`../16.fpga-cpu-hdmi`](../16.fpga-cpu-hdmi): HDMI con framebuffer mínimo, y
  después doble framebuffer con intercambio sincronizado por vblank.

## Por qué está aquí y no dentro de 16

Vivía en `16.fpga-cpu-hdmi/docs/`, que lo hacía parecer documentación de esa
carpeta. No lo es: describe la GPU entera y es anterior al trabajo de HDMI, que
no es más que una de sus fases. Con su propio número queda en el sitio que le
toca en la escalera —el diseño antes de la implementación— y deja de sugerir que
solo aplica al proyecto que lo alojaba.
