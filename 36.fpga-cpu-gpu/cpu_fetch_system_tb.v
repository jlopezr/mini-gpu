`timescale 1ns / 1ps
`default_nettype none

/*
 * Banco INTEGRADO del camino de instrucciones de la CPU:
 *
 *   cpu -> instruction_buffer -> fabric_fifo_bridge (puerto 1, clk -> clk_mem)
 *       -> memory_fabric_fifo_6 -> sdram_controller_128 -> sdram_model
 *
 * y el de datos (cpu_dmem_adapter, puerto 0), con los relojes de la placa
 * (CPU 80 MHz, memoria 100 MHz, GPU 25 MHz) y el mismo cableado que top.v. Nadie
 * simulaba hasta hoy una linea de instrucciones de principio a fin: cada modulo
 * se probaba suelto.
 *
 * Reproduce lo que hace el arnes de pruebas en placa:
 *   1. rellena la zona de programa con basura (el residuo de un caso anterior);
 *   2. escribe el programa por el puerto 3 (el del monitor), 16 B por peticion y
 *      con mascara parcial en la ultima linea;
 *   3. arranca la CPU, espera a que pare y compara el PC y los registros con los
 *      esperados (ficheros .val/.chk generados desde test.json).
 * Se repite `+runs=N` veces con reset de CPU entre medias, como `reset_cpu`.
 *
 * Uso: vvp ... +prog=x.hex +val=x.val +chk=x.chk +nwords=63 [+runs=3]
 */
module cpu_fetch_system_tb;
    // ---------------- Relojes (periodos de la placa) ----------------
    reg clk = 0, clk_mem = 0, clk_gpu = 0;
    always #6.25 clk     = ~clk;        // 80 MHz
    always #5.0  clk_mem = ~clk_mem;    // 100 MHz
    always #20.0 clk_gpu = ~clk_gpu;    // 25 MHz

    // ---------------- Resets sincronizados, como en top.v ----------------
    reg arst = 1'b1;
    wire reset, reset_mem, reset_gpu;
    reset_sync #(.STAGES(4)) rs_cpu (.clk(clk),     .arst(arst), .rst(reset));
    reset_sync #(.STAGES(4)) rs_mem (.clk(clk_mem), .arst(arst), .rst(reset_mem));
    reset_sync #(.STAGES(4)) rs_gpu (.clk(clk_gpu), .arst(arst), .rst(reset_gpu));

    // ---------------- CPU ----------------
    reg  cpu_reset_request = 1'b0;
    reg  cpu_run_request   = 1'b0;
    wire cpu_halted, cpu_error, cpu_instruction_retired;
    wire [7:0] cpu_error_code;
    wire [31:0] cpu_pc;
    wire cpu_imem_valid, cpu_imem_ready;
    wire [31:0] cpu_imem_address, cpu_imem_read_data;
    wire cpu_dmem_valid, cpu_dmem_ready, cpu_dmem_error;
    wire [31:0] cpu_dmem_address, cpu_dmem_write_data, cpu_dmem_read_data;
    wire [3:0] cpu_dmem_write_enable;
    reg  [4:0] dbg_reg_addr = 0;
    wire [31:0] dbg_reg_data;

    cpu cpu_i(
        .clk(clk), .reset(reset || cpu_reset_request),
        .run_request(cpu_run_request), .halt_request(1'b0), .step_request(1'b0),
        .halted(cpu_halted), .error(cpu_error), .error_code(cpu_error_code),
        .instruction_retired(cpu_instruction_retired),
        .imem_valid(cpu_imem_valid), .imem_address(cpu_imem_address),
        .imem_read_data(cpu_imem_read_data), .imem_ready(cpu_imem_ready),
        .dmem_valid(cpu_dmem_valid), .dmem_address(cpu_dmem_address),
        .dmem_write_data(cpu_dmem_write_data),
        .dmem_write_enable(cpu_dmem_write_enable),
        .dmem_read_data(cpu_dmem_read_data), .dmem_ready(cpu_dmem_ready),
        .dmem_error(cpu_dmem_error),
        .debug_register_address(dbg_reg_addr),
        .debug_register_data(dbg_reg_data), .debug_pc(cpu_pc));

    // ---------------- Puertos hacia el fabric ----------------
    wire init_done, init_done_mem;

    wire p0_valid, p0_ready, p0_write, p0_rsp_valid, p0_rsp_ready, p0_rsp_error;
    wire [31:0] p0_addr; wire [127:0] p0_wdata, p0_rsp_rdata; wire [15:0] p0_wmask;
    wire p1_valid, p1_ready, p1_write, p1_rsp_valid, p1_rsp_ready, p1_rsp_error;
    wire [31:0] p1_addr; wire [127:0] p1_wdata, p1_rsp_rdata; wire [15:0] p1_wmask;

    wire wb_dirty;
    cpu_dmem_adapter dmem_adapter_i(
        .clk(clk), .reset(reset), .init_done(init_done),
        .dmem_valid(cpu_dmem_valid), .dmem_address(cpu_dmem_address),
        .dmem_write_data(cpu_dmem_write_data),
        .dmem_write_enable(cpu_dmem_write_enable),
        .dmem_read_data(cpu_dmem_read_data), .dmem_ready(cpu_dmem_ready),
        .dmem_error(cpu_dmem_error), .cpu_halted(cpu_halted),
        .wb_dirty(wb_dirty), .merge_count(), .flush_count(),
        .mmio_req(), .mmio_ack(1'b0), .mmio_write(), .mmio_write_mask(),
        .mmio_address(), .mmio_write_data(), .mmio_read_data(32'd0), .mmio_error(1'b0),
        .req_valid(p0_valid), .req_ready(p0_ready), .req_write(p0_write),
        .req_addr(p0_addr), .req_wdata(p0_wdata), .req_wmask(p0_wmask),
        .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
        .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));

    instruction_buffer #(.LINES(4), .INDEX_BITS(2)) instruction_buffer_i(
        .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(cpu_halted),
        .cpu_imem_valid(cpu_imem_valid), .cpu_imem_address(cpu_imem_address),
        .cpu_imem_read_data(cpu_imem_read_data), .cpu_imem_ready(cpu_imem_ready),
        .req_valid(p1_valid), .req_ready(p1_ready), .req_write(p1_write),
        .req_addr(p1_addr), .req_wdata(p1_wdata), .req_wmask(p1_wmask),
        .rsp_valid(p1_rsp_valid), .rsp_ready(p1_rsp_ready),
        .rsp_rdata(p1_rsp_rdata), .rsp_error(p1_rsp_error),
        .hit_count(), .miss_count(), .hit_event(), .miss_event());

    // Puerto 3: el "monitor", manejado por el banco.
    reg         t_valid = 0;
    reg         t_write = 1;
    reg  [31:0] t_addr  = 0;
    reg  [127:0] t_wdata = 0;
    reg  [15:0] t_wmask = 16'hffff;
    wire        t_ready, t_rsp_valid, t_rsp_error;
    wire [127:0] t_rsp_rdata;

    // Vectores hacia los bridges (puertos 0..5). 2 (video), 4 y 5 (GPU): inactivos.
    wire [5:0]  m_req_ready, m_rsp_valid, m_rsp_error;
    wire [5:0]  m_rsp_ready  = {1'b1, 1'b1, 1'b1, 1'b1, p1_rsp_ready, p0_rsp_ready};
    wire [31:0] m_req_addr  [0:5];
    wire [127:0] m_req_wdata [0:5];
    wire [15:0] m_req_wmask [0:5];
    wire [127:0] m_rsp_rdata [0:5];

    // Orden de bits del vector: [5]=p5 [4]=p4 [3]=monitor [2]=video [1]=p1 [0]=p0
    // (t_valid es el puerto 3, asi que va en el bit 3).
    wire [5:0]  m_req_valid_ok = {1'b0, 1'b0, t_valid, 1'b0, p1_valid, p0_valid};
    wire [5:0]  m_req_write_ok = {1'b0, 1'b0, t_write, 1'b0, p1_write, p0_write};

    assign m_req_addr[0] = p0_addr;  assign m_req_wdata[0] = p0_wdata;  assign m_req_wmask[0] = p0_wmask;
    assign m_req_addr[1] = p1_addr;  assign m_req_wdata[1] = p1_wdata;  assign m_req_wmask[1] = p1_wmask;
    assign m_req_addr[2] = 32'd0;    assign m_req_wdata[2] = 128'd0;    assign m_req_wmask[2] = 16'd0;
    assign m_req_addr[3] = t_addr;   assign m_req_wdata[3] = t_wdata;   assign m_req_wmask[3] = t_wmask;
    assign m_req_addr[4] = 32'd0;    assign m_req_wdata[4] = 128'd0;    assign m_req_wmask[4] = 16'd0;
    assign m_req_addr[5] = 32'd0;    assign m_req_wdata[5] = 128'd0;    assign m_req_wmask[5] = 16'd0;

    assign p0_ready = m_req_ready[0];   assign p0_rsp_valid = m_rsp_valid[0];
    assign p0_rsp_rdata = m_rsp_rdata[0]; assign p0_rsp_error = m_rsp_error[0];
    assign p1_ready = m_req_ready[1];   assign p1_rsp_valid = m_rsp_valid[1];
    assign p1_rsp_rdata = m_rsp_rdata[1]; assign p1_rsp_error = m_rsp_error[1];
    assign t_ready = m_req_ready[3];    assign t_rsp_valid = m_rsp_valid[3];
    assign t_rsp_rdata = m_rsp_rdata[3]; assign t_rsp_error = m_rsp_error[3];

    wire [5:0] req_empty, req_rd_en, req_rd_valid;
    wire [177:0] req_data [0:5];
    wire [5:0] rsp_full, rsp_wr_en;
    wire [128:0] rsp_data [0:5];

    genvar bi;
    generate
        for (bi = 0; bi < 6; bi = bi + 1) begin : g_bridge
            fabric_fifo_bridge #(.FIFO_ADDR_WIDTH(2)) bridge_i(
                .master_clk(bi >= 4 ? clk_gpu : clk),
                .master_reset(bi >= 4 ? reset_gpu : reset),
                .req_valid(m_req_valid_ok[bi]), .req_ready(m_req_ready[bi]),
                .req_urgent(1'b0), .req_write(m_req_write_ok[bi]),
                .req_addr(m_req_addr[bi]), .req_wdata(m_req_wdata[bi]),
                .req_wmask(m_req_wmask[bi]),
                .rsp_valid(m_rsp_valid[bi]), .rsp_ready(m_rsp_ready[bi]),
                .rsp_rdata(m_rsp_rdata[bi]), .rsp_error(m_rsp_error[bi]),
                .mem_clk(clk_mem), .mem_reset(reset_mem),
                .mem_req_empty(req_empty[bi]), .mem_req_rd_en(req_rd_en[bi]),
                .mem_req_rd_valid(req_rd_valid[bi]), .mem_req_data(req_data[bi]),
                .mem_rsp_full(rsp_full[bi]), .mem_rsp_wr_en(rsp_wr_en[bi]),
                .mem_rsp_data(rsp_data[bi]),
                .dbg_req_ptrs(), .dbg_rsp());
        end
    endgenerate

    wire fab_req_valid, fab_req_ready, fab_req_write, fab_done, fabric_busy;
    wire [23:0] fab_req_addr;
    wire [127:0] fab_req_wdata, fab_rdata;
    wire [15:0] fab_req_wmask;

    memory_fabric_fifo_6 fabric_i(
        .clk(clk_mem), .reset(reset_mem),
        .p0_req_empty(req_empty[0]), .p0_req_rd_en(req_rd_en[0]), .p0_req_rd_valid(req_rd_valid[0]), .p0_req_data(req_data[0]), .p0_rsp_full(rsp_full[0]), .p0_rsp_wr_en(rsp_wr_en[0]), .p0_rsp_data(rsp_data[0]),
        .p1_req_empty(req_empty[1]), .p1_req_rd_en(req_rd_en[1]), .p1_req_rd_valid(req_rd_valid[1]), .p1_req_data(req_data[1]), .p1_rsp_full(rsp_full[1]), .p1_rsp_wr_en(rsp_wr_en[1]), .p1_rsp_data(rsp_data[1]),
        .p2_req_empty(req_empty[2]), .p2_req_rd_en(req_rd_en[2]), .p2_req_rd_valid(req_rd_valid[2]), .p2_req_data(req_data[2]), .p2_rsp_full(rsp_full[2]), .p2_rsp_wr_en(rsp_wr_en[2]), .p2_rsp_data(rsp_data[2]),
        .p3_req_empty(req_empty[3]), .p3_req_rd_en(req_rd_en[3]), .p3_req_rd_valid(req_rd_valid[3]), .p3_req_data(req_data[3]), .p3_rsp_full(rsp_full[3]), .p3_rsp_wr_en(rsp_wr_en[3]), .p3_rsp_data(rsp_data[3]),
        .p4_req_empty(req_empty[4]), .p4_req_rd_en(req_rd_en[4]), .p4_req_rd_valid(req_rd_valid[4]), .p4_req_data(req_data[4]), .p4_rsp_full(rsp_full[4]), .p4_rsp_wr_en(rsp_wr_en[4]), .p4_rsp_data(rsp_data[4]),
        .p5_req_empty(req_empty[5]), .p5_req_rd_en(req_rd_en[5]), .p5_req_rd_valid(req_rd_valid[5]), .p5_req_data(req_data[5]), .p5_rsp_full(rsp_full[5]), .p5_rsp_wr_en(rsp_wr_en[5]), .p5_rsp_data(rsp_data[5]),
        .sdram_req_valid(fab_req_valid), .sdram_req_ready(fab_req_ready),
        .sdram_req_write(fab_req_write), .sdram_req_addr(fab_req_addr),
        .sdram_req_wdata(fab_req_wdata), .sdram_req_wmask(fab_req_wmask),
        .sdram_done(fab_done), .sdram_rdata(fab_rdata), .busy(fabric_busy),
        .dbg(), .dbg2(), .dbg3(), .dbg4(), .dbg5(),
        .dbg_trace_idx(5'd0), .dbg_trace_data(), .dbg_trace_n());

    // init_done del controlador (clk_mem) al dominio de la CPU, como en top.v.
    reg init_done_sync1, init_done_sync2;
    always @(posedge clk) begin
        if (reset) begin init_done_sync1 <= 1'b0; init_done_sync2 <= 1'b0; end
        else begin init_done_sync1 <= init_done_mem; init_done_sync2 <= init_done_sync1; end
    end
    assign init_done = init_done_sync2;

    wire sdram_cke, sdram_csn, sdram_rasn, sdram_casn, sdram_wen, sdram_busy;
    wire [12:0] sdram_a; wire [1:0] sdram_ba, sdram_dqm; wire [15:0] sdram_d;

    sdram_controller_128 #(.CLK_FREQ_HZ(100_000_000), .POWERUP_DELAY_US(2),
                           .READ_DELAY_CYCLES(2)) controller_i(
        .clk(clk_mem), .reset(reset_mem),
        .req_valid(fab_req_valid), .req_write(fab_req_write),
        .req_addr(fab_req_addr), .req_wdata(fab_req_wdata),
        .req_wmask(fab_req_wmask), .req_ready(fab_req_ready),
        .done(fab_done), .rdata(fab_rdata),
        .init_done(init_done_mem), .busy(sdram_busy), .sdram_clk(),
        .sdram_cke(sdram_cke), .sdram_csn(sdram_csn), .sdram_rasn(sdram_rasn),
        .sdram_casn(sdram_casn), .sdram_wen(sdram_wen), .sdram_a(sdram_a),
        .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm), .sdram_d(sdram_d));

    sdram_model #(.POWERUP_DELAY_NS(2000), .READ_DELAY_CYCLES(0)) mem_i(
        .clk(clk_mem), .cke(sdram_cke), .csn(sdram_csn), .rasn(sdram_rasn),
        .casn(sdram_casn), .wen(sdram_wen), .a(sdram_a), .ba(sdram_ba),
        .dqm(sdram_dqm), .dq(sdram_d));

    // ---------------- Banco ----------------
    reg [31:0] prog [0:1023];
    reg [31:0] exp_val [0:32];
    reg [31:0] exp_chk [0:32];
    integer nwords, runs, run_i, errors, i, line, w, timeout;
    reg [31:0]  junk;
    reg [127:0] data16;
    reg [15:0]  mask16;
    reg [1023:0] f_prog, f_val, f_chk;
    reg acc;

    // Escribe 16 B por el puerto 3 y espera a que el fabric lo acepte.
    task wr16(input [31:0] addr, input [127:0] data, input [15:0] mask);
        begin
            @(negedge clk);
            t_addr = addr; t_wdata = data; t_wmask = mask; t_write = 1'b1; t_valid = 1'b1;
            acc = 1'b0;
            while (!acc) begin
                @(posedge clk);
                acc = t_ready;
            end
            @(negedge clk) t_valid = 1'b0;
        end
    endtask

    task load_program;
        begin
            // 1) basura en 0x000..0x3FF: lo que dejo el caso anterior
            for (line = 0; line < 64; line = line + 1) begin
                junk = 32'h586a0000 + line * 4;
                data16 = {junk + 32'd3, junk + 32'd2, junk + 32'd1, junk};
                wr16(line * 16, data16, 16'hffff);
            end
            // 2) el programa, 16 B por peticion, mascara parcial en la ultima linea
            for (line = 0; line * 4 < nwords; line = line + 1) begin
                data16 = 128'd0; mask16 = 16'd0;
                for (w = 0; w < 4; w = w + 1) begin
                    if (line * 4 + w < nwords) begin
                        data16[w*32 +: 32] = prog[line * 4 + w];
                        mask16[w*4 +: 4]   = 4'hf;
                    end
                end
                wr16(line * 16, data16, mask16);
            end
            // Que las escrituras lleguen a la SDRAM antes de arrancar.
            repeat (400) @(posedge clk_mem);
        end
    endtask

    task check_results;
        reg [31:0] got;
        integer k;
        begin
            if (exp_chk[0] != 0 && cpu_pc !== exp_val[0]) begin
                errors = errors + 1;
                $display("FALLO run %0d: pc esperado %h, obtenido %h  (halted=%b error=%b code=%h)",
                         run_i, exp_val[0], cpu_pc, cpu_halted, cpu_error, cpu_error_code);
            end
            for (k = 0; k < 32; k = k + 1) begin
                dbg_reg_addr = k[4:0];
                repeat (6) @(posedge clk);
                got = dbg_reg_data;
                if (exp_chk[k + 1] != 0 && got !== exp_val[k + 1]) begin
                    errors = errors + 1;
                    $display("FALLO run %0d: R%0d esperado %h, obtenido %h", run_i, k, exp_val[k + 1], got);
                end
            end
        end
    endtask

    initial begin
        if (!$value$plusargs("prog=%s", f_prog) || !$value$plusargs("val=%s", f_val) ||
            !$value$plusargs("chk=%s", f_chk) || !$value$plusargs("nwords=%d", nwords)) begin
            $display("Faltan +prog= +val= +chk= +nwords=");
            $finish;
        end
        if (!$value$plusargs("runs=%d", runs)) runs = 3;
        $readmemh(f_prog, prog);
        $readmemh(f_val, exp_val);
        $readmemh(f_chk, exp_chk);
        errors = 0;

        repeat (20) @(posedge clk_mem);
        arst = 1'b0;

        // Esperar a que el controlador termine la inicializacion.
        timeout = 0;
        while (!init_done && timeout < 200000) begin @(posedge clk); timeout = timeout + 1; end
        if (!init_done) begin
            $display("FALLO: init_done no llego"); $finish;
        end
        repeat (50) @(posedge clk);

        // +phantom=1: reproduce lo que se ve en la placa nada mas programarla, con
        // `aceptadas=0`: una respuesta retenida (`hold_valid=1`) en los puertos 0 y
        // 1 que ninguna peticion ha pedido. Se escribe el registro a mano.
        if ($test$plusargs("phantom")) begin
            @(negedge clk);
            g_bridge[0].bridge_i.rsp_hold_data  = 129'd0;
            g_bridge[0].bridge_i.rsp_hold_valid = 1'b1;
            g_bridge[1].bridge_i.rsp_hold_data  = 129'd0;
            g_bridge[1].bridge_i.rsp_hold_valid = 1'b1;
            $display("    (respuesta fantasma inyectada en los puertos 0 y 1)");
        end

        for (run_i = 0; run_i < runs; run_i = run_i + 1) begin
            // reset_cpu del monitor
            @(negedge clk) cpu_reset_request = 1'b1;
            repeat (4) @(posedge clk);
            @(negedge clk) cpu_reset_request = 1'b0;
            repeat (40) @(posedge clk);

            load_program();

            // run
            @(negedge clk) cpu_run_request = 1'b1;
            @(negedge clk) cpu_run_request = 1'b0;
            timeout = 0;
            while (cpu_halted && timeout < 20) begin @(posedge clk); timeout = timeout + 1; end
            timeout = 0;
            while (!cpu_halted && timeout < 400000) begin @(posedge clk); timeout = timeout + 1; end
            if (!cpu_halted) begin
                errors = errors + 1;
                $display("FALLO run %0d: la CPU no paro (pc=%h)", run_i, cpu_pc);
            end else begin
                check_results();
            end
            // Respuestas que quedan retenidas en los bridges al terminar (en la
            // placa, `puerto 1 rsp: hold_valid=1` aparece siempre con nada en vuelo).
            $display("    run %0d: respuestas retenidas  p0=%b p1=%b p3=%b",
                     run_i, m_rsp_valid[0], m_rsp_valid[1], m_rsp_valid[3]);
            if (errors == 0) $display("ok  run %0d: pc=%h", run_i, cpu_pc);
        end

        if (errors == 0) $display("PASS: cpu_fetch_system (%0d ejecuciones)", runs);
        else             $display("FAIL: cpu_fetch_system (%0d errores)", errors);
        $finish;
    end
endmodule

`default_nettype wire
