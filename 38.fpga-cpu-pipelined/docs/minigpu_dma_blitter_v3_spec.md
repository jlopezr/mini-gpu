# MiniGPU — DMA/Blitter v3 (propuesta)

**Estado:** especificación de diseño, no implementada.  
**Fecha:** 2026-11-14  
**Base:** `dma_engine_v2` existente; mantener compatibilidad funcional de `FILL` y `COPY`.

## 1. Objetivo

Evolucionar el DMA de MiniGPU en un blitter de propósito general con operaciones de transferencia, relleno y comparación/escritura condicional, reutilizable desde CPU y GPU. El datapath físico y el interfaz de memoria continúan siendo de **128 bits**, con **16 bits de máscara de escritura por byte**. Mantener un único puerto físico hacia el fabric, con arbitraje de canales.

**Principios de diseño:**

- `FILL` y `COPY` conservan su semántica y deben conservar, idealmente, el número de solicitudes y ciclos del motor V2. No introducir lecturas del destino en estos dos modos.
- No duplicar el datapath ni crear motores independientes por formato.
- Separar framebuffer de color y depth buffer.
- Permitir formatos de **color 16/32 bits** y **profundidad Z16/Z32**, configurables de forma independiente **por trabajo**.
- Aprovechar las máscaras de byte para escrituras condicionales; no hacer read-modify-write del color si basta con `req_wmask`.
- Preservar colas, etiquetas de respuestas, backpressure y gestión de errores.
- Distinguir especificación propuesta de implementación validada.

## 2. Estado de partida, ya implementado

| Operación | Estado | Semántica |
|---|---|---|
| `FILL` | Implementado y validado por TB de estrés | Patrón de 32 bits repetido, 1D/2D, bloques alineados de 16 bytes |
| `COPY` | Implementado y validado por TB de estrés | Copia 1D/2D, strides de origen/destino, bloques alineados de 16 bytes |
| `COMPARE_WRITE` | Propuesto | Genera máscara mediante comparación y escribe condicionalmente |
| `Z_TEST_COLOR` | Propuesto | Compara Z en buffer separado y escribe Z y color con la misma decisión por píxel |

**Métricas de referencia V2 de 2 canales (última síntesis comunicada):** 2.376 LUT4, 1.357 TRELLIS_FF, 152 CCU2C, 637 PFUMX y 21 L6MUX21. Test de estrés: PASS, 1.922 solicitudes/1.922 respuestas, 641 lecturas, 1.281 escrituras, máximo 5 pendientes y 1.369 cambios de canal. Estos resultados **no** incluyen los modos propuestos.

## 3. Modelo funcional de operaciones

### 3.1 `FILL`

Para cada bloque alineado de 128 bits: escribir el patrón repetido. `req_wmask=16'hffff`. Sin lectura previa.

### 3.2 `COPY`

Leer bloque origen de 128 bits y escribir el mismo bloque en destino. `req_wmask=16'hffff`. Mantener restricciones actuales de alineación y ausencia de solapamiento de rangos.

### 3.3 `COMPARE_WRITE` genérico

Operación por elemento de 16 o 32 bits:

```text
A := SRC / valor incremental / constante
B := DST leído / constante
pass := compare(A, B)    // ALWAYS, EQ, NE, LT, LE, GT, GE
if pass: DST := WRITE_VALUE
```

`WRITE_VALUE` puede proceder de origen, valor generado o constante. Las comparaciones deben definir explícitamente si son **sin signo** (recomendación inicial: solo sin signo) y cómo se interpreta cada anchura.

Ejemplos: copia transparente (`SRC != COLOR_KEY`, escribir SRC), máximo/mínimo (`SRC > DST` o `SRC < DST`), relleno condicional y comparación de profundidad.

**Accesos según modo:** `TRANSPARENT_COPY` necesita leer origen, pero **no** destino; `COMPARE_WRITE` contra destino sí necesita leer destino. Evitar obligar a ambos a una secuencia universal de lectura del destino.

### 3.4 `Z_TEST_COLOR` con buffers separados

Por cada píxel i:

```text
new_z[i] = z_initial + i * dz  // generación incremental, con definición de punto fijo
old_z[i] = DEPTH[i]
if compare(new_z[i], old_z[i]):
    DEPTH[i] = encode_z(new_z[i])
    COLOR[i] = color_constant
```

Variantes futuras: origen de color desde memoria (sombreado previo por GPU) y, eventualmente, generación incremental de color. No se incluyen en el mínimo inicial.

Con Z y color separados, la transacción básica de un grupo es **leer Z, escribir Z condicionalmente, escribir color condicionalmente**. Si ninguna comparación pasa, omitir ambas escrituras. Las dos escrituras deben utilizar exactamente la misma máscara de píxeles (convertida a máscaras de byte de cada formato).

Las actualizaciones a profundidad y color **no son atómicas como pareja**. Si otros maestros acceden o escriben las mismas regiones al mismo tiempo se requiere una disciplina externa de propiedad/sincronización.

## 4. Formatos y agrupación

| Color | Profundidad | Píxeles por palabra color de 128 bits | Píxeles por palabra depth de 128 bits |
|---|---|---:|---:|
| Color16 | Z16 | 8 | 8 |
| Color16 | Z32 | 8 | 4 |
| Color32 | Z16 | 4 | 8 |
| Color32 | Z32 | 4 | 4 |

Una **unidad lógica de comparación de 4 píxeles** facilita reutilizar cuatro comparadores de 32 bits en modo Z32 y particionarlos como ocho comparadores de 16 bits cuando corresponda. Sin embargo, **la implementación debe agrupar dos mitades** para que Color16+Z16 procese los ocho píxeles completos por bloque de 128 bits, sin duplicar transacciones de memoria. El mapeo de máscaras y alineaciones ha de probarse para las cuatro combinaciones.

**Ejemplo de máscaras:** para Z16, cada píxel que pasa habilita dos bits adyacentes de `req_wmask`; para Z32, cuatro. El formato de color se trata independientemente. Una máscara de aprobación de ocho bits se convierte en una o dos máscaras de escritura de 128 bits según el formato.

## 5. Generador de profundidad

- Admitir `Z_INITIAL` y `DZ` por trabajo, con acumulación incremental por píxel.
- La precisión interna debe definirse antes de implementar. **Propuesta:** acumulador fijo de precisión superior a Z16, con truncamiento/saturación explícitos al escribir Z16 y Z32.
- Especificar convenciones de rango, signo, comparación y tratamiento del desbordamiento. No asumir que Z32 implica coma flotante.
- Para operaciones 2D, definir `DZ_ROW` o `Z_ROW_START`/paso de fila como extensión explícita; no inferir que el `dz` horizontal basta para interpolación 2D arbitraria.

## 6. Arquitectura orientativa

```text
                  ┌─────────────────┐
CPU / GPU ──────> │ Cola de trabajos│   (interfaz por definir)
                  └────────┬────────┘
                           │
                     ┌─────▼─────┐
                     │ Scheduler │  N canales
                     └─────┬─────┘
                           │
                  ┌────────▼─────────┐
                  │ Datapath 128 bit │
                  │ FILL / COPY      │── bypass, sin comparación
                  │ COMPARE / Z      │── generador Z + comparadores
                  │ Máscaras bytes   │
                  └────────┬─────────┘
                           │
                      Fabric 128 bit
```

**Uso desde la GPU:** la GPU puede delegar limpieza de buffers, copias de superficies y escritura de spans con test Z. Para rasterización con color constante, un trabajo puede aportar direcciones de color/depth, longitud, Z inicial y ΔZ. Para texturas, sombreado o color por píxel, hace falta una fuente de colores calculados; no basta con `COLOR` constante.

**Interfaz CPU/GPU pendiente de decidir:** (a) MMIO accesible por CPU y GPU, o (b) cola de descriptores en RAM compartida con señalización y ownership. El hecho de compartir SDRAM no habilita automáticamente a la GPU a programar los registros MMIO del DMA.

## 7. MMIO: propuesta de extensión (no asignación definitiva)

**Mantener sin cambios** los registros de canal existentes: `SRC`, `DST`, `WIDTH`, `HEIGHT`, `SRC_STRIDE`, `DST_STRIDE`, `PATTERN`, `CTRL`, `STATUS`, `BYTES_DONE`, y los globales existentes. No reinterpretar campos existentes sin versionar `ID/CAPS`.

La ventana de canal actual tiene stride **0x40** y los registros de control global comienzan en **+0x200**. Para añadir parámetros de comparación, doble destino y Z hacen falta más registros que los huecos disponibles por canal. En vez de proponer offsets que puedan colisionar, estudiar una de estas opciones:

1. **Descriptores en memoria** para trabajos extendidos; MMIO solo para enviar punteros y consultar estado (preferida si la GPU también va a consumirlos).
2. Banco de parámetros extendido por canal en una región MMIO adicional, explícitamente versionada, sin alterar el mapa V2.

**Campos lógicos mínimos de un descriptor extendido:**

| Campo | Finalidad |
|---|---|
| `OP` | FILL, COPY, COMPARE_WRITE, Z_TEST_COLOR |
| `COLOR_FORMAT` | 16 o 32 bits por píxel |
| `Z_FORMAT` | 16 o 32 bits por píxel |
| `COMPARE_OP` | ALWAYS, EQ, NE, LT, LE, GT, GE |
| `COMPARE_SRC_A/B` | Selección entre origen, destino, constante o generador |
| `COLOR_BASE` / `COLOR_STRIDE` | Framebuffer de color |
| `DEPTH_BASE` / `DEPTH_STRIDE` | Depth buffer |
| `WIDTH_PIXELS` / `HEIGHT` | Extensión en píxeles/filas, si se trata de superficies gráficas |
| `COLOR_VALUE` | Color constante |
| `Z_INITIAL` / `DZ_X` | Interpolación horizontal |
| `DZ_Y` (opcional) | Interpolación entre filas |
| `FLAGS` | Comparación sin signo, máscaras, interrupción, etc. |

Para conservar compatibilidad, las longitudes en **bytes** del DMA V2 no deben cambiar silenciosamente a **píxeles**: el descriptor nuevo ha de distinguirlas explícitamente.

## 8. Tráfico de memoria y prestaciones

| Modo | Lecturas de bloque | Escrituras de bloque | Observaciones |
|---|---:|---:|---|
| FILL | 0 | 1 | Mantener V2 |
| COPY | 1 | 1 | Mantener V2 |
| Copia transparente | 1 origen | 0–1 destino | Máscara por elemento; omitir write si toda la máscara es cero |
| Z-test con color separado, 16/16 | 1 depth | 0–2 | Para ocho píxeles, en caso de todos aprobados |
| Z-test con formatos mixtos | Dependiente del agrupamiento | Dependiente | Puede requerir dos bloques color o depth por grupo |

Las cifras describen los casos más sencillos y **no** incluyen tráfico adicional por descriptores, alineaciones ni acceso compartido al fabric. En Z-test se debe comprobar la asignación de datos cuando los tamaños de píxel son distintos.

**Requisito de regresión:** `FILL`/`COPY` no deben adquirir lecturas extra ni solicitudes adicionales. Medir también ciclos totales, rendimiento efectivo y Fmax tras place & route, además del conteo de transacciones.

## 9. Coherencia y concurrencia

- El motor, CPU y GPU comparten memoria, pero no se presupone coherencia automática con cachés o write-combining buffers.
- Antes de consumir datos escritos por CPU, asegurar drenado de escrituras; tras escrituras del DMA, invalidar o sincronizar vistas cacheadas cuando corresponda.
- La pareja `DEPTH` y `COLOR` no constituye una operación atómica: imponer ausencia de escritores simultáneos sobre las mismas regiones o introducir un protocolo de propiedad.
- El DMA debe publicar `DONE` solo tras completar o drenar todas las respuestas relevantes; mantener estados de error e IRQ.
- Un blitter con Z-test no es sustituto universal de un shader o un rasterizador de triángulos: necesita fragmentos/spans preparados o un formato de entrada adecuado.

## 10. Validación y entrega incremental

1. **Congelar V2**: conservar checkpoint y los testbenches existentes.
2. **Especificar descriptor, precisión de Z y ownership** antes de ampliar RTL.
3. **Añadir comparación por elemento y máscaras** (primero `TRANSPARENT_COPY` sobre fuente, sin lectura de destino).
4. **Añadir `COMPARE_WRITE` con lectura de destino** y comparaciones EQ/NE/LT/LE/GT/GE.
5. **Añadir Z16 + Color16** con depth separado; comprobar ocho píxeles por bloque.
6. **Ampliar formatos mixtos** y Z32/Color32, validando máscaras y direcciones.
7. **Integrar uso desde GPU** mediante interfaz de trabajos definida; comprobar sincronización con fabric, CPU y caches.
8. **Comparar síntesis y timing** de cada versión contra V2; rechazar regresiones graves en FILL/COPY.

**Testbenches requeridos:** conservar estrés V2 de 2 y 4 canales; añadir comprobación de memoria para máscaras parciales y todas las combinaciones de formatos, comparadores con igualdad y límites, saltos de fila, Z inicial/ΔZ positivos y negativos si se admiten, ausencia total de píxeles aprobados, errores en cada una de las fases read-depth/write-depth/write-color, backpressure, concurrencia y finalización/IRQ sin anticipación.

## 11. Decisiones pendientes

- Precisión y codificación de `Z_INITIAL`, `DZ_X`, posible `DZ_Y` y conversión Z16/Z32.
- Si `COMPARE_WRITE` genérico debe soportar comparaciones con signo además de sin signo.
- Forma de enviar trabajos desde GPU: MMIO accesible o descriptores en memoria.
- Si el color en `Z_TEST_COLOR` será solo constante inicialmente o también tomado de memoria.
- Semántica exacta ante error entre las dos escrituras de una misma máscara (posible profundidad actualizada sin color o viceversa).
- Reglas de alineación y gestión de spans cuyos tamaños no sean múltiplos de una palabra de 128 bits.
- Límite de recursos y frecuencia objetivo en la ECP5.

---

**Conclusión:** ampliar V2 con comparación condicional y soporte independiente Color16/32 y Z16/32 es coherente si se comparte el datapath y se preservan los caminos rápidos de FILL/COPY. La integración con la GPU es especialmente interesante para operaciones de memoria y rasterización por spans, pero necesita una interfaz de trabajos y sincronización explícitas.
