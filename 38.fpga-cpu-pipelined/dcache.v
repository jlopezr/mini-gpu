`timescale 1ns / 1ps
`default_nettype none

/*
 * Cache de datos de la CPU: mapeo directo, lineas de 16 bytes, escritura
 * inmediata a memoria (write-through) y sin reservar linea al escribir.
 *
 * Va pegada al pipeline de cpu.v (IF ID EX MEM WB), con dos lados:
 *
 *   consulta  ID da la direccion del acceso que entra en EX (`lookup_address`);
 *             en EX, la cache dice si acierta y da la palabra (`ex_hit`,
 *             `ex_read_data`). Un LOAD que acierta no hace nada mas: su dato
 *             va a MEM con el, como el resultado de una suma.
 *   peticion  MEM pide lo demas (fallos, STORE, MMIO) con el protocolo de
 *             siempre: `valid/ready` acepta y `rvalid` (+ `error`) contesta
 *             despues, una por peticion y EN ORDEN. Pasa directo al
 *             adaptador, salvo el fallo, que ademas rellena la linea.
 *
 *   cpu.v ──consulta──► dcache (EBR)
 *   cpu.v ──peticion──► dcache ──mem──► cpu_dmem_adapter ──128 bits──► arbitro
 *
 * =====================================================================
 * Que hace con cada acceso
 * =====================================================================
 *
 *   LOAD a SDRAM   La EBR se lee en el flanco en que entra en EX; en EX se
 *                  compara la etiqueta y se elige la palabra. Si acierta, ya
 *                  esta. Si falla, MEM pide la palabra, que llega con la
 *                  linea entera (`mem_read_line`): se guarda.
 *   STORE a SDRAM  Pasa directo al adaptador desde MEM (el dato llega a
 *                  memoria por el bufer de combinacion) y, si su linea esta
 *                  en la cache, la actualiza: en EX se mezcla la palabra en
 *                  la linea leida y, cuando el adaptador acepta el STORE, se
 *                  escribe la linea entera (leer, mezclar, escribir: la EBR
 *                  no necesita escrituras por bytes). Si no esta, no la trae.
 *                  Antes un STORE invalidaba su linea, y el codigo
 *                  compilado, que guarda en la pila y relee al momento,
 *                  fallaba en el 26-33 % de los LOAD.
 *   MMIO, fuera de rango, cualquier otra cosa
 *                  Nunca aciertan: MEM las pide y pasan directas.
 *   `invalidate`   Invalida todo (quien la conecte: CPU parada para el
 *                  monitor). `reset` tambien.
 *
 * ---------------------------------------------------------------------
 * La lectura en cada ciclo, y lo que se escribe mientras tanto
 * ---------------------------------------------------------------------
 *
 * La EBR se lee en CADA flanco con `lookup_address`: la del acceso que entra
 * en EX, o la del que sigue en EX si EX esta parado (cpu.v elige). Asi un
 * acceso que espera en EX ve lo que se haya escrito antes de su ultimo flanco.
 * Quedan dos casos, y la linea (y la etiqueta) que ve EX pasa por un
 * adelantamiento para cada uno:
 *
 *   - lo que se escribe en ESTE ciclo (el STORE de MEM que se acepta, o el
 *     relleno de un fallo): EX puede pasar a MEM en este mismo flanco;
 *   - lo que se escribio en el flanco anterior (W), el mismo en que se leyo:
 *     leer y escribir el mismo indice a la vez, por puertos distintos, da un
 *     dato que la EBR no garantiza.
 *
 * Solo escribe una cosa a la vez: el STORE que acierta se escribe cuando se
 * acepta (en IDLE), el relleno en FILL y el barrido en SWEEP.
 *
 * ---------------------------------------------------------------------
 * El fallo y el orden de las respuestas
 * ---------------------------------------------------------------------
 *
 * Un STORE a SDRAM no espera su respuesta en la CPU (la cuenta mem_drop y la
 * descarta). `pending` cuenta las respuestas que debe el adaptador, y el
 * fallo no se pide hasta que llega a cero: asi la primera respuesta despues
 * es la suya, la de la linea. Los LOAD que aciertan no usan las respuestas.
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
 *   - Una linea se guarda con la epoca del momento en que se ACEPTO el fallo:
 *     si se invalido mientras tanto, nace ya invalida.
 *   - LA VUELTA. Al pasar de la ultima epoca a la 1, una linea que nadie ha
 *     tocado desde hace 2^EPOCH_BITS - 1 invalidaciones volveria a coincidir y
 *     resucitaria con un dato viejo. Por eso, al dar la vuelta, un barrido
 *     escribe epoca 0 en todas las lineas (LINES ciclos, con la cache sin
 *     aceptar peticiones y sin acertar). Con 6 bits, una vez cada 63
 *     invalidaciones.
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

    // Consulta. `lookup_address` se lee en cada flanco: el acceso que estara
    // en EX el ciclo siguiente. En EX: acierta o no, y la palabra.
    input  wire [31:0] lookup_address,
    output wire        ex_hit,
    output wire [31:0] ex_read_data,
    // EX pasa a MEM este ciclo (`mem_advance`) un LOAD o un STORE (`ex_load`,
    // `ex_store`), con el dato y la mascara del STORE para mezclarlos.
    input  wire        mem_advance,
    input  wire        ex_load,
    input  wire        ex_store,
    input  wire [31:0] ex_write_data,
    input  wire [3:0]  ex_write_enable,

    // Peticion desde MEM (el puerto dmem de cpu.v).
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

    // Un pulso por LOAD a SDRAM que pasa a MEM, acierte o falle, para los
    // contadores de rendimiento.
    output reg         hit_event,
    output reg         miss_event
);
  localparam integer TAG_LSB = 4 + INDEX_BITS;
  localparam integer ADDR_BITS = $clog2(SDRAM_SIZE_BYTES);
  localparam integer TAG_BITS = ADDR_BITS - TAG_LSB;
  localparam integer ENTRY_BITS = EPOCH_BITS + TAG_BITS;
  localparam [31:0] ADDR_RANGE_MASK = ~(SDRAM_SIZE_BYTES - 32'd1);
  localparam [EPOCH_BITS-1:0] EPOCH_LAST = {EPOCH_BITS{1'b1}};

  localparam [1:0] ST_IDLE = 2'd0, ST_FILL = 2'd1, ST_SWEEP = 2'd2;

  reg [1:0] state;

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
  // Y un ciclo mas: la ultima linea del barrido se escribe en el mismo flanco
  // en que EX pudo leerla.
  reg sweep_tail = 1'b0;
  wire wrapping = sweep_pending || sweep_tail || (bump && epoch == EPOCH_LAST);

  // -- Almacenamiento ---------------------------------------------------------
  reg [127:0] data_mem[0:LINES-1];
  reg [ENTRY_BITS-1:0] tag_mem[0:LINES-1];
  reg [127:0] data_q;
  reg [ENTRY_BITS-1:0] tag_q;
  // La direccion leida en el flanco anterior: la del acceso en EX.
  reg [31:0] ex_address;

  wire [INDEX_BITS-1:0] lookup_index = lookup_address[TAG_LSB-1:4];
  wire [INDEX_BITS-1:0] ex_index = ex_address[TAG_LSB-1:4];
  wire [TAG_BITS-1:0] ex_tag = ex_address[ADDR_BITS-1:TAG_LSB];
  wire ex_in_sdram = ((ex_address & ADDR_RANGE_MASK) == 32'd0);

  // -- Peticiones desde MEM -----------------------------------------------------
  wire cpu_in_sdram = ((cpu_address & ADDR_RANGE_MASK) == 32'd0);
  wire cpu_is_write = |cpu_write_enable;
  wire cpu_cacheable_load = cpu_in_sdram && !cpu_is_write;

  // Respuestas que debe el adaptador (incluida la del fallo). Tres bits: la
  // CPU no deja mas de unas pocas.
  reg [2:0] pending;

  // Un fallo espera a que el adaptador no deba nada; el resto pasa directo
  // (`ready` y `valid` se cruzan sin registro). Nada mientras haya un barrido
  // pendiente, que usa el puerto de etiquetas.
  wire idle_open = (state == ST_IDLE) && !sweep_pending;
  assign cpu_ready = idle_open && mem_ready && (!cpu_cacheable_load || pending == 3'd0);
  wire cpu_accept = cpu_valid && cpu_ready;
  wire miss_accept = cpu_accept && cpu_cacheable_load;

  assign mem_valid = cpu_valid && idle_open &&
                     (!cpu_cacheable_load || pending == 3'd0);
  assign mem_address = cpu_address;
  assign mem_write_data = cpu_write_data;
  assign mem_write_enable = cpu_write_enable;

  assign cpu_rvalid = mem_rvalid;
  assign cpu_read_data = mem_read_data;
  assign cpu_error = mem_error;

  // -- El fallo en curso ---------------------------------------------------------
  reg [INDEX_BITS-1:0] fill_index;
  reg [TAG_BITS-1:0] fill_tag;
  reg [EPOCH_BITS-1:0] fill_epoch;   // la epoca al aceptar el fallo

  // -- El STORE en MEM ------------------------------------------------------------
  // Mezclado en EX y guardado al pasar a MEM: si acerto, su linea con la
  // palabra nueva. Se escribe cuando el adaptador acepta el STORE.
  reg mem_store_hit;
  reg [INDEX_BITS-1:0] mem_store_index;
  reg [127:0] mem_store_line;

  // -- Escrituras --------------------------------------------------------------
  reg [INDEX_BITS-1:0] sweep_index;
  wire fill_write = (state == ST_FILL) && mem_rvalid && !mem_error && pending == 3'd1;
  wire store_write = cpu_accept && cpu_is_write && mem_store_hit;
  wire sweep_write = (state == ST_SWEEP);
  wire data_write = fill_write || store_write;
  wire [INDEX_BITS-1:0] data_write_index = fill_write ? fill_index : mem_store_index;
  wire [127:0] data_write_value = fill_write ? mem_read_line : mem_store_line;
  wire tag_write = fill_write || sweep_write;
  wire [INDEX_BITS-1:0] tag_write_index = sweep_write ? sweep_index : fill_index;
  wire [ENTRY_BITS-1:0] fill_entry = {fill_epoch, fill_tag};
  wire [ENTRY_BITS-1:0] tag_write_value = fill_write ? fill_entry : {ENTRY_BITS{1'b0}};

  always @(posedge clk) begin
    data_q <= data_mem[lookup_index];
    tag_q <= tag_mem[lookup_index];
    ex_address <= lookup_address;
    if (data_write) data_mem[data_write_index] <= data_write_value;
    if (tag_write) tag_mem[tag_write_index] <= tag_write_value;
  end

  // W: lo escrito en el flanco anterior, el de la lectura (cabecera).
  reg w_data_valid;
  reg w_tag_valid;
  reg [INDEX_BITS-1:0] w_index;
  reg [127:0] w_line;
  reg [ENTRY_BITS-1:0] w_entry;
  always @(posedge clk) begin
    w_data_valid <= data_write;
    w_tag_valid <= fill_write;
    w_index <= data_write_index;
    w_line <= data_write_value;
    w_entry <= fill_entry;
  end

  // -- EX: la linea y la etiqueta, con lo escrito despues de leerlas ----------------
  wire [127:0] ex_line =
      (data_write && data_write_index == ex_index) ? data_write_value :
      (w_data_valid && w_index == ex_index) ? w_line : data_q;
  wire [ENTRY_BITS-1:0] ex_entry =
      (fill_write && fill_index == ex_index) ? fill_entry :
      (w_tag_valid && w_index == ex_index) ? w_entry : tag_q;
  wire [EPOCH_BITS-1:0] ex_entry_epoch = ex_entry[ENTRY_BITS-1:TAG_BITS];
  assign ex_hit = ex_in_sdram && (ex_entry == {epoch, ex_tag}) &&
                  (ex_entry_epoch != {EPOCH_BITS{1'b0}}) && !bump && !wrapping;
  assign ex_read_data = ex_line[{ex_address[3:2], 5'b00000} +: 32];

  // La palabra del STORE mezclada en la linea, byte a byte.
  reg [127:0] ex_merged;
  integer b;
  always @* begin
    ex_merged = ex_line;
    for (b = 0; b < 4; b = b + 1)
      if (ex_write_enable[b])
        ex_merged[{ex_address[3:2], 5'b00000} + b * 8 +: 8] = ex_write_data[b * 8 +: 8];
  end

  always @(posedge clk) begin
    hit_event <= 1'b0;
    miss_event <= 1'b0;
    invalidate_prev <= invalidate_any;
    sweep_tail <= sweep_write;

    // La epoca avanza tambien durante `reset`, que es justo cuando hace falta.
    if (bump) begin
      if (epoch == EPOCH_LAST) begin
        epoch <= {{(EPOCH_BITS-1){1'b0}}, 1'b1};
        sweep_pending <= 1'b1;
      end else begin
        epoch <= epoch + 1'b1;
      end
    end

    if (mem_advance) begin
      mem_store_hit <= ex_store && ex_hit;
      mem_store_index <= ex_index;
      mem_store_line <= ex_merged;
      hit_event <= ex_load && ex_in_sdram && ex_hit;
      miss_event <= ex_load && ex_in_sdram && !ex_hit;
    end

    if (reset) begin
      state <= ST_IDLE;
      pending <= 3'd0;
      fill_index <= {INDEX_BITS{1'b0}};
      fill_tag <= {TAG_BITS{1'b0}};
      fill_epoch <= {EPOCH_BITS{1'b0}};
      sweep_index <= {INDEX_BITS{1'b0}};
      mem_store_hit <= 1'b0;
    end else begin
      pending <= pending + {2'b00, cpu_accept} - {2'b00, mem_rvalid};

      case (state)
        ST_IDLE: begin
          if (sweep_pending) begin
            sweep_index <= {INDEX_BITS{1'b0}};
            state <= ST_SWEEP;
          end else if (miss_accept) begin
            fill_index <= cpu_address[TAG_LSB-1:4];
            fill_tag <= cpu_address[ADDR_BITS-1:TAG_LSB];
            fill_epoch <= epoch;
            state <= ST_FILL;
          end
        end

        // Con `pending` a cero al pedir, la primera respuesta es la nuestra.
        // Va a la CPU por el camino directo; aqui solo se guarda la linea, con
        // `fill_epoch`: si hubo un `invalidate` entre medias, ya nace vieja.
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
