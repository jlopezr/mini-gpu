`timescale 1ns / 1ps
`default_nettype none

/*
 * Banco de cpu_dmem_adapter contra un modelo del puerto del arbitro que se
 * porta como el de verdad (fabric_fifo_bridge + memory_fabric_fifo_6 +
 * sdram_controller_128):
 *
 *   - una cola de PORT_DEPTH peticiones (`req_ready` = cola no llena);
 *   - se ejecutan EN ORDEN, una cada SERVICE_CYCLES como mucho, y la memoria
 *     cambia al ejecutarse (asi una lectura detras de una escritura a la misma
 *     linea ve lo escrito, como en el controlador: un slot por banco y los
 *     READ/WRITE en orden de llegada);
 *   - la respuesta llega LATENCY ciclos despues de aceptar, en orden.
 *
 * Pruebas de correccion (1-8): lo que el adaptador tiene que cumplir siempre.
 * Pruebas de rendimiento (P1-P2): que los volcados no esperen su respuesta. El
 * adaptador con una sola linea que espera cada volcado NO las pasa.
 */
module cpu_dmem_adapter_tb;
  reg clk = 0;
  always #5 clk = ~clk;

  localparam integer PORT_DEPTH = 4;
  localparam integer LATENCY = 16;
  localparam integer SERVICE_CYCLES = 3;
  localparam [31:0] MMIO_DATA = 32'h1234_5678;

  reg reset = 1, init_done = 1, cpu_halted = 0;

  reg dmem_valid = 0;
  reg [31:0] dmem_address = 0, dmem_write_data = 0;
  reg [3:0] dmem_write_enable = 0;
  wire dmem_ready, dmem_rvalid, dmem_error, wb_dirty;
  wire [31:0] dmem_read_data;
  wire [127:0] dmem_read_line;

  wire mmio_req, mmio_write;
  reg mmio_ack = 0, mmio_error = 0;
  wire [3:0] mmio_write_mask;
  wire [31:0] mmio_address, mmio_write_data;

  wire req_valid, req_write, rsp_ready;
  reg req_ready = 1'b1;
  wire [31:0] req_addr;
  wire [127:0] req_wdata;
  wire [15:0] req_wmask;
  reg rsp_valid = 0, rsp_error = 0;
  reg [127:0] rsp_rdata = 0;

  cpu_dmem_adapter dut(
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(cpu_halted),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data), .dmem_write_enable(dmem_write_enable),
      .dmem_ready(dmem_ready), .dmem_read_data(dmem_read_data),
      .dmem_read_line(dmem_read_line), .dmem_rvalid(dmem_rvalid), .dmem_error(dmem_error),
      .wb_dirty(wb_dirty),
      .mmio_req(mmio_req), .mmio_ack(mmio_ack), .mmio_write(mmio_write),
      .mmio_write_mask(mmio_write_mask), .mmio_address(mmio_address),
      .mmio_write_data(mmio_write_data), .mmio_read_data(MMIO_DATA),
      .mmio_error(mmio_error),
      .req_valid(req_valid), .req_ready(req_ready), .req_write(req_write),
      .req_addr(req_addr), .req_wdata(req_wdata), .req_wmask(req_wmask),
      .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata),
      .rsp_error(rsp_error),
      .merge_count(), .flush_count());

  // -- Modelo del puerto -------------------------------------------------------
  // 4 KiB de memoria por bytes, repetidos en todo el rango de la SDRAM.
  reg [7:0] memory[0:4095];
  integer i;

  // Cola de peticiones aceptadas: se ejecutan en orden y se contestan en orden.
  reg q_write[0:63];
  reg [31:0] q_addr[0:63];
  reg [127:0] q_wdata[0:63];
  reg [15:0] q_wmask[0:63];
  reg [127:0] q_rdata[0:63];
  integer q_ready_at[0:63];     // ciclo en que puede contestarse
  integer q_head = 0, q_exec = 0, q_tail = 0;
  integer cycle = 0, next_exec_at = 0;
  integer writes_in_flight = 0;  // aceptadas por el puerto, sin respuesta
  integer max_in_flight = 0;
  integer port_reads = 0, port_writes = 0;

  // `req_ready` sale de un registro, como en el puente (cola no llena). Si se
  // calculara de las variables que este bloque cambia en el mismo flanco, el
  // adaptador lo leeria ya cambiado y la misma peticion entraria dos veces.

  always @(posedge clk) begin
    cycle <= cycle + 1;
    rsp_valid <= 1'b0;
    // Ejecutar la siguiente, en orden y al ritmo de la memoria.
    if (q_exec < q_tail && cycle >= next_exec_at) begin
      if (q_write[q_exec % 64]) begin
        for (i = 0; i < 16; i = i + 1)
          if (q_wmask[q_exec % 64][i]) memory[{q_addr[q_exec % 64][11:4], 4'b0} + i] = q_wdata[q_exec % 64][i*8 +: 8];
      end else begin
        for (i = 0; i < 16; i = i + 1)
          q_rdata[q_exec % 64][i*8 +: 8] = memory[{q_addr[q_exec % 64][11:4], 4'b0} + i];
      end
      q_exec = q_exec + 1;
      next_exec_at = cycle + SERVICE_CYCLES;
    end
    // Contestar la mas antigua, ya ejecutada y con su latencia cumplida.
    if (q_head < q_exec && cycle >= q_ready_at[q_head % 64] && rsp_ready) begin
      rsp_valid <= 1'b1;
      rsp_error <= 1'b0;
      rsp_rdata <= q_write[q_head % 64] ? 128'd0 : q_rdata[q_head % 64];
      if (q_write[q_head % 64]) writes_in_flight = writes_in_flight - 1;
      q_head = q_head + 1;
    end
    // Aceptar.
    if (req_valid && req_ready) begin
      q_write[q_tail % 64] = req_write;
      q_addr[q_tail % 64] = req_addr;
      q_wdata[q_tail % 64] = req_wdata;
      q_wmask[q_tail % 64] = req_wmask;
      q_ready_at[q_tail % 64] = cycle + LATENCY;
      q_tail = q_tail + 1;
      if (req_write) begin
        port_writes = port_writes + 1;
        writes_in_flight = writes_in_flight + 1;
        if (writes_in_flight > max_in_flight) max_in_flight = writes_in_flight;
      end else begin
        port_reads = port_reads + 1;
      end
    end
    req_ready <= (q_tail - q_head) < PORT_DEPTH;
  end

  // -- Modelo MMIO -------------------------------------------------------------
  // Contesta a los 3 ciclos. Al empezar cada acceso comprueba que no queda
  // NINGUNA escritura sin confirmar: el MMIO no va por el puerto, asi que su
  // orden respecto a los volcados no lo da la cola.
  integer mmio_wait = 0;
  integer mmio_accesses = 0;
  reg mmio_req_prev = 0;
  integer errors = 0;
  always @(posedge clk) begin
    mmio_ack <= 1'b0;
    mmio_req_prev <= mmio_req;
    if (mmio_req && !mmio_req_prev) begin
      mmio_accesses = mmio_accesses + 1;
      if (writes_in_flight != 0 || dut.wb_valid) begin
        errors = errors + 1;
        $display("FALLO: MMIO con %0d escrituras sin confirmar (bufer %b)", writes_in_flight, dut.wb_valid);
      end
      mmio_wait <= 3;
    end
    if (mmio_wait > 1) mmio_wait <= mmio_wait - 1;
    if (mmio_wait == 1) begin mmio_wait <= 0; mmio_ack <= 1'b1; end
  end

  // -- Comprobacion de respuestas, en orden --------------------------------------
  reg [31:0] exp_data[0:255];
  reg exp_error[0:255];
  reg exp_check[0:255];
  integer exp_head = 0, exp_tail = 0;
  integer last_rvalid_cycle = 0;

  always @(posedge clk) begin
    if (dmem_rvalid) begin
      last_rvalid_cycle <= cycle;
      if (exp_head == exp_tail) begin
        errors = errors + 1;
        $display("FALLO: respuesta sin peticion (%h)", dmem_read_data);
      end else begin
        if (dmem_error !== exp_error[exp_head] ||
            (exp_check[exp_head] && dmem_read_data !== exp_data[exp_head])) begin
          errors = errors + 1;
          $display("FALLO: respuesta %0d = %h err=%b, esperaba %h err=%b", exp_head,
                   dmem_read_data, dmem_error, exp_data[exp_head], exp_error[exp_head]);
        end
        exp_head = exp_head + 1;
      end
    end
  end

  // -- La CPU de prueba ----------------------------------------------------------
  // Peticion: `valid` hasta ver `ready` en un flanco.
  task request(input [31:0] address, input [31:0] data, input [3:0] wen);
    integer t;
    begin
      @(negedge clk);
      dmem_address = address; dmem_write_data = data; dmem_write_enable = wen; dmem_valid = 1;
      @(posedge clk);
      t = 0;
      while (!dmem_ready && t < 500) begin @(posedge clk); t = t + 1; end
      if (!dmem_ready) begin
        errors = errors + 1;
        $display("FALLO: ready no sube (direccion %h, estado %0d)", address, dut.state);
        $display("FAIL: cpu_dmem_adapter (colgado)");
        $finish;
      end
      #1 dmem_valid = 0;
    end
  endtask

  task expect_response(input [31:0] data, input error, input check);
    begin
      exp_data[exp_tail] = data; exp_error[exp_tail] = error;
      exp_check[exp_tail] = check; exp_tail = exp_tail + 1;
    end
  endtask

  task wait_responses;
    integer t;
    begin
      t = 0;
      while (exp_head != exp_tail && t < 500) begin @(posedge clk); t = t + 1; end
      if (exp_head != exp_tail) begin
        errors = errors + 1;
        $display("FALLO: faltan %0d respuestas", exp_tail - exp_head);
        exp_head = exp_tail;
      end
      #1;
    end
  endtask

  // STORE como lo hace cpu.v a SDRAM: no espera la respuesta.
  task store(input [31:0] address, input [31:0] data, input [3:0] wen);
    begin
      expect_response(32'd0, 1'b0, 1'b0);
      request(address, data, wen);
    end
  endtask

  task load(input [31:0] address, input [31:0] expected, input expected_error);
    begin
      expect_response(expected, expected_error, !expected_error);
      request(address, 32'd0, 4'b0000);
      wait_responses;
    end
  endtask

  function [31:0] mem_word(input [31:0] a);
    mem_word = {memory[{a[11:2], 2'd3}], memory[{a[11:2], 2'd2}],
                memory[{a[11:2], 2'd1}], memory[{a[11:2], 2'd0}]};
  endfunction

  // Espera a que todo este en memoria: lo que hace el monitor tras parar.
  task halt_and_drain(input [8*24-1:0] name);
    integer t;
    begin
      @(negedge clk); cpu_halted = 1;
      @(negedge clk);
      t = 0;
      while (wb_dirty && t < 500) begin @(negedge clk); t = t + 1; end
      if (wb_dirty) begin errors = errors + 1; $display("FALLO %0s: wb_dirty no baja", name); end
      if (writes_in_flight != 0) begin
        errors = errors + 1;
        $display("FALLO %0s: wb_dirty bajo con %0d escrituras sin confirmar", name, writes_in_flight);
      end
      @(negedge clk); cpu_halted = 0;
    end
  endtask

  task check_word(input [31:0] a, input [31:0] expected, input [8*24-1:0] name);
    begin
      if (mem_word(a) !== expected) begin
        errors = errors + 1;
        $display("FALLO %0s: memoria[%h] = %h, esperaba %h", name, a, mem_word(a), expected);
      end
    end
  endtask

  integer n, start, elapsed, reads_before;

  initial begin
    for (i = 0; i < 4096; i = i + 1) memory[i] = i[7:0] ^ 8'h5A;
    repeat (3) @(posedge clk);
    reset = 0;
    repeat (2) @(posedge clk);

    // 1) Cuatro STORE a la misma linea se funden; cambiar de linea la vuelca.
    store(32'h0000_0100, 32'h1111_1111, 4'b1111);
    store(32'h0000_0104, 32'h2222_2222, 4'b1111);
    store(32'h0000_0108, 32'h3333_3333, 4'b1111);
    store(32'h0000_010C, 32'h4444_4444, 4'b0011);
    store(32'h0000_0200, 32'h5555_5555, 4'b1111);
    wait_responses;
    halt_and_drain("1 volcado");
    check_word(32'h100, 32'h1111_1111, "1");
    check_word(32'h10C, {mem_word(32'h10C) & 32'hFFFF_0000} | 32'h0000_4444, "1 mascara");
    check_word(32'h200, 32'h5555_5555, "1 linea nueva");

    // 2) LOAD a la linea que esta en el bufer: ve lo escrito.
    store(32'h0000_0300, 32'hAAAA_0001, 4'b1111);
    load(32'h0000_0300, 32'hAAAA_0001, 1'b0);
    if (dmem_read_line[31:0] !== 32'hAAAA_0001) begin
      errors = errors + 1; $display("FALLO 2: read_line = %h", dmem_read_line);
    end

    // 3) LOAD a una linea con su volcado en vuelo: ve lo escrito.
    store(32'h0000_0400, 32'hBBBB_0001, 4'b1111);
    store(32'h0000_0500, 32'hCCCC_0001, 4'b1111);   // vuelca la 0x400
    load(32'h0000_0400, 32'hBBBB_0001, 1'b0);
    load(32'h0000_0500, 32'hCCCC_0001, 1'b0);

    // 4) MMIO detras de escrituras: el modelo MMIO comprueba que no quede
    //    ninguna sin confirmar.
    store(32'h0000_0600, 32'hDDDD_0001, 4'b1111);
    store(32'h0000_0700, 32'hDDDD_0002, 4'b1111);
    store(32'h0000_0800, 32'hDDDD_0003, 4'b1111);
    expect_response(32'd0, 1'b0, 1'b0);
    request(32'h8020_0000, 32'h0000_0001, 4'b1111);   // como un SWAP
    wait_responses;
    if (mmio_accesses != 1) begin errors = errors + 1; $display("FALLO 4: %0d accesos MMIO", mmio_accesses); end
    check_word(32'h600, 32'hDDDD_0001, "4");
    check_word(32'h800, 32'hDDDD_0003, "4");

    // 4b) MMIO con el bufer ya vacio pero su volcado aun sin confirmar: una
    //     parada corta vuelca la linea y la CPU arranca enseguida con un MMIO.
    //     El atajo que pide el MMIO sin pasar por ST_DRAIN no puede mirar solo
    //     el bufer.
    store(32'h0000_0610, 32'hDDDD_0004, 4'b1111);
    wait_responses;
    @(negedge clk); cpu_halted = 1;
    repeat (2) @(negedge clk); cpu_halted = 0;
    expect_response(32'd0, 1'b0, 1'b0);
    request(32'h8020_0000, 32'h0000_0001, 4'b1111);
    wait_responses;
    check_word(32'h610, 32'hDDDD_0004, "4b");

    // 5) Lectura MMIO.
    expect_response(MMIO_DATA, 1'b0, 1'b1);
    request(32'h8020_0004, 32'd0, 4'b0000);
    wait_responses;

    // 6) Parar con escrituras en vuelo: wb_dirty no baja hasta que esten en
    //    memoria (si no, el monitor leeria lo de antes).
    for (n = 0; n < 6; n = n + 1) store(32'h0000_0900 + 16 * n, 32'hEEEE_0000 + n, 4'b1111);
    halt_and_drain("6 parada");
    for (n = 0; n < 6; n = n + 1) check_word(32'h900 + 16 * n, 32'hEEEE_0000 + n, "6");

    // 7) Errores: fuera de la SDRAM, y antes de init_done.
    load(32'h0400_0000, 32'd0, 1'b1);
    init_done = 0;
    load(32'h0000_0100, 32'd0, 1'b1);
    init_done = 1;

    // 8) Orden de respuestas mezclando STORE sin esperar y LOAD.
    store(32'h0000_0A00, 32'h0A0A_0001, 4'b1111);
    store(32'h0000_0B00, 32'h0B0B_0001, 4'b1111);
    expect_response(32'h0A0A_0001, 1'b0, 1'b1);
    request(32'h0000_0A00, 32'd0, 4'b0000);
    store(32'h0000_0C00, 32'h0C0C_0001, 4'b1111);
    expect_response(32'h0B0B_0001, 1'b0, 1'b1);
    request(32'h0000_0B00, 32'd0, 4'b0000);
    wait_responses;

    // ---- Rendimiento ----
    halt_and_drain("antes de P1");

    // P1) 32 STORE seguidos a direcciones consecutivas (8 lineas), uno por
    //     ciclo en cuanto se aceptan: con los volcados sin esperar respuesta,
    //     entran casi al ritmo de la CPU. Esperando cada volcado son unos
    //     7 x LATENCY ciclos de mas.
    @(negedge clk); start = cycle;
    for (n = 0; n < 32; n = n + 1) store(32'h0000_0D00 + 4 * n, 32'hF000_0000 + n, 4'b1111);
    elapsed = cycle - start;
    wait_responses;
    $display("P1: 32 STORE aceptados en %0d ciclos; hasta %0d escrituras en vuelo", elapsed, max_in_flight);
    if (elapsed > 32 * 2 + 3 * LATENCY) begin
      errors = errors + 1; $display("FALLO P1: los volcados esperan su respuesta");
    end
    if (max_in_flight < 2) begin
      errors = errors + 1; $display("FALLO P1: nunca hubo mas de una escritura en vuelo");
    end
    halt_and_drain("P1");
    for (n = 0; n < 32; n = n + 1) check_word(32'hD00 + 4 * n, 32'hF000_0000 + n, "P1");

    // P2) LOAD a la linea del bufer: el volcado y la lectura van seguidos,
    //     sin esperar la respuesta del volcado (una latencia, no dos).
    store(32'h0000_0E00, 32'h0E0E_0001, 4'b1111);
    @(negedge clk); start = cycle;
    load(32'h0000_0E00, 32'h0E0E_0001, 1'b0);
    elapsed = last_rvalid_cycle - start;
    $display("P2: LOAD a la linea del bufer contestado en %0d ciclos", elapsed);
    if (elapsed > LATENCY + SERVICE_CYCLES + 8) begin
      errors = errors + 1; $display("FALLO P2: la lectura espera a que acabe el volcado");
    end

    repeat (10) @(posedge clk);
    if (errors == 0) $display("PASS: cpu_dmem_adapter");
    else             $display("FAIL: cpu_dmem_adapter (%0d errores)", errors);
    $finish;
  end
endmodule

`default_nettype wire
