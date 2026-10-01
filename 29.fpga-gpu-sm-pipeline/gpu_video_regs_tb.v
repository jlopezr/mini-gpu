`timescale 1ns/1ps
`default_nettype none

// La alarma HALT_AT de `gpu_video_regs`: mismo contrato que `video_registers.v`
// de las CPU (mmio.md §9.6), probado aqui sin SM ni SDRAM. Cuenta INTERCAMBIOS
// completados desde que se arma; HALT_TARGET dice a quien para (bit 1 = GPU).
module gpu_video_regs_tb;
  localparam [3:0] REG_SWAP       = 4'd3;
  localparam [3:0] REG_FRAME_COUNT = 4'd5;
  localparam [3:0] REG_SWAP_COUNT = 4'd6;
  localparam [3:0] REG_HALT_AT    = 4'd7;
  localparam [3:0] REG_HALT_TARGET = 4'd8;

  localparam [31:0] TARGET_CPU = 32'd1;
  localparam [31:0] TARGET_GPU = 32'd2;

  reg clk = 1'b0;
  always #5 clk = ~clk;

  reg reset = 1'b1;
  reg sel = 1'b0;
  reg [3:0] word = 4'd0;
  reg write = 1'b0;
  reg [31:0] write_data = 32'd0;
  reg [3:0] write_strobe = 4'b1111;
  wire [31:0] read_data;
  wire bad;
  reg frame_pulse = 1'b0;

  wire [1:0] video_mode;
  wire [23:0] fb_base;
  wire underflow_clear, halt_request;

  gpu_video_regs dut(
      .clk(clk), .reset(reset),
      .sel(sel), .word(word), .write(write), .write_data(write_data),
      .write_strobe(write_strobe), .read_data(read_data), .bad(bad),
      .underflow(1'b0), .frame_pulse(frame_pulse),
      .video_tx(1'b0), .running(1'b1),
      .video_mode(video_mode), .fb_base(fb_base),
      .underflow_clear(underflow_clear), .halt_request(halt_request));

  // `halt_request` es un pulso de un ciclo: se cuenta, no se mira con un `if`.
  integer halt_count = 0;
  always @(posedge clk) if (halt_request) halt_count = halt_count + 1;

  task bus_write;
    input [3:0] reg_word;
    input [31:0] value;
    input [3:0] strobe;
    begin
      @(negedge clk);
      sel = 1'b1; word = reg_word; write = 1'b1;
      write_data = value; write_strobe = strobe;
      @(negedge clk);
      sel = 1'b0; write = 1'b0; write_strobe = 4'b1111;
    end
  endtask

  task bus_write_word;
    input [3:0] reg_word;
    input [31:0] value;
    begin bus_write(reg_word, value, 4'b1111); end
  endtask

  task bus_read;
    input [3:0] reg_word;
    output [31:0] value;
    begin
      @(negedge clk);
      sel = 1'b1; word = reg_word;
      #1 value = read_data;
      @(negedge clk);
      sel = 1'b0;
    end
  endtask

  // Un vsync: el intercambio pendiente se aplica aqui.
  task vsync;
    begin
      @(negedge clk); frame_pulse = 1'b1;
      @(negedge clk); frame_pulse = 1'b0;
      repeat (2) @(negedge clk);
    end
  endtask

  // Un intercambio COMPLETADO: pedirlo y dejar que llegue el vsync.
  task complete_swap;
    begin
      bus_write_word(REG_SWAP, 32'd1);
      vsync;
    end
  endtask

  reg [31:0] value;
  reg [31:0] frames_before, swaps_before;
  integer mark;

  initial begin
    $dumpvars(0, gpu_video_regs_tb);
    repeat (3) @(negedge clk);
    reset = 1'b0;
    @(negedge clk);

    // --- valores de reset --------------------------------------------------
    bus_read(REG_HALT_AT, value);
    if (value !== 32'd0) $fatal(1, "HALT_AT no arranca a cero: %08x", value);
    bus_read(REG_HALT_TARGET, value);
    if (value !== 32'd0) $fatal(1, "HALT_TARGET no arranca a cero: %08x", value);

    // --- ya no son huecos: se escriben y se leen ---------------------------
    bus_write_word(REG_HALT_AT, 32'd77);
    bus_read(REG_HALT_AT, value);
    if (value !== 32'd77) $fatal(1, "HALT_AT no se leyo de vuelta: %08x", value);
    bus_write_word(REG_HALT_AT, 32'd0);

    // Solo existen los bits de CPU y GPU; el resto esta reservado.
    bus_write_word(REG_HALT_TARGET, 32'hFFFF_FFFF);
    bus_read(REG_HALT_TARGET, value);
    if (value !== 32'd3) $fatal(1, "HALT_TARGET no enmascaro: %08x", value);
    bus_write_word(REG_HALT_TARGET, 32'd0);

    // --- desarmada, un intercambio no para a nadie --------------------------
    mark = halt_count;
    complete_swap;
    if (halt_count != mark) $fatal(1, "desarmada paro la GPU");

    // --- HALT_TARGET: la alarma dice A QUIEN para --------------------------
    // Tras reset no para a nadie, asi que armar solo HALT_AT no detiene nada.
    bus_write_word(REG_HALT_AT, 32'd1);
    mark = halt_count;
    complete_swap;
    if (halt_count != mark)
      $fatal(1, "paro sin HALT_TARGET: la alarma no mira a quien para");

    // El bit de CPU se acepta y no hace nada: aqui solo hay GPU.
    bus_write_word(REG_HALT_TARGET, TARGET_CPU);
    bus_write_word(REG_HALT_AT, 32'd1);
    mark = halt_count;
    complete_swap;
    if (halt_count != mark)
      $fatal(1, "el bit de CPU de HALT_TARGET paro a la GPU");

    bus_write_word(REG_HALT_TARGET, TARGET_GPU);

    // --- armar: relativo, y sin tocar los contadores del dispositivo -------
    bus_read(REG_FRAME_COUNT, frames_before);
    bus_read(REG_SWAP_COUNT, swaps_before);
    bus_write_word(REG_HALT_AT, 32'd2);
    bus_read(REG_FRAME_COUNT, value);
    if (value !== frames_before)
      $fatal(1, "armar HALT_AT toco FRAME_COUNT: %0d -> %0d", frames_before, value);
    bus_read(REG_SWAP_COUNT, value);
    if (value !== swaps_before)
      $fatal(1, "armar HALT_AT toco SWAP_COUNT: %0d -> %0d", swaps_before, value);

    // Frames SIN intercambio no cuentan: un kernel lento deja pasar muchos y la
    // alarma espera a sus swaps, no al barrido.
    mark = halt_count;
    repeat (3) vsync;
    if (halt_count != mark)
      $fatal(1, "HALT_AT paro en un frame sin intercambio");

    complete_swap;
    if (halt_count != mark)
      $fatal(1, "HALT_AT paro en el intercambio equivocado");
    complete_swap;
    if (halt_count == mark)
      $fatal(1, "HALT_AT no paro a los dos intercambios");

    // --- se puede volver a armar -------------------------------------------
    // Con la cuenta libre, la segunda vez que un kernel arma la alarma no pararia
    // NUNCA: el contador ya habria pasado de largo.
    bus_write_word(REG_HALT_AT, 32'd1);
    mark = halt_count;
    complete_swap;
    if (halt_count == mark)
      $fatal(1, "HALT_AT no volvio a armarse");

    // --- es de UN disparo ---------------------------------------------------
    mark = halt_count;
    complete_swap;
    if (halt_count != mark)
      $fatal(1, "HALT_AT siguio disparando despues de consumirse");

    // --- escritura byte a byte, como la hace el monitor ---------------------
    // Los bytes altos a cero no cambian el valor, asi que arma con 2 igualmente.
    bus_write(REG_HALT_AT, 32'h0000_0002, 4'b0001);
    bus_write(REG_HALT_AT, 32'h0000_0000, 4'b0010);
    bus_write(REG_HALT_AT, 32'h0000_0000, 4'b0100);
    bus_write(REG_HALT_AT, 32'h0000_0000, 4'b1000);
    bus_read(REG_HALT_AT, value);
    if (value !== 32'd2) $fatal(1, "escritura por bytes dio %08x", value);
    mark = halt_count;
    complete_swap;
    if (halt_count != mark) $fatal(1, "por bytes paro un intercambio antes");
    complete_swap;
    if (halt_count == mark) $fatal(1, "por bytes no paro a los dos intercambios");

    $display("OK: HALT_AT de la GPU cuenta intercambios y respeta HALT_TARGET");
    $finish;
  end

  initial begin
    #500_000;
    $fatal(1, "timeout");
  end
endmodule

`default_nettype wire
