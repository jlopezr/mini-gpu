# MiniGL — fases y estado

| Fase | Enfoque | Estado |
|---|---|---|
| V0 | Directo: la CPU rasteriza al invocar Processing/MiniGL | Implementada; prueba host |
| V1 | Diferido: command buffer interpretado por la CPU, que reutiliza el rasterizador de V0 | Implementada; prueba host |
| V2 | La GPU interpreta el mismo command buffer y rasteriza con 8 lanes SIMT, un warp | Validado en el simulador de MiniGPU (`make check-minigpu V=2`); dibuja con el `raster.c` de V0 por lanes |
| V3 | CPU convierte geometría a triángulos; GPU rasteriza triángulos | Diseño, pendiente |
| V4 | Shaders GPU especializados por primitiva | Diseño, pendiente |
| V5 | Renderer GPU por tiles, explota localidad de memoria | Diseño, pendiente |

Cada versión añade una sola idea. Las entregas de `archive/` usan la numeración antigua: `minigl_v0_direct` = V0, `minigl_v0_deferred` = V1, `minigl_v1_gpu` = V2 (y las fases antiguas V2–V4 son las actuales V3–V5).

## Principios de comparación
Mantener la API Processing, las escenas de prueba y una referencia V0 CPU píxel a píxel. Medir tiempo de frame, ciclos CPU/GPU, bytes y transacciones SDRAM, ocupación de warps, stalls y tamaño del código. Distinguir coste de generar comandos, interpretar comandos y rasterizar.

## Trabajo pendiente priorizado
1. Hecho: validar C89 de `src/` con LCC y mini-opt, incluyendo divergencia/SSY y tamaños de tipos, para V0, V1 y V2 (`platform_minigpu.c`, `make check-minigpu V=0|1|2`). El kernel de V2 (`KERNEL(mgl_render)`) llama a funciones de su unidad, y `kernelcalls` de mini-opt las expande (la GPU de la 36 no tiene `JAL`).
2. Hecho en el simulador: la entrada de la GPU (el trabajo, por `GETARG`), un warp lanzado por la CPU, que espera a que acabe antes del swap, y el framebuffer, los comandos y los sprites en la memoria compartida.
3. Hecho: el kernel de V2 dibuja con el `raster.c` de V0 por lanes, por spans y no filtrando cada píxel. En instrucciones, la GPU dibuja con menos que la CPU de V0; en tiempo aún es más lenta (ver [validacion.md](validacion.md)). Escribir dos píxeles por acceso se probó y no compensa (ver [v2-dos-pixeles.md](v2-dos-pixeles.md)).
4. Varios warps (hoy uno de 8 lanes); con varios, las primitivas solapadas exigen sincronización. Solapar la CPU con la GPU ganaría poco mientras la CPU haga tan poco por frame en V2.
5. Comparar resultados en la FPGA con V0 CPU.
6. Mejorar batching; más adelante V3–V5.

## Alternativas deliberadas
- V0 (directo) elimina coste del buffer; V1 (diferido) permite grabar/reproducir y delegar a GPU.
- V2 interpreta y rasteriza en GPU; V3 mueve conversión a triángulos a CPU; V4 especializa shaders; V5 agrupa por tiles. Ninguna opción sustituye automáticamente a las otras: se conservan como benchmarks.
- Un warp inicialmente reduce complejidad de orden; múltiples warps exigirán sincronización si hay primitivas solapadas.
