`timescale 1ns/1ps
`default_nettype none

/*
 * Banco de la combinacion de escrituras de cpu_dmem_adapter.
 *
 * El plan avisaba de que este es el paso mas delicado, y no por la combinacion
 * —que es facil— sino por los VACIADOS. Un bufer que se vacia cuando le apetece
 * es un error de coherencia esperando a ocurrir, y aqui el que lo sufriria es
 * el subsistema de video, que lee el framebuffer de la SDRAM por su cuenta y no
 * tiene forma de enterarse de que hay pixeles retenidos.
 *
 * Asi que la mitad de este banco son los tres vaciados forzados, cada uno con
 * su control negativo: no basta con ver que el dato acaba en memoria, hay que
 * ver que acaba ANTES de lo que no debe adelantarlo.
 *
 * El caso del SWAP es el mas fino. Comprobar «despues del SWAP la memoria tiene
 * los pixeles» no prueba nada, porque el vaciado podria haber ocurrido justo
 * despues y en la placa se veria un frame a medias igual. Lo que hay que
 * comprobar es el ORDEN: que la rafaga de escritura sale antes de que
 * `mmio_req` suba. Eso es lo que hace `orden_ok`.
 */
module write_combine_tb;
  reg clk = 0;
  reg reset = 1;
  reg init_done = 1;
  reg cpu_halted = 0;
  always #5 clk = ~clk;

  integer errors = 0;
  integer guard;
  integer i;

  // -- Lado CPU -------------------------------------------------------------
  reg dmem_valid = 0;
  reg [31:0] dmem_address = 0;
  reg [31:0] dmem_write_data = 0;
  reg [3:0] dmem_write_enable = 0;
  wire [31:0] dmem_read_data;
  wire dmem_ready, dmem_error;
  wire wb_dirty;
  wire [31:0] merges, flushes;

  // -- MMIO -----------------------------------------------------------------
  wire mmio_req, mmio_write;
  wire [3:0] mmio_mask;
  wire [11:0] mmio_addr;   // la pagina MMIO entera
  wire [31:0] mmio_wdata;
  reg mmio_ack = 0;
  reg [31:0] mmio_rdata = 32'hcafe_0000;

  // -- Memoria --------------------------------------------------------------
  wire req_valid, req_ready, req_write;
  wire [31:0] req_addr;
  wire [127:0] req_wdata;
  wire [15:0] req_wmask;
  wire rsp_valid, rsp_ready;
  wire [127:0] rsp_rdata;

  cpu_dmem_adapter dut (
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(cpu_halted),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data),
      .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(dmem_error), .wb_dirty(wb_dirty),
      .mmio_req(mmio_req), .mmio_ack(mmio_ack), .mmio_write(mmio_write),
      .mmio_write_mask(mmio_mask), .mmio_address(mmio_addr),
      .mmio_write_data(mmio_wdata), .mmio_read_data(mmio_rdata),
      .req_valid(req_valid), .req_ready(req_ready), .req_write(req_write),
      .req_addr(req_addr), .req_wdata(req_wdata), .req_wmask(req_wmask),
      .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata),
      .rsp_error(1'b0),
      .merge_count(merges), .flush_count(flushes));

  // El MMIO se confirma dos ciclos despues de pedirlo, como hace mmio_mux.
  reg [1:0] mmio_delay;
  always @(posedge clk) begin
    mmio_ack <= 1'b0;
    if (reset) mmio_delay <= 2'd0;
    else if (mmio_req && !mmio_ack) begin
      if (mmio_delay == 2'd1) begin
        mmio_ack <= 1'b1;
        mmio_delay <= 2'd0;
      end else begin
        mmio_delay <= mmio_delay + 1'b1;
      end
    end
  end

  // Memoria de 16 bytes por linea, con mascara. Guarda ademas la ultima rafaga
  // vista, para poder mirarla desde las pruebas.
  // 4096 lineas: el indice tiene que cubrir todas las direcciones que usa el
  // banco. Con 64 y un indice de seis bits, 0x400 y 0x000 caian en la misma
  // entrada y las comprobaciones leian X.
  localparam integer LINES = 4096;
  reg [127:0] mem[0:LINES-1];
  reg [3:0] mem_count;
  reg mem_busy;
  reg [31:0] held_addr;
  reg held_write;
  reg [127:0] held_wdata;
  reg [15:0] held_wmask;
  reg mem_ready_r, mem_rsp;
  reg [127:0] mem_rdata;
  integer n_bursts;
  reg [127:0] last_burst_data;
  reg [15:0] last_burst_mask;
  reg [31:0] last_burst_addr;

  assign req_ready = mem_ready_r;
  assign rsp_valid = mem_rsp;
  assign rsp_rdata = mem_rdata;

  integer k;
  initial begin
    for (i = 0; i < LINES; i = i + 1) mem[i] = 128'd0;
    mem_ready_r = 1'b1;
    mem_rsp = 1'b0;
    mem_busy = 1'b0;
    mem_count = 0;
    mem_rdata = 128'd0;
    n_bursts = 0;
    last_burst_data = 128'd0;
    last_burst_mask = 16'd0;
    last_burst_addr = 32'd0;
  end

  always @(posedge clk) begin
    mem_rsp <= 1'b0;
    if (reset) begin
      mem_busy <= 1'b0;
      mem_ready_r <= 1'b1;
      mem_count <= 0;
    end else if (!mem_busy) begin
      if (req_valid && mem_ready_r) begin
        held_addr <= req_addr;
        held_write <= req_write;
        held_wdata <= req_wdata;
        held_wmask <= req_wmask;
        mem_busy <= 1'b1;
        mem_ready_r <= 1'b0;
        mem_count <= 0;
        n_bursts = n_bursts + 1;
        if (req_write) begin
          last_burst_addr = req_addr;
          last_burst_data = req_wdata;
          last_burst_mask = req_wmask;
        end
      end
    end else if (mem_count >= 4) begin
      if (held_write) begin
        for (k = 0; k < 16; k = k + 1)
          if (held_wmask[k])
            mem[held_addr[15:4]][k*8 +: 8] <= held_wdata[k*8 +: 8];
      end else begin
        mem_rdata <= mem[held_addr[15:4]];
      end
      mem_rsp <= 1'b1;
      mem_busy <= 1'b0;
      mem_ready_r <= 1'b1;
    end else begin
      mem_count <= mem_count + 1'b1;
    end
  end

  // -- Vigilancia del ORDEN entre el volcado y el MMIO ----------------------
  // `orden_ok` se pone a cero si `mmio_req` sube teniendo el bufer sucio. Es
  // la comprobacion que de verdad cubre el caso del SWAP.
  reg orden_ok;
  initial orden_ok = 1'b1;
  always @(posedge clk)
    if (!reset && mmio_req && wb_dirty) orden_ok = 1'b0;

  // -------------------------------------------------------------------------
  task store;
    input [31:0] a;
    input [31:0] d;
    input [3:0] en;
    begin
      @(negedge clk);
      dmem_address = a;
      dmem_write_data = d;
      dmem_write_enable = en;
      dmem_valid = 1'b1;
      guard = 0;
      while (!dmem_ready && guard < 500) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (!dmem_ready) $fatal(1, "el STORE a %08x no recibio respuesta", a);
      dmem_valid = 1'b0;
      dmem_write_enable = 4'b0000;
      @(negedge clk);
    end
  endtask

  reg [31:0] leido;
  task load;
    input [31:0] a;
    begin
      @(negedge clk);
      dmem_address = a;
      dmem_write_enable = 4'b0000;
      dmem_valid = 1'b1;
      guard = 0;
      while (!dmem_ready && guard < 500) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (!dmem_ready) $fatal(1, "el LOAD de %08x no recibio respuesta", a);
      leido = dmem_read_data;
      dmem_valid = 1'b0;
      @(negedge clk);
    end
  endtask

  task check;
    input [255:0] etiqueta;
    input integer got;
    input integer want;
    begin
      if (got != want) begin
        $display("FALLO %0s: %0d, esperado %0d", etiqueta, got, want);
        errors = errors + 1;
      end
    end
  endtask

  integer b0;

  initial begin
    repeat (4) @(negedge clk);
    reset = 0;
    @(negedge clk);

    // ---------------------------------------------------------------------
    // 1. Cuatro STORE consecutivos con +4 caben en una linea. Es el bucle
    //    interior de swap_demo_fast, y tiene que dar TRES fusiones y CERO
    //    rafagas: mientras no se salga de la linea, la memoria no se toca.
    // ---------------------------------------------------------------------
    b0 = n_bursts;
    store(32'h0000_0100, 32'h1111_1111, 4'b1111);
    store(32'h0000_0104, 32'h2222_2222, 4'b1111);
    store(32'h0000_0108, 32'h3333_3333, 4'b1111);
    store(32'h0000_010c, 32'h4444_4444, 4'b1111);
    check("fusiones en una linea", merges, 3);
    check("rafagas mientras no se sale de la linea", n_bursts - b0, 0);
    if (!wb_dirty) begin
      $display("FALLO: el bufer deberia estar sucio");
      errors = errors + 1;
    end
    $display("Cuatro STORE con +4: %0d fusiones, %0d rafagas", merges,
             n_bursts - b0);

    // ---------------------------------------------------------------------
    // 2. Al salirse de la linea se vuelca, y la rafaga lleva las CUATRO
    //    palabras con la mascara entera. Si el volcado se hiciera palabra a
    //    palabra, o perdiera alguna, se ve aqui.
    // ---------------------------------------------------------------------
    b0 = n_bursts;
    store(32'h0000_0110, 32'h5555_5555, 4'b1111);
    check("rafagas al cambiar de linea", n_bursts - b0, 1);
    if (last_burst_addr !== 32'h0000_0100) begin
      $display("FALLO: se volco la linea %08x, esperada 00000100",
               last_burst_addr);
      errors = errors + 1;
    end
    if (last_burst_data !== 128'h4444_4444_3333_3333_2222_2222_1111_1111) begin
      $display("FALLO: la rafaga volcada lleva %032x", last_burst_data);
      errors = errors + 1;
    end
    if (last_burst_mask !== 16'hffff) begin
      $display("FALLO: la mascara volcada es %04x, esperada ffff",
               last_burst_mask);
      errors = errors + 1;
    end

    // ---------------------------------------------------------------------
    // 3. VACIADO 1: el acceso MMIO. Y lo que se comprueba no es que el dato
    //    acabe en memoria, sino que la rafaga sale ANTES de que `mmio_req`
    //    suba. Con el SWAP, el orden es justo lo que importa: vaciar despues
    //    daria un frame a medias igual.
    // ---------------------------------------------------------------------
    orden_ok = 1'b1;
    // El primer store cambia de linea y vuelca la anterior; eso no es lo que
    // se mide aqui, asi que la cuenta empieza despues.
    store(32'h0000_0200, 32'haaaa_aaaa, 4'b1111);
    b0 = n_bursts;
    store(32'h0000_0204, 32'hbbbb_bbbb, 4'b1111);
    // Escribir SWAP.
    store(32'h8000_0008, 32'h0000_0001, 4'b1111);
    check("rafagas provocadas por el acceso MMIO", n_bursts - b0, 1);
    if (!orden_ok) begin
      $display("FALLO: `mmio_req` subio con el bufer todavia sucio: el SWAP");
      $display("       podria adelantar a los pixeles del frame");
      errors = errors + 1;
    end
    if (mem[32'h20] !== 128'h0000_0000_0000_0000_bbbb_bbbb_aaaa_aaaa) begin
      $display("FALLO: la linea 0x200 quedo como %032x", mem[32'h20]);
      errors = errors + 1;
    end
    if (wb_dirty) begin
      $display("FALLO: el bufer sigue sucio tras el MMIO");
      errors = errors + 1;
    end
    $display("Vaciado por MMIO: la rafaga sale antes de que suba mmio_req");

    // ---------------------------------------------------------------------
    // 4. VACIADO 3: una lectura que cae en la linea guardada. Sin vaciar
    //    antes, devolveria el dato viejo de la SDRAM.
    // ---------------------------------------------------------------------
    store(32'h0000_0300, 32'hdead_beef, 4'b1111);
    b0 = n_bursts;
    load(32'h0000_0300);
    if (leido !== 32'hdead_beef) begin
      $display("FALLO: la lectura de su propia escritura dio %08x", leido);
      errors = errors + 1;
    end
    // Una rafaga de volcado y otra de lectura.
    check("rafagas de una lectura sobre la linea guardada", n_bursts - b0, 2);
    $display("Lectura sobre la linea guardada: vuelca y luego lee");

    // ---------------------------------------------------------------------
    // 5. Y el control negativo del caso anterior: una lectura a OTRA linea
    //    no vacia nada. Si vaciara siempre, la combinacion no serviria en un
    //    bucle que mezcle LOAD y STORE.
    // ---------------------------------------------------------------------
    store(32'h0000_0400, 32'h0f0f_0f0f, 4'b1111);
    b0 = n_bursts;
    load(32'h0000_0500);
    check("rafagas de una lectura a otra linea", n_bursts - b0, 1);
    if (!wb_dirty) begin
      $display("FALLO: una lectura a otra linea vacio el bufer sin necesidad");
      errors = errors + 1;
    end

    // ---------------------------------------------------------------------
    // 6. VACIADO 2: al parar la CPU. Y lo que importa es que `wb_dirty` no
    //    baja hasta que la rafaga ha terminado, porque el adaptador del
    //    monitor lo usa para saber cuando puede leer memoria de verdad.
    // ---------------------------------------------------------------------
    b0 = n_bursts;
    @(negedge clk);
    cpu_halted = 1'b1;
    guard = 0;
    while (wb_dirty && guard < 200) begin
      @(negedge clk);
      guard = guard + 1;
    end
    if (wb_dirty) begin
      $display("FALLO: el bufer no se vacio al parar la CPU");
      errors = errors + 1;
    end
    check("rafagas provocadas por el halt", n_bursts - b0, 1);
    // Y la memoria ya tiene el dato cuando `wb_dirty` baja, que es la
    // condicion que el monitor espera.
    if (mem[32'h40] !== 128'h0000_0000_0000_0000_0000_0000_0f0f_0f0f) begin
      $display("FALLO: al bajar wb_dirty la memoria tiene %032x", mem[32'h40]);
      errors = errors + 1;
    end
    $display("Vaciado por halt: wb_dirty baja con el dato ya en memoria");
    cpu_halted = 1'b0;
    @(negedge clk);

    // ---------------------------------------------------------------------
    // 7. Mascaras parciales. Dos escrituras de media palabra en la misma
    //    linea tienen que fundirse sin pisarse, y la mascara volcada solo
    //    puede marcar los bytes escritos: los otros doce sobreviven.
    // ---------------------------------------------------------------------
    mem[32'h50] = 128'hffff_ffff_ffff_ffff_ffff_ffff_ffff_ffff;
    store(32'h0000_0500, 32'h0000_1234, 4'b0011);
    store(32'h0000_0508, 32'h5678_0000, 4'b1100);
    store(32'h0000_0600, 32'h0000_0000, 4'b1111);   // fuerza el volcado
    if (last_burst_mask !== 16'b0000_1100_0000_0011) begin
      $display("FALLO: la mascara parcial salio %016b", last_burst_mask);
      errors = errors + 1;
    end
    // 0x508 cae en la palabra 2 de la linea, y la mascara 1100 marca sus dos
    // bytes altos: el 5678 va a los bytes 10 y 11, no a los 6 y 7.
    if (mem[32'h50] !== 128'hffff_ffff_5678_ffff_ffff_ffff_ffff_1234) begin
      $display("FALLO: la fusion parcial dejo la linea en %032x", mem[32'h50]);
      errors = errors + 1;
    end
    $display("Mascaras parciales: solo se escriben los bytes marcados");

    if (!orden_ok) begin
      $display("FALLO: hubo algun MMIO con el bufer sucio en todo el banco");
      errors = errors + 1;
    end

    if (errors != 0) $fatal(1, "%0d comprobaciones fallaron", errors);
    $display("");
    $display("PASS: write_combine");
    $finish;
  end
endmodule

`default_nettype wire
