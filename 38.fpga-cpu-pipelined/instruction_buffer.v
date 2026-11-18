`default_nettype none

/*
 * Cache de instrucciones: LINES lineas de 16 bytes, mapeo directo, en EBR.
 *
 * Se intercala entre el puerto `imem` de la CPU y el bus de memoria. Del lado
 * de la CPU el contrato es el de `imem` tal cual; del lado de la memoria es un
 * puerto de 128 bits contra memory_fabric_4. El puerto `imem` separa peticion
 * (`valid`/`ready`) y respuesta (`rvalid`), para poder servir un acierto por
 * ciclo.
 *
 * Una linea son 16 bytes porque **una linea es exactamente una rafaga BL8**: un
 * fallo se resuelve con UNA peticion.
 *
 * ---------------------------------------------------------------------
 * De 4 lineas en biestables a 512 en EBR
 * ---------------------------------------------------------------------
 *
 * Empezo como un bufer de cuatro lineas (64 bytes) para que cupiera el bucle
 * de swap_demo_fast, con todo en biestables y la etiqueta comparada en el
 * mismo ciclo de la peticion. Con 16 lineas bresenham bajo de un CPI de 7,8 a
 * 2,6, pero 16 lineas en biestables ya empujaban la colocacion del resto (el
 * controlador de la SDRAM dejo de cerrar con todas las semillas). En EBR, 8 KB
 * cuestan 5 bloques de los 208 y casi nada de logica.
 *
 * La EBR se lee en un flanco y da el dato en el siguiente, asi que la
 * consulta va en dos ciclos:
 *
 *   ciclo N   se acepta la peticion A y la EBR lee su linea y su etiqueta
 *   ciclo N+1 se compara: acierto -> la respuesta va a un registro, y en
 *             ese mismo ciclo se acepta (y se lee) la peticion siguiente, B
 *   ciclo N+2 `rvalid` con la instruccion, desde ese registro
 *
 * Se sigue aceptando una peticion por ciclo y contestando una por ciclo
 * mientras se acierte; el acierto tarda dos ciclos. La respuesta sale
 * registrada porque la EBR da el dato tarde (~6 ns despues del flanco, sin
 * registro de salida) y, con `rvalid` combinacional, EBR + comparacion + la
 * cola de la CPU eran el camino critico del diseno. La CPU necesita por eso
 * una cola de cuatro entradas para una instruccion por ciclo (cpu.v).
 *
 * EL FALLO CON B YA ACEPTADA. Cuando A falla, B ya entro (en N+1 `ready` estaba
 * alto). B se queda en `lookup_*` y su lectura de la EBR se repite mientras se
 * contesta A (ST_SERVE): cuando A ya esta en la cache, y B se evalua al ciclo
 * siguiente como cualquier otra, acertando si cae en la linea de A. Asi
 * `ready` sigue saliendo de un registro: hacerlo depender del acierto ponia la
 * EBR y la comparacion en el `if_accept` de la CPU.
 *
 * ---------------------------------------------------------------------
 * Coherencia, con epoca
 * ---------------------------------------------------------------------
 *
 * El monitor escribe la memoria de programa con la CPU parada, y la GPU tras un
 * error no llega a `halted` pero si recibe `reset`. Asi que la cache se
 * invalida entera en el FLANCO de `reset || cpu_halted`. Como en dcache.v, sin
 * bits de valido: cada etiqueta guarda la epoca en que se escribio y vale si es
 * la actual; invalidar es sumar uno a la epoca. La epoca 0 es "invalida" (la
 * EBR arranca a ceros) y al dar la vuelta un barrido pone todas las lineas a 0.
 * Ver la cabecera de dcache.v.
 *
 * Esta CPU no escribe su propio codigo (`dmem` no pasa por aqui), asi que no
 * hay mas casos de incoherencia.
 *
 * Lo que NO se guarda: las direcciones fuera de la SDRAM y las busquedas
 * anteriores a `init_done`. Se responden con 0xf8000000, que es un opcode
 * invalido a proposito; guardarlo lo haria permanente.
 */
module instruction_buffer #(
    parameter integer LINES = 512,        // potencia de dos
    parameter integer INDEX_BITS = 9,     // $clog2(LINES)
    parameter integer EPOCH_BITS = 6,
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        init_done,
    input  wire        cpu_halted,

    // Lado CPU: el puerto imem de cpu.v, con peticion y respuesta separadas.
    // La peticion se acepta en el ciclo en que `valid` y `ready` estan altos;
    // la respuesta llega despues con `rvalid`, una por peticion y en orden. Un
    // acierto responde dos ciclos despues, y entre tanto se siguen aceptando
    // peticiones: una busqueda por ciclo mientras se acierte. Durante un
    // fallo `ready` esta bajo hasta servirlo.
    input  wire        cpu_imem_valid,
    input  wire [31:0] cpu_imem_address,
    output wire        cpu_imem_ready,
    output wire [31:0] cpu_imem_read_data,
    output wire        cpu_imem_rvalid,

    // Puerto de 128 bits hacia el arbitro, con direccion de BYTE alineada a 16.
    output wire         req_valid,
    input  wire         req_ready,
    output wire         req_write,
    output reg  [31:0]  req_addr,
    output wire [127:0] req_wdata,
    output wire [15:0]  req_wmask,

    input  wire         rsp_valid,
    output wire         rsp_ready,
    input  wire [127:0] rsp_rdata,
    input  wire         rsp_error,

    // Solo para los bancos de prueba.
    output reg  [31:0] hit_count,
    output reg  [31:0] miss_count,

    // Para los contadores de rendimiento de la CPU (IMEM_HITS e IMEM_MISSES):
    // un pulso de UN ciclo por busqueda cacheable, registrado para no colgar
    // una carga mas de la comparacion.
    output reg         hit_event,
    output reg         miss_event
);
  localparam integer TAG_LSB = 4 + INDEX_BITS;
  localparam integer ADDR_BITS = $clog2(SDRAM_SIZE_BYTES);
  localparam integer TAG_BITS = ADDR_BITS - TAG_LSB;
  localparam integer ENTRY_BITS = EPOCH_BITS + TAG_BITS;
  localparam [EPOCH_BITS-1:0] EPOCH_LAST = {EPOCH_BITS{1'b1}};
  localparam [31:0] INVALID_OPCODE = 32'hf800_0000;

  localparam [2:0] ST_IDLE = 3'd0, ST_ISSUE = 3'd1, ST_WAIT = 3'd2,
                   ST_SERVE = 3'd3, ST_SWEEP = 3'd4;

  reg [2:0] state;

  // El bufer nunca escribe.
  assign req_write = 1'b0;
  assign req_wdata = 128'd0;
  assign req_wmask = 16'd0;
  // `req_valid` se mantiene hasta ver `req_ready`: en memory_fabric_4 la
  // concesion mira el `valid` del puerto, asi que bajarlo antes cuelga.
  assign req_valid = (state == ST_ISSUE);
  assign rsp_ready = (state == ST_WAIT);

  // -- La epoca (ver dcache.v) ---------------------------------------------------
  // Ni `epoch` ni `sweep_pending` se reinician con `reset`: un reset es una
  // invalidacion mas.
  reg [EPOCH_BITS-1:0] epoch = {{(EPOCH_BITS-1){1'b0}}, 1'b1};
  reg sweep_pending = 1'b0;
  reg invalidate_prev = 1'b0;
  wire invalidate_any = reset || cpu_halted;
  wire bump = invalidate_any && !invalidate_prev;
  wire wrapping = sweep_pending || (bump && epoch == EPOCH_LAST);

  // Sale de registros: no depende de la CPU ni de la EBR en este ciclo.
  assign cpu_imem_ready = (state == ST_IDLE) && !sweep_pending;
  wire accept = cpu_imem_ready && cpu_imem_valid;

  // -- La peticion en consulta -----------------------------------------------
  // `lookup_valid`: hay una peticion aceptada cuya linea ya esta (o estara en
  // el ciclo siguiente) a la salida de la EBR. Se evalua en ST_IDLE.
  reg lookup_valid;
  reg [31:0] lookup_address;
  reg [EPOCH_BITS-1:0] lookup_epoch;
  reg lookup_cacheable;
  wire [INDEX_BITS-1:0] lookup_index = lookup_address[TAG_LSB-1:4];
  wire [TAG_BITS-1:0] lookup_tag = lookup_address[ADDR_BITS-1:TAG_LSB];

  // Comparar el rango con `<` cuesta un comparador de magnitud de 32 bits;
  // siendo el tamano potencia de dos basta con mirar los bits altos.
  localparam [31:0] ADDR_RANGE_MASK = ~(SDRAM_SIZE_BYTES - 32'd1);
  wire cacheable = init_done &&
                   ((cpu_imem_address & ADDR_RANGE_MASK) == 32'd0) &&
                   (cpu_imem_address[1:0] == 2'b00);
  wire [INDEX_BITS-1:0] cpu_index = cpu_imem_address[TAG_LSB-1:4];

  // -- Almacenamiento -------------------------------------------------------------
  reg [127:0] data_mem[0:LINES-1];
  reg [ENTRY_BITS-1:0] tag_mem[0:LINES-1];
  reg [127:0] data_q;
  reg [ENTRY_BITS-1:0] tag_q;

  // El fallo en curso: que linea se rellena y con que epoca.
  reg [INDEX_BITS-1:0] fill_index;
  reg [TAG_BITS-1:0] fill_tag;
  reg [EPOCH_BITS-1:0] fill_epoch;
  reg [1:0] fill_word;
  reg [31:0] serve_data;

  // Lectura: al aceptar, o la repeticion de B mientras se contesta A.
  wire replay_read = (state == ST_SERVE) && lookup_valid;
  wire read_enable = accept || replay_read;
  wire [INDEX_BITS-1:0] read_index = (state == ST_IDLE) ? cpu_index : lookup_index;

  // Escritura: el relleno, o el barrido (nunca a la vez).
  reg [INDEX_BITS-1:0] sweep_index;
  wire fill_write = (state == ST_WAIT) && rsp_valid && !rsp_error;
  wire sweep_write = (state == ST_SWEEP);

  always @(posedge clk) begin
    if (read_enable) begin
      data_q <= data_mem[read_index];
      tag_q <= tag_mem[read_index];
    end
    if (fill_write) data_mem[fill_index] <= rsp_rdata;
    if (fill_write || sweep_write)
      tag_mem[sweep_write ? sweep_index : fill_index] <=
          sweep_write ? {ENTRY_BITS{1'b0}} : {fill_epoch, fill_tag};
  end

  // -- La evaluacion (ciclo N+1) ------------------------------------------------
  wire [EPOCH_BITS-1:0] stored_epoch = tag_q[ENTRY_BITS-1:TAG_BITS];
  wire hit = (tag_q == {epoch, lookup_tag}) &&
             (stored_epoch != {EPOCH_BITS{1'b0}}) && !bump && !wrapping;
  wire evaluating = (state == ST_IDLE) && lookup_valid;
  wire answer_now = evaluating && (!lookup_cacheable || hit);
  wire miss_now = evaluating && lookup_cacheable && !hit;

  wire [31:0] hit_word = data_q[{lookup_address[3:2], 5'b00000} +: 32];

  // La respuesta, registrada: `rvalid` y el dato llegan a la CPU un ciclo
  // despues de evaluar, desde biestables (ver la cabecera).
  reg rsp_valid_q;
  reg [31:0] rsp_data_q;
  assign cpu_imem_rvalid = rsp_valid_q;
  assign cpu_imem_read_data = rsp_data_q;

  always @(posedge clk) begin
    rsp_valid_q <= !reset && (answer_now || (state == ST_SERVE));
    rsp_data_q <= (state == ST_SERVE) ? serve_data :
                  (lookup_cacheable ? hit_word : INVALID_OPCODE);
  end

  always @(posedge clk) begin
    hit_event <= 1'b0;
    miss_event <= 1'b0;
    invalidate_prev <= invalidate_any;

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
      lookup_valid <= 1'b0;
      lookup_address <= 32'd0;
      lookup_epoch <= {EPOCH_BITS{1'b0}};
      lookup_cacheable <= 1'b0;
      req_addr <= 32'h0000_0000;
      fill_index <= {INDEX_BITS{1'b0}};
      fill_tag <= {TAG_BITS{1'b0}};
      fill_epoch <= {EPOCH_BITS{1'b0}};
      fill_word <= 2'd0;
      serve_data <= 32'd0;
      sweep_index <= {INDEX_BITS{1'b0}};
      hit_count <= 32'd0;
      miss_count <= 32'd0;
    end else begin
      // Una peticion aceptada pasa a consulta. En un ciclo de fallo tambien:
      // es B, y se queda esperando a que se conteste A.
      if (accept) begin
        lookup_address <= cpu_imem_address;
        lookup_epoch <= epoch;
        lookup_cacheable <= cacheable;
      end

      case (state)
        ST_IDLE: begin
          lookup_valid <= accept;
          if (evaluating && lookup_cacheable) begin
            if (hit) begin
              hit_count <= hit_count + 1'b1;
              hit_event <= 1'b1;
            end else begin
              miss_count <= miss_count + 1'b1;
              miss_event <= 1'b1;
              fill_index <= lookup_index;
              fill_tag <= lookup_tag;
              fill_epoch <= lookup_epoch;
              fill_word <= lookup_address[3:2];
              req_addr <= {lookup_address[31:4], 4'b0000};
              state <= ST_ISSUE;
            end
          end
          // El barrido espera a que no quede consulta: con `ready` bajo no
          // entra ninguna nueva, y la que hubiera falla (hit se anula) y se
          // resuelve antes.
          if (!lookup_valid && sweep_pending) begin
            sweep_index <= {INDEX_BITS{1'b0}};
            state <= ST_SWEEP;
          end
        end

        ST_ISSUE:
          if (req_ready) state <= ST_WAIT;

        ST_WAIT:
          if (rsp_valid) begin
            // Un error no deberia pasar (`cacheable` ya filtro el rango). Si
            // pasa, opcode invalido y no se guarda la linea.
            serve_data <= rsp_error ? INVALID_OPCODE :
                          rsp_rdata[{fill_word, 5'b00000} +: 32];
            state <= ST_SERVE;
          end

        // Contesta A. Si B esta esperando, su lectura de la EBR se repite en
        // este ciclo (`replay_read`) y se evalua en ST_IDLE al siguiente.
        ST_SERVE:
          state <= ST_IDLE;

        ST_SWEEP: begin
          sweep_index <= sweep_index + 1'b1;
          if (sweep_index == {INDEX_BITS{1'b1}}) begin
            // Si en este mismo ciclo da OTRA vuelta, queda otro barrido.
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
