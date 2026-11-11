`timescale 1ns / 1ps
`default_nettype none

/*
 * Banco de dcache.v con 4 lineas (64 bytes), para forzar conflictos de indice
 * con direcciones cercanas, y 2 bits de epoca, para dar la vuelta (y obligar
 * al barrido) con tres invalidaciones. El adaptador es un modelo: una peticion cada vez,
 * escrituras contestadas al ciclo siguiente (como al fundirse en el bufer de
 * combinacion) salvo en la zona "lenta" (bit 12 de la direccion, como un
 * volcado), y lecturas a los READ_CYCLES ciclos con la palabra y la linea.
 *
 * La CPU de prueba se porta como cpu.v: un LOAD espera su respuesta; un STORE a
 * SDRAM no, y su respuesta se descarta al llegar. Cada respuesta se compara
 * contra la que tocaba en ese orden.
 */
module dcache_tb;
  reg clk = 0;
  always #5 clk = ~clk;

  localparam integer READ_CYCLES = 6;
  localparam integer SLOW_CYCLES = 12;
  localparam [31:0] MMIO_DATA = 32'h1234_5678;

  reg reset = 1, invalidate = 0;

  reg cpu_valid = 0;
  reg [31:0] cpu_address = 0, cpu_write_data = 0;
  reg [3:0] cpu_write_enable = 0;
  wire cpu_ready, cpu_rvalid, cpu_error;
  wire [31:0] cpu_read_data;

  wire mem_valid;
  wire [31:0] mem_address, mem_write_data;
  wire [3:0] mem_write_enable;
  wire mem_ready;
  reg [31:0] mem_read_data = 0;
  reg [127:0] mem_read_line = 0;
  reg mem_rvalid = 0, mem_error = 0;
  wire hit_event, miss_event;

  // EPOCH_BITS = 2: solo tres epocas validas, para dar la vuelta enseguida.
  dcache #(.LINES(4), .INDEX_BITS(2), .EPOCH_BITS(2)) dut(
      .clk(clk), .reset(reset), .invalidate(invalidate),
      .cpu_valid(cpu_valid), .cpu_address(cpu_address),
      .cpu_write_data(cpu_write_data), .cpu_write_enable(cpu_write_enable),
      .cpu_ready(cpu_ready), .cpu_read_data(cpu_read_data),
      .cpu_rvalid(cpu_rvalid), .cpu_error(cpu_error),
      .mem_valid(mem_valid), .mem_address(mem_address),
      .mem_write_data(mem_write_data), .mem_write_enable(mem_write_enable),
      .mem_ready(mem_ready), .mem_read_data(mem_read_data),
      .mem_read_line(mem_read_line), .mem_rvalid(mem_rvalid),
      .mem_error(mem_error),
      .hit_event(hit_event), .miss_event(miss_event));

  // -- Modelo del adaptador -----------------------------------------------------
  // 4 KiB de "SDRAM" por palabras, repetidos en todo el rango (basta para el
  // banco). Lo que no es SDRAM ni MMIO contesta con error.
  reg [31:0] memory[0:1023];
  integer busy = 0;
  reg [31:0] req_address;
  reg req_write;
  assign mem_ready = (busy == 0);

  integer mem_reads = 0, mem_writes = 0;

  function [31:0] merge(input [31:0] old, input [31:0] data, input [3:0] wen);
    integer b;
    begin
      merge = old;
      for (b = 0; b < 4; b = b + 1) if (wen[b]) merge[b*8 +: 8] = data[b*8 +: 8];
    end
  endfunction

  always @(posedge clk) begin
    mem_rvalid <= 1'b0;
    mem_error <= 1'b0;
    if (busy > 1) busy <= busy - 1;
    if (busy == 1) begin
      busy <= 0;
      mem_rvalid <= 1'b1;
      if (req_address[31]) begin
        mem_read_data <= req_write ? 32'd0 : MMIO_DATA;
      end else if (req_address[31:25] != 0) begin
        mem_error <= 1'b1;
      end else if (req_write) begin
        // Un dato reconocible: si una respuesta de STORE se cruza con la de un
        // LOAD, el LOAD lo ve.
        mem_read_data <= 32'hDEAD_57E0;
      end else begin
        mem_read_data <= memory[req_address[11:2]];
        mem_read_line <= {memory[{req_address[11:4], 2'd3}], memory[{req_address[11:4], 2'd2}],
                          memory[{req_address[11:4], 2'd1}], memory[{req_address[11:4], 2'd0}]};
      end
    end
    if (mem_valid && mem_ready) begin
      req_address <= mem_address;
      req_write <= |mem_write_enable;
      if (|mem_write_enable) begin
        mem_writes = mem_writes + 1;
        if (mem_address[31:25] == 0)
          memory[mem_address[11:2]] <= merge(memory[mem_address[11:2]], mem_write_data, mem_write_enable);
        busy <= mem_address[12] ? SLOW_CYCLES : 1;
      end else begin
        mem_reads = mem_reads + 1;
        busy <= READ_CYCLES;
      end
    end
  end

  // -- Comprobacion de respuestas, en orden --------------------------------------
  // Cada peticion apunta lo que espera; cada `rvalid` consume la siguiente.
  reg [31:0] exp_data[0:63];
  reg exp_error[0:63];
  reg exp_check[0:63];         // 0 = STORE o error: no se mira el dato
  integer exp_head = 0, exp_tail = 0;
  integer errors = 0;
  integer cycle = 0;
  integer last_rvalid_cycle = 0;

  always @(posedge clk) begin
    cycle <= cycle + 1;
    if (cpu_rvalid) begin
      last_rvalid_cycle <= cycle;
      if (exp_head == exp_tail) begin
        errors = errors + 1;
        $display("FALLO: respuesta sin peticion (dato %h)", cpu_read_data);
      end else begin
        if (cpu_error !== exp_error[exp_head] ||
            (exp_check[exp_head] && cpu_read_data !== exp_data[exp_head])) begin
          errors = errors + 1;
          $display("FALLO: respuesta %0d = %h err=%b, esperaba %h err=%b", exp_head,
                   cpu_read_data, cpu_error, exp_data[exp_head], exp_error[exp_head]);
        end
        exp_head = exp_head + 1;
      end
    end
  end

  // -- La CPU de prueba ------------------------------------------------------------
  task request(input [31:0] address, input [31:0] data, input [3:0] wen);
    begin
      @(negedge clk);
      cpu_address = address; cpu_write_data = data; cpu_write_enable = wen; cpu_valid = 1;
      @(posedge clk);
      while (!cpu_ready) @(posedge clk);
      #1 cpu_valid = 0;
    end
  endtask

  task wait_responses;
    integer t;
    begin
      t = 0;
      while (exp_head != exp_tail && t < 200) begin @(posedge clk); t = t + 1; end
      if (exp_head != exp_tail) begin
        errors = errors + 1;
        $display("FALLO: faltan %0d respuestas", exp_tail - exp_head);
        exp_head = exp_tail;
      end
      #1;
    end
  endtask

  task load(input [31:0] address, input [31:0] expected, input expected_error);
    begin
      exp_data[exp_tail] = expected; exp_error[exp_tail] = expected_error;
      exp_check[exp_tail] = !expected_error; exp_tail = exp_tail + 1;
      request(address, 0, 4'b0000);
    end
  endtask

  // STORE que no espera, como el de cpu.v a SDRAM.
  task store(input [31:0] address, input [31:0] data, input [3:0] wen);
    begin
      exp_data[exp_tail] = 0; exp_error[exp_tail] = 0;
      exp_check[exp_tail] = 0; exp_tail = exp_tail + 1;
      request(address, data, wen);
    end
  endtask

  // LOAD que espera su respuesta y cuenta las lecturas que llegaron al adaptador.
  task load_wait(input [31:0] address, input [31:0] expected, input expected_error,
                 input integer expected_mem_reads, input [8*24-1:0] name);
    integer reads_before;
    begin
      reads_before = mem_reads;
      load(address, expected, expected_error);
      wait_responses;
      if (mem_reads - reads_before != expected_mem_reads) begin
        errors = errors + 1;
        $display("FALLO %0s: %0d lecturas al adaptador, esperaba %0d", name,
                 mem_reads - reads_before, expected_mem_reads);
      end
    end
  endtask

  integer k, start, hits_before, misses_before;
  reg [1:0] epoch_before;
  integer hits = 0, misses = 0;
  always @(posedge clk) begin
    if (hit_event) hits = hits + 1;
    if (miss_event) misses = misses + 1;
  end

  initial begin
    for (k = 0; k < 1024; k = k + 1) memory[k] = 32'hA000_0000 | (k << 2);
    repeat (3) @(posedge clk);
    reset = 0;
    repeat (2) @(posedge clk);

    // 1) Fallo y despues aciertos en la misma linea, cualquier palabra.
    load_wait(32'h0000_0100, 32'hA000_0100, 0, 1, "1 fallo");
    load_wait(32'h0000_0100, 32'hA000_0100, 0, 0, "1 acierto");
    load_wait(32'h0000_010C, 32'hA000_010C, 0, 0, "1 otra palabra");
    load_wait(32'h0000_0105, 32'hA000_0104, 0, 0, "1 byte");   // la CPU elige el byte

    // 2) El acierto contesta dos ciclos despues de aceptar.
    @(negedge clk); start = cycle;
    load(32'h0000_0104, 32'hA000_0104, 0);
    wait_responses;
    if (last_rvalid_cycle - start > 3) begin
      errors = errors + 1;
      $display("FALLO 2: acierto en %0d ciclos", last_rvalid_cycle - start);
    end

    // 3) Un STORE pasa al adaptador e invalida la linea: el LOAD siguiente falla
    //    y trae el dato nuevo. El LOAD va pegado detras, como en la CPU.
    store(32'h0000_0108, 32'h0000_00EE, 4'b0001);
    load_wait(32'h0000_0108, 32'hA000_01EE, 0, 1, "3 tras store");
    load_wait(32'h0000_0100, 32'hA000_0100, 0, 0, "3 linea de nuevo");

    // 4) Conflicto de indice: 0x100 y 0x140 caen en la misma de las 4 lineas.
    load_wait(32'h0000_0140, 32'hA000_0140, 0, 1, "4 expulsa");
    load_wait(32'h0000_0100, 32'hA000_0100, 0, 1, "4 vuelve a fallar");
    load_wait(32'h0000_0110, 32'hA000_0110, 0, 1, "4 otro indice");
    load_wait(32'h0000_0100, 32'hA000_0100, 0, 0, "4 sigue ahi");

    // 5) MMIO pasa directo y no se guarda.
    load_wait(32'h8101_0000, MMIO_DATA, 0, 1, "5 mmio");
    load_wait(32'h8101_0000, MMIO_DATA, 0, 1, "5 mmio otra vez");

    // 6) Fuera de rango: error, y no se guarda.
    load_wait(32'h0400_0000, 32'd0, 1, 1, "6 error");
    load_wait(32'h0400_0000, 32'd0, 1, 1, "6 error otra vez");
    load_wait(32'h0000_0100, 32'hA000_0100, 0, 0, "6 la buena sigue");

    // 7) `invalidate` borra todo.
    @(negedge clk); invalidate = 1; @(negedge clk); invalidate = 0;
    load_wait(32'h0000_0100, 32'hA000_0100, 0, 1, "7 tras invalidar");

    // 8) Orden: un STORE lento (como un volcado) y detras un LOAD que acierta
    //    en OTRA linea. La respuesta del STORE tiene que salir antes.
    load_wait(32'h0000_0110, 32'hA000_0110, 0, 1, "8 preparar");
    store(32'h0000_1000, 32'h1111_1111, 4'b1111);
    load_wait(32'h0000_0110, 32'hA000_0110, 0, 0, "8 acierto detras");

    // 9) Varios STORE seguidos y un LOAD a la primera linea: falla y ve todos.
    store(32'h0000_0100, 32'h0000_0001, 4'b1111);
    store(32'h0000_0104, 32'h0000_0002, 4'b1111);
    store(32'h0000_0100, 32'h0000_0003, 4'b0001);
    load_wait(32'h0000_0100, 32'h0000_0003, 0, 1, "9 tras varios store");
    load_wait(32'h0000_0104, 32'h0000_0002, 0, 0, "9 misma linea");

    // 10) `invalidate` en mitad de un fallo: contesta, pero no guarda la linea.
    //     Que no coincida con una vuelta: el barrido lo taparia todo.
    if (dut.epoch == 2'd3) begin
      @(negedge clk); invalidate = 1; @(negedge clk); invalidate = 0;
    end
    load(32'h0000_0120, 32'hA000_0120, 0);
    repeat (3) @(posedge clk);
    @(negedge clk); invalidate = 1; @(negedge clk); invalidate = 0;
    wait_responses;
    load_wait(32'h0000_0120, 32'hA000_0120, 0, 1, "10 no guardada");

    // 11) Contadores de rendimiento: un pulso por consulta.
    hits_before = hits; misses_before = misses;
    load_wait(32'h0000_0124, 32'hA000_0124, 0, 0, "11 acierto");
    load_wait(32'h0000_0200, 32'hA000_0200, 0, 1, "11 fallo");
    if (hits - hits_before != 1 || misses - misses_before != 1) begin
      errors = errors + 1;
      $display("FALLO 11: %0d aciertos y %0d fallos", hits - hits_before, misses - misses_before);
    end

    // 12) `reset` invalida: la memoria cambia por detras (como cuando escribe
    //     el monitor) y tras el reset se ve el dato nuevo.
    load_wait(32'h0000_0130, 32'hA000_0130, 0, 1, "12 preparar");
    load_wait(32'h0000_0130, 32'hA000_0130, 0, 0, "12 en cache");
    memory[32'h130 >> 2] = 32'h0000_1212;
    @(negedge clk); reset = 1; repeat (2) @(negedge clk); reset = 0;
    load_wait(32'h0000_0130, 32'h0000_1212, 0, 1, "12 tras reset");

    // 13) La vuelta de la epoca. Con dos bits, tras tres invalidaciones la
    //     epoca vuelve a la de la linea guardada: sin el barrido, la linea
    //     resucitaria con el dato viejo. Se prueba desde las tres epocas.
    memory[32'h110 >> 2] = 32'h0000_1300;
    @(negedge clk); invalidate = 1; @(negedge clk); invalidate = 0;
    load_wait(32'h0000_0110, 32'h0000_1300, 0, 1, "13 preparar");
    for (k = 1; k <= 3; k = k + 1) begin
      load_wait(32'h0000_0110, 32'h0000_1300 + k - 1, 0, 0, "13 en cache");
      memory[32'h110 >> 2] = 32'h0000_1300 + k;
      repeat (3) begin
        @(negedge clk); invalidate = 1; @(negedge clk); invalidate = 0;
      end
      load_wait(32'h0000_0110, 32'h0000_1300 + k, 0, 1, "13 tras la vuelta");
    end

    // 14) `invalidate` sostenido muchos ciclos (la CPU parada) cuenta como UNA
    //     invalidacion: no puede dar vueltas sin parar.
    load_wait(32'h0000_0150, 32'hA000_0150, 0, 1, "14 preparar");
    epoch_before = dut.epoch;
    @(negedge clk); invalidate = 1; repeat (42) @(negedge clk); invalidate = 0;   // 42: multiplo de 3, por si contara cada ciclo
    if (dut.epoch !== (epoch_before == 2'd3 ? 2'd1 : epoch_before + 2'd1)) begin
      errors = errors + 1;
      $display("FALLO 14: la epoca paso de %0d a %0d", epoch_before, dut.epoch);
    end
    load_wait(32'h0000_0150, 32'hA000_0150, 0, 1, "14 fallo tras invalidar");
    load_wait(32'h0000_0150, 32'hA000_0150, 0, 0, "14 y luego acierta");

    repeat (20) @(posedge clk);
    wait_responses;

    if (errors == 0) $display("PASS: dcache");
    else             $display("FAIL: dcache (%0d errores)", errors);
    $finish;
  end
endmodule

`default_nettype wire
