# MiniGL — fases y estado

| Fase | Enfoque | Estado |
|---|---|---|
| V0 | Directo: la CPU rasteriza al invocar Processing/MiniGL | Implementada; prueba host |
| V1 | Diferido: command buffer interpretado por la CPU, que reutiliza el rasterizador de V0 | Implementada; prueba host |
| V2 | La GPU interpreta el mismo command buffer y rasteriza con 8 lanes SIMT, un warp | Código C89 y emulación funcional host; sin validación MiniGPU |
| V3 | CPU convierte geometría a triángulos; GPU rasteriza triángulos | Diseño, pendiente |
| V4 | Shaders GPU especializados por primitiva | Diseño, pendiente |
| V5 | Renderer GPU por tiles, explota localidad de memoria | Diseño, pendiente |

Cada versión añade una sola idea. Las entregas de `archive/` usan la numeración antigua: `minigl_v0_direct` = V0, `minigl_v0_deferred` = V1, `minigl_v1_gpu` = V2 (y las fases antiguas V2–V4 son las actuales V3–V5).

## Principios de comparación
Mantener la API Processing, las escenas de prueba y una referencia V0 CPU píxel a píxel. Medir tiempo de frame, ciclos CPU/GPU, bytes y transacciones SDRAM, ocupación de warps, stalls y tamaño del código. Distinguir coste de generar comandos, interpretar comandos y rasterizar.

## Trabajo pendiente priorizado
1. Validar C89 de `src/` con LCC y mini-opt, incluyendo divergencia/SSY y tamaños de tipos. Hecho para V0 en la CPU (`platform_minigpu.c`, `make check-minigpu`); falta V1/V2, y el kernel de V2 no puede llamar a funciones (la GPU del simulador y de la 36 no tiene `JAL`).
2. Fijar ABI de entrada GPU y direcciones compartidas reales para framebuffer, comandos y sprites.
3. Integrar arranque de un warp, sincronización CPU/GPU y presentación de frame.
4. Comparar resultados en simulador MiniGPU y FPGA con V0 CPU.
5. Mejorar batching y evaluar estrategias de distribución de píxeles; más adelante V3–V5.

## Alternativas deliberadas
- V0 (directo) elimina coste del buffer; V1 (diferido) permite grabar/reproducir y delegar a GPU.
- V2 interpreta y rasteriza en GPU; V3 mueve conversión a triángulos a CPU; V4 especializa shaders; V5 agrupa por tiles. Ninguna opción sustituye automáticamente a las otras: se conservan como benchmarks.
- Un warp inicialmente reduce complejidad de orden; múltiples warps exigirán sincronización si hay primitivas solapadas.
