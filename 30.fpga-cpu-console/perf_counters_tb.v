`timescale 1ns/1ps
`default_nettype none

// Los contadores de rendimiento de la CPU (mmio.md §12 y §13.2), aislados.
//
// Hasta ahora este bloque solo se probaba de rebote, leyendo CYCLES y RETIRED
// desde `--measure`. Con seis contadores de eventos hace falta probar cada uno
// por su cuenta: cuenta lo que dice, solo con el nucleo corriendo, se congela y
// se pone a cero con PERF_CTRL, y su bandera de desbordamiento sube.
//
// Los eventos entran registrados y se cuentan un ciclo despues, asi que cada
// lectura espera unos ciclos a que el ultimo evento llegue al contador.
module perf_counters_tb;
  reg clk = 0, reset = 1;
  always #5 clk = ~clk;

  reg select = 0, write = 0;
  reg [3:0] write_mask = 4'b0000;
  reg [15:0] address = 0;
  reg [31:0] write_data = 0;
  wire [31:0] read_data;
  reg running = 0, retired = 0, restart = 0;
  reg imem_valid = 0, imem_ready = 0, dmem_valid = 0, dmem_ready = 0;
  reg dmem_is_mmio = 0, imem_hit = 0, imem_miss = 0, mem_req0 = 0, mem_req1 = 0;

  cpu_perf_counters dut(
      .clk(clk), .reset(reset),
      .select(select), .write(write), .write_mask(write_mask),
      .address(address), .write_data(write_data), .read_data(read_data),
      .running(running), .retired(retired), .restart(restart),
      .imem_valid(imem_valid), .imem_ready(imem_ready),
      .dmem_valid(dmem_valid), .dmem_ready(dmem_ready),
      .dmem_is_mmio(dmem_is_mmio),
      .imem_hit(imem_hit), .imem_miss(imem_miss),
      .mem_req0(mem_req0), .mem_req1(mem_req1));

  localparam [15:0] CYCLES = 16'h0000, RETIRED = 16'h0004, IMEM_HITS = 16'h0008,
                    IMEM_MISSES = 16'h000c, MEM_TX = 16'h0010, STALL_MEM = 16'h0014,
                    STALL_FETCH = 16'h0018, STALL_MMIO = 16'h001c,
                    CTRL = 16'h0100, OVF0 = 16'h0104;

  integer fallos = 0;

  task esperar(input integer n);
    begin repeat (n) @(negedge clk); end
  endtask

  task leer(input [15:0] a, output [31:0] v);
    begin address = a; #1; v = read_data; end
  endtask

  task comprobar(input [8*30:1] nombre, input [15:0] a, input [31:0] esperado);
    reg [31:0] v;
    begin
      leer(a, v);
      if (v !== esperado) begin
        $display("FAIL %0s: leido %0d (%h), esperado %0d (%h)", nombre, v, v, esperado, esperado);
        fallos = fallos + 1;
      end else $display("ok   %0s = %0d", nombre, v);
    end
  endtask

  task escribir(input [15:0] a, input [31:0] d);
    begin
      @(negedge clk);
      select = 1; write = 1; write_mask = 4'b1111; address = a; write_data = d;
      @(negedge clk);
      select = 0; write = 0;
    end
  endtask

  task pulso_restart;
    begin
      @(negedge clk); restart = 1;
      @(negedge clk); restart = 0;
    end
  endtask

  // Un pulso de un ciclo en `hit`/`miss`, con un ciclo de hueco despues.
  task pulsos_hit(input integer n);
    integer i;
    begin for (i = 0; i < n; i = i + 1) begin @(negedge clk); imem_hit = 1; @(negedge clk); imem_hit = 0; end end
  endtask
  task pulsos_miss(input integer n);
    integer i;
    begin for (i = 0; i < n; i = i + 1) begin @(negedge clk); imem_miss = 1; @(negedge clk); imem_miss = 0; end end
  endtask
  task esperas_fetch(input integer n);
    begin @(negedge clk); imem_valid = 1; imem_ready = 0; esperar(n); imem_valid = 0; end
  endtask
  task esperas_datos(input integer n, input mmio);
    begin @(negedge clk); dmem_is_mmio = mmio; dmem_valid = 1; dmem_ready = 0; esperar(n);
          dmem_valid = 0; dmem_is_mmio = 0; end
  endtask

  reg [31:0] antes, despues;

  initial begin
    esperar(3);
    reset = 0;
    running = 1;
    pulso_restart;

    // ---- 1. Tras arrancar, todo a cero y contando --------------------------
    esperar(2);
    comprobar("tras run: IMEM_HITS", IMEM_HITS, 0);
    comprobar("tras run: STALL_MEM", STALL_MEM, 0);
    comprobar("tras run: PERF_CTRL.ENABLE", CTRL, 1);

    // ---- 2. Cada contador cuenta lo suyo ------------------------------------
    pulsos_hit(5);
    pulsos_miss(3);
    esperas_fetch(7);
    esperas_datos(4, 0);      // datos a memoria
    esperas_datos(6, 1);      // datos a MMIO
    // `ready` alto no es espera: valid && ready no cuenta.
    @(negedge clk); dmem_valid = 1; dmem_ready = 1; esperar(3); dmem_valid = 0; dmem_ready = 0;
    // MEM_TX: tres pulsos en el puerto 0, dos en el 1, uno en los dos a la vez
    // (+2 en un ciclo) y uno mantenido alto diez ciclos (cuenta UNA peticion).
    repeat (3) begin @(negedge clk); mem_req0 = 1; @(negedge clk); mem_req0 = 0; end
    repeat (2) begin @(negedge clk); mem_req1 = 1; @(negedge clk); mem_req1 = 0; end
    @(negedge clk); mem_req0 = 1; mem_req1 = 1; @(negedge clk); mem_req0 = 0; mem_req1 = 0;
    @(negedge clk); mem_req0 = 1; esperar(10); mem_req0 = 0;
    esperar(4);
    comprobar("IMEM_HITS", IMEM_HITS, 5);
    comprobar("IMEM_MISSES", IMEM_MISSES, 3);
    comprobar("STALL_FETCH", STALL_FETCH, 7);
    comprobar("STALL_MEM = busqueda + datos", STALL_MEM, 7 + 4);
    comprobar("STALL_MMIO", STALL_MMIO, 6);
    comprobar("MEM_TX = 3 + 2 + 2 + 1", MEM_TX, 8);
    leer(CYCLES, antes);
    if (antes < 40) begin
      $display("FAIL CYCLES no cuenta con la CPU en marcha (%0d)", antes);
      fallos = fallos + 1;
    end

    // ---- 3. Con la CPU parada solo RETIRED avanza ---------------------------
    running = 0;
    leer(CYCLES, antes);
    pulsos_hit(2);
    esperas_fetch(5);
    esperas_datos(3, 1);
    @(negedge clk); mem_req1 = 1; @(negedge clk); mem_req1 = 0;
    esperar(4);
    comprobar("parada: IMEM_HITS igual", IMEM_HITS, 5);
    comprobar("parada: STALL_FETCH igual", STALL_FETCH, 7);
    comprobar("parada: STALL_MMIO igual", STALL_MMIO, 6);
    comprobar("parada: MEM_TX igual", MEM_TX, 8);
    comprobar("parada: CYCLES igual", CYCLES, antes);
    // El HALT retira en el ciclo en que la CPU se para: RETIRED NO va con running.
    leer(RETIRED, antes);
    @(negedge clk); retired = 1; esperar(3); retired = 0; esperar(2);
    comprobar("parada: RETIRED sigue contando", RETIRED, antes + 3);

    // ---- 4. Congelar: PERF_CTRL.ENABLE = 0 para todo el bloque --------------
    running = 1;
    escribir(CTRL, 0);
    esperar(2);
    leer(CYCLES, antes);
    leer(RETIRED, despues);
    pulsos_hit(2);
    esperas_fetch(4);
    @(negedge clk); retired = 1; esperar(3); retired = 0;
    esperar(4);
    comprobar("congelado: CYCLES", CYCLES, antes);
    comprobar("congelado: RETIRED", RETIRED, despues);
    comprobar("congelado: IMEM_HITS", IMEM_HITS, 5);
    comprobar("congelado: STALL_FETCH", STALL_FETCH, 7);
    escribir(CTRL, 1);
    esperar(2);
    pulsos_hit(1);
    esperar(4);
    comprobar("descongelado: IMEM_HITS", IMEM_HITS, 6);

    // ---- 5. RESET_COUNTERS: a cero, y tambien PERF_OVF ----------------------
    escribir(CTRL, 3);
    esperar(2);
    comprobar("reset: IMEM_HITS", IMEM_HITS, 0);
    comprobar("reset: MEM_TX", MEM_TX, 0);
    comprobar("reset: STALL_MEM", STALL_MEM, 0);
    comprobar("reset: PERF_OVF0", OVF0, 0);
    comprobar("reset deja ENABLE a uno", CTRL, 1);

    // ---- 6. Desbordamiento: la bandera de cada contador ---------------------
    // 2^32 eventos no se simulan; se deja el contador a un paso del borde.
    @(negedge clk);
    dut.stall_mmio = 32'hFFFF_FFFF;
    dut.mem_tx = 32'hFFFF_FFFF;
    dut.imem_hits = 32'hFFFF_FFFF;
    esperas_datos(1, 1);                       // STALL_MMIO: FFFFFFFF -> 0
    @(negedge clk); mem_req0 = 1; mem_req1 = 1; @(negedge clk); mem_req0 = 0; mem_req1 = 0;
    pulsos_hit(1);                             // IMEM_HITS: FFFFFFFF -> 0
    esperar(4);
    comprobar("STALL_MMIO da la vuelta", STALL_MMIO, 0);
    // FFFFFFFF + 2 = 1 con acarreo: la bandera sale del acarreo, no de mirar
    // si estaba a tope, porque MEM_TX suma hasta dos por ciclo.
    comprobar("MEM_TX: FFFFFFFF + 2", MEM_TX, 1);
    comprobar("PERF_OVF0 = MMIO(7), TX(4), HITS(2)", OVF0, 32'h0000_0094);
    // W1C: un uno limpia solo ese bit.
    escribir(OVF0, 32'h0000_0080);
    comprobar("W1C limpia solo el bit 7", OVF0, 32'h0000_0014);

    $display("");
    if (fallos == 0) $display("perf_counters_tb: OK");
    else $display("perf_counters_tb: %0d FALLO(S)", fallos);
    $display("");
    if (fallos != 0) $stop;
    $finish;
  end

  initial begin
    #2000000;
    $display("FAIL: timeout");
    $stop;
  end
endmodule

`default_nettype wire
