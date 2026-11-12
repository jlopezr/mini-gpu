`timescale 1ns / 1ps
`default_nettype none

/*
 * Banco de dcache.v con 4 lineas (64 bytes), para forzar conflictos de indice
 * con direcciones cercanas, y 2 bits de epoca, para dar la vuelta (y obligar
 * al barrido) con tres invalidaciones.
 *
 * El banco hace de pipeline de cpu.v en pequeno, con sus dos etapas que tocan
 * la cache:
 *
 *   EX   el acceso cuya linea se leyo en el flanco anterior: la cache dice si
 *        acierta y da la palabra; si pasa a MEM se guardan.
 *   MEM  un LOAD que acerto ya tiene su dato; uno que fallo (o MMIO) lo pide
 *        y espera la respuesta; un STORE se pide siempre y termina al
 *        aceptarse (a SDRAM no se espera la respuesta: se descarta al llegar,
 *        como mem_drop). Mientras MEM espera, EX tambien, y la cache relee la
 *        linea de EX en cada flanco (`lookup_address`).
 *
 * Los accesos salen en orden de programa, con 0..2 ciclos entre ellos; cada
 * LOAD se compara con una copia de la memoria tomada en ese orden. Asi se
 * cubre lo delicado: un LOAD o un STORE justo detras de un STORE que acierta
 * (la linea adelantada desde la escritura de este ciclo o del anterior), un
 * LOAD detras del relleno de su misma linea, y STOREs seguidos a una linea.
 *
 * El adaptador es un modelo: acepta con `ready` aleatorio, escribe al aceptar
 * y contesta en orden tras 1..8 ciclos, las lecturas con la linea entera. De
 * vez en cuando la "CPU" se para: se vacia el pipeline y `invalidate` sube
 * unos ciclos (cada tres, una vuelta de epoca y un barrido).
 *
 * Al final, casos dirigidos para lo que el aleatorio podria no forzar: el
 * STORE que falla no trae la linea, y MMIO nunca acierta.
 */
module dcache_tb;
  reg clk = 0;
  always #5 clk = ~clk;

  localparam [31:0] MMIO_DATA = 32'h1234_5678;
  localparam integer N_RANDOM = 6000;

  reg reset = 1, invalidate = 0;

  // -- La cache ------------------------------------------------------------------
  wire [31:0] lookup_address;
  wire ex_hit;
  wire [31:0] ex_read_data;
  wire mem_advance, ex_load, ex_store;
  wire cpu_valid, cpu_ready, cpu_rvalid, cpu_error;
  wire [31:0] cpu_read_data;
  wire mem_valid, mem_ready;
  wire [31:0] mem_address, mem_write_data;
  wire [3:0] mem_write_enable;
  reg [31:0] mem_read_data = 0;
  reg [127:0] mem_read_line = 0;
  reg mem_rvalid = 0, mem_error = 0;
  wire hit_event, miss_event;

  // Lo que EX y MEM tienen (registros del banco).
  reg ex_v = 0, ex_is_load = 0;
  reg [31:0] ex_addr = 0, ex_data = 0, ex_expect = 0;
  reg [3:0] ex_wen = 0;
  reg m_v = 0, m_is_load = 0, m_hit = 0, m_sent = 0, m_got = 0;
  reg [31:0] m_addr = 0, m_data = 0, m_wdata = 0, m_expect = 0;
  reg [3:0] m_wen = 0;
  // El siguiente acceso, listo para entrar en EX.
  reg nx_v = 0, nx_is_load = 0;
  reg [31:0] nx_addr = 0, nx_data = 0, nx_expect = 0;
  reg [3:0] nx_wen = 0;

  wire m_in_sdram = m_addr[31:25] == 7'd0;
  wire m_needs = m_v && (m_is_load ? !(m_hit || m_got) : 1'b1);
  assign cpu_valid = m_needs && !m_sent;
  wire m_store_posted = cpu_valid && cpu_ready && !m_is_load && m_in_sdram;
  wire m_busy = m_v && (m_is_load ? !(m_hit || m_got) : !m_store_posted);
  wire advance = !m_busy;

  assign lookup_address = advance ? nx_addr : ex_addr;
  assign mem_advance = advance;
  assign ex_load = advance && ex_v && ex_is_load;
  assign ex_store = advance && ex_v && !ex_is_load;

  dcache #(.LINES(4), .INDEX_BITS(2), .EPOCH_BITS(2)) dut(
      .clk(clk), .reset(reset), .invalidate(invalidate),
      .lookup_address(lookup_address), .ex_hit(ex_hit), .ex_read_data(ex_read_data),
      .mem_advance(mem_advance), .ex_load(ex_load), .ex_store(ex_store),
      .ex_write_data(ex_data), .ex_write_enable(ex_is_load ? 4'b0000 : ex_wen),
      .cpu_valid(cpu_valid), .cpu_address(m_addr),
      .cpu_write_data(m_wdata), .cpu_write_enable(m_is_load ? 4'b0000 : m_wen),
      .cpu_ready(cpu_ready), .cpu_read_data(cpu_read_data),
      .cpu_rvalid(cpu_rvalid), .cpu_error(cpu_error),
      .mem_valid(mem_valid), .mem_address(mem_address),
      .mem_write_data(mem_write_data), .mem_write_enable(mem_write_enable),
      .mem_ready(mem_ready), .mem_read_data(mem_read_data),
      .mem_read_line(mem_read_line), .mem_rvalid(mem_rvalid),
      .mem_error(mem_error),
      .hit_event(hit_event), .miss_event(miss_event));

  // -- Modelo del adaptador -----------------------------------------------------------
  // 4 KiB de "SDRAM" por palabras, repetidos en todo el rango. MMIO contesta
  // con un valor fijo.
  reg [31:0] memory[0:1023];
  reg [31:0] q_data[0:15];
  reg [127:0] q_line[0:15];
  integer q_time[0:15];
  integer q_w = 0, q_r = 0, now = 0;
  integer seed = 32'hdcac4e;
  reg ready_rand = 1;
  assign mem_ready = ready_rand && (q_w - q_r < 8);
  integer mem_reads = 0;

  function [31:0] merge(input [31:0] old, input [31:0] data, input [3:0] wen);
    integer b;
    begin
      merge = old;
      for (b = 0; b < 4; b = b + 1) if (wen[b]) merge[b*8 +: 8] = data[b*8 +: 8];
    end
  endfunction

  always @(posedge clk) begin
    now = now + 1;
    mem_rvalid <= 1'b0;
    ready_rand <= ($random(seed) & 3) != 0;
    if (mem_valid && mem_ready) begin
      if (mem_address[31]) begin
        q_data[q_w % 16] = MMIO_DATA;
        q_line[q_w % 16] = 128'd0;
      end else begin
        if (|mem_write_enable)
          memory[mem_address[11:2]] = merge(memory[mem_address[11:2]], mem_write_data,
                                            mem_write_enable);
        else
          mem_reads = mem_reads + 1;
        q_data[q_w % 16] = memory[mem_address[11:2]];
        q_line[q_w % 16] = {memory[{mem_address[11:4], 2'd3}], memory[{mem_address[11:4], 2'd2}],
                            memory[{mem_address[11:4], 2'd1}], memory[{mem_address[11:4], 2'd0}]};
      end
      q_time[q_w % 16] = now + 1 + ($random(seed) & 7);
      if (q_w > q_r && q_time[q_w % 16] < q_time[(q_w - 1) % 16])
        q_time[q_w % 16] = q_time[(q_w - 1) % 16];
      q_w = q_w + 1;
    end
    if (q_r < q_w && q_time[q_r % 16] <= now) begin
      mem_read_data <= q_data[q_r % 16];
      mem_read_line <= q_line[q_r % 16];
      mem_rvalid <= 1'b1;
      q_r = q_r + 1;
    end
  end

  // -- La copia en orden de programa, y el generador ---------------------------------
  reg [31:0] shadow[0:1023];
  integer errors = 0, checked = 0, hits = 0, misses = 0;
  integer generated = 0, gap = 0, drop = 0;
  reg generating = 0;
  reg [31:0] a, d;
  reg [3:0] m;

  // Uno nuevo en nx_*, en orden de programa: la copia se actualiza ya.
  task new_access;
    begin
      a = 32'h0000_0100 | ($random(seed) & 32'hFC);
      d = $random(seed);
      case ($random(seed) & 3)
        0: m = 4'b1111;
        1: m = ($random(seed) & 1) ? 4'b1100 : 4'b0011;
        default: m = 4'b0001 << ($random(seed) & 3);
      endcase
      // No bloqueantes: la cache lee lookup_address en este mismo flanco.
      nx_v <= 1; nx_addr <= a; nx_data <= d; nx_wen <= m;
      if (($random(seed) & 31) == 0) begin
        nx_is_load <= 1; nx_addr <= 32'h8000_0000; nx_expect <= MMIO_DATA;
      end else if ($random(seed) & 1) begin
        nx_is_load <= 1; nx_expect <= shadow[a[11:2]];
      end else begin
        nx_is_load <= 0;
        shadow[a[11:2]] = merge(shadow[a[11:2]], d, m);
      end
      generated = generated + 1;
    end
  endtask

  // Cobertura: accesos que salen de EX con la linea adelantada desde la
  // escritura de este ciclo o desde W (la del anterior).
  integer fwd_now = 0, fwd_w = 0;
  always @(posedge clk) begin
    if (advance && ex_v && dut.data_write && dut.data_write_index == dut.ex_index)
      fwd_now = fwd_now + 1;
    else if (advance && ex_v && dut.w_data_valid && dut.w_index == dut.ex_index)
      fwd_w = fwd_w + 1;
  end

  always @(posedge clk) begin
    if (hit_event) hits = hits + 1;
    if (miss_event) misses = misses + 1;
    // Respuestas: la del acceso de MEM, o la de un STORE ya terminado.
    if (cpu_rvalid) begin
      if (drop > 0) drop = drop - 1;
      else if (m_v && m_sent && m_is_load) begin
        m_got <= 1'b1;
        m_data <= cpu_read_data;
      end
    end
    if (m_store_posted) drop = drop + 1;
    if (cpu_valid && cpu_ready) m_sent <= 1'b1;
    if (advance) begin
      // Lo que sale de MEM.
      if (m_v && m_is_load) begin
        checked = checked + 1;
        if (m_data !== m_expect) begin
          errors = errors + 1;
          if (errors < 10)
            $display("FALLO: LOAD %h = %h, esperaba %h (acierto %b)", m_addr, m_data,
                     m_expect, m_hit);
        end
      end
      // EX -> MEM: un acierto lleva su dato.
      m_v <= ex_v; m_addr <= ex_addr; m_wdata <= ex_data; m_wen <= ex_wen;
      m_is_load <= ex_is_load; m_expect <= ex_expect;
      m_hit <= ex_v && ex_is_load && ex_hit; m_data <= ex_read_data;
      m_sent <= 1'b0; m_got <= 1'b0;
      // Siguiente -> EX.
      ex_v <= nx_v; ex_addr <= nx_addr; ex_data <= nx_data; ex_wen <= nx_wen;
      ex_is_load <= nx_is_load; ex_expect <= nx_expect;
      nx_v <= 0;
      if (generating) begin
        if (gap > 0) gap = gap - 1;
        else begin
          new_access();
          gap = $random(seed) & 3;
          if (gap == 3) gap = 0;
        end
      end
    end
  end

  // Para y vacia el pipeline (lo que hace la CPU antes de que suba invalidate).
  task drain;
    integer t;
    begin
      generating = 0;
      t = 0;
      while ((nx_v || ex_v || m_v || drop > 0 || q_r != q_w) && t < 500) begin
        @(posedge clk); t = t + 1;
      end
      if (t >= 500) begin errors = errors + 1; $display("FALLO: el pipeline no se vacia"); end
      @(negedge clk);
    end
  endtask

  // Un acceso suelto, dirigido, y esperar a que salga.
  task single(input is_load, input [31:0] address, input [31:0] data);
    begin
      @(negedge clk);
      nx_v = 1; nx_is_load = is_load; nx_addr = address; nx_data = data; nx_wen = 4'b1111;
      nx_expect = data;
      if (!is_load && address[31:25] == 0) shadow[address[11:2]] = data;
      @(posedge clk); while (nx_v) @(posedge clk);
      drain();
    end
  endtask

  integer k, round;
  initial begin
    for (k = 0; k < 1024; k = k + 1) begin
      memory[k] = 32'hA000_0000 | (k << 2);
      shadow[k] = 32'hA000_0000 | (k << 2);
    end
    repeat (3) @(posedge clk);
    reset = 0;
    repeat (2) @(posedge clk);

    for (round = 0; round < 12; round = round + 1) begin
      @(negedge clk); generating = 1;
      while (generated < (round + 1) * N_RANDOM / 12) @(posedge clk);
      drain();
      // La "CPU" parada: invalidate unos ciclos (cada tres, la vuelta).
      invalidate = 1; repeat (2 + (round & 3)) @(negedge clk); invalidate = 0;
      repeat (2) @(negedge clk);
    end

    // Dirigidos. El STORE que falla no trae la linea: el LOAD despues falla.
    @(negedge clk); invalidate = 1; @(negedge clk); invalidate = 0; repeat (3) @(negedge clk);
    k = mem_reads;
    single(0, 32'h0000_0140, 32'h1919_1919);
    single(1, 32'h0000_0140, 32'h1919_1919);
    if (mem_reads - k != 1) begin
      errors = errors + 1;
      $display("FALLO: el STORE que falla trajo la linea (%0d lecturas)", mem_reads - k);
    end
    // Y MMIO nunca acierta: dos lecturas, las dos al adaptador.
    k = q_w;
    single(1, 32'h8000_0000, MMIO_DATA);
    single(1, 32'h8000_0000, MMIO_DATA);
    if (q_w - k != 2) begin
      errors = errors + 1; $display("FALLO: MMIO llego %0d veces al adaptador, esperaba 2", q_w - k);
    end

    $display("dcache: %0d LOAD comprobados, %0d aciertos, %0d fallos a SDRAM; adelantada %0d (este ciclo) y %0d (W)",
             checked, hits, misses, fwd_now, fwd_w);
    if (hits < checked / 8 || misses < 100 || fwd_now < 50 || fwd_w < 50) begin
      errors = errors + 1; $display("FALLO: mezcla de aciertos y fallos sospechosa");
    end
    if (errors == 0) $display("PASS: dcache");
    else             $display("FAIL: dcache (%0d errores)", errors);
    $finish;
  end

  initial begin
    #5_000_000;
    $display("FAIL: dcache (timeout)");
    $finish;
  end
endmodule

`default_nettype wire
