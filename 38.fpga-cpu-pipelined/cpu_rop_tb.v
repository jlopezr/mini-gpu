`timescale 1ns / 1ps
`default_nettype none

/*
 * La familia ROP (opcode 0x37, 1.isa/isa.md §7.5) en la CPU pipelined:
 * cpu.v (ROP = 1) -> rop_frontend -> rop_core, con la memoria de datos y la del
 * ROP sobre el mismo array.
 *
 * La memoria de datos acepta un STORE al momento pero no lo hace visible (ni
 * lo confirma) hasta STORE_CONFIRM ciclos despues: mientras, `mem_quiet` esta
 * bajo. Es lo que hace que ROPSUBMIT.F signifique algo aqui: sin esperar, el
 * ROP leeria el valor de antes. Los LOAD de la CPU ven sus propios STORE
 * (se aplican antes de leer). La memoria del ROP es de 128 bits, en orden,
 * con latencia y contrapresion variables.
 *
 * Programas:
 *   basic    FILL con ROPSET + ROPSUBMIT, ROPWAIT y LOAD del resultado;
 *            ROPSTATUS justo despues de un SUBMIT, usado por la instruccion de
 *            detras (adelantamiento desde MEM); SUBMIT que escribe dos
 *            parametros; ROPSTATUS en reposo.
 *   fence    STORE y luego COPY de esa palabra con ROPSUBMIT.F.
 *   queue    24 FILL seguidos (mas que la cola de 16): la CPU se para y no se
 *            pierde ninguno.
 *   span     SPAN explicito Z16 con FRAC = 8 y SAT, LT, escribe Z y color.
 *   inv      ROPWAIT INV da un pulso de invalidacion.
 *   asyncerr un SPAN de ancho 0: el ROP lo rechaza y ROPWAIT para con
 *            ERROR_ROP (0x07) en su PC; ROPSTATUS ve el bit y CLEAR lo borra.
 *   badmode  ROPSET PMODE con [31:16] != 0: ERROR_INVALID_ENCODING preciso.
 *   encoding indice 11, op FRAGMENT, sub 5: errores de decodificacion.
 */
module cpu_rop_tb;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg [4:0] debug_register_address = 5'd0;
  wire [31:0] imem_read_data;
  wire imem_rvalid;

  wire dmem_valid;
  wire [31:0] dmem_address, dmem_write_data;
  wire [3:0] dmem_write_enable;
  reg [31:0] dmem_read_data = 32'h0000_0000;
  reg dmem_rvalid = 1'b0;
  wire dmem_ready;
  wire dmem_waiting;

  wire halted, error, instruction_retired, imem_valid;
  wire [7:0] error_code;
  wire [31:0] imem_address, debug_register_data, debug_pc;

  wire rop_valid, rop_ready, rop_clear, rop_bad_value, rop_error, rop_fence;
  wire rop_dcache_invalidate;
  wire [1:0] rop_uop;
  wire [3:0] rop_ia, rop_ib;
  wire [31:0] rop_da, rop_db, rop_rdata;
  wire [2:0] rop_op;
  wire mem_quiet;

  localparam integer WORDS = 256;
  reg [31:0] instruction_memory[0:WORDS-1];
  integer k, pc;

  always #5 clk = ~clk;

  cpu #(.ROP(1)) dut (
      .clk(clk), .reset(reset), .soft_reset(1'b0),
      .run_request(run_request), .halt_request(1'b0), .step_request(1'b0),
      .halted(halted), .error(error), .error_code(error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid), .imem_address(imem_address),
      .imem_read_data(imem_read_data), .imem_ready(1'b1), .imem_rvalid(imem_rvalid),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data), .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_rvalid(dmem_rvalid), .dmem_error(1'b0), .dmem_waiting(dmem_waiting),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data), .debug_pc(debug_pc),
      .perf_stall(), .perf_muldiv_retired(),
      .dcache_lookup_address(), .dcache_hit(1'b0), .dcache_read_data(32'd0),
      .dcache_mem_advance(), .dcache_ex_load(), .dcache_ex_store(),
      .dcache_ex_write_data(), .dcache_ex_write_enable(),
      .rop_valid(rop_valid), .rop_uop(rop_uop), .rop_ia(rop_ia), .rop_ib(rop_ib),
      .rop_da(rop_da), .rop_db(rop_db), .rop_op(rop_op), .rop_clear(rop_clear),
      .rop_ready(rop_ready), .rop_rdata(rop_rdata),
      .rop_bad_value(rop_bad_value), .rop_error(rop_error),
      .rop_fence(rop_fence), .mem_quiet(mem_quiet),
      .rop_dcache_invalidate(rop_dcache_invalidate));

  wire rop_cmd_valid, rop_cmd_ready, rop_done_valid, rop_done_error;
  wire [2:0] rop_cmd_op;
  wire [15:0] rop_cmd_mode;
  wire [319:0] rop_cmd_params;
  rop_frontend #(.QUEUE_DEPTH(16)) frontend (
      .clk(clk), .reset(reset),
      .cpu_valid(rop_valid), .cpu_ready(rop_ready), .cpu_uop(rop_uop),
      .cpu_ia(rop_ia), .cpu_ib(rop_ib), .cpu_da(rop_da), .cpu_db(rop_db),
      .cpu_op(rop_op), .cpu_clear(rop_clear), .cpu_rdata(rop_rdata),
      .cpu_bad_value(rop_bad_value), .cpu_rop_error(rop_error), .cpu_busy(),
      .rop_cmd_valid(rop_cmd_valid), .rop_cmd_ready(rop_cmd_ready),
      .rop_cmd_op(rop_cmd_op), .rop_cmd_mode(rop_cmd_mode),
      .rop_cmd_params(rop_cmd_params),
      .rop_done_valid(rop_done_valid), .rop_done_error(rop_done_error));

  wire req_valid, req_write, rsp_ready;
  reg req_ready = 1'b1;
  wire [31:0] req_addr;
  wire [127:0] req_wdata;
  wire [15:0] req_wmask;
  reg rsp_valid = 1'b0;
  reg [127:0] rsp_rdata = 128'd0;
  rop_core #(.TAG_DEPTH(8)) core (
      .clk(clk), .reset(reset),
      .cmd_valid(rop_cmd_valid), .cmd_ready(rop_cmd_ready),
      .cmd_op(rop_cmd_op), .cmd_mode(rop_cmd_mode), .cmd_params(rop_cmd_params),
      .cmd_frag_colors(256'd0), .cmd_frag_z(256'd0),
      .done_valid(rop_done_valid), .done_error(rop_done_error), .busy(),
      .req_valid(req_valid), .req_ready(req_ready), .req_write(req_write),
      .req_addr(req_addr), .req_wdata(req_wdata), .req_wmask(req_wmask),
      .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata),
      .rsp_error(1'b0));

  // ---- Instrucciones: un acierto del bufer, dos ciclos -------------------
  reg [1:0] imem_pipe_valid = 2'b00;
  reg [31:0] imem_pipe_data0, imem_pipe_data1;
  always @(posedge clk) begin
    imem_pipe_valid <= reset ? 2'b00 : {imem_pipe_valid[0], imem_valid};
    imem_pipe_data0 <= instruction_memory[imem_address[9:2]];
    imem_pipe_data1 <= imem_pipe_data0;
  end
  assign imem_rvalid = imem_pipe_valid[1];
  assign imem_read_data = imem_pipe_data1;

  // ---- Datos: 4 KB compartidos con el ROP ---------------------------------
  localparam integer STORE_CONFIRM = 12;
  localparam integer READ_CYCLES = 4;
  reg [31:0] data_memory[0:1023];
  // Un STORE pendiente de confirmar: invisible para el ROP hasta entonces.
  reg pend_valid = 1'b0;
  reg [9:0] pend_word;
  reg [31:0] pend_data;
  reg [3:0] pend_mask;
  integer pend_left = 0;
  assign mem_quiet = !pend_valid;
  task apply_pending;
    begin
      if (pend_valid) begin
        if (pend_mask[0]) data_memory[pend_word][7:0] = pend_data[7:0];
        if (pend_mask[1]) data_memory[pend_word][15:8] = pend_data[15:8];
        if (pend_mask[2]) data_memory[pend_word][23:16] = pend_data[23:16];
        if (pend_mask[3]) data_memory[pend_word][31:24] = pend_data[31:24];
        pend_valid = 1'b0;
      end
    end
  endtask
  reg d_busy = 1'b0;
  integer d_wait = 0;
  assign dmem_ready = !d_busy;
  integer fence_cycles = 0;
  always @(posedge clk) begin
    dmem_rvalid <= 1'b0;
    if (rop_fence) fence_cycles = fence_cycles + 1;
    if (reset) begin
      d_busy <= 1'b0;
      pend_valid = 1'b0;
    end else begin
      if (pend_valid) begin
        pend_left = pend_left - 1;
        if (pend_left <= 0) apply_pending;
      end
      if (d_busy) begin
        if (d_wait <= 1) begin dmem_rvalid <= 1'b1; d_busy <= 1'b0; end
        else d_wait <= d_wait - 1;
      end else if (dmem_valid) begin
        if (dmem_write_enable != 4'd0) begin
          apply_pending;
          pend_valid = 1'b1;
          pend_word = dmem_address[11:2];
          pend_data = dmem_write_data;
          pend_mask = dmem_write_enable;
          pend_left = STORE_CONFIRM;
          dmem_rvalid <= 1'b1;
        end else begin
          apply_pending;
          dmem_read_data <= data_memory[dmem_address[11:2]];
          d_wait <= READ_CYCLES;
          d_busy <= 1'b1;
        end
      end
    end
  end

  // ---- Memoria del ROP: 128 bits, en orden ---------------------------------
  localparam integer QMAX = 32;
  reg [127:0] q_data [0:QMAX-1];
  integer q_due [0:QMAX-1];
  integer q_head = 0, q_tail = 0, q_count = 0, tick = 0;
  reg consumed = 1'b0;
  integer seed = 7;
  reg [127:0] line;
  integer b;
  always @(negedge clk) begin
    tick = tick + 1;
    req_ready = (($random(seed) & 3) != 0);
    if (!rsp_valid || consumed) begin
      rsp_valid = (q_count != 0) && (tick >= q_due[q_head]);
      rsp_rdata = (q_count != 0) ? q_data[q_head] : 128'd0;
    end
    consumed = 1'b0;
  end
  always @(posedge clk) begin
    if (reset) begin
      q_head = 0; q_tail = 0; q_count = 0;
    end else begin
      if (rsp_valid && rsp_ready) begin
        consumed = 1'b1;
        q_head = (q_head + 1) % QMAX;
        q_count = q_count - 1;
      end
      if (req_valid && req_ready) begin
        if (req_addr[3:0] != 0 || req_addr >= 32'd4096)
          $fatal(1, "ROP request out of range %h", req_addr);
        line = {data_memory[{req_addr[11:4], 2'd3}], data_memory[{req_addr[11:4], 2'd2}],
                data_memory[{req_addr[11:4], 2'd1}], data_memory[{req_addr[11:4], 2'd0}]};
        if (req_write) begin
          for (b = 0; b < 16; b = b + 1)
            if (req_wmask[b]) line[8*b +: 8] = req_wdata[8*b +: 8];
          {data_memory[{req_addr[11:4], 2'd3}], data_memory[{req_addr[11:4], 2'd2}],
           data_memory[{req_addr[11:4], 2'd1}], data_memory[{req_addr[11:4], 2'd0}]} = line;
        end
        q_data[q_tail] = line;
        q_due[q_tail] = tick + 2 + ($random(seed) & 7);
        if (q_count != 0 && q_due[q_tail] < q_due[(q_tail + QMAX - 1) % QMAX])
          q_due[q_tail] = q_due[(q_tail + QMAX - 1) % QMAX];
        q_tail = (q_tail + 1) % QMAX;
        q_count = q_count + 1;
      end
    end
  end

  integer inv_pulses = 0;
  always @(posedge clk) if (rop_dcache_invalidate) inv_pulses = inv_pulses + 1;

  // ---- Codificaciones ------------------------------------------------------
  localparam [31:0] HALT = 32'hFC00_0000;
  localparam [3:0] NONE = 4'd15, PMODE = 4'd10;
  function [31:0] movi(input [4:0] rd, input [15:0] imm);
    movi = 32'h4000_0000 | (rd << 21) | imm;
  endfunction
  // SHLI: SHL (0x07) con la cantidad en el campo Rb y el bit 10 a uno.
  function [31:0] shli(input [4:0] rd, input [4:0] ra, input [4:0] amount);
    shli = {6'h07, rd, ra, amount, 1'b1, 10'd0};
  endfunction
  function [31:0] addi(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    addi = 32'h4400_0000 | (rd << 21) | (ra << 16) | imm;
  endfunction
  function [31:0] andi(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    andi = 32'h4800_0000 | (rd << 21) | (ra << 16) | imm;
  endfunction
  function [31:0] store(input [4:0] rs, input [4:0] ra, input [15:0] imm);
    store = 32'h5800_0000 | (rs << 21) | (ra << 16) | imm;
  endfunction
  function [31:0] load(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    load = 32'h5400_0000 | (rd << 21) | (ra << 16) | imm;
  endfunction
  function [31:0] rop(input [3:0] sub, input [4:0] x, input [4:0] y, input [11:0] low);
    rop = {6'h37, x, y, sub, low};
  endfunction
  function [31:0] ropset(input [3:0] pa, input [4:0] ra, input [3:0] pb, input [4:0] rb);
    ropset = rop(4'd0, ra, rb, {pa, pb, 4'd0});
  endfunction
  function [31:0] ropsubmit(input [2:0] op, input f, input [3:0] pa, input [4:0] ra,
                            input [3:0] pb, input [4:0] rb);
    ropsubmit = rop(4'd1, ra, rb, {op, f, pa, pb});
  endfunction
  function [31:0] ropwait(input inv);
    ropwait = rop(4'd2, 5'd0, 5'd0, {11'd0, inv});
  endfunction
  function [31:0] ropstatus(input [4:0] rd, input clr);
    ropstatus = rop(4'd3, rd, 5'd0, {11'd0, clr});
  endfunction

  task clear_program;
    begin
      for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
      pc = 0;
    end
  endtask
  task emit(input [31:0] w);
    begin instruction_memory[pc] = w; pc = pc + 1; end
  endtask

  task expect_register(input [4:0] address, input [31:0] expected);
    begin
      debug_register_address = address;
      repeat (2) @(posedge clk);
      #1;
      if (debug_register_data !== expected)
        $fatal(1, "R%0d: expected %08x, got %08x", address, expected, debug_register_data);
    end
  endtask
  task expect_word(input [11:0] a, input [31:0] expected);
    begin
      if (data_memory[a[11:2]] !== expected)
        $fatal(1, "mem[%03x]: expected %08x, got %08x", a, expected, data_memory[a[11:2]]);
    end
  endtask

  // Reset (memoria del ROP y frontend incluidos), RUN y esperar a que pare.
  task run(input [8*10-1:0] name, input expect_error, input [7:0] code, input [31:0] epc);
    integer watch;
    begin
      @(negedge clk);
      reset = 1'b1;
      repeat (3) @(negedge clk);
      reset = 1'b0;
      @(negedge clk);
      run_request = 1'b1;
      @(negedge clk);
      run_request = 1'b0;
      wait (!halted);
      watch = 0;
      while (!halted) begin
        @(posedge clk); watch = watch + 1;
        if (watch > 200000) $fatal(1, "%0s: timeout", name);
      end
      @(posedge clk); #1;
      if (expect_error) begin
        if (!error || error_code !== code || debug_pc !== epc)
          $fatal(1, "%0s: expected error %02x at %08x, got error=%b %02x at %08x",
                 name, code, epc, error, error_code, debug_pc);
      end else if (error) begin
        $fatal(1, "%0s: error %02x at pc %08x", name, error_code, debug_pc);
      end
      $display("ok %0s", name);
    end
  endtask

  initial begin
    #20_000_000;
    $fatal(1, "cpu_rop_tb: timeout");
  end

  integer i;
  initial begin
    for (i = 0; i < 1024; i = i + 1) data_memory[i] = 32'hdead0000 + i;

    // ---- basic ------------------------------------------------------------
    clear_program();
    emit(movi(5'd1, 16'h0200));            // P0 destino
    emit(movi(5'd2, 16'd32));              // P1 ancho en bytes
    emit(ropset(4'd0, 5'd1, 4'd1, 5'd2));
    emit(movi(5'd3, 16'd2));               // P2 filas
    emit(movi(5'd4, 16'd64));              // P3 stride
    emit(ropset(4'd2, 5'd3, 4'd3, 5'd4));
    emit(movi(5'd5, 16'h1234));            // P4 patron
    emit(ropset(4'd4, 5'd5, PMODE, 5'd0)); // PMODE = 0
    emit(ropsubmit(3'd0, 1'b0, NONE, 5'd0, NONE, 5'd0));
    emit(ropstatus(5'd6, 1'b0));           // justo detras: pendiente
    emit(andi(5'd7, 5'd6, 16'h0001));      // usa el valor: adelantamiento
    emit(ropwait(1'b0));
    emit(load(5'd8, 5'd1, 16'd0));
    emit(load(5'd9, 5'd1, 16'd92));        // fila 1, ultima palabra (64+28)
    emit(load(5'd10, 5'd1, 16'd32));       // fuera del ancho: intacta
    // SUBMIT que escribe dos parametros: destino 0x300 y patron 0x5678.
    emit(movi(5'd11, 16'h0300));
    emit(movi(5'd12, 16'h5678));
    emit(ropsubmit(3'd0, 1'b0, 4'd0, 5'd11, 4'd4, 5'd12));
    emit(ropwait(1'b0));
    emit(load(5'd13, 5'd11, 16'd64));
    emit(ropstatus(5'd14, 1'b0));          // en reposo
    emit(HALT);
    run("basic", 1'b0, 8'd0, 32'd0);
    expect_register(5'd7, 32'd1);
    expect_register(5'd8, 32'h0000_1234);
    expect_register(5'd9, 32'h0000_1234);
    expect_register(5'd10, 32'hdead0000 + (12'h220 >> 2));
    expect_register(5'd13, 32'h0000_5678);
    expect_register(5'd14, 32'h0000_1000);   // 16 huecos libres, nada pendiente

    // ---- fence --------------------------------------------------------------
    // COPY de 16 bytes de 0x400 a 0x500 justo despues de un STORE a 0x400.
    clear_program();
    emit(movi(5'd1, 16'h0400));
    emit(movi(5'd2, 16'h0500));
    emit(movi(5'd3, 16'd16));
    emit(movi(5'd4, 16'd1));
    emit(ropset(4'd0, 5'd1, 4'd1, 5'd2));     // P0 origen, P1 destino
    emit(ropset(4'd2, 5'd3, 4'd3, 5'd4));     // P2 ancho, P3 filas
    emit(ropset(4'd4, 5'd3, 4'd5, 5'd3));     // strides
    emit(movi(5'd5, 16'h7777));
    emit(store(5'd5, 5'd1, 16'd4));
    emit(ropsubmit(3'd1, 1'b1, NONE, 5'd0, NONE, 5'd0));
    emit(ropwait(1'b0));
    emit(load(5'd6, 5'd2, 16'd4));
    emit(HALT);
    fence_cycles = 0;
    run("fence", 1'b0, 8'd0, 32'd0);
    expect_register(5'd6, 32'h0000_7777);
    if (fence_cycles == 0) $fatal(1, "fence: ROPSUBMIT.F never waited");

    // ---- queue: 24 FILL de 16 bytes, uno por palabra 0x600 + 16 k ---------
    clear_program();
    emit(movi(5'd1, 16'd16));
    emit(movi(5'd2, 16'd1));
    emit(ropset(4'd1, 5'd1, 4'd2, 5'd2));     // ancho 16, filas 1
    emit(ropset(4'd3, 5'd1, PMODE, 5'd0));
    for (i = 0; i < 24; i = i + 1) begin
      emit(movi(5'd3, 16'h0600 + 16*i));
      emit(movi(5'd4, 16'h0100 + i));
      emit(ropsubmit(3'd0, 1'b0, 4'd0, 5'd3, 4'd4, 5'd4));
    end
    emit(ropwait(1'b0));
    emit(HALT);
    run("queue", 1'b0, 8'd0, 32'd0);
    for (i = 0; i < 24; i = i + 1) begin
      expect_word(12'h600 + 16*i, 32'h0100 + i);
      expect_word(12'h600 + 16*i + 12, 32'h0100 + i);
    end

    // ---- span: Z16 FRAC 8 SAT, LT, Z y color, 6 pixeles -------------------
    // Z vieja 0xFFFF; z0 = -256 (-> 0), dx = 0x00800000 (32768 por pixel).
    for (i = 0; i < 4; i = i + 1) data_memory[(12'h800 >> 2) + i] = 32'hffffffff;
    for (i = 0; i < 4; i = i + 1) data_memory[(12'h900 >> 2) + i] = 32'h00000000;
    clear_program();
    emit(movi(5'd1, 16'h0900));               // P0 color
    emit(movi(5'd2, 16'h0800));               // P1 Z
    emit(ropset(4'd0, 5'd1, 4'd1, 5'd2));
    emit(movi(5'd3, 16'd6));                  // P2 ancho
    emit(movi(5'd4, 16'd1));                  // P3 filas
    emit(ropset(4'd2, 5'd3, 4'd3, 5'd4));
    emit(movi(5'd5, 16'd64));
    emit(ropset(4'd4, 5'd5, 4'd5, 5'd5));     // strides
    emit(movi(5'd6, 16'h00ab));               // P6 color
    emit(movi(5'd7, 16'hff00));               // P7 z0 = -256
    emit(ropset(4'd6, 5'd6, 4'd7, 5'd7));
    emit(movi(5'd8, 16'h0080));
    emit(shli(5'd8, 5'd8, 5'd16));            // 0x00800000
    emit(ropset(4'd8, 5'd8, 4'd9, 5'd0));     // P8 dx, P9 dy = 0
    emit(movi(5'd9, 16'h2863));               // SAT, FRAC 8, Z y color, LT
    emit(ropsubmit(3'd3, 1'b0, PMODE, 5'd9, NONE, 5'd0));
    emit(ropwait(1'b0));
    emit(HALT);
    run("span", 1'b0, 8'd0, 32'd0);
    // Z = sat16((-256 + x * 0x00800000) >> 8): 0, 0x7FFF, 0xFFFF (no pasa LT
    // contra 0xFFFF), saturado...
    expect_word(12'h800, 32'h7fff_0000);
    expect_word(12'h804, 32'hffff_ffff);
    expect_word(12'h808, 32'hffff_ffff);
    expect_word(12'h900, 32'h00ab_00ab);
    expect_word(12'h904, 32'h0000_0000);

    // ---- inv ----------------------------------------------------------------
    clear_program();
    emit(ropwait(1'b1));
    emit(ropwait(1'b0));
    emit(HALT);
    inv_pulses = 0;
    run("inv", 1'b0, 8'd0, 32'd0);
    if (inv_pulses != 1) $fatal(1, "inv: %0d invalidation pulses, expected 1", inv_pulses);

    // ---- asyncerr: SPAN de ancho 0 ----------------------------------------
    clear_program();
    emit(ropset(4'd2, 5'd0, 4'd3, 5'd0));     // ancho 0, filas 0
    emit(movi(5'd9, 16'h0063));
    emit(ropsubmit(3'd3, 1'b0, PMODE, 5'd9, NONE, 5'd0));
    emit(ropstatus(5'd1, 1'b0));
    emit(ropwait(1'b0));                      // PC 0x10: ERROR_ROP
    emit(HALT);
    run("asyncerr", 1'b1, 8'h07, 32'h10);
    // Mismo error, sondeado y borrado: ROPWAIT ya no para.
    clear_program();
    emit(ropset(4'd2, 5'd0, 4'd3, 5'd0));
    emit(movi(5'd9, 16'h0063));
    emit(ropsubmit(3'd3, 1'b0, PMODE, 5'd9, NONE, 5'd0));
    for (i = 0; i < 20; i = i + 1) emit(32'h0000_0000);   // NOP: que el ROP lo rechace
    emit(ropstatus(5'd1, 1'b1));              // lee el error y lo borra
    emit(ropwait(1'b0));
    emit(ropstatus(5'd2, 1'b0));
    emit(HALT);
    run("errclear", 1'b0, 8'd0, 32'd0);
    expect_register(5'd1, 32'h0000_1004);
    expect_register(5'd2, 32'h0000_1000);

    // ---- badmode: PMODE con [31:16] != 0 -----------------------------------
    clear_program();
    emit(movi(5'd1, 16'h0001));
    emit(shli(5'd1, 5'd1, 5'd16));            // 0x00010000
    emit(ropset(PMODE, 5'd1, NONE, 5'd0));    // PC 8
    emit(HALT);
    run("badmode", 1'b1, 8'h05, 32'h8);

    // ---- encoding -----------------------------------------------------------
    clear_program();
    emit(ropset(4'd11, 5'd0, NONE, 5'd0));
    emit(HALT);
    run("enc-idx", 1'b1, 8'h05, 32'h0);
    clear_program();
    emit(ropsubmit(3'd4, 1'b0, NONE, 5'd0, NONE, 5'd0));
    emit(HALT);
    run("enc-frag", 1'b1, 8'h05, 32'h0);
    clear_program();
    emit(rop(4'd5, 5'd0, 5'd0, 12'd0));
    emit(HALT);
    run("enc-sub", 1'b1, 8'h01, 32'h0);
    clear_program();
    emit(ropset(4'd2, 5'd1, 4'd2, 5'd2));     // pA = pB
    emit(HALT);
    run("enc-same", 1'b1, 8'h05, 32'h0);
    clear_program();
    emit(ropset(NONE, 5'd3, NONE, 5'd0));     // indice 15 con registro != R0
    emit(HALT);
    run("enc-none", 1'b1, 8'h05, 32'h0);

    $display("PASS: cpu_rop");
    $finish;
  end
endmodule

`default_nettype wire
