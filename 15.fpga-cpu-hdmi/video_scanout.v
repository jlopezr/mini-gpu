`default_nettype none

// Scanout: convierte lineas fuente RGB565 de 320 pixeles en 640x480 por HDMI,
// duplicando cada pixel en horizontal y cada linea en vertical.
//
// Contiene el cruce de dominios entre el productor de lineas (dominio de
// sistema, 120 MHz) y la salida de video (dominio de pixel, 25 MHz). El
// productor es intercambiable: en el hito B es un generador de patron
// (`video_line_source_pattern`) y en el hito C sera un lector de SDRAM. El
// contrato no cambia.
//
// ---------------------------------------------------------------------------
// Cruce de dominios
// ---------------------------------------------------------------------------
//
// Handshake de dos fases, con una sola peticion viva en cada momento:
//
//   pixel                                     sistema
//   -----                                     -------
//   req_toggle      ---- 2 FF ---->           fill_start (pulso)
//   fill_line, fill_bank (datos estables)      |
//                                              | el productor escribe
//                                              | SRC_W palabras
//   done_pulse_pix  <--- 2 FF ----            fill_done (pulso)
//
// Los buses `fill_line` y `fill_bank` NO se sincronizan: cambian en el mismo
// flanco de pixel que `req_toggle` y no vuelven a cambiar hasta dos lineas de
// pantalla despues, asi que cuando el pulso sincronizado llega al dominio de
// sistema llevan estables mas de un ciclo de 120 MHz. Es el patron habitual de
// dato acompanando a un toggle; lo que hace falta es que el sintetizador no
// mueva esos registros lejos, no que haya sincronizadores.
//
// El lector manda: solo el dominio de pixel decide que linea toca y en que
// banco. El productor no lleva contador de linea propio, de modo que no puede
// desincronizarse del barrido.
//
// ---------------------------------------------------------------------------
// Secuencia por frame
// ---------------------------------------------------------------------------
//
//   inicio de blanking vertical  -> S_IDLE
//   S_IDLE : pide linea 0 al banco 0
//   S_PRE0 : pide linea 1 al banco 1
//   S_PRE1 : espera; al terminar hay dos lineas listas
//   S_ACTIVE: al acabar cada linea de pantalla IMPAR se ha mostrado dos veces
//             la linea fuente actual: se cambia de banco y se pide la siguiente
//             al banco que queda libre.
//
// El prellenado cabe de sobra en el blanking vertical: 45 lineas son 1,44 ms,
// frente a los pocos microsegundos que cuesta una linea.
//
// Tras un reset el barrido ya esta en marcha, asi que el primer frame muestra
// basura hasta el siguiente `frame_start`, momento en el que todo se resincroniza.
// No se marca `underflow` por ello: solo se vigila el estado S_ACTIVE.

module video_scanout #(
    parameter integer SRC_W      = 320,  // pixeles por linea fuente
    parameter integer SRC_H      = 240,  // lineas fuente
    parameter integer H_ACTIVE   = 640,
    parameter integer V_ACTIVE   = 480,
    parameter integer LINE_END   = 799,  // ultimo pixel de la linea
    parameter integer ADDR_BITS  = 9,
    parameter integer LINE_BITS  = 8     // bits para numerar lineas fuente
) (
    // ---- dominio de pixel ----
    input wire clk_pix,
    input wire rst_pix,
    input wire [11:0] sx,
    input wire [11:0] sy,
    input wire de_in,
    input wire hsync_in,
    input wire vsync_in,
    output wire [7:0] r,
    output wire [7:0] g,
    output wire [7:0] b,
    output reg de_out,
    output reg hsync_out,
    output reg vsync_out,
    output reg underflow,        // pegajoso hasta rst_pix

    // ---- dominio de sistema: interfaz del productor ----
    input wire clk_sys,
    input wire rst_sys,
    output reg fill_start,                  // pulso de un ciclo
    output wire [LINE_BITS-1:0] fill_line,  // linea fuente pedida
    input wire fill_we,                     // escritura de palabra
    input wire [ADDR_BITS-1:0] fill_addr,
    input wire [15:0] fill_data,
    input wire fill_done                    // pulso de un ciclo
);
  // ---------------------------------------------------------------------------
  // Dominio de pixel: maquina de peticion
  // ---------------------------------------------------------------------------
  localparam [1:0] S_IDLE = 2'd0, S_PRE0 = 2'd1, S_PRE1 = 2'd2, S_ACTIVE = 2'd3;

  // Los parametros son enteros; se truncan una vez aqui para no repartir
  // part-selects sobre parametros por todo el codigo.
  localparam [11:0] V_ACTIVE_W = V_ACTIVE;
  localparam [11:0] LINE_END_W = LINE_END;
  localparam [LINE_BITS-1:0] SRC_H_W = SRC_H;

  reg [1:0] state;
  reg bank_rd;
  reg [1:0] bank_valid;
  reg req_toggle;
  reg req_bank;
  reg [LINE_BITS-1:0] req_line;
  reg [LINE_BITS-1:0] next_line;
  reg pending;

  // respuesta del productor, sincronizada al dominio de pixel
  reg done_toggle_sys;
  reg done_sync_0, done_sync_1, done_sync_2;
  wire done_pulse_pix = done_sync_1 ^ done_sync_2;

  always @(posedge clk_pix) begin
    done_sync_0 <= done_toggle_sys;
    done_sync_1 <= done_sync_0;
    done_sync_2 <= done_sync_1;
  end

  wire frame_start = (sy == V_ACTIVE_W) && (sx == 12'd0);
  // Al acabar una linea de pantalla impar se ha mostrado dos veces la misma
  // linea fuente: toca cambiar de banco.
  wire line_consumed = (sx == LINE_END_W) && sy[0] && (sy < V_ACTIVE_W);
  wire busy = pending && !done_pulse_pix;
  wire need_next = (next_line <= SRC_H);

  always @(posedge clk_pix) begin
    if (rst_pix) begin
      state <= S_IDLE;
      bank_rd <= 1'b0;
      bank_valid <= 2'b00;
      req_toggle <= 1'b0;
      req_bank <= 1'b0;
      req_line <= 0;
      next_line <= 0;
      pending <= 1'b0;
      underflow <= 1'b0;
    end else begin
      // La respuesta del productor valida el banco que se pidio. Va antes del
      // `case` para que liberar un banco en el mismo ciclo tenga prioridad.
      if (done_pulse_pix) begin
        pending <= 1'b0;
        bank_valid[req_bank] <= 1'b1;
      end

      if (frame_start) begin
        state <= S_IDLE;
        bank_rd <= 1'b0;
        bank_valid <= 2'b00;
        next_line <= 0;
      end else begin
        case (state)
          S_IDLE:
            if (!busy) begin
              req_bank <= 1'b0;
              req_line <= 0;
              req_toggle <= ~req_toggle;
              pending <= 1'b1;
              next_line <= 1;
              state <= S_PRE0;
            end
          S_PRE0:
            if (!busy) begin
              req_bank <= 1'b1;
              req_line <= 1;
              req_toggle <= ~req_toggle;
              pending <= 1'b1;
              next_line <= 2;
              state <= S_PRE1;
            end
          S_PRE1:
            if (!busy) state <= S_ACTIVE;
          S_ACTIVE:
            if (line_consumed) begin
              // `next_line` es la linea que tocaria PEDIR, asi que la que
              // toca MOSTRAR a continuacion es `next_line - 1`. Al final del
              // frame ya no queda ninguna: entonces no se cambia de banco ni
              // se exige que el otro sea valido. Sin esto, las dos ultimas
              // lineas de cada frame darian un underflow que no existe.
              if (need_next) begin
                if (bank_valid[~bank_rd]) begin
                  bank_rd <= ~bank_rd;
                  bank_valid[bank_rd] <= 1'b0;  // el banco que se abandona
                  if (next_line < SRC_H_W) begin
                    req_bank <= bank_rd;
                    req_line <= next_line;
                    req_toggle <= ~req_toggle;
                    pending <= 1'b1;
                  end
                end else begin
                  // El productor no ha llegado a tiempo. La imagen ya esta
                  // rota; lo util es que quede constancia.
                  underflow <= 1'b1;
                end
              end
              // Se incrementa siempre, tambien cuando ya no se pide nada, para
              // que `need_next` sepa distinguir la ultima linea de la penultima.
              next_line <= next_line + 1'b1;
            end
          default: state <= S_IDLE;
        endcase
      end
    end
  end

  // ---------------------------------------------------------------------------
  // Dominio de sistema: recepcion de la peticion
  // ---------------------------------------------------------------------------
  reg req_sync_0, req_sync_1, req_sync_2;
  always @(posedge clk_sys) begin
    if (rst_sys) begin
      req_sync_0 <= 1'b0;
      req_sync_1 <= 1'b0;
      req_sync_2 <= 1'b0;
      fill_start <= 1'b0;
      done_toggle_sys <= 1'b0;
    end else begin
      req_sync_0 <= req_toggle;
      req_sync_1 <= req_sync_0;
      req_sync_2 <= req_sync_1;
      fill_start <= req_sync_1 ^ req_sync_2;
      if (fill_done) done_toggle_sys <= ~done_toggle_sys;
    end
  end

  assign fill_line = req_line;

  // El productor no sabe en que banco escribe: lo decide el lector y se
  // concatena aqui. Asi el productor del hito C solo tiene que preocuparse de
  // direcciones de SDRAM.
  wire [15:0] rd_data;
  line_buffer #(.ADDR_BITS(ADDR_BITS)) buffer_i(
      .wr_clk(clk_sys), .wr_en(fill_we), .wr_bank(req_bank),
      .wr_addr(fill_addr), .wr_data(fill_data),
      .rd_clk(clk_pix), .rd_bank(bank_rd), .rd_addr(sx[ADDR_BITS:1]),
      .rd_data(rd_data));

  // ---------------------------------------------------------------------------
  // Salida
  // ---------------------------------------------------------------------------
  // `rd_data` sale un ciclo despues de presentar `sx`, asi que los sincronismos
  // se retrasan un ciclo para viajar junto al pixel al que corresponden.
  always @(posedge clk_pix) begin
    if (rst_pix) begin
      de_out <= 1'b0;
      hsync_out <= 1'b0;
      vsync_out <= 1'b0;
    end else begin
      de_out <= de_in;
      hsync_out <= hsync_in;
      vsync_out <= vsync_in;
    end
  end

  // RGB565 -> RGB888 replicando los bits altos, para que 5'b11111 llegue a
  // 8'hff y no a 8'hf8.
  assign r = de_out ? {rd_data[15:11], rd_data[15:13]} : 8'h00;
  assign g = de_out ? {rd_data[10:5],  rd_data[10:9]}  : 8'h00;
  assign b = de_out ? {rd_data[4:0],   rd_data[4:2]}   : 8'h00;
endmodule

`default_nettype wire
