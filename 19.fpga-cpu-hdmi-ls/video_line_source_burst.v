`default_nettype none

/*
 * Productor de lineas sobre rafagas BL8.
 *
 * Sustituye a video_line_source_sdram.v sin cambiar el contrato con el
 * scanout —fill_start / fill_we,addr,data / fill_done—, que es justo lo que su
 * cabecera anticipaba: «el dia que el controlador sepa hacer bursts, este es el
 * modulo que cambia».
 *
 * Lo que cambia es el otro lado. Donde antes habia SRC_W transacciones de 16
 * bits, ahora hay SRC_W/8 peticiones de 128 bits: para una linea de 320
 * pixeles, **40 rafagas en vez de 320 accesos sueltos**. Es el cliente que
 * mejor encaja en una rafaga de todo el sistema, porque lee 320 palabras
 * consecutivas sin una sola bifurcacion.
 *
 * Alineacion, que es la parte que no es obvia
 * -------------------------------------------
 *
 * Una linea son 320 palabras = 640 bytes = 40 rafagas EXACTAS, asi que si la
 * base del framebuffer esta alineada a 16 bytes, todas las lineas lo estan y no
 * sobra ni falta nada. Con el framebuffer en 0x01000000 es el caso.
 *
 * Pero `video_registers` solo obliga a alinear FB_FRONT y FB_BACK a CUATRO
 * bytes, asi que nada impide poner el framebuffer en 0x01000004 desde el
 * monitor y dejar todas las lineas desalineadas. Este modulo no da por hecho lo
 * que no esta garantizado: arranca en la rafaga alineada que contiene la
 * primera palabra, descarta las palabras que sobran por delante, y pide una
 * rafaga de mas si hace falta. El coste es una rafaga extra por linea en el
 * caso desalineado, y cero en el alineado.
 *
 * Solapamiento
 * ------------
 *
 * Una rafaga tarda ~19 ciclos en volver y vaciarla en el line buffer cuesta 8,
 * asi que la peticion siguiente se lanza nada mas llegar la respuesta y el
 * vaciado ocurre por debajo. Para que eso no sea una apuesta sobre tiempos,
 * `rsp_ready` se mantiene bajo mientras quede algo por vaciar: si algun dia la
 * memoria responde mas rapido que el vaciado, el contrato frena en vez de
 * pisar el dato.
 *
 * Prioridad
 * ---------
 *
 * `urgent` deja saltarse el round-robin del arbitro. Mantenerlo alto siempre
 * seria repetir el fallo que ya costo un dia en la 16: prioridad absoluta
 * resulto ser monopolio. Aqui solo se levanta cuando el relleno lleva mas de
 * URGENT_AFTER ciclos sin terminar, o sea cuando va de verdad con retraso.
 */
module video_line_source_burst #(
    parameter integer SRC_W     = 320,
    parameter integer ADDR_BITS = 9,
    parameter integer LINE_BITS = 8,
    // Ciclos desde fill_start a partir de los cuales el relleno se declara con
    // retraso y se salta el turno. El presupuesto por par de lineas de pantalla
    // son 6400 ciclos a 100 MHz; a la mitad ya ha pasado tiempo de sobra.
    parameter integer URGENT_AFTER = 3200
) (
    input wire clk,
    input wire reset,

    // Direccion de palabra de 16 bits del buffer que toca mostrar, igual que en
    // el lector sin rafagas.
    input wire [23:0] fb_base,

    input wire fill_start,
    input wire [LINE_BITS-1:0] fill_line,
    output reg fill_we,
    output reg [ADDR_BITS-1:0] fill_addr,
    output reg [15:0] fill_data,
    output reg fill_done,

    // Puerto de 128 bits hacia el arbitro. La direccion es de BYTE y siempre
    // alineada a 16, que es lo que memory_fabric_4 exige.
    output reg          req_valid,
    input  wire         req_ready,
    output wire         req_write,
    output reg  [31:0]  req_addr,
    output wire [127:0] req_wdata,
    output wire [15:0]  req_wmask,
    output wire         urgent,

    input  wire         rsp_valid,
    output wire         rsp_ready,
    input  wire [127:0] rsp_rdata,
    input  wire         rsp_error
);
  // Part-select explicito: el estrechamiento es deliberado y asi verilator no
  // avisa de WIDTHTRUNC.
  localparam [ADDR_BITS-1:0] LAST_X = SRC_W[ADDR_BITS-1:0] - 1'b1;

  localparam [1:0] S_IDLE = 2'd0, S_REQUEST = 2'd1, S_WAIT = 2'd2;

  reg [1:0] state;
  reg [127:0] hold;
  reg [2:0] word_sel;
  reg [3:0] unload_left;
  reg [ADDR_BITS-1:0] out_x;
  reg [ADDR_BITS:0] words_left;
  reg [15:0] late_count;
  reg running;

  // El lector nunca escribe.
  assign req_write = 1'b0;
  assign req_wdata = 128'd0;
  assign req_wmask = 16'd0;

  // Frenar al arbitro mientras quede algo por vaciar, en vez de confiar en que
  // la memoria siempre tarda mas que el vaciado.
  assign rsp_ready = (unload_left == 4'd0);

  // `urgent` va REGISTRADO. Combinacional era un comparador de 16 bits
  // colgando de la concesion del arbitro, y de la concesion cuelga el resto
  // del sistema: la sintesis se quedaba en 78 MHz con ese camino. Un ciclo de
  // retraso en «voy con retraso» no cambia nada, porque el umbral son miles.
  reg urgent_r;
  assign urgent = urgent_r;

  // Palabras que entrega la rafaga recien llegada: lo que reste de sus ocho
  // desde `word_sel`, o lo que falte de la linea, lo que sea menor. Se declara
  // con el mismo ancho que `words_left` para que la comparacion no dependa de
  // reglas de extension.
  reg [ADDR_BITS:0] chunk;
  reg [ADDR_BITS:0] take;
  // Direccion de palabra de 16 bits de la primera columna de la linea.
  reg [23:0] line_word;

  always @(posedge clk) begin
    if (reset) begin
      state <= S_IDLE;
      req_valid <= 1'b0;
      req_addr <= 32'd0;
      fill_we <= 1'b0;
      fill_done <= 1'b0;
      fill_addr <= {ADDR_BITS{1'b0}};
      fill_data <= 16'h0000;
      hold <= 128'd0;
      word_sel <= 3'd0;
      unload_left <= 4'd0;
      out_x <= {ADDR_BITS{1'b0}};
      words_left <= {(ADDR_BITS+1){1'b0}};
      late_count <= 16'd0;
      running <= 1'b0;
      urgent_r <= 1'b0;
    end else begin
      fill_we <= 1'b0;
      fill_done <= 1'b0;

      if (running && late_count != 16'hffff) late_count <= late_count + 1'b1;
      urgent_r <= running && (late_count >= URGENT_AFTER[15:0]);

      // -- Vaciado de la rafaga al line buffer, un pixel por ciclo ----------
      // Va fuera del `case` porque corre en paralelo con la peticion siguiente.
      if (unload_left != 4'd0) begin
        fill_we <= 1'b1;
        fill_addr <= out_x;
        fill_data <= hold[{word_sel, 4'b0000} +: 16];
        word_sel <= word_sel + 1'b1;
        unload_left <= unload_left - 1'b1;
        if (out_x == LAST_X) begin
          fill_done <= 1'b1;
          running <= 1'b0;
          unload_left <= 4'd0;
        end else begin
          out_x <= out_x + 1'b1;
        end
      end

      case (state)
        S_IDLE:
          if (fill_start) begin
            // El producto es una vez por linea y queda fuera de todo camino
            // critico, igual que en el lector sin rafagas.
            line_word = fb_base + {{(24-LINE_BITS){1'b0}}, fill_line} * SRC_W[23:0];
            // Direccion de BYTE de la rafaga alineada que contiene esa palabra:
            // (palabra & ~7) * 2, que son los mismos bits recolocados.
            req_addr <= {7'b000_0000, line_word[23:3], 4'b0000};
            // Y la palabra por la que hay que empezar dentro de ella. Con el
            // framebuffer alineado a 16 bytes esto sale cero siempre.
            word_sel <= line_word[2:0];
            out_x <= {ADDR_BITS{1'b0}};
            words_left <= SRC_W[ADDR_BITS:0];
            late_count <= 16'd0;
            running <= 1'b1;
            req_valid <= 1'b1;
            state <= S_WAIT;
          end

        S_REQUEST: begin
          req_valid <= 1'b1;
          state <= S_WAIT;
        end

        S_WAIT: begin
          if (req_valid && req_ready) req_valid <= 1'b0;
          if (rsp_valid && rsp_ready) begin
            hold <= rsp_rdata;
            // De las ocho palabras de esta rafaga se entregan las que van desde
            // `word_sel` hasta el final, sin pasarse de la linea.
            chunk = {{(ADDR_BITS-3){1'b0}}, 4'd8} - {{(ADDR_BITS-2){1'b0}}, word_sel};
            take = (chunk > words_left) ? words_left : chunk;
            unload_left <= take[3:0];
            words_left <= words_left - take;

            if (words_left > chunk) begin
              // Quedan mas. `word_sel` se enrolla solo al vaciar las ocho, asi
              // que la rafaga siguiente empieza en su palabra cero sin tocarlo.
              req_addr <= req_addr + 32'd16;
              state <= S_REQUEST;
            end else begin
              state <= S_IDLE;
            end
          end
        end

        default: state <= S_IDLE;
      endcase
    end
  end
endmodule

`default_nettype wire
