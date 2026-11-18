# Frontend ROP de CPU

`rop_frontend.v` adapta la familia de instrucciones ROP (`0x37`,
[`1.isa/isa.md`](../../1.isa/isa.md#75-rop--0x37-capability-rop-contrato-propuesto))
al interfaz de comandos de `rop_core.v`.

## Ruta de datos

```text
cpu.v (MEM) -> rop_frontend -> rop_core -> blit_arbiter_i -> dma_arbiter_i -> fabric p3
```

La CPU mantiene `rop_valid` hasta que el frontend acepta la microoperación por
`rop_ready`. El frontend conserva `P0`–`P9` y `PMODE`; `ROPSUBMIT` actualiza
hasta dos de ellos y encola una instantánea completa para el core.

## Cola y terminación

- La cola tiene 16 descriptores (`QUEUE_DEPTH=16` en `top.v`).
- `submitted` y `completed` permiten que `ROPWAIT` espere a todos los envíos
  anteriores, no solo a que la cola se vacíe.
- `rop_done_valid` procede del core cuando han drenado las respuestas de
  memoria del trabajo.
- Un error asíncrono del core queda en `sticky_error`; `ROPSTATUS.CLEAR` lo
  observa y lo borra conforme al contrato ISA.

El core es el maestro prioritario del árbitro ROP/DMA; el DMA agregado comparte
después el puerto 3 con el monitor. Los dos árbitros conservan una FIFO de
propietarios, por lo que las respuestas llegan de vuelta al maestro que emitió
cada petición.

## Reset del monitor

`RESET_CPU` se difiere para el ROP: `top.v` espera a que frontend y core estén
inactivos, y solo entonces los reinicia. Así se limpian los parámetros,
descriptores y el error pegajoso sin perder una respuesta que los árbitros aún
tengan en vuelo.

## Validación

La integración CPU→frontend→core está cubierta por `cpu_rop_tb.v`; el core
tiene además `rop_core_tb.sv` y `rop_core_stress_tb.sv`. Los programas de
conformidad `t.tests/cases-cpu/extensions/rop/` verifican FILL, COPY, SPAN,
`ROPWAIT` y el error asíncrono tanto en `sim-cpu` como en la placa que declare
la capability `rop`.
