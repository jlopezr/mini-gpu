# MiniGL — fases y estado

| Fase | Enfoque | Estado |
|---|---|---|
| V0 directa | CPU rasteriza al invocar Processing/MiniGL | Implementada; prueba host |
| V0 diferida | CPU interpreta command buffer y reutiliza rasterizador | Implementada; prueba host |
| V1 | GPU interpreta comandos y rasteriza con 8 lanes SIMT, un warp | Código C89 y emulación funcional host; sin validación MiniGPU |
| V2 | CPU convierte geometría a triángulos; GPU rasteriza triángulos | Diseño, pendiente |
| V3 | Shaders GPU especializados por primitiva | Diseño, pendiente |
| V4 | Renderer GPU por tiles, explota localidad de memoria | Diseño, pendiente |

## Principios de comparación
Mantener la API Processing, las escenas de prueba y una referencia V0 CPU píxel a píxel. Medir tiempo de frame, ciclos CPU/GPU, bytes y transacciones SDRAM, ocupación de warps, stalls y tamaño del código. Distinguir coste de generar comandos, interpretar comandos y rasterizar.

## Trabajo pendiente priorizado
1. Validar C89 de `src/` con LCC y mini-opt, incluyendo divergencia/SSY y tamaños de tipos.
2. Fijar ABI de entrada GPU y direcciones compartidas reales para framebuffer, comandos y sprites.
3. Integrar arranque de un warp, sincronización CPU/GPU y presentación de frame.
4. Comparar resultados en simulador MiniGPU y FPGA con V0 CPU.
5. Mejorar batching y evaluar estrategias de distribución de píxeles; más adelante V2–V4.

## Alternativas deliberadas
- V0 directa elimina coste del buffer; V0 diferida permite grabar/reproducir y delegar a GPU.
- V1 interpreta y rasteriza en GPU; V2 mueve conversión a triángulos a CPU; V3 especializa shaders; V4 agrupa por tiles. Ninguna opción sustituye automáticamente a las otras: se conservan como benchmarks.
- Un warp inicialmente reduce complejidad de orden; múltiples warps exigirán sincronización si hay primitivas solapadas.
