`timescale 1ns / 1ps
`default_nettype none

/*
 * INPUT_EVENTS (0x3B) e INPUT_PRESENCE (0x3C) del monitor, contra el
 * input_registers REAL.
 *
 * Igual que monitor_tb.v con el puerto serie: lo que se prueba no es que el
 * monitor mande los bytes que dice un modelo, sino que monitor y FIFO se
 * entienden. El control de flujo --los huecos libres que viajan en la
 * respuesta-- solo tiene sentido con la FIFO de verdad detras. El banco hace de
 * CPU sobre la ventana de INPUT para leer STATUS, EVENT_DATA y KEY_STATE.
 *
 * Un segundo monitor con HAS_INPUT = 0 comprueba que los dos comandos
 * contestan `ff`, como cualquier comando desconocido: es lo que hace que anadir
 * INPUT a la copia comun de monitor.v no cambie el protocolo de las demas
 * carpetas.
 */

// Receptor de la UART del monitor: modelo minimo del handshake ready/strobe
// que guarda los bytes que salen.
module tx_sink (
    input  wire       clk,
    input  wire       reset,
    input  wire [7:0] tx_data,
    input  wire       tx_strobe,
    output reg        tx_ready,
    input  wire       clear,
    output reg  [7:0] count,
    output reg  [7:0] b0, b1, b2
);
  integer busy;
  initial begin tx_ready = 1'b1; count = 0; busy = 0; end
  always @(posedge clk) begin
    if (reset || clear) begin
      count <= 8'd0;
      if (reset) begin tx_ready <= 1'b1; busy <= 0; end
    end
    if (!reset) begin
      if (tx_strobe && tx_ready) begin
        case (count)
          8'd0: b0 <= tx_data;
          8'd1: b1 <= tx_data;
          8'd2: b2 <= tx_data;
          default: ;
        endcase
        if (!clear) count <= count + 1'b1;
        tx_ready <= 1'b0;
        busy <= 2;
      end else if (busy > 0) begin
        busy <= busy - 1;
        if (busy == 1) tx_ready <= 1'b1;
      end
    end
  end
endmodule

module monitor_input_tb;
  reg clk = 1'b0;
  reg reset = 1'b1;
  always #5 clk = ~clk;

  // ---- monitor con INPUT ----------------------------------------------------
  reg  [7:0] rx_data = 0;
  reg        rx_strobe = 0;
  wire [7:0] tx_data;
  wire       tx_strobe, tx_ready;
  wire       input_event_valid, input_presence_write;
  wire [31:0] input_event_word;
  wire       input_presence_keyboard, input_presence_mouse;
  wire [4:0] free_slots;
  wire       busy;

  wire [7:0] cnt, r0, r1, r2;
  reg        clear_rx = 0;

  tx_sink sink (.clk(clk), .reset(reset), .tx_data(tx_data), .tx_strobe(tx_strobe),
                .tx_ready(tx_ready), .clear(clear_rx), .count(cnt),
                .b0(r0), .b1(r1), .b2(r2));

  monitor #(.VERSION_MAJOR(8'd5), .VERSION_MINOR(8'd30), .HAS_INPUT(1),
            .RAM_END(33'h0_0200_0000)) dut (
      .clk(clk), .reset(reset), .rx_data(rx_data), .rx_strobe(rx_strobe),
      .tx_data(tx_data), .tx_strobe(tx_strobe), .tx_ready(tx_ready),
      .mem_read_data(8'd0), .mem_read_word(32'd0),
      .mem_ready(1'b0), .mem_error(1'b0),
      .cpu_halted(1'b1), .cpu_error(1'b0), .cpu_error_code(8'd0),
      .cpu_pc(32'd0), .cpu_debug_register_data(32'd0),
      .serial_rx_free(8'd0), .serial_tx_data(8'd0), .serial_tx_count(8'd0),
      .input_event_valid(input_event_valid), .input_event_word(input_event_word),
      .input_presence_write(input_presence_write),
      .input_presence_keyboard(input_presence_keyboard),
      .input_presence_mouse(input_presence_mouse),
      .input_free_slots(free_slots),
      .busy(busy));

  // ---- el bloque INPUT de verdad, y el banco como CPU ------------------------
  reg         cpu_select = 0, cpu_write = 0;
  reg  [7:0]  cpu_address = 0;
  reg  [31:0] cpu_write_data = 0;
  wire [31:0] cpu_read_data;
  wire        input_error;

  input_registers input_i (
      .clk(clk), .reset(reset),
      .select(cpu_select), .write(cpu_write), .write_mask(4'b1111),
      .address(cpu_address), .write_data(cpu_write_data),
      .read_data(cpu_read_data), .input_error(input_error),
      .event_valid(input_event_valid), .event_word(input_event_word),
      .presence_write(input_presence_write),
      .presence_keyboard(input_presence_keyboard),
      .presence_mouse(input_presence_mouse), .free_slots(free_slots));

  // ---- monitor sin INPUT ----------------------------------------------------
  reg  [7:0] rx_data0 = 0;
  reg        rx_strobe0 = 0;
  wire [7:0] tx_data0;
  wire       tx_strobe0, tx_ready0;
  wire [7:0] cnt0, s0, s1, s2;
  reg        clear0 = 0;

  tx_sink sink0 (.clk(clk), .reset(reset), .tx_data(tx_data0), .tx_strobe(tx_strobe0),
                 .tx_ready(tx_ready0), .clear(clear0), .count(cnt0),
                 .b0(s0), .b1(s1), .b2(s2));

  // Sin conectar los puertos de INPUT, como hacen los tops de las demas carpetas.
  monitor #(.VERSION_MAJOR(8'd4), .VERSION_MINOR(8'd19), .HAS_INPUT(0),
            .RAM_END(33'h0_0200_0000)) dut0 (
      .clk(clk), .reset(reset), .rx_data(rx_data0), .rx_strobe(rx_strobe0),
      .tx_data(tx_data0), .tx_strobe(tx_strobe0), .tx_ready(tx_ready0),
      .mem_read_data(8'd0), .mem_read_word(32'd0),
      .mem_ready(1'b0), .mem_error(1'b0),
      .cpu_halted(1'b1), .cpu_error(1'b0), .cpu_error_code(8'd0),
      .cpu_pc(32'd0), .cpu_debug_register_data(32'd0),
      .serial_rx_free(8'd0), .serial_tx_data(8'd0), .serial_tx_count(8'd0));

  // ---- utilidades -------------------------------------------------------------
  integer errors = 0;
  integer i, n;
  reg [31:0] leido;

  task send_byte(input [7:0] b);
    begin
      @(negedge clk);
      rx_data = b; rx_strobe = 1'b1;
      @(negedge clk);
      rx_strobe = 1'b0;
      repeat (5) @(negedge clk);   // mas rapido que cualquier UART real
    end
  endtask

  task send_word(input [31:0] w);
    begin
      send_byte(w[7:0]); send_byte(w[15:8]); send_byte(w[23:16]); send_byte(w[31:24]);
    end
  endtask

  // Espera la respuesta de dos bytes y comprueba cabecera y huecos libres.
  task expect_response(input [7:0] head, input [7:0] free, input [255:0] what);
    begin
      n = 0;
      while (cnt < 2 && n < 2000) begin @(negedge clk); n = n + 1; end
      if (cnt !== 8'd2 || r0 !== head || r1 !== free) begin
        errors = errors + 1;
        $display("FALLO %0s: respuesta %0d bytes %02h %02h, esperado %02h %02h",
                 what, cnt, r0, r1, head, free);
      end
      clear_rx = 1'b1; @(negedge clk); clear_rx = 1'b0; @(negedge clk);
    end
  endtask

  task cpu_read(input [7:0] offset);
    begin
      @(negedge clk);
      cpu_address = offset; cpu_select = 1'b1; cpu_write = 1'b0;
      @(negedge clk);
      leido = cpu_read_data;
      cpu_select = 1'b0;
      repeat (2) @(negedge clk);
    end
  endtask

  task expect_read(input [7:0] offset, input [31:0] value, input [255:0] what);
    begin
      cpu_read(offset);
      if (leido !== value) begin
        errors = errors + 1;
        $display("FALLO %0s: leido %08h, esperado %08h", what, leido, value);
      end
    end
  endtask

  // Eventos de prueba, con el formato de §25.5-§25.8.
  function [31:0] key_event(input [7:0] usage, input down, input [7:0] mods);
    key_event = {8'h00, mods, 7'd0, down, usage};
  endfunction
  function [31:0] move_event(input [11:0] dx, input [11:0] dy);
    move_event = {8'h02, dy, dx};
  endfunction

  localparam [7:0] STATUS = 8'h04, KEY0 = 8'h10, DATA = 8'h00;

  initial begin
    repeat (3) @(negedge clk);
    reset = 1'b0;
    repeat (2) @(negedge clk);

    // 1. Presencia de los dos: 3c 03 -> bc 10 (la FIFO esta vacia).
    send_byte(8'h3c); send_byte(8'h03);
    expect_response(8'hbc, 8'd16, "presencia");
    expect_read(STATUS, 32'h0006_0000, "STATUS tras presencia");

    // 2. Un evento: 3b 01 <A down + shift izquierdo> -> bb 0f.
    send_byte(8'h3b); send_byte(8'h01); send_word(key_event(8'h04, 1'b1, 8'h02));
    expect_response(8'hbb, 8'd15, "un evento");
    expect_read(STATUS, 32'h0006_0001, "STATUS con un evento");
    expect_read(KEY0, 32'h0000_0010, "KEY_STATE0 bit 4");
    expect_read(DATA, key_event(8'h04, 1'b1, 8'h02), "EVENT_DATA");
    expect_read(STATUS, 32'h0006_0000, "STATUS vacia");

    // 3. Lote de 16: llena la FIFO, en el orden en que se mando.
    send_byte(8'h3b); send_byte(8'h10);
    for (i = 0; i < 16; i = i + 1) send_word(move_event(i + 1, 12'hFFF - i));
    expect_response(8'hbb, 8'd0, "lote de 16");
    expect_read(STATUS, 32'h0006_0010, "STATUS llena");
    for (i = 0; i < 16; i = i + 1)
      expect_read(DATA, move_event(i + 1, 12'hFFF - i), "orden del lote");

    // 4. Sondeo con N = 0: responde sin esperar palabras.
    send_byte(8'h3b); send_byte(8'h00);
    expect_response(8'hbb, 8'd16, "sondeo N=0");

    // 5. Lote mayor que los huecos: 12 y despues 8. Entran 4, se pierden 4, el
    // enlace sigue sincronizado y OVERFLOW queda a uno.
    send_byte(8'h3b); send_byte(8'h0c);
    for (i = 0; i < 12; i = i + 1) send_word(move_event(100 + i, 0));
    expect_response(8'hbb, 8'd4, "12 de 16");
    send_byte(8'h3b); send_byte(8'h08);
    for (i = 0; i < 8; i = i + 1) send_word(move_event(200 + i, 0));
    expect_response(8'hbb, 8'd0, "lote que no cabe");
    expect_read(STATUS, 32'h0007_0010, "OVERFLOW y llena");
    // Sincronizado: el siguiente comando se entiende. Sondeo con la FIFO llena.
    send_byte(8'h3b); send_byte(8'h00);
    expect_response(8'hbb, 8'd0, "sincronia tras perdida");
    // Lo que entro es lo primero que se mando (drop-new).
    for (i = 0; i < 12; i = i + 1)
      expect_read(DATA, move_event(100 + i, 0), "contenido tras perdida");
    for (i = 0; i < 4; i = i + 1)
      expect_read(DATA, move_event(200 + i, 0), "relleno tras perdida");
    expect_read(DATA, 32'd0, "FIFO vacia");

    // 6. Flujo: con 5 eventos dentro, los huecos que anuncia son 11.
    send_byte(8'h3b); send_byte(8'h05);
    for (i = 0; i < 5; i = i + 1) send_word(move_event(i, i));
    expect_response(8'hbb, 8'd11, "flujo");

    // 7. Presencia a cero del teclado: su STATE se pone a cero, el raton sigue.
    send_byte(8'h3b); send_byte(8'h01); send_word(key_event(8'h05, 1'b1, 8'h00));
    expect_response(8'hbb, 8'd10, "tecla B");
    expect_read(KEY0, 32'h0000_0030, "KEY_STATE0 con A y B");
    send_byte(8'h3c); send_byte(8'h02);
    expect_response(8'hbc, 8'd10, "teclado fuera");
    expect_read(KEY0, 32'd0, "KEY_STATE0 a cero");
    expect_read(STATUS, 32'h0005_0006, "STATUS (6 eventos, solo raton, OVERFLOW)");

    // 8. El monitor sin INPUT contesta ff, como a cualquier comando desconocido.
    @(negedge clk);
    rx_data0 = 8'h3b; rx_strobe0 = 1'b1;
    @(negedge clk);
    rx_strobe0 = 1'b0;
    repeat (40) @(negedge clk);
    if (cnt0 !== 8'd1 || s0 !== 8'hff) begin
      errors = errors + 1; $display("FALLO HAS_INPUT=0 con 3b: %0d bytes, %02h", cnt0, s0);
    end
    clear0 = 1'b1; @(negedge clk); clear0 = 1'b0; @(negedge clk);
    rx_data0 = 8'h3c; rx_strobe0 = 1'b1;
    @(negedge clk);
    rx_strobe0 = 1'b0;
    repeat (40) @(negedge clk);
    if (cnt0 !== 8'd1 || s0 !== 8'hff) begin
      errors = errors + 1; $display("FALLO HAS_INPUT=0 con 3c: %0d bytes, %02h", cnt0, s0);
    end

    if (errors == 0) $display("monitor_input_tb PASS");
    else             $display("monitor_input_tb FAIL: %0d errores", errors);
    $finish;
  end

  initial begin
    #50000000;
    $display("monitor_input_tb TIMEOUT");
    $finish;
  end
endmodule

`default_nettype wire
