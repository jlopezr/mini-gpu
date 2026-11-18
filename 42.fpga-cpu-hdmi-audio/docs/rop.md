# MiniGPU — Propuesta de extensión ISA para el motor ROP

Quiero diseñar y especificar una extensión de la ISA de MiniGPU para controlar el motor ROP (Raster Operations Processor) desde la CPU y la GPU SIMT.

## 1. Contexto arquitectónico

MiniGPU dispone de:

- Una CPU de 32 bits.
- Una GPU SIMT de 8 lanes.
- Memoria compartida a través de un memory fabric.
- Un controlador SDRAM con interfaz de 128 bits.
- Un motor ROP que evolucionó a partir de un DMA multicanal.

La CPU y la GPU tienen sus propios contadores de programa y unidades de ejecución.

El ROP será una unidad física compartida, inicialmente con un único contexto de ejecución. En el futuro podría soportar varios contextos para aprovechar mejor la concurrencia del fabric y ocultar la latencia SDRAM.

**La ISA no debería depender del número de contextos físicos del ROP.**

Queremos que el software pueda enviar trabajos al ROP, continuar ejecutándose y sincronizarse posteriormente.

## 2. Formato de instrucción propuesto

Habíamos considerado reservar el opcode `0x37` (6 bits) para instrucciones ROP.

Formato de 32 bits:

```text
 31      26 25     21 20     16 15              0
+----------+---------+---------+-----------------+
|  OPCODE  |   Ra    |   Rb    |      MODE       |
+----------+---------+---------+-----------------+
    6 bits   5 bits    5 bits       16 bits
```

- `OPCODE`: identifica la familia ROP.
- `Ra`, `Rb`: operandos cuyo significado depende de la operación.
- `MODE`: selecciona la operación y sus modificadores.

Hay que comprobar que `0x37` está libre en la ISA actual antes de asignarlo definitivamente.

No debemos modificar la codificación de otras instrucciones sin justificarlo.

## 3. Instrucciones contempladas

### ROPCONFIG

Actualiza la configuración persistente del ROP.

Debe permitir configurar:

- Dirección base del framebuffer de color.
- Dirección base del Z-buffer.
- Strides independientes.
- Formatos Color16/Color32 y Z16/Z32.
- Modo de comparación Z.
- Comparación signed/unsigned.
- Escritura de color, Z o ambos.
- Color constante.
- Z inicial y deltas dX/dY.

Queremos evitar tener que retransmitir todos estos parámetros en cada instrucción.

La configuración debe tener una semántica ordenada: modificarla no puede alterar trabajos anteriores que todavía estén ejecutándose.

### ROPFILL

Rellena regiones de memoria con un patrón constante.

Debe admitir operaciones 1D y 2D, con ancho, alto y stride.

### ROPCOPY

Copia regiones de memoria.

Debe admitir operaciones 1D y 2D, con origen, destino y strides independientes.

### ROPGENERATE

Genera valores incrementales:

`Z(x,y) = Z0 + x*dX + y*dY`

Debe admitir:

- GENERATE 1D y GENERATE2D.
- Formatos de 16 y 32 bits.
- Escritura incondicional.
- Comparación opcional con el contenido anterior del destino.

Modos de comparación:

`ALWAYS`, `EQ`, `NE`, `LT`, `LE`, `GT`, `GE`.

### ROPSPAN

Procesa spans horizontales.

La CPU o las lanes GPU pueden definir un span con una posición inicial, longitud, color y profundidad.

Debe permitir:

- Color y Z en superficies independientes.
- Interpolación incremental de Z.
- Comparación Z.
- Actualización selectiva de color y profundidad.
- Configuración persistente para reducir operandos.

Debemos precisar cómo se representan los spans procedentes de las 8 lanes GPU.

### ROPWRITE

Envía fragmentos al ROP.

La propuesta para GPU SIMT es que cada una de las 8 lanes proporcione:

- Un color de hasta 32 bits.
- Un Z de hasta 32 bits.
- Un bit de cobertura o activación.

Inicialmente se soportan hasta 8 fragmentos consecutivos por operación, no scatter arbitrario.

Los formatos de color y Z pueden ser independientes.

Hay que definir cómo se transmiten los operandos de todas las lanes a través del banco de registros y del interfaz ROP.

El ROP v0.4 denomina a esta operación `FRAGMENT`; debemos decidir si el nombre ISA será `ROPWRITE` o `ROPFRAGMENT`.

### ROPWAIT

Permite sincronizar el procesador emisor con el ROP.

Para la primera versión proponemos:

- Los comandos se aceptan en orden.
- El procesador puede continuar tras enviar una operación.
- `ROPWAIT` espera hasta que hayan terminado los comandos anteriores del emisor.
- Terminar significa que las respuestas de las operaciones de memoria correspondientes ya se han recibido, no simplemente que se hayan emitido las escrituras.
- Debe existir una forma de detectar errores.

En el futuro podemos estudiar tickets de trabajos, pero no queremos introducirlos en la ISA si no son necesarios.

## 4. CPU y GPU

Debemos estudiar las diferencias entre ambos emisores.

CPU:
- Ejecuta una instrucción cada vez.
- Dispone de registros escalares.
- Puede preparar descriptores de operaciones grandes.
- Resulta especialmente útil para FILL, COPY, GENERATE y SPAN.

GPU:
- Ejecuta grupos SIMT de 8 lanes.
- Puede aportar simultáneamente colores y profundidades.
- Resulta especialmente útil para ROPWRITE/FRAGMENT y ROPSPAN.
- Debe respetarse la máscara de lanes activas.

Queremos evitar que la CPU necesite ocho registros de color y ocho registros Z para ejecutar operaciones que naturalmente son escalares.

Estudiar si conviene usar la misma codificación con distinta semántica de operandos o definir variantes específicas.

## 5. Envío de comandos

El núcleo ROP ya dispone conceptualmente de un interfaz:

- `cmd_valid`
- `cmd_ready`
- `cmd_op`
- `cmd_mode`
- Parámetros de comando
- Datos de fragmentos
- `done_valid`
- `done_error`

No queremos acoplar la ISA a ese descriptor RTL concreto.

Debemos definir cómo se traducen las instrucciones en comandos, especialmente cuando un comando requiere más parámetros de los que caben en `Ra`, `Rb` y `MODE`.

Alternativas que queremos estudiar:

- Registros persistentes del ROP.
- Descriptor en memoria.
- Secuencias de instrucciones ROPCONFIG.
- Combinaciones de las anteriores.

Hay que prestar especial atención al coste de decodificación y a evitar demasiadas instrucciones para operaciones frecuentes.

## 6. Concurrencia futura

Inicialmente el ROP ejecutará un solo trabajo activo, aunque pueda tener varias transacciones pendientes en el memory fabric.

Posteriormente podríamos añadir N contextos físicos.

Queremos que:

- La CPU y la GPU no tengan que seleccionar contextos físicos.
- El hardware pueda distribuir internamente los trabajos.
- La ISA siga siendo compatible.
- Las operaciones dependientes respeten el orden de memoria.
- Las operaciones independientes puedan solaparse cuando el software y el hardware lo permitan.

Debemos definir claramente cuándo una operación requiere barrera y qué garantías de orden proporciona ROPWAIT.

## 7. Objetivo del diseño

La plataforma objetivo es una FPGA Lattice ECP5.

Priorizamos:

1. Bajo consumo de LUT4, FF y CCU2C.
2. Decodificación de instrucciones sencilla.
3. Alto aprovechamiento del bus SDRAM de 128 bits.
4. Poca sobrecarga de CPU por operación.
5. Integración natural con las 8 lanes GPU.
6. Compatibilidad futura con varios contextos ROP.

## 8. Qué quiero obtener

Analiza la propuesta y ayúdame a concretar:

1. La codificación exacta de instrucciones y suboperaciones dentro de MODE.
2. La semántica de Ra y Rb para CPU y GPU.
3. El mecanismo de configuración y paso de descriptores.
4. La ejecución asíncrona y las condiciones de bloqueo.
5. La semántica precisa de ROPWAIT.
6. Las garantías de orden entre CPU, GPU, ROP y SDRAM.
7. El tratamiento de errores.
8. La compatibilidad con una futura versión multicontexto.

**Importante:** no des por cerradas las decisiones que todavía estamos estudiando. Señala las alternativas, sus ventajas y sus costes en hardware.

Quiero una propuesta minimalista, implementable en ECP5 y coherente con la ISA existente de MiniGPU. Antes de fijar la codificación definitiva, revisa `isa.md` y `propuesta-v0.2.md`.

Avancemos primero por la arquitectura y las decisiones principales, antes de escribir RTL.