`timescale 1ns / 1ps
`default_nettype none

/*
 * Cache de datos de la CPU: mapeo directo, lineas de 16 bytes, escritura
 * inmediata a memoria (write-through) y sin reservar linea al escribir.
 *
 * Va entre cpu.v y cpu_dmem_adapter, con el mismo protocolo a los dos lados:
 * `valid/ready` acepta una peticion y `rvalid` (+ `error`) la contesta despues,
 * una por peticion y EN ORDEN.
 *
 *   cpu.v ──dmem──► dcache ──mem──► cpu_dmem_adapter ──128 bits──► arbitro
 *
 * =====================================================================
 * Que hace con cada acceso
 * =====================================================================
 *
 *   LOAD a SDRAM   Ciclo N: se acepta y la EBR lee datos y etiqueta. Ciclo
 *                  N+1: si acierta, contesta. Si falla, pide la palabra al
 *                  adaptador, contesta con ella y guarda la linea entera
 *                  (`mem_read_line`, que el adaptador ya tiene).
 *   STORE a SDRAM  Pasa directo al adaptador e invalida la linea de su
 *                  indice, sin mirar la etiqueta: puede tirar una linea ajena
 *                  que comparte indice, lo que solo cuesta un fallo. El dato
 *                  llega a memoria por el bufer de combinacion, como antes.
 *   MMIO, fuera de rango, cualquier otra cosa
 *                  Pasa directo, sin cache.
 *   `invalidate`   Invalida todo (quien la conecte: CPU parada para el
 *                  monitor, y el registro MMIO). `reset` tambien.
 *
 * El acierto tarda dos ciclos y no uno, pero la CPU solo tiene un acceso a
 * memoria en EX a la vez, asi que no hace falta solapar peticiones.
 *
 * ---------------------------------------------------------------------
 * El orden de las respuestas
 * ---------------------------------------------------------------------
 *
 * Un STORE a SDRAM no espera su respuesta en la CPU (cpu.v la cuenta en
 * `ex_mem_drop` y la descarta cuando llega). Si un LOAD que acierta contestara
 * ANTES de que llegue la respuesta de ese STORE, la CPU descartaria la del
 * LOAD. Por eso `pending` cuenta las respuestas que debe el adaptador, y la
 * consulta (acierto o fallo) espera a que llegue a cero. El caso habitual —el
 * STORE se funde en el bufer y el adaptador contesta al ciclo siguiente— cuesta
 * como mucho un ciclo.
 *
 * Todas las respuestas del adaptador van a la CPU tal cual; las de la cache
 * salen de un registro. Nunca coinciden: la cache solo contesta con
 * `pending == 0`.
 *
 * ---------------------------------------------------------------------
 * Invalidar sin bits de valido: la epoca
 * ---------------------------------------------------------------------
 *
 * Con un bit de valido por linea en biestables, invalidar todo es un ciclo,
 * pero cada bit lleva su logica (poner, borrar por indice, borrar todo) y hay
 * que multiplexar 512 a 1 para leerlo: unas 2.000 LUT, casi todo el coste de
 * la cache. En su lugar, cada etiqueta guarda la EPOCA en que se escribio, en
 * los bits que le sobran a la EBR (18 de ancho, 12 de etiqueta), y una linea
 * vale si su epoca es la actual. Invalidar todo es sumar uno a la epoca.
 *
 *   - La epoca 0 es "invalida": la EBR arranca a ceros, asi que al configurar
 *     la FPGA no hay nada valido sin hacer nada. Por la misma razon un acierto
 *     exige epoca distinta de 0, por si el registro de epoca arrancara en 0.
 *   - Un STORE escribe epoca 0 en su indice.
 *   - Una linea se guarda con la epoca del momento en que se ACEPTO el LOAD: si
 *     se invalido mientras tanto, nace ya invalida.
 *   - LA VUELTA. Al pasar de la ultima epoca a la 1, una linea que nadie ha
 *     tocado desde hace 2^EPOCH_BITS - 1 invalidaciones volveria a coincidir y
 *     resucitaria con un dato viejo. Por eso, al dar la vuelta, un barrido
 *     escribe epoca 0 en todas las lineas (LINES ciclos, con la cache sin
 *     aceptar nada). Con 6 bits, una vez cada 63 invalidaciones.
 *
 * Se suma en el FLANCO de `invalidate || reset`: `invalidate` cuelga de que la
 * CPU este parada, que dura mucho, y sumar en cada ciclo daria vueltas sin
 * parar. Una vez basta: con la CPU parada nadie rellena lineas.
 *
 * ---------------------------------------------------------------------
 * Donde vive cada cosa
 * ---------------------------------------------------------------------
 *
 * Datos (LINES x 128) y etiquetas con epoca (LINES x 18) en EBR: lectura
 * sincrona, un puerto de lectura y uno de escritura, sin reset ni bucles, que
 * es lo que Yosys/Diamond necesitan para inferir DP16KD. Con 512 lineas: 4
 * bloques de datos y 1 de etiquetas.
 */
module dcache #(
    parameter integer LINES = 512,          // potencia de dos
    parameter integer INDEX_BITS = 9,       // $clog2(LINES)
    parameter integer EPOCH_BITS = 6,
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        invalidate,

    // Lado CPU (el puerto dmem de cpu.v).
    input  wire        cpu_valid,
    input  wire [31:0] cpu_address,
    input  wire [31:0] cpu_write_data,
    input  wire [3:0]  cpu_write_enable,
    output wire        cpu_ready,
    output wire [31:0] cpu_read_data,
    output wire        cpu_rvalid,
    output wire        cpu_error,

    // Lado memoria (el puerto CPU de cpu_dmem_adapter), mas la linea entera de
    // la ultima lectura, valida con `mem_rvalid`.
    output wire         mem_valid,
    output wire [31:0]  mem_address,
    output wire [31:0]  mem_write_data,
    output wire [3:0]   mem_write_enable,
    input  wire         mem_ready,
    input  wire [31:0]  mem_read_data,
    input  wire [127:0] mem_read_line,
    input  wire         mem_rvalid,
    input  wire         mem_error,

    // Un pulso por consulta resuelta, para los contadores de rendimiento.
    output reg         hit_event,
    output reg         miss_event
);
  localparam integer TAG_LSB = 4 + INDEX_BITS;
  localparam integer ADDR_BITS = $clog2(SDRAM_SIZE_BYTES);
  localparam integer TAG_BITS = ADDR_BITS - TAG_LSB;
  localparam integer ENTRY_BITS = EPOCH_BITS + TAG_BITS;
  localparam [31:0] ADDR_RANGE_MASK = ~(SDRAM_SIZE_BYTES - 32'd1);
  localparam [EPOCH_BITS-1:0] EPOCH_LAST = {EPOCH_BITS{1'b1}};

  localparam [2:0] ST_IDLE = 3'd0, ST_LOOKUP = 3'd1, ST_ISSUE = 3'd2,
                   ST_FILL = 3'd3, ST_SWEEP = 3'd4;

  reg [2:0] state;

  // -- Clasificacion de la peticion de la CPU -------------------------------
  wire cpu_in_sdram = ((cpu_address & ADDR_RANGE_MASK) == 32'd0);
  wire cpu_is_write = |cpu_write_enable;
  wire cpu_cacheable_load = cpu_in_sdram && !cpu_is_write;

  wire [INDEX_BITS-1:0] cpu_index = cpu_address[TAG_LSB-1:4];

  // -- La epoca ----------------------------------------------------------------
  // Ni `epoch` ni `sweep_pending` se reinician con `reset`: un reset es una
  // invalidacion mas, y reiniciar la epoca a un valor fijo resucitaria las
  // lineas de esa epoca.
  reg [EPOCH_BITS-1:0] epoch = {{(EPOCH_BITS-1){1'b0}}, 1'b1};
  reg sweep_pending = 1'b0;
  reg invalidate_prev = 1'b0;
  wire invalidate_any = invalidate || reset;
  wire bump = invalidate_any && !invalidate_prev;
  // Una vuelta pendiente o en este mismo ciclo: hasta que acabe el barrido
  // puede quedar alguna linea de la epoca que va a volver.
  wire wrapping = sweep_pending || (bump && epoch == EPOCH_LAST);

  // Una peticion que no es LOAD a SDRAM pasa directa: `ready` y `valid` se
  // cruzan sin registro, asi que el adaptador la ve el mismo ciclo. Mientras
  // haya un barrido pendiente no se acepta nada (tambien un STORE escribiria
  // en la EBR de etiquetas, que es del barrido).
  wire idle_open = (state == ST_IDLE) && !sweep_pending;
  wire pass_through = idle_open && !cpu_cacheable_load;
  wire pass_accept = pass_through && cpu_valid && mem_ready;
  wire load_accept = idle_open && cpu_valid && cpu_cacheable_load;

  assign cpu_ready = idle_open && (cpu_cacheable_load || mem_ready);

  // -- La consulta en curso ---------------------------------------------------
  reg [31:0] held_address;
  reg [EPOCH_BITS-1:0] held_epoch;   // la epoca al aceptar el LOAD
  wire [INDEX_BITS-1:0] held_index = held_address[TAG_LSB-1:4];
  wire [TAG_BITS-1:0] held_tag = held_address[ADDR_BITS-1:TAG_LSB];

  // -- Almacenamiento ---------------------------------------------------------
  reg [127:0] data_mem[0:LINES-1];
  reg [ENTRY_BITS-1:0] tag_mem[0:LINES-1];

  reg [127:0] data_q;
  reg [ENTRY_BITS-1:0] tag_q;

  // Un solo puerto de escritura en las etiquetas, para tres usos que nunca
  // coinciden porque van en estados distintos: el barrido, el STORE (en IDLE)
  // y el relleno (en FILL).
  reg [INDEX_BITS-1:0] sweep_index;
  wire fill_write = (state == ST_FILL) && mem_rvalid && !mem_error;
  wire store_clear = pass_accept && cpu_in_sdram && cpu_is_write;
  wire sweep_write = (state == ST_SWEEP);
  wire tag_write = fill_write || store_clear || sweep_write;
  wire [INDEX_BITS-1:0] tag_write_index =
      sweep_write ? sweep_index : (store_clear ? cpu_index : held_index);
  wire [ENTRY_BITS-1:0] tag_write_value =
      fill_write ? {held_epoch, held_tag} : {ENTRY_BITS{1'b0}};

  always @(posedge clk) begin
    if (load_accept) begin
      data_q <= data_mem[cpu_index];
      tag_q <= tag_mem[cpu_index];
    end
    if (fill_write) data_mem[held_index] <= mem_read_line;
    if (tag_write) tag_mem[tag_write_index] <= tag_write_value;
  end

  wire [EPOCH_BITS-1:0] stored_epoch = tag_q[ENTRY_BITS-1:TAG_BITS];
  wire hit = (tag_q == {epoch, held_tag}) && (stored_epoch != {EPOCH_BITS{1'b0}}) &&
             !bump && !wrapping;

  // -- Respuestas pendientes del adaptador -----------------------------------
  // Cuenta las peticiones aceptadas por el adaptador y aun sin contestar,
  // incluida la del fallo. Tres bits: la CPU no deja mas de unas pocas.
  reg [2:0] pending;
  wire issue_accept = (state == ST_ISSUE) && mem_ready;
  wire [2:0] pending_next = pending + {2'b00, pass_accept || issue_accept}
                                    - {2'b00, mem_rvalid};

  // -- Hacia el adaptador -----------------------------------------------------
  assign mem_valid = (pass_through && cpu_valid) || (state == ST_ISSUE);
  assign mem_address = (state == ST_ISSUE) ? held_address : cpu_address;
  assign mem_write_data = cpu_write_data;
  assign mem_write_enable = (state == ST_ISSUE) ? 4'b0000 : cpu_write_enable;

  // -- Hacia la CPU -------------------------------------------------------------
  reg local_rvalid;
  reg [31:0] local_data;
  assign cpu_rvalid = local_rvalid || mem_rvalid;
  assign cpu_read_data = local_rvalid ? local_data : mem_read_data;
  assign cpu_error = !local_rvalid && mem_error;

  always @(posedge clk) begin
    local_rvalid <= 1'b0;
    hit_event <= 1'b0;
    miss_event <= 1'b0;
    invalidate_prev <= invalidate_any;

    // La epoca avanza tambien durante `reset`, que es justo cuando hace falta.
    if (bump) begin
      if (epoch == EPOCH_LAST) begin
        epoch <= {{(EPOCH_BITS-1){1'b0}}, 1'b1};
        sweep_pending <= 1'b1;
      end else begin
        epoch <= epoch + 1'b1;
      end
    end

    if (reset) begin
      state <= ST_IDLE;
      pending <= 3'd0;
      held_address <= 32'd0;
      held_epoch <= {EPOCH_BITS{1'b0}};
      local_data <= 32'd0;
      sweep_index <= {INDEX_BITS{1'b0}};
    end else begin
      pending <= pending_next;

      case (state)
        ST_IDLE: begin
          if (sweep_pending) begin
            sweep_index <= {INDEX_BITS{1'b0}};
            state <= ST_SWEEP;
          end else if (load_accept) begin
            held_address <= cpu_address;
            held_epoch <= epoch;
            state <= ST_LOOKUP;
          end
        end

        // Datos y etiqueta ya leidos. Se espera a que el adaptador no deba
        // nada: asi la respuesta sale detras de las anteriores.
        ST_LOOKUP:
          if (pending == 3'd0) begin
            if (hit) begin
              local_data <= data_q[{held_address[3:2], 5'b00000} +: 32];
              local_rvalid <= 1'b1;
              hit_event <= 1'b1;
              state <= ST_IDLE;
            end else begin
              miss_event <= 1'b1;
              state <= ST_ISSUE;
            end
          end

        ST_ISSUE:
          if (mem_ready) state <= ST_FILL;

        // Con `pending` a cero al pedir, la primera respuesta es la nuestra.
        // Va a la CPU por el camino directo; aqui solo se guarda la linea, con
        // `held_epoch`: si hubo un `invalidate` entre medias, ya nace vieja.
        ST_FILL:
          if (mem_rvalid) state <= ST_IDLE;

        // Una linea por ciclo a epoca 0. Lo pone en marcha IDLE, asi que nunca
        // empieza con un fallo a medias.
        ST_SWEEP: begin
          sweep_index <= sweep_index + 1'b1;
          if (sweep_index == {INDEX_BITS{1'b1}}) begin
            // Si en este mismo ciclo da OTRA vuelta, queda pendiente otro
            // barrido: sin la guarda, esta asignacion pisaria la de arriba.
            if (!(bump && epoch == EPOCH_LAST)) sweep_pending <= 1'b0;
            state <= ST_IDLE;
          end
        end

        default: state <= ST_IDLE;
      endcase
    end
  end

`ifndef SYNTHESIS
  // Solo para simulacion: la EBR de verdad arranca a ceros al configurar.
  integer i;
  initial begin
    for (i = 0; i < LINES; i = i + 1) begin
      data_mem[i] = 128'd0;
      tag_mem[i] = {ENTRY_BITS{1'b0}};
    end
  end
`endif
endmodule

`default_nettype wire
