`timescale 1ns/1ps
// El bus MMIO entero de la 36: mmio_mux + mmio_decoder + video_registers,
// text_console, serial_port, input_registers, cpu_perf_counters y una GPU
// simulada (dispositivo lento: contesta con `done` a los 4 ciclos).
//
// No hay otro banco que monte mux, decodificador y dispositivos juntos; los de
// la 30 montan los suyos. Lo que se comprueba es lo que ve el cliente en el
// ciclo del `ack`: `read_data` y `error` de 96 accesos (lecturas, escrituras,
// errores de dato, de direccion, mascara parcial, la GPU lenta). El resultado
// esperado esta en sim/mmio_bus_expected.hex, una palabra de 40 bits por acceso:
// {error, comparar_dato, read_data}. Salio del decodificador de dos etapas
// anterior a registrar la salida de cada dispositivo (mmio_decoder, "etapa 3"),
// que es la prueba de que esa etapa solo cambio la latencia. Los contadores de
// rendimiento cuentan tiempo y ese dato no se compara (`comparar_dato` = 0).
//
// Ejecutar desde esta carpeta (lee fonts/):
//   iverilog -g2012 -o mmio_bus_tb.vvp mmio_bus_tb.v mmio_decoder.v mmio_mux.v \
//       sysid.v serial_port.v input_registers.v cpu_perf_counters.v \
//       video_registers.v text_console.v && vvp mmio_bus_tb.vvp
module mmio_bus_tb;
  reg host_push = 0; reg [7:0] host_push_data = 0;
  reg clk = 0, reset = 1;
  always #6 clk = ~clk;

  reg b_req = 0, b_write = 0; reg [3:0] b_mask = 4'hf; reg [31:0] b_addr = 0, b_wdata = 0;
  wire b_ack;
  wire select, write; wire [3:0] write_mask; wire [31:0] address, write_data;
  wire mmio_error; wire [31:0] mmio_read_data;
  wire video_select, serial_select, input_select, perf_select, gpu_select;
  wire [31:0] video_core_rd, console_rd, serial_rd, input_rd, perf_rd;
  wire video_core_err, console_err, input_err;
  wire [31:0] video_rd = video_core_rd | console_rd;
  wire video_err = video_core_err | console_err;
  reg gpu_done = 0; reg [3:0] gpu_cnt = 0;
  wire gpu_start = gpu_select;
  always @(posedge clk) begin
    gpu_done <= 0;
    if (gpu_select) gpu_cnt <= 4'd4;
    else if (gpu_cnt != 0) begin gpu_cnt <= gpu_cnt - 1; if (gpu_cnt == 1) gpu_done <= 1; end
  end

  mmio_mux mux_i(.clk(clk), .reset(reset),
      .a_req(1'b0), .a_ack(), .a_write(1'b0), .a_write_mask(4'b0), .a_address(32'b0), .a_write_data(32'b0),
      .b_req(b_req), .b_ack(b_ack), .b_write(b_write), .b_write_mask(b_mask),
      .b_address(b_addr), .b_write_data(b_wdata),
      .slow_start(gpu_select), .slow_done(gpu_done),
      .select(select), .write(write), .write_mask(write_mask), .address(address), .write_data(write_data));

  mmio_decoder #(.FOLDER(32'd36), .HAS_SERIAL(1), .HAS_INPUT(1), .HAS_GPU(1), .PERF_SLOTS(8),
      .VIDEO_REGISTERS(64'h0000_0000_0001_03ff), .ISA_PROFILE(32'd7), .DEVICES(32'h0A37),
      .MEM_BASE(32'h0), .MEM_SIZE(32'h0200_0000), .MONITOR_VERSION(32'h0005_0024))
    dec_i(.clk(clk), .select(select), .write(write), .write_mask(write_mask), .address(address),
      .video_select(video_select), .video_read_data(video_rd), .video_error(video_err),
      .serial_select(serial_select), .serial_read_data(serial_rd),
      .input_select(input_select), .input_read_data(input_rd), .input_error(input_err),
      .perf_select(perf_select), .perf_read_data(perf_rd),
      .gpu_select(gpu_select), .gpu_read_data(32'hABCD_0000 | address[15:0]), .gpu_error(address[15:0] == 16'h0ffc),
      .read_data(mmio_read_data), .error(mmio_error));

  reg retired = 0;
  always @(posedge clk) retired <= ~retired;
  cpu_perf_counters perf_i(.clk(clk), .reset(reset), .select(perf_select), .write(write),
      .write_mask(write_mask), .address(address[15:0]), .write_data(write_data), .read_data(perf_rd),
      .running(1'b1), .retired(retired), .restart(1'b0),
      .imem_valid(1'b1), .imem_ready(retired), .dmem_valid(1'b0), .dmem_ready(1'b0),
      .dmem_is_mmio(1'b0), .imem_hit(1'b0), .imem_miss(1'b0), .mem_req0(1'b0), .mem_req1(1'b0));

  wire [23:0] fb_base; wire [1:0] video_mode; wire text_enable;
  video_registers registers_i(.clk(clk), .reset(reset), .select(video_select), .write(write),
      .write_mask(write_mask), .address(address[15:0]), .write_data(write_data),
      .read_data(video_core_rd), .error(video_core_err), .running(1'b1),
      .fill_start(1'b0), .fill_first(1'b0), .fb_base(fb_base), .underflow_pix(1'b0),
      .underflow_clear(), .halt_request(), .video_mode(video_mode), .text_enable(text_enable),
      .debug_front(), .debug_back());

  serial_port serial_i(.clk(clk), .reset(reset), .select(serial_select), .write(write),
      .write_mask(write_mask), .address(address[7:0]), .write_data(write_data), .read_data(serial_rd),
      .host_push(host_push), .host_push_data(host_push_data), .host_rx_free(),
      .host_pop(1'b0), .host_tx_data(), .host_tx_count());

  input_registers input_i(.clk(clk), .reset(reset), .select(input_select), .write(write),
      .write_mask(write_mask), .address(address[7:0]), .write_data(write_data),
      .read_data(input_rd), .input_error(input_err),
      .event_valid(1'b0), .event_word(32'b0), .presence_write(1'b0),
      .presence_keyboard(1'b0), .presence_mouse(1'b0), .free_slots());

  text_console console_i(.clk_sys(clk), .reset_sys(reset), .select(video_select), .write(write),
      .write_mask(write_mask), .address(address[15:0]), .write_data(write_data),
      .read_data(console_rd), .error(console_err),
      .clk_pix(clk), .reset_pix(reset), .enable(1'b1), .sx(12'd0), .sy(12'd0),
      .r_in(8'd0), .g_in(8'd0), .b_in(8'd0), .de_in(1'b0), .hsync_in(1'b0), .vsync_in(1'b0),
      .r_out(), .g_out(), .b_out(), .de_out(), .hsync_out(), .vsync_out());

  localparam EXPECTED = 96;
  reg [39:0] golden [0:EXPECTED-1];
  initial $readmemh("sim/mmio_bus_expected.hex", golden);

  integer n = 0, timeout, failures = 0;
  task access(input w, input [31:0] a, input [31:0] d, input [3:0] m);
    begin
      @(negedge clk);
      b_req = 1; b_write = w; b_addr = a; b_wdata = d; b_mask = m;
      timeout = 0;
      @(posedge clk);
      while (!b_ack && timeout < 200) begin @(posedge clk); timeout = timeout + 1; end
      // El cliente muestrea read_data y error EN el ciclo del ack.
      if (timeout >= 200 || n >= EXPECTED
          || mmio_error !== golden[n][36]
          || (golden[n][32] && mmio_read_data !== golden[n][31:0])) begin
        failures = failures + 1;
        $display("FALLO acceso %0d %s %h m=%b d=%h: rd=%h err=%b, esperado rd=%h%s err=%b%s",
                 n, w ? "W" : "R", a, m, d, mmio_read_data, mmio_error,
                 golden[n][31:0], golden[n][32] ? "" : " (no se compara)", golden[n][36],
                 timeout >= 200 ? " TIMEOUT" : "");
      end
      n = n + 1;
      @(negedge clk); b_req = 0;
      repeat (3) @(negedge clk);
    end
  endtask
  task rd(input [31:0] a); access(0, a, 0, 4'hf); endtask
  task wr(input [31:0] a, input [31:0] d); access(1, a, d, 4'hf); endtask

  integer i;
  initial begin
    repeat (4) @(posedge clk); reset = 0; repeat (4) @(posedge clk);
    for (i = 0; i < 8; i = i + 1) rd(32'h8000_0000 + 4*i);      // SYSTEM (la 7 y mas dan error)
    wr(32'h8000_0000, 1);                                         // escritura a solo lectura
    rd(32'h8020_0000); rd(32'h8020_0004); rd(32'h8020_0008); rd(32'h8020_0010);
    wr(32'h8020_0004, 32'h0100_0010);                             // FB_FRONT alineada
    wr(32'h8020_0004, 32'h0100_0011);                             // desalineada: error
    wr(32'h8020_0008, 32'h0200_0000);
    rd(32'h8020_0004); rd(32'h8020_0008);
    wr(32'h8020_0000, 32'd1); rd(32'h8020_0000);                  // CTRL modo 1
    wr(32'h8020_0000, 32'd3); rd(32'h8020_0000);                  // modo reservado: error
    wr(32'h8020_000c, 32'd1); rd(32'h8020_0010);                  // SWAP
    wr(32'h8020_000c, 32'd8);                                     // SWAP invalido
    wr(32'h8020_0040, 32'd4); rd(32'h8020_0040); wr(32'h8020_0040, 32'd8);  // CONFIG
    wr(32'h8020_001c, 32'd5); rd(32'h8020_001c);                  // HALT_AT
    rd(32'h8020_0014); rd(32'h8020_0018); rd(32'h8020_0024);
    access(1, 32'h8020_0004, 32'h0000_0020, 4'b0011);             // parcial
    // consola: paleta, texto, fuente
    wr(32'h8020_1004, 32'h00ff_8040); rd(32'h8020_1004); rd(32'h8020_1008);
    wr(32'h8020_6000, 32'h0000_1f41); rd(32'h8020_6000);
    wr(32'h8020_6004, 32'h0000_2042); rd(32'h8020_6004); rd(32'h8020_6000);
    wr(32'h8020_6008, 32'h1_0000);                                // bits reservados
    wr(32'h8020_0084, 32'd3); rd(32'h8020_0084);                  // FONT_GLYPH
    wr(32'h8020_0080, 32'd2); rd(32'h8020_0080); wr(32'h8020_0080, 32'd300);
    wr(32'h8020_0088, 32'h1111_1111); wr(32'h8020_008c, 32'h2222_2222); wr(32'h8020_0090, 32'h3333_3333);
    rd(32'h8020_0088); rd(32'h8020_0090);
    wr(32'h8020_0094, 32'h4444_4444); rd(32'h8020_0080); rd(32'h8020_0084);
    rd(32'h8020_2000); rd(32'h8020_0098); rd(32'h8020_0001);      // huecos y desalineada
    // serie
    for (i = 0; i < 4; i = i + 1) rd(32'h8010_0000 + 4*i);
    wr(32'h8010_0004, 32'h41); rd(32'h8010_0004); rd(32'h8010_0008); rd(32'h8010_000c);
    // input
    for (i = 0; i < 5; i = i + 1) rd(32'h8060_0000 + 4*i);
    wr(32'h8060_0008, 32'h1); wr(32'h8060_0008, 32'hffff_ffff);
    // perf
    for (i = 0; i < 9; i = i + 1) rd(32'h8101_0000 + 4*i);
    rd(32'h8101_0100); wr(32'h8101_0100, 32'd1); rd(32'h8101_0100); rd(32'h8101_0200);
    // gpu (dispositivo lento)
    rd(32'h8200_0000); rd(32'h8200_0010); rd(32'h8200_0ffc); wr(32'h8200_0004, 32'h55);
    rd(32'h8200_0001);                                            // desalineada
    // errores de direccion
    rd(32'h8030_0000); rd(32'h0000_1000); rd(32'h9000_0000); rd(32'h8020_0100);
    if (n != EXPECTED) begin
      failures = failures + 1;
      $display("FALLO: %0d accesos y se esperaban %0d", n, EXPECTED);
    end
    if (failures == 0) $display("PASS: %0d accesos MMIO", n);
    else $display("FAIL: %0d diferencias", failures);
    $finish;
  end
endmodule

