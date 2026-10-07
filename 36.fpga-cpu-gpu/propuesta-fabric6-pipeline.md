# Propuesta: fabric de seis puertos a 100 MHz y SDRAM con varias peticiones pendientes

## Estado de implementación

Las fases 1 y 2 se implementaron y validaron en placa el 7 de octubre de 2026:

- destino de respuesta one-hot y router registrado;
- cola global de ocho comandos;
- cola global de ocho respuestas;
- frontend de arbitraje desacoplado del backend SDRAM;
- test RTL con varias solicitudes acumuladas y backpressure de respuesta;
- Fmax de memoria de 105,83 MHz con semilla 12;
- validación completa de placa, incluido soak de 60 segundos, sin errores ni
  mismatches.

El controlador continúa siendo secuencial: hay varias peticiones aceptadas y
pendientes, pero una sola operación SDRAM interna ejecutándose. La fase 3 queda
como trabajo futuro.

## Objetivo

Esta propuesta plantea una evolución incremental del subsistema de memoria para:

1. recuperar el cierre de timing a 100 MHz con seis puertos;
2. permitir que el fabric acepte nuevas peticiones sin esperar a que termine la
   transacción anterior;
3. preparar el camino para que el controlador SDRAM pueda tener varias
   operaciones realmente en vuelo;
4. conservar una interfaz estable para CPU, GPU, monitor y generadores de
   tráfico mientras evoluciona la implementación interna.

Son dos problemas relacionados, pero diferentes. Añadir una FIFO permite tener
varias peticiones pendientes; solo segmentar el controlador permite solapar su
ejecución y aumentar el throughput de SDRAM.

## Situación actual

El sistema utiliza dos dominios de reloj:

- masters, monitor y registros MEMTEST a 25 MHz;
- fabric y controlador SDRAM a 100 MHz.

Cada master cruza al dominio de memoria mediante dos FIFO asíncronas, una de
peticiones y otra de respuestas. El fabric selecciona una petición, espera a que
el controlador la acepte, espera su finalización y finalmente escribe la
respuesta en la FIFO del master correspondiente.

Por tanto, solo existe una transacción SDRAM global en vuelo.

### Resultados de síntesis

Con semilla 12:

| Variante | Fmax memoria | `TRELLIS_COMB` | `TRELLIS_FF` | `TRELLIS_RAMW` |
|---|---:|---:|---:|---:|
| `top`, cuatro puertos | 105,03 MHz | 7398 | 4556 | 312 |
| `top_fabric6`, antes de las colas | 89,43 MHz | 9466 | 5964 | 468 |
| `top_fabric6`, router y colas | 105,83 MHz | 9785 | 6307 | 548 |

El camino crítico de `top_fabric6` mide 11,18 ns. Parte de
`fabric_i.active_master` y termina en la lógica de escritura de una FIFO de
respuesta. El primer cuello de botella está en el encaminamiento de la
respuesta, no en la secuencia de comandos de SDRAM.

## Fase 1: registrar el encaminamiento de respuestas

### Cambio propuesto

Separar la captura de la respuesta SDRAM de su escritura en la FIFO del master:

```text
ST_WAIT -> ST_ROUTE -> ST_RESP -> ST_IDLE
```

Cuando `sdram_done` se activa, `ST_ROUTE` registra:

- datos de respuesta;
- indicador de error;
- puerto de destino.

El puerto de destino debería almacenarse en formato one-hot de seis bits:

```verilog
response_port <= 6'b000001 << active_master;
```

La etapa siguiente solo tendría que evaluar señales sencillas:

```verilog
p0_rsp_wr_en = response_pending && response_port[0];
p1_rsp_wr_en = response_pending && response_port[1];
// ...
p5_rsp_wr_en = response_pending && response_port[5];
```

`response_pending` se mantiene hasta que la FIFO seleccionada tenga espacio.
El arbitraje no comienza otra transacción mientras la respuesta registrada no
haya sido entregada.

### Resultado esperado

- eliminar del mismo camino combinacional la decodificación de
  `active_master`, la selección de `rsp_full` y la escritura de la FIFO;
- recuperar margen hacia los 100 MHz;
- añadir un ciclo de latencia por respuesta sin reducir el throughput actual,
  porque el diseño todavía procesa una sola transacción global cada vez.

Después del cambio se realizará un nuevo barrido de semillas. La semilla 12 se
mantendrá solo si sigue siendo la mejor opción para la nueva netlist.

### Alternativa si no basta

Colocar un buffer síncrono de una entrada delante de cada FIFO de respuesta. El
router escribiría el buffer seleccionado y cada buffer alimentaría su FIFO de
forma local. Esto añade registros, pero reduce fanout y distancia de routing.

No se propone empezar con restricciones manuales de colocación: primero debe
eliminarse la causa arquitectónica del camino largo.

## Fase 2: aceptar varias peticiones pendientes

### Cola global de comandos

Insertar una FIFO síncrona entre el árbitro y el controlador SDRAM:

```text
FIFO de cada master
        |
        v
arbitraje urgent/RR
        |
        v
FIFO global de comandos
        |
        v
controlador SDRAM
```

Cada entrada contendrá:

```text
{master_id, write, address, write_data, write_mask}
```

El fabric podrá conceder y extraer una nueva petición siempre que la FIFO global
no esté llena. Así dejará de bloquear a todos los masters durante la latencia de
la transacción que el controlador está ejecutando.

Una profundidad inicial de 8 entradas parece suficiente para medir el efecto
sin comprometer demasiados recursos. Debe quedar parametrizada.

### Semántica inicial

El controlador seguirá consumiendo un comando cada vez y conservará el orden.
En esta fase habrá varias peticiones aceptadas y pendientes, pero solo una
operación ejecutándose dentro del controlador.

Esto mejora el desacoplamiento y permite que los masters entreguen ráfagas, pero
no garantiza aceptar una petición nueva en cada ciclo indefinidamente. Solo se
podrá mantener ese ritmo hasta llenar la cola si el controlador consume más
despacio de lo que llegan las peticiones.

### Respuestas y backpressure

Antes de entregar un comando al controlador debe garantizarse que su respuesta
podrá conservarse. Hay dos opciones:

1. reservar espacio en la FIFO de respuesta del master al emitir el comando;
2. utilizar una FIFO global de respuestas suficientemente profunda y aplicar el
   backpressure al demultiplexarla.

Para la primera implementación se recomienda una FIFO global de respuestas con
entradas:

```text
{master_id, error, read_data}
```

El router de respuestas la vaciará hacia las FIFO por puerto. De esta forma, una
FIFO de master momentáneamente llena no bloquea inmediatamente la finalización
del controlador, mientras quede espacio en la cola global.

## Fase 3: varias operaciones realmente en vuelo

Para aumentar el throughput del controlador hay que permitir que acepte un
nuevo comando antes de finalizar el anterior. La máquina monolítica actual debe
dividirse, como mínimo, en:

- recepción y decodificación del comando;
- planificación de banco y fila;
- emisión de `ACTIVE`, `READ`, `WRITE` y `PRECHARGE`;
- temporizadores de restricciones SDRAM;
- captura de datos de lectura;
- producción de la respuesta;
- refresh con prioridad y backpressure definidos.

### Primera versión: finalización en orden

Mientras las respuestas terminen en el mismo orden que las peticiones, basta
con una FIFO paralela de metadatos:

```text
{master_id, write, response_required}
```

Cada respuesta toma el `master_id` de la cabeza. Es la opción recomendada para
la primera versión segmentada porque evita etiquetas y una tabla de
transacciones pendientes.

Las escrituras también deben producir una confirmación ordenada, ya que los
masters actuales esperan una respuesta antes de continuar.

### Versión posterior: reordenación

La reordenación puede aprovechar una fila abierta o alternar bancos para ocultar
latencias. En ese caso cada petición necesita un `transaction_id` y el sistema
debe conservar el contexto hasta que llegue la respuesta:

```text
{transaction_id, master_id, tipo, estado}
```

También habrá que decidir el contrato de orden observable por cada master. No
se recomienda introducir reordenación antes de medir que la ejecución en orden
es insuficiente.

## Arbitraje y tráfico urgent

La prioridad actual es estricta: si existe una petición urgente, no se concede
una normal. En `top_fabric6`, GEN2 controla simultáneamente los generadores de
p2, p4 y p5; juntos pueden mantener tráfico urgente continuamente y dejar sin
progreso a p0 y p1.

Esto es correcto según el contrato actual, pero al integrar CPU y GPU conviene
decidir explícitamente entre:

- prioridad estricta, aceptando posible starvation;
- cuota máxima de concesiones urgentes consecutivas;
- round-robin ponderado;
- clases de servicio con contadores de créditos.

Una solución sencilla sería permitir como máximo `URGENT_BURST` concesiones
urgentes consecutivas antes de servir una normal pendiente. Debe implementarse
solo si CPU/GPU necesitan una garantía de progreso; cambiaría la semántica que
el test dirigido verifica actualmente.

## Plan de implementación

1. Añadir el registro one-hot de destino y la etapa `ST_ROUTE`.
2. Ejecutar el test RTL de prioridad, round-robin, payload y respuestas.
3. Sintetizar `top_fabric6` y realizar un sweep de semillas.
4. Validar en placa los seis puertos con `validate_fabric6.ps1`.
5. Añadir la FIFO global parametrizable de comandos, inicialmente de 8 entradas.
6. Añadir la FIFO global de respuestas y su router registrado.
7. Crear tests con ráfagas simultáneas y backpressure de respuesta.
8. Integrar la CPU y medir ocupación de colas, latencia y peticiones por ciclo.
9. Segmentar el controlador SDRAM solo si las medidas muestran que es el cuello
   de botella.

Cada fase debe conservar una variante sintetizable y validable en placa. No se
debería mezclar el cierre de timing del router con el rediseño completo del
controlador en un único cambio.

## Verificación propuesta

### RTL

- respuesta encaminada siempre al master que originó la petición;
- ningún puerto recibe respuestas duplicadas;
- el backpressure de un puerto no corrompe respuestas de otro;
- orden por master conservado;
- FIFO de comandos llena aplica backpressure sin perder peticiones;
- FIFO de respuestas llena detiene la emisión de forma segura;
- wrap de punteros con FIFO vacía, llena y ocupación intermedia;
- tráfico urgent y normal simultáneo;
- refresh durante cola llena y durante lecturas pendientes;
- reset con comandos pendientes, con comportamiento documentado.

### Placa

`validate_fabric6.ps1` seguirá siendo la regresión funcional base. Se añadirán
contadores de diagnóstico para observar, al menos:

- comandos aceptados por el fabric;
- máximo de ocupación de la FIFO de comandos;
- ciclos con la FIFO llena;
- respuestas pendientes;
- máximo de operaciones internas en vuelo;
- errores y mismatches por puerto.

Estos contadores deben ser opcionales o compactos para no convertir la
telemetría en el nuevo camino crítico ni distorsionar significativamente la
medida de recursos.

## Criterios de aceptación

### Fase 1

- `top_fabric6` cumple 100 MHz al menos con una semilla reproducible;
- test RTL completo sin regresiones;
- validación de placa sin errores ni mismatches;
- el camino crítico deja de atravesar el router de respuestas.

### Fase 2

- el fabric acepta ráfagas hasta la capacidad de la cola sin perder comandos;
- respuestas correctas y en orden;
- backpressure correcto en comandos y respuestas;
- CPU, monitor y generadores pueden compartir memoria sin deadlock.

### Fase 3

- el controlador acepta una nueva petición al ritmo definido por su interfaz;
- existe más de una operación interna en vuelo de forma medible;
- mejora el throughput real frente a la fase 2;
- se respetan todas las temporizaciones SDRAM y el refresh;
- el aumento de throughput compensa el coste de área, latencia y complejidad.

## Decisión recomendada tras las fases 1 y 2

Integrar ahora la CPU sobre esta base de seis puertos a 100 MHz y medir ocupación
de las colas, latencia y throughput real. El controlador SDRAM segmentado debe
abordarse si esas medidas muestran que su ejecución secuencial es el siguiente
cuello de botella; las interfaces y las colas actuales ya permiten hacerlo sin
cambiar los masters.
