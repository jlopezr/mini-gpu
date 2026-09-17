`timescale 1ns/1ps
`default_nettype none

/*
 * Banco de los accesos de 8 y 16 bits.
 *
 * Monta el mismo sistema que cpu_burst_system_tb.v --CPU, bufer de
 * instrucciones, adaptador de datos, adaptador de monitor, mux de MMIO,
 * memory_fabric_4, sdram_controller_128 y el modelo de SDRAM-- porque las
 * escrituras parciales solo se pueden dar por buenas de extremo a extremo: la
 * CPU pone la mascara de byte, el adaptador la desplaza dentro de la linea de
 * 16 bytes, el fabric la transporta y el controlador la convierte en DQM. Un
 * banco con memoria ideal no distingue una mascara correcta de una que escribe
 * la palabra entera, que es justo el fallo que se busca.
 *
 * Cubre tres cosas:
 *
 *   1. Que STOREB y STOREH tocan SOLO los bytes que les tocan. Se comprueba
 *      releyendo por el monitor los vecinos que debian quedar intactos.
 *   2. Que las seis cargas extienden como deben: LOADB/LOADH con signo,
 *      LOADUB/LOADUH con ceros, y que el byte elegido depende de los dos bits
 *      bajos de la direccion.
 *   3. Que una media palabra en direccion impar y una palabra desalineada
 *      paran la CPU con ERROR_MEMORY_ACCESS y dejan el PC en la instruccion
 *      culpable, no en la siguiente.
 */
module subword_ls_tb;
  localparam integer CLK_HZ = 100_000_000;
  localparam integer POWERUP_US = 2;

  localparam [31:0] BASE = 32'h0001_0000;
  localparam [7:0] ERROR_MEMORY_ACCESS = 8'h02;

  // Opcodes, en el mapa de 1.isa/propuesta-v0.2.md §7.
  localparam [5:0] OP_ORI = 6'h13;
  localparam [5:0] OP_MOVI = 6'h10;
  localparam [5:0] OP_LOAD = 6'h15;
  localparam [5:0] OP_STORE = 6'h16;
  localparam [5:0] OP_MOVHI = 6'h17;
  localparam [5:0] OP_LOADB = 6'h18;
  localparam [5:0] OP_LOADUB = 6'h19;
  localparam [5:0] OP_STOREB = 6'h1a;
  localparam [5:0] OP_LOADH = 6'h1b;
  localparam [5:0] OP_LOADUH = 6'h1c;
  localparam [5:0] OP_STOREH = 6'h1d;
  localparam [31:0] INSTR_HALT = 32'hfc00_0000;

  reg clk = 0;
  reg reset = 1;
  always #5 clk = ~clk;

  integer errors = 0;
  integer guard;
  integer i;

  // -- CPU ------------------------------------------------------------------
  reg run_request = 0;
  wire halted, cpu_error, instruction_retired;
  wire [7:0] cpu_error_code;
  wire imem_valid, imem_ready;
  wire [31:0] imem_address, imem_read_data;
  wire dmem_valid, dmem_ready, dmem_error;
  wire [31:0] dmem_address, dmem_write_data, dmem_read_data;
  wire [3:0] dmem_write_enable;
  reg [4:0] debug_register_address = 0;
  wire [31:0] debug_register_data, debug_pc;

  cpu cpu_i (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halt_request(1'b0), .step_request(1'b0), .halted(halted),
      .error(cpu_error), .error_code(cpu_error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid), .imem_address(imem_address),
      .imem_read_data(imem_read_data), .imem_ready(imem_ready),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data), .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(dmem_error),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data), .debug_pc(debug_pc));

  // -- Monitor --------------------------------------------------------------
  reg [31:0] mon_address = 0;
  reg [7:0] mon_write_data = 0;
  reg mon_write_enable = 0, mon_read_enable = 0;
  wire [7:0] mon_read_data;
  wire [31:0] mon_read_word;   // la misma lectura sin trocear
  wire mon_ready, mon_error;

  // -- Puertos del arbitro --------------------------------------------------
  wire p0_valid, p0_ready, p0_write, p0_rsp_valid, p0_rsp_ready, p0_rsp_error;
  wire [31:0] p0_addr;
  wire [127:0] p0_wdata, p0_rsp_rdata;
  wire [15:0] p0_wmask;

  wire p1_valid, p1_ready, p1_write, p1_rsp_valid, p1_rsp_ready, p1_rsp_error;
  wire [31:0] p1_addr;
  wire [127:0] p1_wdata, p1_rsp_rdata;
  wire [15:0] p1_wmask;

  wire p3_valid, p3_ready, p3_write, p3_rsp_valid, p3_rsp_ready, p3_rsp_error;
  wire [31:0] p3_addr;
  wire [127:0] p3_wdata, p3_rsp_rdata;
  wire [15:0] p3_wmask;

  // -- MMIO -----------------------------------------------------------------
  wire mon_mmio_req, mon_mmio_ack, mon_mmio_write;
  wire [3:0] mon_mmio_mask;
  wire [4:0] mon_mmio_addr;
  wire [31:0] mon_mmio_wdata;
  wire cpu_mmio_req, cpu_mmio_ack, cpu_mmio_write;
  wire [3:0] cpu_mmio_mask;
  wire [4:0] cpu_mmio_addr;
  wire [31:0] cpu_mmio_wdata;
  wire mmio_select, mmio_write;
  wire [3:0] mmio_write_mask;
  wire [4:0] mmio_address;
  wire [31:0] mmio_write_data;
  wire [31:0] ibuf_hits, ibuf_misses;
  wire wb_dirty;
  wire [31:0] wb_merges, wb_flushes;

  reg [31:0] mmio_regs[0:3];
  wire [31:0] mmio_read_data = mmio_regs[mmio_address[3:2]];
  always @(posedge clk) begin
    if (reset) begin
      mmio_regs[0] <= 32'h0100_0000;
      mmio_regs[1] <= 32'h0102_5800;
      mmio_regs[2] <= 32'd0;
      mmio_regs[3] <= 32'd0;
    end else if (mmio_select && mmio_write) begin
      for (i = 0; i < 4; i = i + 1)
        if (mmio_write_mask[i])
          mmio_regs[mmio_address[4:2]][i*8 +: 8] <= mmio_write_data[i*8 +: 8];
    end
  end

  // -- SDRAM ----------------------------------------------------------------
  wire s_req_valid, s_req_ready, s_req_write, s_done;
  wire [23:0] s_req_addr;
  wire [127:0] s_req_wdata, s_rdata;
  wire [15:0] s_req_wmask;
  wire init_done, ctrl_busy, fabric_busy, sdram_clk_unused;
  wire cke, csn, rasn, casn, wen;
  wire [12:0] sdram_a;
  wire [1:0] sdram_ba, sdram_dqm;
  wire [15:0] sdram_dq;

  cpu_dmem_adapter dmem_adapter_i (
      .clk(clk), .reset(reset), .init_done(init_done),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data),
      .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(dmem_error), .cpu_halted(halted),
      .wb_dirty(wb_dirty), .merge_count(wb_merges), .flush_count(wb_flushes),
      .mmio_req(cpu_mmio_req), .mmio_ack(cpu_mmio_ack),
      .mmio_write(cpu_mmio_write), .mmio_write_mask(cpu_mmio_mask),
      .mmio_address(cpu_mmio_addr), .mmio_write_data(cpu_mmio_wdata),
      .mmio_read_data(mmio_read_data), .mmio_error(1'b0),
      .req_valid(p0_valid), .req_ready(p0_ready), .req_write(p0_write),
      .req_addr(p0_addr), .req_wdata(p0_wdata), .req_wmask(p0_wmask),
      .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
      .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));

  instruction_buffer #(.LINES(4), .INDEX_BITS(2)) ibuf_i (
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(halted),
      .cpu_imem_valid(imem_valid), .cpu_imem_address(imem_address),
      .cpu_imem_read_data(imem_read_data), .cpu_imem_ready(imem_ready),
      .req_valid(p1_valid), .req_ready(p1_ready), .req_write(p1_write),
      .req_addr(p1_addr), .req_wdata(p1_wdata), .req_wmask(p1_wmask),
      .rsp_valid(p1_rsp_valid), .rsp_ready(p1_rsp_ready),
      .rsp_rdata(p1_rsp_rdata), .rsp_error(p1_rsp_error),
      .hit_count(ibuf_hits), .miss_count(ibuf_misses));

  monitor_mem_adapter_128 monitor_adapter_i (
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(halted),
      .wb_dirty(wb_dirty),
      .mem_address(mon_address), .mem_write_data(mon_write_data),
      .mem_write_enable(mon_write_enable),
      .mem_write_word(32'd0), .mem_write_word_enable(1'b0), .mem_read_enable(mon_read_enable),
      .mem_read_data(mon_read_data), .mem_read_word(mon_read_word), .mem_ready(mon_ready),
      .mem_error(mon_error),
      .mmio_req(mon_mmio_req), .mmio_ack(mon_mmio_ack),
      .mmio_write(mon_mmio_write), .mmio_write_mask(mon_mmio_mask),
      .mmio_address(mon_mmio_addr), .mmio_write_data(mon_mmio_wdata),
      .mmio_read_data(mmio_read_data), .mmio_error(1'b0),
      .req_valid(p3_valid), .req_ready(p3_ready), .req_write(p3_write),
      .req_addr(p3_addr), .req_wdata(p3_wdata), .req_wmask(p3_wmask),
      .rsp_valid(p3_rsp_valid), .rsp_ready(p3_rsp_ready),
      .rsp_rdata(p3_rsp_rdata), .rsp_error(p3_rsp_error));

  mmio_mux mmio_mux_i (
      .clk(clk), .reset(reset),
      .a_req(mon_mmio_req), .a_ack(mon_mmio_ack), .a_write(mon_mmio_write),
      .a_write_mask(mon_mmio_mask), .a_address(mon_mmio_addr),
      .a_write_data(mon_mmio_wdata),
      .b_req(cpu_mmio_req), .b_ack(cpu_mmio_ack), .b_write(cpu_mmio_write),
      .b_write_mask(cpu_mmio_mask), .b_address(cpu_mmio_addr),
      .b_write_data(cpu_mmio_wdata),
      .select(mmio_select), .write(mmio_write),
      .write_mask(mmio_write_mask), .address(mmio_address),
      .write_data(mmio_write_data));

  memory_fabric_4 fabric_i (
      .clk(clk), .reset(reset),
      .p0_req_valid(p0_valid), .p0_req_ready(p0_ready),
      .p0_req_write(p0_write), .p0_req_addr(p0_addr),
      .p0_req_wdata(p0_wdata), .p0_req_wmask(p0_wmask),
      .p0_rsp_valid(p0_rsp_valid), .p0_rsp_ready(p0_rsp_ready),
      .p0_rsp_rdata(p0_rsp_rdata), .p0_rsp_error(p0_rsp_error),

      .p1_req_valid(p1_valid), .p1_req_ready(p1_ready),
      .p1_req_write(p1_write), .p1_req_addr(p1_addr),
      .p1_req_wdata(p1_wdata), .p1_req_wmask(p1_wmask),
      .p1_rsp_valid(p1_rsp_valid), .p1_rsp_ready(p1_rsp_ready),
      .p1_rsp_rdata(p1_rsp_rdata), .p1_rsp_error(p1_rsp_error),

      .p2_req_valid(1'b0), .p2_req_ready(), .p2_req_write(1'b0),
      .p2_req_addr(32'd0), .p2_req_wdata(128'd0), .p2_req_wmask(16'd0),
      .p2_urgent(1'b0), .p2_rsp_valid(), .p2_rsp_ready(1'b1),
      .p2_rsp_rdata(), .p2_rsp_error(),

      .p3_req_valid(p3_valid), .p3_req_ready(p3_ready),
      .p3_req_write(p3_write), .p3_req_addr(p3_addr),
      .p3_req_wdata(p3_wdata), .p3_req_wmask(p3_wmask),
      .p3_rsp_valid(p3_rsp_valid), .p3_rsp_ready(p3_rsp_ready),
      .p3_rsp_rdata(p3_rsp_rdata), .p3_rsp_error(p3_rsp_error),

      .sdram_req_valid(s_req_valid), .sdram_req_ready(s_req_ready),
      .sdram_req_write(s_req_write), .sdram_req_addr(s_req_addr),
      .sdram_req_wdata(s_req_wdata), .sdram_req_wmask(s_req_wmask),
      .sdram_done(s_done), .sdram_rdata(s_rdata), .busy(fabric_busy));

  sdram_controller_128 #(
      .CLK_FREQ_HZ(CLK_HZ), .POWERUP_DELAY_US(POWERUP_US)
  ) ctrl (
      .clk(clk), .reset(reset),
      .req_valid(s_req_valid), .req_write(s_req_write), .req_addr(s_req_addr),
      .req_wdata(s_req_wdata), .req_wmask(s_req_wmask),
      .req_ready(s_req_ready), .done(s_done), .rdata(s_rdata),
      .init_done(init_done), .busy(ctrl_busy),
      .sdram_clk(sdram_clk_unused), .sdram_cke(cke), .sdram_csn(csn),
      .sdram_rasn(rasn), .sdram_casn(casn), .sdram_wen(wen),
      .sdram_a(sdram_a), .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm),
      .sdram_d(sdram_dq));

  sdram_model #(
      .POWERUP_DELAY_NS(POWERUP_US * 1000), .READ_DELAY_CYCLES(1)
  ) mem (
      .clk(clk), .cke(cke), .csn(csn), .rasn(rasn), .casn(casn), .wen(wen),
      .a(sdram_a), .ba(sdram_ba), .dqm(sdram_dqm), .dq(sdram_dq));

  // -- Utilidades del banco -------------------------------------------------

  // Todas las instrucciones que prueba este banco son de formato I:
  // {opcode, Rx, Ra, imm16}. En las escrituras, Rx es el registro fuente.
  function [31:0] enc_i;
    input [5:0] op;
    input [4:0] rx;
    input [4:0] ra;
    input [15:0] imm;
    begin
      enc_i = {op, rx, ra, imm};
    end
  endfunction

  task mon_write;
    input [31:0] address;
    input [7:0] value;
    begin
      @(negedge clk);
      mon_address = address;
      mon_write_data = value;
      mon_write_enable = 1'b1;
      @(negedge clk);
      mon_write_enable = 1'b0;
      guard = 0;
      while (!mon_ready && guard < 2000) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (!mon_ready) $fatal(1, "el monitor no respondio al escribir %08x", address);
      if (mon_error) $fatal(1, "error al escribir %08x desde el monitor", address);
      @(negedge clk);
    end
  endtask

  reg [7:0] leido;
  task mon_read;
    input [31:0] address;
    begin
      @(negedge clk);
      mon_address = address;
      mon_read_enable = 1'b1;
      @(negedge clk);
      mon_read_enable = 1'b0;
      guard = 0;
      while (!mon_ready && guard < 2000) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (!mon_ready) $fatal(1, "el monitor no respondio al leer %08x", address);
      if (mon_error) $fatal(1, "error al leer %08x desde el monitor", address);
      leido = mon_read_data;
      @(negedge clk);
    end
  endtask

  task mon_write_word;
    input [31:0] address;
    input [31:0] value;
    begin
      mon_write(address + 0, value[7:0]);
      mon_write(address + 1, value[15:8]);
      mon_write(address + 2, value[23:16]);
      mon_write(address + 3, value[31:24]);
    end
  endtask

  task expect_byte;
    input [31:0] address;
    input [7:0] expected;
    input [255:0] nombre;
    begin
      mon_read(address);
      if (leido !== expected) begin
        $display("FALLO: %0s: en %08x se leyo %02x, esperado %02x",
                 nombre, address, leido, expected);
        errors = errors + 1;
      end
    end
  endtask

  task expect_register;
    input [4:0] address;
    input [31:0] expected;
    input [255:0] nombre;
    begin
      debug_register_address = address;
      repeat (2) @(posedge clk);
      #1;
      if (debug_register_data !== expected) begin
        $display("FALLO: %0s: R%0d = %08x, esperado %08x",
                 nombre, address, debug_register_data, expected);
        errors = errors + 1;
      end
    end
  endtask

  integer longitud;
  reg [31:0] programa[0:63];

  // Reset, espera de init, carga del programa por el monitor y arranque.
  task cargar_y_ejecutar;
    begin
      @(negedge clk);
      reset = 1;
      repeat (4) @(negedge clk);
      reset = 0;
      guard = 0;
      while (!init_done && guard < 200_000) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (!init_done) $fatal(1, "la inicializacion no termino");

      for (i = 0; i < longitud; i = i + 1)
        mon_write_word(i * 4, programa[i]);

      @(negedge clk); run_request = 1;
      @(negedge clk); run_request = 0;

      guard = 0;
      while (!halted && guard < 500_000) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (!halted) $fatal(1, "la CPU no llego a parar");
      // `pc_restore` resta los cuatro bytes ya dentro de STATE_HALTED, un ciclo
      // despues de que suba `halted`. Sin esta espera se leeria el PC de la
      // instruccion siguiente y las trampas de alineacion darian falso fallo.
      repeat (3) @(negedge clk);
    end
  endtask

  // -- Programa 1: escrituras y lecturas parciales --------------------------
  task programa_principal;
    begin
      // R6 = 0x00010000, la base del area de datos.
      programa[0]  = enc_i(OP_MOVHI,  5'd6,  5'd0,  16'h0001);
      // Sembrar la palabra base con 0x12345678 para poder ver que STOREB y
      // STOREH respetan los bytes que no les corresponden.
      programa[1]  = enc_i(OP_MOVHI,  5'd1,  5'd0,  16'h1234);
      programa[2]  = enc_i(OP_ORI,    5'd1,  5'd1,  16'h5678);
      programa[3]  = enc_i(OP_STORE,  5'd1,  5'd6,  16'h0000);
      // STOREB en el byte 1: 0x12345678 -> 0x1234AA78.
      programa[4]  = enc_i(OP_MOVI,   5'd2,  5'd0,  16'h00aa);
      programa[5]  = enc_i(OP_STOREB, 5'd2,  5'd6,  16'h0001);
      // STOREH en la mitad alta: 0x1234AA78 -> 0xBEEFAA78. El inmediato de MOVI
      // se extiende con signo, pero STOREH solo mira los 16 bits bajos.
      programa[6]  = enc_i(OP_MOVI,   5'd3,  5'd0,  16'hbeef);
      programa[7]  = enc_i(OP_STOREH, 5'd3,  5'd6,  16'h0002);

      // Las ocho cargas sobre esa misma palabra.
      programa[8]  = enc_i(OP_LOADUB, 5'd10, 5'd6,  16'h0001);  // 0x000000AA
      programa[9]  = enc_i(OP_LOADB,  5'd11, 5'd6,  16'h0001);  // 0xFFFFFFAA
      programa[10] = enc_i(OP_LOADUB, 5'd12, 5'd6,  16'h0000);  // 0x00000078
      programa[11] = enc_i(OP_LOADB,  5'd13, 5'd6,  16'h0000);  // 0x00000078
      programa[12] = enc_i(OP_LOADUH, 5'd14, 5'd6,  16'h0002);  // 0x0000BEEF
      programa[13] = enc_i(OP_LOADH,  5'd15, 5'd6,  16'h0002);  // 0xFFFFBEEF
      programa[14] = enc_i(OP_LOADUH, 5'd16, 5'd6,  16'h0000);  // 0x0000AA78
      programa[15] = enc_i(OP_LOADH,  5'd17, 5'd6,  16'h0000);  // 0xFFFFAA78
      programa[16] = enc_i(OP_LOAD,   5'd18, 5'd6,  16'h0000);  // 0xBEEFAA78

      // Cuatro STOREB seguidos sobre la palabra siguiente: el unico modo de ver
      // que la mascara se desplaza bien en los cuatro carriles. Ademas caen en
      // la misma linea de 16 bytes, asi que ejercitan la combinacion de
      // escrituras del adaptador.
      programa[17] = enc_i(OP_MOVI,   5'd20, 5'd0,  16'h0011);
      programa[18] = enc_i(OP_STOREB, 5'd20, 5'd6,  16'h0004);
      programa[19] = enc_i(OP_MOVI,   5'd21, 5'd0,  16'h0022);
      programa[20] = enc_i(OP_STOREB, 5'd21, 5'd6,  16'h0005);
      programa[21] = enc_i(OP_MOVI,   5'd22, 5'd0,  16'h0033);
      programa[22] = enc_i(OP_STOREB, 5'd22, 5'd6,  16'h0006);
      programa[23] = enc_i(OP_MOVI,   5'd23, 5'd0,  16'h0044);
      programa[24] = enc_i(OP_STOREB, 5'd23, 5'd6,  16'h0007);
      programa[25] = enc_i(OP_LOAD,   5'd24, 5'd6,  16'h0004);  // 0x44332211

      // Y una media palabra en la mitad baja de una tercera palabra, para
      // comprobar que no arrastra la mitad alta.
      programa[26] = enc_i(OP_MOVHI,  5'd25, 5'd0,  16'hffff);
      programa[27] = enc_i(OP_ORI,    5'd25, 5'd25, 16'hffff);
      programa[28] = enc_i(OP_STORE,  5'd25, 5'd6,  16'h0008);
      programa[29] = enc_i(OP_MOVI,   5'd26, 5'd0,  16'h0000);
      programa[30] = enc_i(OP_STOREH, 5'd26, 5'd6,  16'h0008);
      programa[31] = enc_i(OP_LOAD,   5'd27, 5'd6,  16'h0008);  // 0xFFFF0000

      programa[32] = INSTR_HALT;
      longitud = 33;

      cargar_y_ejecutar;

      if (cpu_error) begin
        $display("FALLO: la CPU paro con error %02x en pc=%08x",
                 cpu_error_code, debug_pc);
        errors = errors + 1;
      end

      // Extension de signo y de ceros.
      expect_register(5'd10, 32'h0000_00aa, "LOADUB byte 1");
      expect_register(5'd11, 32'hffff_ffaa, "LOADB byte 1");
      expect_register(5'd12, 32'h0000_0078, "LOADUB byte 0");
      expect_register(5'd13, 32'h0000_0078, "LOADB byte 0");
      expect_register(5'd14, 32'h0000_beef, "LOADUH mitad alta");
      expect_register(5'd15, 32'hffff_beef, "LOADH mitad alta");
      expect_register(5'd16, 32'h0000_aa78, "LOADUH mitad baja");
      expect_register(5'd17, 32'hffff_aa78, "LOADH mitad baja");
      expect_register(5'd18, 32'hbeef_aa78, "LOAD tras las parciales");
      expect_register(5'd24, 32'h4433_2211, "LOAD tras cuatro STOREB");
      expect_register(5'd27, 32'hffff_0000, "LOAD tras STOREH bajo");

      // Y lo mismo visto desde la memoria, que es donde se notaria una mascara
      // de mas: si STOREB hubiera escrito la palabra entera, el byte 0 valdria
      // 0xAA en vez de 0x78.
      expect_byte(BASE + 0, 8'h78, "STOREB no toco el byte 0");
      expect_byte(BASE + 1, 8'haa, "STOREB escribio el byte 1");
      expect_byte(BASE + 2, 8'hef, "STOREH byte bajo");
      expect_byte(BASE + 3, 8'hbe, "STOREH byte alto");
      expect_byte(BASE + 4, 8'h11, "STOREB carril 0");
      expect_byte(BASE + 5, 8'h22, "STOREB carril 1");
      expect_byte(BASE + 6, 8'h33, "STOREB carril 2");
      expect_byte(BASE + 7, 8'h44, "STOREB carril 3");
      expect_byte(BASE + 8, 8'h00, "STOREH bajo, byte 0");
      expect_byte(BASE + 9, 8'h00, "STOREH bajo, byte 1");
      expect_byte(BASE + 10, 8'hff, "STOREH bajo no toco el byte 2");
      expect_byte(BASE + 11, 8'hff, "STOREH bajo no toco el byte 3");
    end
  endtask

  // -- Programas 2..4: trampas de alineacion --------------------------------
  //
  // Cada uno es un programa de tres instrucciones cuyo acceso, el segundo,
  // esta desalineado. La CPU tiene que parar con ERROR_MEMORY_ACCESS y dejar
  // el PC en 4: en la instruccion culpable, no en la siguiente.
  task trampa_alineacion;
    input [5:0] op;
    input [4:0] rx;
    input [15:0] offset;
    input [255:0] nombre;
    begin
      programa[0] = enc_i(OP_MOVHI, 5'd6, 5'd0, 16'h0001);
      programa[1] = enc_i(op, rx, 5'd6, offset);
      programa[2] = INSTR_HALT;
      longitud = 3;

      cargar_y_ejecutar;

      if (!cpu_error) begin
        $display("FALLO: %0s no provoco error", nombre);
        errors = errors + 1;
      end else if (cpu_error_code !== ERROR_MEMORY_ACCESS) begin
        $display("FALLO: %0s dio error %02x, esperado %02x",
                 nombre, cpu_error_code, ERROR_MEMORY_ACCESS);
        errors = errors + 1;
      end else if (debug_pc !== 32'd4) begin
        $display("FALLO: %0s dejo el PC en %08x, esperado 00000004",
                 nombre, debug_pc);
        errors = errors + 1;
      end
    end
  endtask

  initial begin
    $dumpvars(0, subword_ls_tb);

    programa_principal;

    trampa_alineacion(OP_LOADH,  5'd7, 16'h0001, "LOADH impar");
    trampa_alineacion(OP_LOADUH, 5'd7, 16'h0003, "LOADUH impar");
    trampa_alineacion(OP_STOREH, 5'd7, 16'h0001, "STOREH impar");
    trampa_alineacion(OP_LOAD,   5'd7, 16'h0002, "LOAD desalineado");
    trampa_alineacion(OP_STORE,  5'd7, 16'h0001, "STORE desalineado");

    // Un byte en direccion impar NO es un error: es el caso normal de LOADB.
    programa[0] = enc_i(OP_MOVHI,  5'd6, 5'd0, 16'h0001);
    programa[1] = enc_i(OP_LOADUB, 5'd7, 5'd6, 16'h0003);
    programa[2] = INSTR_HALT;
    longitud = 3;
    cargar_y_ejecutar;
    if (cpu_error) begin
      $display("FALLO: LOADB en direccion impar provoco error %02x",
               cpu_error_code);
      errors = errors + 1;
    end

    $display("");
    if (errors == 0) $display("subword_ls_tb: OK");
    else $display("subword_ls_tb: %0d FALLOS", errors);
    if (errors != 0) $fatal(1, "el banco fallo");
    $finish;
  end

  initial begin
    #20_000_000;
    $fatal(1, "timeout global del banco");
  end

endmodule

`default_nettype wire
