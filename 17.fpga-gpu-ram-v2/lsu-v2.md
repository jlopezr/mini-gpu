# Propuesta: LSU v2, sobre el fabric y el controlador BL8

Este documento es una propuesta de diseño, no código. Nada de lo que hay aquí
está implementado. El objetivo es dejar de invertir en pulir
`17.fpga-gpu-ram-v2/gpu_lsu.v` (rendimientos decrecientes, ver
`docs/optimizacion.md` paso 7 y `lsu.md`) y en su lugar diseñar una LSU nueva
que se apoye en piezas que la CPU (`21.fpga-cpu-hdmi-alu`) ya tiene
construidas, medidas y validadas: `memory_fabric_4.v` y
`sdram_controller_128.v`.

## Por qué el pivote

- El paso 7 de la LSU actual (encoder one-hot rotado) dio +3,2% de Fmax
  confirmado por barrido de semillas, a cambio de +3,4% de área — una mejora
  real pero modesta, con rendimientos claramente decrecientes.
- El camino crítico del chip completo ya no vive en la LSU, vive en el SM.
- El proyecto ya resolvió, para la CPU, el mismo problema de fondo que tiene
  la GPU hoy: un canal de 16 bits BL1 compartido por varios clientes con
  arbitraje casero. La solución — fabric de 4 puertos + controlador BL8 de
  128 bits — está en producción en `18.fpga-cpu-hdmi-bl8`,
  `19.fpga-cpu-hdmi-ls` y `21.fpga-cpu-hdmi-alu`, con sus bancos de pruebas
  pasando y con lecciones de Fmax ya incorporadas (concesión registrada,
  máscara de bits altos en vez de comparador de magnitud, `urgent`
  registrado).
- El propio código del fabric reserva el puerto 1 para la GPU
  (`docs/camino-de-memoria.md` de 21: "el puerto 1 está pensado... para una
  GPU"). No hay que inventar el hueco, ya existe.

## Qué se reutiliza sin tocar

| Módulo | De dónde | Por qué no hace falta cambiarlo |
| --- | --- | --- |
| `memory_fabric_4.v` | `21.fpga-cpu-hdmi-alu/` | Árbitro de 4 puertos genérico: no sabe qué hay detrás de cada puerto. Ya tiene concesión registrada y comparación por máscara de bits altos, las dos correcciones de Fmax que a nuestra LSU le faltan. Para un sistema **sin CPU** (como `17.fpga-gpu-ram-v2`) no hace falta ensancharlo a más de 4 puertos: los 4 clientes de la GPU caben en los que ya hay (ver mapeo más abajo). |
| `sdram_controller_128.v` | `21.fpga-cpu-hdmi-alu/` | Controlador BL8, 128 bits por transacción, con máscara de byte de 16 bits — sin necesidad de lectura-modificación-escritura para escrituras parciales. Ya validado con `sdram_controller_128_tb.v`. |

Ninguno de los dos sabe nada de "warps" ni "lanes". Son piezas de transporte
genéricas — coalescencia y arbitraje quedan claramente separados, que es
justo la distinción que motivó este documento.

## Qué se reutiliza como plantilla (no verbatim)

| Módulo original | Qué hace hoy (CPU) | Qué cambia para la GPU |
| --- | --- | --- |
| `instruction_buffer.v` | Intercepta el puerto `imem` de `cpu.v` (32 bits, un acceso), lo traduce a peticiones de 128 bits contra el fabric, y cachea 4 líneas de 16 bytes de mapeo directo. | El contrato con `gpu_sm.imem_*` es **prácticamente idéntico** al de `cpu.v` (`imem_valid`/`imem_address`/`imem_rsp_valid`/`imem_data`, ver `gpu_system.v:71-73`). Candidato a reuso casi directo, cambiando el nombre de las señales del lado CPU. El único matiz: la GPU tiene 8 warps con PC independiente, así que las 4 líneas de mapeo directo pueden fallar más a menudo que con una sola CPU secuencial — a medir, no a asumir. |
| `monitor_mem_adapter_128.v` | Traduce accesos byte a byte del monitor UART a peticiones de 128 bits, y decodifica la ventana de vídeo 0x80000000 y el `wb_dirty` del buffer de combinación de la CPU. | La GPU **no tiene** buffer de combinación de escrituras (no hace falta: no hay concepto de vídeo leyendo el framebuffer por detrás en `17.fpga-gpu-ram-v2` todavía) ni la misma ventana MMIO. Sirve como **esqueleto** (pulso de un ciclo del monitor, traducción byte→máscara de 16 bits) pero hay que quitar lo específico de vídeo/CPU y enganchar el MMIO que ya decodifica `gpu_system.v` (`cfg_read_data`, `retired_count`, etc.), que además usa el mismo prefijo `0x80000` por casualidad de convención, no por acoplamiento real. |

## Lo único genuinamente nuevo: el motor de coalescencia

Esta es la LSU v2 en sentido estricto. Todo lo anterior es plomería ya
resuelta; esto es el diseño que falta.

### Interfaz sin cambios hacia `gpu_sm`

El lado `gpu_sm` no se toca: mismo protocolo con tag de hoy (`req_valid` /
`req_tag` / `req_mask` / `req_address` (256 bits) / `req_data` (256 bits),
`rsp_valid` / `rsp_tag` / `rsp_data` / `rsp_error`, 8 slots). `gpu_sm.v` no
necesita saber que cambió el backend.

### Lo que cambia es la trasera: de "una lane, un acceso BL1" a "un grupo, una ráfaga BL8"

Hoy, `gpu_lsu.v` sirve una lane a la vez con dos accesos de 16 bits (12
ciclos aprox., ver `lsu.md`). El algoritmo nuevo:

1. **Arbitraje de warp: igual que hoy.** Reutilizar tal cual el encoder
   one-hot rotado del paso 7 (`eligible`/rotar por `cursor`/priority encoder
   fijo) para elegir `pick`. No hace falta rediseñarlo, ya está medido y
   validado.
2. **Agrupar por línea de 16 bytes, no elegir una sola lane.** Del warp
   elegido, mirar `pending[pick]` y las direcciones de las 8 lanes. Agrupar
   las lanes cuya dirección cae en la misma ventana alineada a 16 bytes
   (`address[31:4]` igual) — hasta 4 lanes por grupo, porque 128 bits / 32
   bits = 4. Elegir el primer grupo no vacío (por ejemplo, el de la lane de
   menor índice pendiente).
3. **Una transacción de 128 bits por grupo:**
   - **Load:** pedir la línea completa (128 bits); al llegar la respuesta,
     repartir cada palabra de 32 bits a las lanes del grupo según su
     `address[3:2]`, limpiar `pending` solo de esas lanes.
     Las lanes fuera del grupo no se tocan.
   - **Store:** construir `wdata`/`wmask` de 128 bits colocando cada lane del
     grupo en su posición (mismo patrón `shifted_data`/`shifted_mask` que ya
     usa `cpu_dmem_adapter.v`), y emitir con la máscara — **sin leer antes**,
     igual que ya está validado ahí. Lanes fuera del grupo no participan en
     esta escritura.
4. **Tras cada grupo, volver a arbitrar** (`cursor<=selected+1`, igual
   filosofía que hoy: repartir el canal entre warps en vez de drenar uno
   entero). Si el warp elegido aún tiene lanes pendientes en otras líneas, se
   le volverá a dar prioridad en una vuelta posterior según el round-robin
   normal — no se le fuerza a terminar antes de ceder el turno.
5. **Cierre del warp:** igual que hoy — cuando `pending[pick]==0`, se forma
   `VECTOR_RESPONSE` con los datos acumulados.

### Por qué esto es la mejora real, no solo un cambio de ancho

El caso más común de una GPU SIMT — accesos coalescidos, donde las 8 lanes
piden direcciones consecutivas (`base + lane*4`) — pasa de **8 accesos** (uno
por lane, ~12 ciclos cada uno con BL1) a **2 transacciones** de 128 bits (una
por cada mitad de 4 lanes). El caso peor (direcciones dispersas, 8 líneas
distintas) sigue costando 8 transacciones, pero cada una ya no necesita el
doble acceso BL1 de hoy. Es la pieza de "coalescencia" que
`14.fpga-gpu-ram/docs/sintesis.md` señalaba desde el principio como pendiente
y que la LSU actual nunca ha tenido — hoy agrupa por *warp*, nunca por
*dirección*.

### Qué se recicla directamente del trabajo ya hecho en v1

- El encoder one-hot rotado del paso 7 (arbitraje de warp): reusar sin
  cambios, es independiente del ancho del backend.
- La idea de segmentación con solapamiento de `lsu.md` (preparar el
  siguiente grupo en la sombra mientras el actual está en la ráfaga BL8):
  sigue aplicando igual, solo que ahora esconde la latencia de una
  transacción de 128 bits en vez de una de 16 bits. Vale la pena revisar esa
  propuesta *después* de tener el motor de coalescencia funcionando, no
  antes.
- Nada del arbitraje aux/`prefer_aux`/`take_aux` se recicla: desaparece,
  sustituido por el fabric.

## Mapeo de puertos propuesto (sistema solo-GPU, sin CPU)

```text
p0  motor de coalescencia GPU (vectorial, dmem-like)
p1  buffer de fetch GPU (imem-like, adaptado de instruction_buffer.v)
p2  sin usar — reservado para vídeo/HDMI si se añade escaneo por SDRAM
p3  monitor/host (adaptado de monitor_mem_adapter_128.v)
    memory_fabric_4  ──►  sdram_controller_128
```

No hace falta ensanchar el fabric a más de 4 puertos porque este prototipo
no tiene CPU real compitiendo por la SDRAM. El día que la GPU y una CPU
convivan en el mismo sistema, esa sí es la "conversación con el reparto ya
medido" que menciona `docs/camino-de-memoria.md` — y en ese momento hará
falta un fabric de más puertos o una jerarquía de dos niveles, no antes.

## Plan de validación

1. **`memory_fabric_4.v` y `sdram_controller_128.v` no se tocan** → sus
   bancos existentes (`memory_fabric_tb.v`, `sdram_controller_128_tb.v`)
   siguen sirviendo como prueba de que esas piezas funcionan; no hace falta
   revalidarlas para la GPU.
2. **Banco de pruebas nuevo para el motor de coalescencia**, con los casos
   que `gpu_lsu_tb.v` no cubre porque no existían antes: lanes coalescidas
   (direcciones consecutivas, debe salir en 1-2 transacciones), lanes
   dispersas (una por línea, debe seguir siendo correcto aunque no gane
   nada), mezcla de ambas dentro del mismo warp, y solapamiento de dos warps
   con líneas distintas.
3. **Reusar el buffer de fetch casi tal cual**, con un banco equivalente a
   `instruction_buffer_tb.v` (si existe) adaptado a 8 PCs independientes en
   vez de uno.
4. **Medida de ciclos**, mismo método que el paso 6 de
   `docs/optimizacion.md`: correr los 32 casos diferenciales de
   `gpu_system_tb.v` antes/después y comparar la suma de ciclos, no solo el
   Fmax — aquí el objetivo principal es caudal (menos transacciones por
   warp), así que el número que importa es distinto del de los pasos 1-7.

## Preguntas abiertas (a decidir, no a asumir)

- **¿Drenar todas las líneas de un warp antes de ceder el turno, o una línea
  y volver a arbitrar?** El diseño de arriba propone lo segundo (mantener la
  filosofía de reparto fino de hoy), pero no está medido si conviene más
  drenar un warp entero cuando ya se le ha dado el turno, especialmente si
  sus lanes están muy coalescidas (pocas transacciones, poco coste de
  monopolizar el canal un momento).
- **Tamaño de agrupación:** ¿agrupar solo por línea de 16 bytes exacta, o
  intentar detectar el patrón "lane i → base+i*4" explícitamente (más barato
  de calcular, cubre el caso común sin comparar 8 direcciones completas entre
  sí)? La primera opción es más general; la segunda es más barata en lógica
  si el patrón dominante es siempre ese.
- **Profundidad de 8 tags:** ¿se mantiene igual que hoy, o con el ahorro de
  ciclos por warp compensa tener menos tags en vuelo y más ancho por tag?
  No hay datos todavía.
- **Buffer de combinación de escrituras tipo `cpu_dmem_adapter`:** la CPU lo
  usa porque su patrón típico es 4 `STORE` secuenciales de 32 bits. El patrón
  de la GPU (8 lanes en paralelo por instrucción) ya coalesce de forma
  natural dentro de una sola instrucción vectorial; no está claro que un
  buffer de combinación *entre instrucciones* aporte tanto aquí. A evaluar
  con tráfico real, no a copiar por analogía.
