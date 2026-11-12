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
 *   STORE a SDRAM  Pasa directo al adaptador (el dato llega a memoria por el
 *                  bufer de combinacion) y, si su linea esta en la cache, la
 *                  actualiza; si no, no la trae (sin reservar). Ver "El STORE
 *                  que actualiza", abajo.
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
 * El STORE que actualiza
 * ---------------------------------------------------------------------
 *
 * Antes un STORE invalidaba la linea de su indice. Parecia barato ("solo
 * cuesta un fallo"), pero el codigo compilado guarda en la pila y relee al
 * momento: el 93 % de los fallos eran lineas recien tiradas por un STORE
 * (26-33 % de fallos en tie_fighter y racer; 1,5-3,5 % actualizando).
 *
 * Ahora el STORE se acepta igual (en un ciclo, y la CPU no espera) y ademas
 * lee etiqueta y linea como un LOAD. Despues, dos etapas registradas:
 *
 *   S1  compara la etiqueta (a un registro, como ST_LOOKUP) y mezcla la
 *       palabra en la linea con su mascara de bytes.
 *   S2  si acerto, escribe la linea entera. Leer, mezclar y escribir: la EBR
 *       no necesita escrituras por bytes.
 *
 * Quien lea la linea mientras tanto (un LOAD, u otro STORE: los PUSH de un
 * prologo van seguidos a la misma linea) la leeria vieja: su lectura es de
 * antes de la escritura de S2, o del mismo ciclo (lectura y escritura del
 * mismo indice en puertos distintos de la EBR: el dato leido no esta
 * garantizado). Por eso la linea leida pasa por `line_now`, que la toma de S2
 * (escribe al final de este ciclo) o de W (escribio al final del anterior) si
 * son del mismo indice. Las etiquetas no cambian con un STORE, asi que la
 * comparacion no necesita adelantamiento.
 *
 * El relleno de un fallo y la escritura de S2 nunca coinciden: un STORE solo
 * se acepta en IDLE, y un LOAD aceptado detras tarda al menos tres ciclos en
 * llegar a ST_FILL. Comparten el puerto de escritura de datos.
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
                   ST_FILL = 3'd3, ST_SWEEP = 3'd4, ST_DECIDE = 3'd5;

  reg [2:0] state;

  // -- Clasificacion de la peticion de la CPU -------------------------------
  wire cpu_in_sdram = ((cpu_address & ADDR_RANGE_MASK) == 32'd0);
  wire cpu_is_write = |cpu_write_enable;
  wire cpu_cacheable_load = cpu_in_sdram && !cpu_is_write;
  wire [TAG_BITS-1:0] cpu_tag = cpu_address[ADDR_BITS-1:TAG_LSB];

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
  wire store_accept = pass_accept && cpu_in_sdram && cpu_is_write;

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

  // Un solo puerto de escritura en las etiquetas, para dos usos que nunca
  // coinciden porque van en estados distintos: el barrido y el relleno (en
  // FILL). Un STORE no las toca.
  reg [INDEX_BITS-1:0] sweep_index;
  wire fill_write = (state == ST_FILL) && mem_rvalid && !mem_error;
  wire sweep_write = (state == ST_SWEEP);
  wire tag_write = fill_write || sweep_write;
  wire [INDEX_BITS-1:0] tag_write_index = sweep_write ? sweep_index : held_index;
  wire [ENTRY_BITS-1:0] tag_write_value =
      fill_write ? {held_epoch, held_tag} : {ENTRY_BITS{1'b0}};

  // -- El STORE que actualiza: S1, S2 y W (cabecera) ---------------------------
  reg s1_valid;
  reg [INDEX_BITS-1:0] s1_index;
  reg [TAG_BITS-1:0] s1_tag;
  reg [1:0] s1_word;
  reg [31:0] s1_data;
  reg [3:0] s1_mask;
  reg s2_valid;                       // acerto: escribe al final de este ciclo
  reg [INDEX_BITS-1:0] s2_index;
  reg [127:0] s2_line;
  reg w_valid;                        // escribio al final del ciclo anterior
  reg [INDEX_BITS-1:0] w_index;
  reg [127:0] w_line;
  // El indice de lo leido en el ciclo anterior (LOAD o STORE), para adelantar.
  reg [INDEX_BITS-1:0] read_index_q;

  // Un solo puerto de escritura de datos: relleno o S2, que nunca coinciden.
  wire data_write = fill_write || s2_valid;
  wire [INDEX_BITS-1:0] data_write_index = fill_write ? held_index : s2_index;
  wire [127:0] data_write_value = fill_write ? mem_read_line : s2_line;

  always @(posedge clk) begin
    if (load_accept || store_accept) begin
      data_q <= data_mem[cpu_index];
      tag_q <= tag_mem[cpu_index];
    end
    if (data_write) data_mem[data_write_index] <= data_write_value;
    if (tag_write) tag_mem[tag_write_index] <= tag_write_value;
  end

  // La linea leida en el ciclo anterior, con lo que S2 o W hayan escrito en
  // ella despues (S2 es mas nueva: si coinciden los dos, ya incluye a W).
  wire [127:0] line_now =
      (s2_valid && s2_index == read_index_q) ? s2_line :
      (w_valid && w_index == read_index_q) ? w_line : data_q;

  wire [EPOCH_BITS-1:0] stored_epoch = tag_q[ENTRY_BITS-1:TAG_BITS];
  wire entry_live = (stored_epoch != {EPOCH_BITS{1'b0}}) && !bump && !wrapping;
  wire hit = (tag_q == {epoch, held_tag}) && entry_live;
  wire s1_hit = s1_valid && (tag_q == {epoch, s1_tag}) && entry_live;

  // La palabra del STORE mezclada en la linea, byte a byte.
  reg [127:0] s1_merged;
  integer b;
  always @* begin
    s1_merged = line_now;
    for (b = 0; b < 4; b = b + 1)
      if (s1_mask[b]) s1_merged[{s1_word, 5'b00000} + b * 8 +: 8] = s1_data[b * 8 +: 8];
  end

  always @(posedge clk) begin
    if (reset) begin
      s1_valid <= 1'b0;
      s2_valid <= 1'b0;
      w_valid <= 1'b0;
    end else begin
      s1_valid <= store_accept;
      s2_valid <= s1_hit;
      w_valid <= s2_valid;
    end
    if (load_accept || store_accept) read_index_q <= cpu_index;
    s1_index <= cpu_index;
    s1_tag <= cpu_tag;
    s1_word <= cpu_address[3:2];
    s1_data <= cpu_write_data;
    s1_mask <= cpu_write_enable;
    s2_index <= s1_index;
    s2_line <= s1_merged;
    w_index <= s2_index;
    w_line <= s2_line;
  end

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

  // -- La comparacion, registrada ---------------------------------------------
  // La EBR da la etiqueta ~6 ns despues del flanco: compararla y decidir el
  // estado y la respuesta en ese mismo ciclo era el camino critico del
  // diseno. En ST_LOOKUP solo se compara y se elige la palabra, a registros;
  // en ST_DECIDE se decide con ellos. Un `bump` entre medias anula el
  // acierto (la epoca ha cambiado).
  reg hit_q;
  reg [31:0] word_q;
  wire decide_hit = (state == ST_DECIDE) && (pending == 3'd0) && hit_q &&
                    !bump && !wrapping;

  // -- Hacia la CPU -------------------------------------------------------------
  // El acierto contesta en ST_DECIDE, combinacional desde registros (hit_q,
  // pending, state): sin coste de latencia frente a registrar la respuesta.
  // Con `pending` a cero el adaptador no contesta nada en ese ciclo.
  assign cpu_rvalid = decide_hit || mem_rvalid;
  assign cpu_read_data = decide_hit ? word_q : mem_read_data;
  assign cpu_error = !decide_hit && mem_error;

  always @(posedge clk) begin
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
      hit_q <= 1'b0;
      word_q <= 32'd0;
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

        // Datos y etiqueta ya leidos: comparar, a registros.
        ST_LOOKUP: begin
          hit_q <= hit;
          word_q <= line_now[{held_address[3:2], 5'b00000} +: 32];
          state <= ST_DECIDE;
        end

        // Se espera a que el adaptador no deba nada: asi la respuesta sale
        // detras de las anteriores. Si la epoca cambia mientras, ya no vale.
        ST_DECIDE:
          if (pending == 3'd0) begin
            if (decide_hit) begin
              hit_event <= 1'b1;
              state <= ST_IDLE;
            end else begin
              miss_event <= 1'b1;
              state <= ST_ISSUE;
            end
          end else if (bump) begin
            hit_q <= 1'b0;
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
