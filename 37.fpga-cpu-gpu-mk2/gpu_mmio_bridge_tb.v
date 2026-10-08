`timescale 1ns/1ps
// El puente CPU -> GPU con sus dos relojes de verdad: clk a 80 MHz y gclk a 25
// MHz, sin relacion de fase, y la fase de gclk se cambia de una ejecucion a otra
// (+phase=N, en ns). Una GPU simulada contesta a los 1..4 ciclos de gclk.
//
// Hace lo que hace `mmio_mux` con un dispositivo lento: mantiene direccion, dato
// y tipo de acceso estables desde ANTES del `start` hasta ver `done`, y pulsa
// `start` un ciclo. Comprueba que:
//   * llega un `done` por acceso, de un ciclo, y ninguno sin `start`;
//   * la lectura y el error son los de ese acceso, aunque el siguiente cambie
//     direccion y dato de inmediato;
//   * `h_valid` se ve una vez por acceso, con los datos del acceso.
//
// Ejecutar desde esta carpeta, una vez por fase:
//   iverilog -g2012 -o gpu_mmio_bridge_tb.vvp gpu_mmio_bridge_tb.v gpu_mmio_bridge.v
//   for p in 0 3 7 11 17 23 31 37; do vvp gpu_mmio_bridge_tb.vvp +phase=$p; done
module gpu_mmio_bridge_tb;
  reg clk = 0, gclk = 0, reset = 1, greset = 1;
  integer phase;
  initial begin
    if (!$value$plusargs("phase=%d", phase)) phase = 0;
    #(phase) forever #20 gclk = ~gclk;       // 25 MHz, desfasado
  end
  always #6.25 clk = ~clk;                   // 80 MHz

  reg start = 0, write = 0; reg [31:0] address = 0, write_data = 0;
  wire done; wire [31:0] read_data; wire error;
  wire h_valid, h_write; wire [31:0] h_addr, h_wdata;
  reg h_done = 0; reg [31:0] h_rdata = 0; reg h_error = 0;

  gpu_mmio_bridge dut(.clk(clk), .reset(reset), .start(start), .write(write),
      .address(address), .write_data(write_data), .done(done),
      .read_data(read_data), .error(error),
      .gclk(gclk), .greset(greset), .h_valid(h_valid), .h_write(h_write),
      .h_addr(h_addr), .h_wdata(h_wdata), .h_done(h_done), .h_rdata(h_rdata),
      .h_error(h_error));

  // Funcion de respuesta de la GPU: depende de la direccion y del dato.
  function [31:0] answer(input [31:0] a, input [31:0] d, input w);
    answer = w ? 32'd0 : (a ^ 32'hA5A5_0000) + d[7:0];
  endfunction
  function bad(input [31:0] a); bad = a[4]; endfunction

  // GPU simulada, en gclk: contesta a los 1..4 ciclos de ver h_valid.
  integer gpu_wait = 0, gpu_seen = 0, delay_sel = 0;
  reg [31:0] g_addr, g_data; reg g_write;
  always @(posedge gclk) begin
    h_done <= 1'b0;
    if (h_valid) begin
      gpu_seen = gpu_seen + 1;
      g_addr = h_addr; g_data = h_wdata; g_write = h_write;
      gpu_wait = 1 + (delay_sel % 4);
      delay_sel = delay_sel + 1;
    end else if (gpu_wait > 0) begin
      gpu_wait = gpu_wait - 1;
      if (gpu_wait == 0) begin
        h_done <= 1'b1;
        h_rdata <= answer(g_addr, g_data, g_write);
        h_error <= bad(g_addr);
      end
    end
  end

  // Contador de `done` y comprobacion de que dura un ciclo y no aparece solo.
  integer dones = 0, failures = 0; reg done_q = 0;
  reg expecting = 0;
  always @(posedge clk) begin
    done_q <= done;
    if (done) begin
      dones = dones + 1;
      if (!expecting) begin failures = failures + 1; $display("FALLO: done sin acceso en curso"); end
      if (done_q) begin failures = failures + 1; $display("FALLO: done de mas de un ciclo"); end
    end
  end

  integer i, waited;
  reg [31:0] a, d; reg w;
  initial begin
    repeat (6) @(posedge clk); reset = 0;
    repeat (4) @(posedge gclk); greset = 0;
    repeat (20) @(posedge clk);
    for (i = 0; i < 300; i = i + 1) begin
      // Direccion y dato cambian justo despues del `done` anterior.
      a = 32'h8200_0000 + ((i * 12) % 4096); d = 32'h0101_0000 * (i % 7) + i; w = (i % 3) == 0;
      @(negedge clk);
      address = a; write_data = d; write = w;
      repeat (1 + (i % 3)) @(negedge clk);       // estables ANTES del start
      expecting = 1;
      start = 1; @(negedge clk); start = 0;
      waited = 0;
      while (!done && waited < 400) begin @(negedge clk); waited = waited + 1; end
      if (waited >= 400) begin
        failures = failures + 1; $display("FALLO: acceso %0d sin done", i);
      end else begin
        // `done` esta en este ciclo: la lectura y el error ya son validos.
        if (read_data !== answer(a, d, w) || error !== bad(a)) begin
          failures = failures + 1;
          $display("FALLO acceso %0d: rd=%h err=%b, esperado %h/%b", i, read_data, error,
                   answer(a, d, w), bad(a));
        end
      end
      // El monitor de `done` muestrea en el flanco siguiente: se baja despues.
      @(posedge clk); #1 expecting = 0;
      // Lo siguiente cambia ya, sin esperar a que la GPU se haya enterado.
      if (i % 5 == 4) begin address = ~address; write_data = ~write_data; end
      if (i % 4 == 0) repeat (i % 9) @(negedge clk);
    end
    repeat (200) @(posedge clk);                // nada espurio en reposo
    if (dones != 300) begin failures = failures + 1; $display("FALLO: %0d done y 300 accesos", dones); end
    if (gpu_seen != 300) begin failures = failures + 1; $display("FALLO: la GPU vio %0d peticiones", gpu_seen); end
    if (failures == 0) $display("PASS fase %0d: 300 accesos, %0d done", phase, dones);
    else $display("FAIL fase %0d: %0d fallos", phase, failures);
    $finish;
  end
endmodule
