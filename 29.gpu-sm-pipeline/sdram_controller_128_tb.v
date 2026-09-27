`timescale 1ns/1ps
`default_nettype none

/*
 * Banco del controlador BL8, contra el modelo de SDRAM.
 *
 * El banco heredado de la 16, sdram_controller_tb.v, comprueba que los
 * COMANDOS salen con la temporizacion JEDEC. Lo que no puede comprobar, porque
 * no hay memoria al otro lado, es que los DATOS acaben donde deben. Con
 * rafagas de ocho eso deja de ser un detalle: hay ocho oportunidades de
 * equivocarse de ciclo, y una sola basta para leer la palabra del vecino.
 *
 * El punto de muestreo, que es lo que este banco existe para fijar
 * -------------------------------------------------------------------
 *
 * Con CL2, la SDRAM presenta D0 dos ciclos despues del comando READ. Pero
 * entre que la FPGA emite el comando y que ve el dato de vuelta hay el camino
 * de salida, el pin, la pista, el pin de vuelta y el camino de entrada, y a
 * 100 MHz eso pasa de un ciclo. Por eso el controlador BL1 de la 16 —el que
 * lleva funcionando en la placa— captura en T+3 y no en T+2:
 *
 *     ST_READ (T) -> ST_READ_WAIT0 -> ST_READ_WAIT1 -> ST_READ_CAPTURE (T+3)
 *
 * El modelo reproduce eso con READ_DELAY_CYCLES: 0 es JEDEC puro sobre el papel
 * y 1 es un bus que se sale de un ciclo.
 *
 * ESTE BANCO NO PUEDE DECIDIR CUAL ES EL DE ESTA PLACA, y es importante no
 * creerse que si. Controlador y modelo comparten el parametro: emparejados
 * leen bien con cualquier valor. Por eso corre los dos emparejamientos y un
 * control negativo cruzado; lo que prueba es que el controlador es correcto
 * para el retardo que sea y que un desajuste se nota, no cuanto vale.
 *
 * Cuanto vale lo dijo la placa, y dijo 0: a 80 MHz el ciclo es de 12,5 ns y el
 * viaje de ida y vuelta cabe dentro. La 16, a 100 MHz y 10 ns, necesitaba 1.
 * Fijarlo aqui por analogia con la 16 fue el error: con 1, una vuelta completa
 * de escribir y leer devolvia la rafaga corrida un beat.
 */
module sdram_controller_128_tb;
  localparam integer CLK_HZ = 100_000_000;
  // Arranque acortado para que la simulacion termine: el modelo comprueba la
  // MISMA constante, asi que el orden de la secuencia se sigue verificando.
  localparam integer POWERUP_US = 2;

  reg clk = 0;
  reg reset = 1;
  always #5 clk = ~clk;

  reg visto_ideal, visto_placa, visto_malo;
  integer errors = 0;
  integer guard;
  integer k;

  // -----------------------------------------------------------------
  // Dos sistemas identicos, uno por cada retardo de bus.
  // -----------------------------------------------------------------
  reg req_valid = 0, req_write = 0;
  reg [23:0] req_addr = 0;
  reg [127:0] req_wdata = 0;
  reg [15:0] req_wmask = 0;

  wire [1:0] req_ready, done, init_done;
  wire [127:0] rdata_ideal, rdata_placa;

  wire [1:0] cke, csn, rasn, casn, wen;
  wire [12:0] a_ideal, a_placa;
  wire [1:0] ba_ideal, ba_placa, dqm_ideal, dqm_placa;
  wire [15:0] dq_ideal, dq_placa;
  wire [1:0] sdram_clk_unused, busy;

  sdram_controller_128 #(
      .CLK_FREQ_HZ(CLK_HZ), .POWERUP_DELAY_US(POWERUP_US),
      .READ_DELAY_CYCLES(0)
  ) ctrl_ideal (
      .clk(clk), .reset(reset),
      .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr),
      .req_wdata(req_wdata), .req_wmask(req_wmask),
      .req_ready(req_ready[0]), .done(done[0]), .rdata(rdata_ideal),
      .init_done(init_done[0]), .busy(busy[0]),
      .sdram_clk(sdram_clk_unused[0]), .sdram_cke(cke[0]), .sdram_csn(csn[0]),
      .sdram_rasn(rasn[0]), .sdram_casn(casn[0]), .sdram_wen(wen[0]),
      .sdram_a(a_ideal), .sdram_ba(ba_ideal), .sdram_dqm(dqm_ideal),
      .sdram_d(dq_ideal));

  sdram_model #(
      .POWERUP_DELAY_NS(POWERUP_US * 1000), .READ_DELAY_CYCLES(0)
  ) mem_ideal (
      .clk(clk), .cke(cke[0]), .csn(csn[0]), .rasn(rasn[0]), .casn(casn[0]),
      .wen(wen[0]), .a(a_ideal), .ba(ba_ideal), .dqm(dqm_ideal),
      .dq(dq_ideal));

  sdram_controller_128 #(
      .CLK_FREQ_HZ(CLK_HZ), .POWERUP_DELAY_US(POWERUP_US),
      .READ_DELAY_CYCLES(1)
  ) ctrl_placa (
      .clk(clk), .reset(reset),
      .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr),
      .req_wdata(req_wdata), .req_wmask(req_wmask),
      .req_ready(req_ready[1]), .done(done[1]), .rdata(rdata_placa),
      .init_done(init_done[1]), .busy(busy[1]),
      .sdram_clk(sdram_clk_unused[1]), .sdram_cke(cke[1]), .sdram_csn(csn[1]),
      .sdram_rasn(rasn[1]), .sdram_casn(casn[1]), .sdram_wen(wen[1]),
      .sdram_a(a_placa), .sdram_ba(ba_placa), .sdram_dqm(dqm_placa),
      .sdram_d(dq_placa));

  sdram_model #(
      .POWERUP_DELAY_NS(POWERUP_US * 1000), .READ_DELAY_CYCLES(1)
  ) mem_placa (
      .clk(clk), .cke(cke[1]), .csn(csn[1]), .rasn(rasn[1]), .casn(casn[1]),
      .wen(wen[1]), .a(a_placa), .ba(ba_placa), .dqm(dqm_placa),
      .dq(dq_placa));

  // Control negativo: el controlador sin margen de muestreo contra el modelo
  // de placa. TIENE que leer mal. Sin esto, el banco aprobaria igual aunque
  // alguien devolviera READ_DELAY_CYCLES a cero, que es el fallo que este
  // fichero existe para haber encontrado.
  wire [127:0] rdata_malo;
  wire ready_malo, done_malo, init_malo, busy_malo, clk_malo;
  wire cke_m, csn_m, rasn_m, casn_m, wen_m;
  wire [12:0] a_malo;
  wire [1:0] ba_malo, dqm_malo;
  wire [15:0] dq_malo;

  sdram_controller_128 #(
      .CLK_FREQ_HZ(CLK_HZ), .POWERUP_DELAY_US(POWERUP_US),
      .READ_DELAY_CYCLES(0)
  ) ctrl_malo (
      .clk(clk), .reset(reset),
      .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr),
      .req_wdata(req_wdata), .req_wmask(req_wmask),
      .req_ready(ready_malo), .done(done_malo), .rdata(rdata_malo),
      .init_done(init_malo), .busy(busy_malo),
      .sdram_clk(clk_malo), .sdram_cke(cke_m), .sdram_csn(csn_m),
      .sdram_rasn(rasn_m), .sdram_casn(casn_m), .sdram_wen(wen_m),
      .sdram_a(a_malo), .sdram_ba(ba_malo), .sdram_dqm(dqm_malo),
      .sdram_d(dq_malo));

  sdram_model #(
      .POWERUP_DELAY_NS(POWERUP_US * 1000), .READ_DELAY_CYCLES(1)
  ) mem_malo (
      .clk(clk), .cke(cke_m), .csn(csn_m), .rasn(rasn_m), .casn(casn_m),
      .wen(wen_m), .a(a_malo), .ba(ba_malo), .dqm(dqm_malo), .dq(dq_malo));

  // -----------------------------------------------------------------
  task check128;
    input [255:0] etiqueta;
    input [127:0] got;
    input [127:0] want;
    begin
      if (got !== want) begin
        $display("FALLO %0s:", etiqueta);
        $display("   leido    %032x", got);
        $display("   esperado %032x", want);
        errors = errors + 1;
      end
    end
  endtask

  task request;
    input write;
    input [23:0] address;
    input [127:0] wdata;
    input [15:0] wmask;
    begin
      @(negedge clk);
      while (!(req_ready[0] && req_ready[1] && ready_malo)) @(negedge clk);
      req_valid = 1'b1;
      req_write = write;
      req_addr = address;
      req_wdata = wdata;
      req_wmask = wmask;
      @(negedge clk);
      req_valid = 1'b0;
      // Los tres controladores tienen latencias de lectura distintas a
      // proposito, asi que sus `done` NO coinciden. Hay que engancharlos uno a
      // uno; esperar a que suban a la vez no termina nunca.
      visto_ideal = 1'b0;
      visto_placa = 1'b0;
      visto_malo = 1'b0;
      guard = 0;
      while (!(visto_ideal && visto_placa && visto_malo) && guard < 500) begin
        @(negedge clk);
        guard = guard + 1;
        if (done[0]) visto_ideal = 1'b1;
        if (done[1]) visto_placa = 1'b1;
        if (done_malo) visto_malo = 1'b1;
      end
      if (!(visto_ideal && visto_placa && visto_malo))
        $fatal(1, "algun controlador no respondio a %0s de %06x (%b%b%b)",
               write ? "la escritura" : "la lectura", address,
               visto_ideal, visto_placa, visto_malo);
    end
  endtask

  reg [127:0] patron;
  reg [127:0] esperado;

  initial begin
    repeat (4) @(negedge clk);
    reset = 0;

    guard = 0;
    while (!(init_done[0] && init_done[1]) && guard < 200_000) begin
      @(negedge clk);
      guard = guard + 1;
    end
    if (!(init_done[0] && init_done[1]))
      $fatal(1, "la inicializacion no termino");

    // ---------------------------------------------------------------
    // 1. Ida y vuelta de una rafaga entera. Cada beat lleva un valor
    //    distinto y reconocible: si el controlador se equivoca de ciclo,
    //    los beats salen corridos y se ve cual.
    // ---------------------------------------------------------------
    patron = 128'h0fee_0edd_0dcc_0cbb_0baa_0a99_0988_0877;
    request(1'b1, 24'h000000, patron, 16'hffff);
    request(1'b0, 24'h000000, 128'd0, 16'h0000);
    check128("rafaga completa, modelo de placa", rdata_placa, patron);
    check128("rafaga completa, modelo ideal", rdata_ideal, patron);

    // El control negativo, aqui y no al final: si el muestreo sin margen
    // acertara, todo lo demas de este banco no probaria nada.
    if (rdata_malo === patron) begin
      $display("FALLO: el controlador sin margen de muestreo acerta contra el");
      $display("       modelo de placa, asi que este banco no distingue nada.");
      errors = errors + 1;
    end else begin
      $display("Control negativo, como debe ser: sin margen de muestreo sale");
      $display("  %032x en vez de %032x", rdata_malo, patron);
    end

    // ---------------------------------------------------------------
    // 2. Otra direccion, en otro banco y otra fila, para que un error de
    //    decodificacion no se esconda detras de la direccion cero.
    // ---------------------------------------------------------------
    patron = 128'h1234_5678_9abc_def0_0fed_cba9_8765_4321;
    request(1'b1, 24'h001a08, patron, 16'hffff);
    request(1'b0, 24'h001a08, 128'd0, 16'h0000);
    check128("otro banco y otra fila", rdata_placa, patron);
    // Y la primera sigue donde estaba: la segunda no la piso.
    request(1'b0, 24'h000000, 128'd0, 16'h0000);
    check128("la rafaga anterior sigue intacta", rdata_placa,
             128'h0fee_0edd_0dcc_0cbb_0baa_0a99_0988_0877);

    // ---------------------------------------------------------------
    // 3. Mascara de byte. Es lo que permite al monitor escribir un byte
    //    sin destruir los otros quince, asi que tiene que ser exacta.
    // ---------------------------------------------------------------
    request(1'b1, 24'h000010, {8{16'haaaa}}, 16'hffff);
    // Solo el byte bajo del beat 0 y el alto del beat 7.
    request(1'b1, 24'h000010, {8{16'h5555}}, 16'b1000_0000_0000_0001);
    esperado = {8{16'haaaa}};
    esperado[7:0] = 8'h55;
    esperado[127:120] = 8'h55;
    request(1'b0, 24'h000010, 128'd0, 16'h0000);
    check128("mascara de byte", rdata_placa, esperado);

    // ---------------------------------------------------------------
    // 4. Mascara a cero: no debe cambiar nada.
    // ---------------------------------------------------------------
    request(1'b1, 24'h000010, {8{16'h0000}}, 16'h0000);
    request(1'b0, 24'h000010, 128'd0, 16'h0000);
    check128("mascara a cero no escribe nada", rdata_placa, esperado);

    // ---------------------------------------------------------------
    // 5. Sobrevivir a un refresco. El temporizador de refresco dispara
    //    cada REFRESH_PERIOD_CYCLES; con esperar de sobra basta.
    // ---------------------------------------------------------------
    repeat (2500) @(negedge clk);
    request(1'b0, 24'h000000, 128'd0, 16'h0000);
    check128("los datos sobreviven al refresco", rdata_placa,
             128'h0fee_0edd_0dcc_0cbb_0baa_0a99_0988_0877);

    // ---------------------------------------------------------------
    // El modelo ha ido comprobando tRCD, tRP, tRAS, tRC, tRFC y tMRD por
    // su cuenta, y la secuencia de arranque entera.
    // ---------------------------------------------------------------
    if (mem_placa.errors != 0) begin
      $display("FALLO: el modelo de SDRAM conto %0d violaciones JEDEC",
               mem_placa.errors);
      errors = errors + 1;
    end
    if (mem_ideal.errors != 0) begin
      $display("FALLO: el modelo ideal conto %0d violaciones JEDEC",
               mem_ideal.errors);
      errors = errors + 1;
    end

    // ---------------------------------------------------------------
    // Y el diagnostico, que es el motivo de instanciar los dos modelos:
    // si el controlador solo acierta con retardo cero, es que muestrea
    // un ciclo antes de lo que esta placa necesita.
    // ---------------------------------------------------------------
    $display("");

    if (errors != 0) $fatal(1, "%0d comprobaciones fallaron", errors);
    $display("PASS: sdram_controller_128");
    $finish;
  end
endmodule

`default_nettype wire
