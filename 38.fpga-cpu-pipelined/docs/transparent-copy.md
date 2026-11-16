Perfecto. Añadimos `TRANSPARENT_COPY` alineado, conservando el camino rápido de 128 bits de `COPY` y sin tocar SPAN/FRAGMENT.

Como vamos a mantener el RTL original como referencia, te dejo los cambios concretos para `rop_core`. No he aplicado ni validado todavía estos cambios en un archivo.

## Interfaz propuesta

| Campo            | Significado                |
| ---------------- | -------------------------- |
| `cmd_op = 6`     | `TRANSPARENT_COPY`         |
| `P0`             | Dirección origen           |
| `P1`             | Dirección destino          |
| `P2`             | Bytes por fila             |
| `P3`             | Número de filas            |
| `P4`             | Stride origen              |
| `P5`             | Stride destino             |
| `P6`             | Color transparente         |
| `cmd_mode[0]`    | 0 = 16 bits; 1 = 32 bits   |
| `cmd_mode[15:1]` | Reservados, deben ser cero |

Conservamos las mismas restricciones de alineación de COPY.

## Cambios en `rop_core`

### 1. Nuevo opcode y registros

```
localparam [2:0] OP_TRANSPARENT_COPY = 3'd6;

reg [31:0] color_key;
```

Inicializar `color_key` a cero durante reset y capturarlo al aceptar el comando.

### 2. Identificar ambas variantes de COPY

```
wire is_copy = (op == OP_COPY ||
                op == OP_TRANSPARENT_COPY);
```

Utilizar `is_copy` donde se decide qué buffer y dirección emplea una copia:

```
wire needs_read = is_copy ||
    ((op == OP_GEN) && (mode[2:0] != 3'd0));
```

En `req_addr`, sustituir la comprobación `op == OP_COPY` por `is_copy`.

En `req_wdata`, igualmente, seleccionar `read_buffer` para ambas operaciones.

### 3. Generar la máscara de transparencia

Comparación paralela de cuatro píxeles de 32 bits u ocho de 16 bits:

```
reg [15:0] transparent_mask;
integer i;

always @* begin
    transparent_mask = 16'h0000;

    if (mode[0]) begin
        for (i = 0; i < 4; i = i + 1)
            if (rsp_rdata[i*32 +: 32] != color_key)
                transparent_mask[i*4 +: 4] = 4'hf;
    end else begin
        for (i = 0; i < 8; i = i + 1)
            if (rsp_rdata[i*16 +: 16] != color_key[15:0])
                transparent_mask[i*2 +: 2] = 2'b11;
    end
end
```

La máscara se calcula en paralelo mientras recibimos el bloque de origen.

### 4. Capturar la máscara al recibir la lectura

En el bloque `if (read_response && !rsp_error)`:

```
if (op == OP_GEN) begin
    generated <= gen_word;
    write_mask <= cmp_mask;
end else if (op == OP_TRANSPARENT_COPY) begin
    write_mask <= transparent_mask;
end else begin
    write_mask <= 16'hffff;
end
```

La FSM ya contempla `write_mask == 0`, por lo que un bloque completamente transparente no genera escritura.

### 5. Validación y carga de parámetros

En `valid_command` añadiríamos:

```
OP_TRANSPARENT_COPY:
    valid_command =
        p2 != 0 && p3 != 0 &&
        p0[3:0] == 0 &&
        p1[3:0] == 0 &&
        p2[3:0] == 0 &&
        p4[3:0] == 0 &&
        p5[3:0] == 0 &&
        cmd_mode[15:1] == 0 &&
        (cmd_mode[0] || p6[31:16] == 0);
```

En la carga de comando, la rama existente `cmd_op == OP_COPY` debe aceptar también `OP_TRANSPARENT_COPY`, y capturar:

```
color_key <= p6;
```

Así compartimos los mismos registros de origen, destino, filas y strides.

## Qué esperamos mantener

| Característica           | COPY         | TRANSPARENT_COPY       |
| ------------------------ | ------------ | ---------------------- |
| Lectura 128 bits         | 1 por bloque | 1 por bloque           |
| Comparación              | No           | 4 u 8 EQ en paralelo   |
| Escritura                | 1 por bloque | 0 o 1 por bloque       |
| Lectura destino          | No           | No                     |
| Ciclos de FSM por bloque | Sin cambios  | Sin ciclos adicionales |
| Máscaras parciales       | No           | Sí                     |

El rendimiento máximo por bloque debería ser similar al de COPY, sujeto al cierre de timing y al comportamiento de memoria.

Antes de darlo por válido, comprobaría cuatro casos: bloque totalmente opaco, totalmente transparente, mezcla de píxeles y copia 2D con strides distintos. Repetiría además el estrés con `req_ready` intermitente y errores de respuesta.

Después compararía LUT4, FF, DSP y Fmax contra los 5.703 LUT4 y 5 DSP de referencia. El objetivo es incorporar la funcionalidad con un incremento de área pequeño y ninguna regresión del COPY existente.