`timescale 1ns/1ps
`default_nettype none

// La cadena MMIO entera del DMA, como en top.v: mmio_mux -> mmio_decoder ->
// dma_engine. Los bancos del motor le ponen `select` a mano y miran el dato en
// ese mismo ciclo; en placa el decodificador reevalua su etapa de salida hasta
// el `ack` del mux, dos ciclos despues, y el motor solo responde mientras
// `select` esta alto. Asi se perdian DMA_ID, las lecturas y los errores (la CPU
// veia ceros y ningun error). Este banco lo comprueba en el ciclo del `ack`,
// que es donde lo muestrea el nucleo.
module dma_mmio_chain_tb;
  reg clk = 1'b0;
  always #5 clk = ~clk;
  reg reset = 1'b1;

  reg req = 1'b0, req_write = 1'b0;
  reg [31:0] req_address = 32'd0, req_data = 32'd0;
  wire ack;

  wire select, write;
  wire [3:0] write_mask;
  wire [31:0] address, write_data;
  wire dma_select, dma_error;
  wire [31:0] dma_read_data, read_data;
  wire error;
  wire [31:0] zero = 32'd0;

  // El DMA no tiene memoria detras: req_ready a 1 y una respuesta por
  // peticion, para que un FILL termine.
  wire req_valid, req_w, rsp_ready;
  reg rsp_valid = 1'b0;

  mmio_mux #(.EXTRA_CYCLES(2)) mux (
      .clk(clk), .reset(reset),
      .a_req(1'b0), .a_ack(), .a_write(1'b0), .a_write_mask(4'h0),
      .a_address(32'd0), .a_write_data(32'd0),
      .b_req(req), .b_ack(ack), .b_write(req_write), .b_write_mask(4'hf),
      .b_address(req_address), .b_write_data(req_data),
      .select(select), .write(write), .write_mask(write_mask),
      .address(address), .write_data(write_data));

  mmio_decoder #(.HAS_SERIAL(1), .HAS_INPUT(1), .HAS_DMA(1), .PERF_SLOTS(18)) dec (
      .clk(clk), .select(select), .write(write), .write_mask(write_mask),
      .address(address),
      .video_select(), .video_read_data(zero), .video_error(1'b0),
      .serial_select(), .serial_read_data(zero),
      .input_select(), .input_read_data(zero), .input_error(1'b0),
      .dma_select(dma_select), .dma_read_data(dma_read_data),
      .dma_error(dma_error),
      .perf_select(), .perf_read_data(zero),
      .phase_select(), .phase_read_data(zero), .phase_error(1'b0),
      .read_data(read_data), .error(error));

  dma_engine #(.NUM_CHANNELS(2), .TAG_DEPTH(8)) dma (
      .clk(clk), .reset(reset), .init_done(1'b1), .wb_dirty(1'b0),
      .select(dma_select), .write(write), .write_mask(write_mask),
      .address(address[15:0]), .write_data(write_data),
      .read_data(dma_read_data), .mmio_error(dma_error), .irq(),
      .req_valid(req_valid), .req_ready(1'b1), .req_write(req_w),
      .req_addr(), .req_wdata(), .req_wmask(),
      .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
      .rsp_rdata(128'd0), .rsp_error(1'b0));

  // Una respuesta por peticion aceptada, un ciclo despues.
  always @(posedge clk) rsp_valid <= req_valid;

  reg [31:0] got;
  reg got_error;

  // Un acceso de la CPU: req alto hasta ver ack, y el dato y el error se
  // muestrean EN el ciclo del ack, como cpu_dmem_adapter.
  task access(input w, input [31:0] a, input [31:0] d);
    begin
      @(negedge clk);
      req = 1'b1; req_write = w; req_address = a; req_data = d;
      @(posedge clk);
      while (!ack) @(posedge clk);
      got = read_data;
      got_error = error;
      @(negedge clk);
      req = 1'b0;
      @(negedge clk);
    end
  endtask

  task expect_read(input [31:0] a, input [31:0] value);
    begin
      access(1'b0, a, 32'd0);
      if (got_error) $fatal(1, "leer %h dio error", a);
      if (got !== value) $fatal(1, "leer %h: %h, se esperaba %h", a, got, value);
    end
  endtask

  task expect_write(input [31:0] a, input [31:0] d, input should_fail);
    begin
      access(1'b1, a, d);
      if (got_error !== should_fail)
        $fatal(1, "escribir %h en %h: error=%b, se esperaba %b", d, a, got_error, should_fail);
    end
  endtask

  integer t;

  initial begin
    repeat (4) @(negedge clk);
    reset = 1'b0;

    expect_read(32'h8050_0200, 32'h444D_4131);   // DMA_ID
    expect_read(32'h8050_0204, 32'd2);           // DMA_CAPS

    expect_write(32'h8050_0004, 32'h0013_0000, 1'b0);
    expect_read(32'h8050_0004, 32'h0013_0000);

    // Offset sin registro y canal que no existe: error.
    access(1'b0, 32'h8050_0300, 32'd0);
    if (!got_error) $fatal(1, "offset +0x300 sin error");
    access(1'b0, 32'h8050_00C0, 32'd0);
    if (!got_error) $fatal(1, "canal 3 sin error");

    // START con WIDTH = 8 (no multiplo de 16): error.
    expect_write(32'h8050_0008, 32'd8, 1'b0);
    expect_write(32'h8050_000C, 32'd1, 1'b0);
    expect_write(32'h8050_0014, 32'd16, 1'b0);
    expect_write(32'h8050_001C, 32'd3, 1'b1);

    // START valido: NO da error, aunque el canal pase a BUSY en ese mismo
    // flanco y el error recalculado despues ya lo seria.
    expect_write(32'h8050_0008, 32'd64, 1'b0);
    expect_write(32'h8050_000C, 32'd4, 1'b0);
    expect_write(32'h8050_001C, 32'd3, 1'b0);

    // Esperar DONE leyendo STATUS por la cadena.
    got = 32'd0;
    for (t = 0; t < 200 && got[1] !== 1'b1; t = t + 1)
      access(1'b0, 32'h8050_0020, 32'd0);
    if (got !== 32'd2) $fatal(1, "STATUS final %h, se esperaba DONE", got);
    expect_read(32'h8050_0024, 32'd256);         // BYTES_DONE

    // W1C de DONE.
    expect_write(32'h8050_0020, 32'd2, 1'b0);
    expect_read(32'h8050_0020, 32'd0);

    $display("PASS dma_mmio_chain_tb");
    $finish;
  end

  initial begin
    #200000;
    $fatal(1, "timeout");
  end
endmodule

`default_nettype wire
