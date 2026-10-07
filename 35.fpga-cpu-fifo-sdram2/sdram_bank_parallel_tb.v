`timescale 1ns/1ps
`default_nettype none

/*
 * Banco del controlador con los cuatro bancos en paralelo, contra el modelo
 * JEDEC de SDRAM.
 *
 * `sdram_controller_128_tb.v` manda una peticion y espera su `done`: prueba que
 * los datos acaban donde deben, pero no puede tener dos peticiones dentro.
 * Este banco hace lo contrario: presenta peticiones sin esperar respuestas,
 * y comprueba tres cosas.
 *
 *   1. CORRECCION. Un marcador de referencia (una memoria en el propio banco)
 *      predice cada lectura, y cada `done` tiene que traer exactamente eso, en
 *      el orden en que se pidieron. El controlador ejecuta en orden, asi que el
 *      valor esperado de una lectura es el de la memoria en el instante de
 *      pedirla.
 *   2. TEMPORIZACION. El modelo comprueba tRCD, tRP, tRAS, tRC, tRFC y tMRD por
 *      su cuenta, y rechaza una rafaga nueva con otra en curso. Cualquier
 *      violacion cuenta en `errors`. El modelo no conoce tRRD ni el cambio de
 *      sentido del bus; esos los vigila `bus_check` aqui abajo.
 *   3. PARALELISMO. Un barrido que alterna bancos tiene que costar bastante
 *      menos por peticion que uno que se queda en un banco, y los dos bastante
 *      menos que los ~16 ciclos del controlador secuencial de la 34.
 *
 * Corre dos veces, con READ_DELAY_CYCLES 0 y 1, como el banco secuencial: el
 * controlador y el modelo comparten el parametro, asi que lo que se prueba es
 * que la planificacion es correcta para el retardo que sea.
 */
module sdram_bank_unit #(
    parameter integer READ_DELAY = 1,
    parameter integer SEED = 1,
    parameter integer RANDOM_REQUESTS = 3000
) (
    input  wire clk,
    input  wire reset,
    output reg  finished,
    output integer errors
);
    localparam integer CLK_HZ = 100_000_000;
    localparam integer POWERUP_US = 2;
    // Filas modeladas por el banco de memoria (ROWS del modelo = 32).
    localparam integer TEST_ROWS = 4;

    reg req_valid = 0, req_write = 0;
    reg [23:0] req_addr = 0;
    reg [127:0] req_wdata = 0;
    reg [15:0] req_wmask = 0;

    wire req_ready, done, init_done, busy;
    wire [127:0] rdata;
    wire sdram_clk_unused, cke, csn, rasn, casn, wen;
    wire [12:0] a;
    wire [1:0] ba, dqm;
    wire [15:0] dq;

    sdram_controller_128 #(
        .CLK_FREQ_HZ(CLK_HZ), .POWERUP_DELAY_US(POWERUP_US),
        .READ_DELAY_CYCLES(READ_DELAY)
    ) ctrl (
        .clk(clk), .reset(reset),
        .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr),
        .req_wdata(req_wdata), .req_wmask(req_wmask),
        .req_ready(req_ready), .done(done), .rdata(rdata),
        .init_done(init_done), .busy(busy),
        .sdram_clk(sdram_clk_unused), .sdram_cke(cke), .sdram_csn(csn),
        .sdram_rasn(rasn), .sdram_casn(casn), .sdram_wen(wen),
        .sdram_a(a), .sdram_ba(ba), .sdram_dqm(dqm), .sdram_d(dq));

    sdram_model #(
        .POWERUP_DELAY_NS(POWERUP_US * 1000), .READ_DELAY_CYCLES(READ_DELAY)
    ) mem (
        .clk(clk), .cke(cke), .csn(csn), .rasn(rasn), .casn(casn),
        .wen(wen), .a(a), .ba(ba), .dqm(dqm), .dq(dq));

    // -----------------------------------------------------------------
    // Vigilante de bus, lo que el modelo no comprueba.
    // -----------------------------------------------------------------
    localparam [3:0] C_ACTIVE = 4'b0011, C_READ = 4'b0101, C_WRITE = 4'b0100,
                     C_REFRESH = 4'b0001;
    integer cyc = 0;
    integer last_active = -1000;
    integer last_col = -1000;
    integer last_col_write = 0;
    integer bus_errors = 0;
    integer refreshes = 0;
    integer active_count = 0, col_count = 0;
    wire [3:0] cmd = {csn, rasn, casn, wen};

    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (init_done && !reset) begin
            if (cmd == C_ACTIVE) begin
                // tRRD: 15 ns = 2 ciclos.
                if (cyc - last_active < 2) begin
                    $display("[RD=%0d] FALLO: dos ACTIVE con %0d ciclo(s) (tRRD)",
                             READ_DELAY, cyc - last_active);
                    bus_errors = bus_errors + 1;
                end
                last_active <= cyc;
                active_count <= active_count + 1;
            end
            if (cmd == C_READ || cmd == C_WRITE) begin
                // Dos columnas nunca a menos de 8 ciclos; de lectura a
                // escritura, ademas el cambio de sentido del bus.
                if (cyc - last_col < 8) begin
                    $display("[RD=%0d] FALLO: columnas a %0d ciclos", READ_DELAY,
                             cyc - last_col);
                    bus_errors = bus_errors + 1;
                end
                if (cmd == C_WRITE && !last_col_write && cyc - last_col < 12) begin
                    $display("[RD=%0d] FALLO: READ -> WRITE a %0d ciclos", READ_DELAY,
                             cyc - last_col);
                    bus_errors = bus_errors + 1;
                end
                last_col <= cyc;
                last_col_write <= (cmd == C_WRITE);
                col_count <= col_count + 1;
            end
            if (cmd == C_REFRESH) refreshes <= refreshes + 1;
        end
    end

    // -----------------------------------------------------------------
    // Marcador: memoria de referencia y cola de respuestas esperadas.
    // -----------------------------------------------------------------
    reg [127:0] ref_mem [0:TEST_ROWS*4*64-1];
    reg [127:0] exp_data [0:8191];
    reg         exp_read [0:8191];
    integer exp_head = 0, exp_tail = 0;
    integer completions = 0;
    integer data_errors = 0;
    integer n;

    function integer ref_index;
        input [23:0] addr;
        begin
            // fila[1:0], banco, bloque de 16 bytes (columna[8:3])
            ref_index = addr[12:11] * 256 + addr[10:9] * 64 + addr[8:3];
        end
    endfunction

    // Direccion de palabra: fila, banco y bloque.
    function [23:0] make_addr;
        input integer row;
        input integer bank;
        input integer blk;
        begin
            make_addr = (row << 11) | (bank << 9) | (blk << 3);
        end
    endfunction

    reg [127:0] merged;
    integer b;

    task send;
        input write;
        input [23:0] addr;
        input [127:0] wdata;
        input [15:0] wmask;
        reg hs;
        begin
            req_valid = 1'b1;
            req_write = write;
            req_addr = addr;
            req_wdata = wdata;
            req_wmask = wmask;
            hs = 1'b0;
            while (!hs) begin
                @(posedge clk);
                hs = req_ready;
                @(negedge clk);
            end
            // Aceptada: actualizar el marcador.
            exp_read[exp_tail % 8192] = !write;
            if (write) begin
                merged = ref_mem[ref_index(addr)];
                for (b = 0; b < 16; b = b + 1)
                    if (wmask[b]) merged[b*8 +: 8] = wdata[b*8 +: 8];
                ref_mem[ref_index(addr)] = merged;
                exp_data[exp_tail % 8192] = 128'd0;
            end else begin
                exp_data[exp_tail % 8192] = ref_mem[ref_index(addr)];
            end
            exp_tail = exp_tail + 1;
        end
    endtask

    task stop_sending;
        begin
            req_valid = 1'b0;
        end
    endtask

    // Cada `done` corresponde a la peticion mas antigua sin responder.
    always @(posedge clk) begin
        if (done && !reset) begin
            if (exp_head == exp_tail) begin
                $display("[RD=%0d] FALLO: done sin peticion pendiente", READ_DELAY);
                data_errors = data_errors + 1;
            end else begin
                if (exp_read[exp_head % 8192] &&
                    rdata !== exp_data[exp_head % 8192]) begin
                    if (data_errors < 8) begin
                        $display("[RD=%0d] FALLO de datos, respuesta %0d:", READ_DELAY,
                                 completions);
                        $display("   leido    %032x", rdata);
                        $display("   esperado %032x", exp_data[exp_head % 8192]);
                    end
                    data_errors = data_errors + 1;
                end
                exp_head = exp_head + 1;
                completions = completions + 1;
            end
        end
    end

    task drain;
        integer guard;
        begin
            guard = 0;
            while (exp_head != exp_tail && guard < 200_000) begin
                @(negedge clk);
                guard = guard + 1;
            end
            if (exp_head != exp_tail) begin
                $display("[RD=%0d] FALLO: %0d peticiones sin respuesta", READ_DELAY,
                         exp_tail - exp_head);
                data_errors = data_errors + 1;
            end
        end
    endtask

    // -----------------------------------------------------------------
    // Estimulo
    // -----------------------------------------------------------------
    integer seed_v;
    integer t0, t1;
    integer k, r, row, bank, blk, gap;
    reg [127:0] pat;
    reg [15:0] msk;
    reg w;
    integer cost_alt, cost_same, cost_rw;

    function [127:0] pattern;
        input integer tag;
        begin
            pattern = {tag[15:0] ^ 16'h0007, tag[15:0] ^ 16'h0006, tag[15:0] ^ 16'h0005,
                       tag[15:0] ^ 16'h0004, tag[15:0] ^ 16'h0003, tag[15:0] ^ 16'h0002,
                       tag[15:0] ^ 16'h0001, tag[15:0]} ^
                      {8{16'h3c5a}};
        end
    endfunction

    initial begin
        finished = 1'b0;
        errors = 0;
        seed_v = SEED;
        for (n = 0; n < TEST_ROWS*4*64; n = n + 1) ref_mem[n] = 128'd0;

        while (reset) @(negedge clk);
        k = 0;
        while (!init_done && k < 200_000) begin
            @(negedge clk);
            k = k + 1;
        end
        if (!init_done) begin
            $display("[RD=%0d] FALLO: la inicializacion no termino", READ_DELAY);
            errors = errors + 1;
        end
        @(negedge clk);

        // ---- 1. Llenar 64 bloques por banco (filas 0 y 1) --------------
        for (k = 0; k < 4 * 64; k = k + 1)
            send(1'b1, make_addr(0, k % 4, k / 4), pattern(k + 1), 16'hffff);
        for (k = 0; k < 4 * 64; k = k + 1)
            send(1'b1, make_addr(1, k % 4, k / 4), pattern(k + 1000), 16'hffff);
        stop_sending;
        drain;

        // ---- 2. Rendimiento: lecturas alternando los cuatro bancos ------
        t0 = cyc;
        for (k = 0; k < 128; k = k + 1)
            send(1'b0, make_addr(0, k % 4, (k / 4) % 64), 128'd0, 16'h0000);
        stop_sending;
        drain;
        t1 = cyc;
        cost_alt = t1 - t0;
        $display("[RD=%0d] 128 lecturas alternando bancos: %0d ciclos (%0d.%02d por peticion)",
                 READ_DELAY, cost_alt, cost_alt / 128, (cost_alt * 100 / 128) % 100);

        // ---- 3. Rendimiento: lecturas siempre al mismo banco ------------
        t0 = cyc;
        for (k = 0; k < 128; k = k + 1)
            send(1'b0, make_addr(1, 2, k % 64), 128'd0, 16'h0000);
        stop_sending;
        drain;
        t1 = cyc;
        cost_same = t1 - t0;
        $display("[RD=%0d] 128 lecturas al mismo banco:   %0d ciclos (%0d.%02d por peticion)",
                 READ_DELAY, cost_same, cost_same / 128, (cost_same * 100 / 128) % 100);

        // ---- 4. Rendimiento: lecturas y escrituras mezcladas ------------
        t0 = cyc;
        for (k = 0; k < 128; k = k + 1)
            send(k[1] , make_addr(0, k % 4, (k / 4) % 64), pattern(k + 5000), 16'hffff);
        stop_sending;
        drain;
        t1 = cyc;
        cost_rw = t1 - t0;
        $display("[RD=%0d] 128 accesos R/W alternados:    %0d ciclos (%0d.%02d por peticion)",
                 READ_DELAY, cost_rw, cost_rw / 128, (cost_rw * 100 / 128) % 100);

        // El controlador secuencial de la 34 necesitaba unos 16 ciclos por
        // peticion en cualquier caso. Alternar bancos tiene que acercarse a los
        // 8 del bus de datos; el mismo banco queda limitado por tRC y la
        // precarga, pero sigue por debajo de lo secuencial.
        if (cost_alt > 128 * 10) begin
            $display("[RD=%0d] FALLO: alternar bancos cuesta mas de 10 ciclos por peticion", READ_DELAY);
            errors = errors + 1;
        end
        if (cost_same > 128 * 14) begin
            $display("[RD=%0d] FALLO: el mismo banco cuesta mas de 14 ciclos por peticion", READ_DELAY);
            errors = errors + 1;
        end
        if (cost_alt * 10 > cost_same * 9) begin
            $display("[RD=%0d] FALLO: alternar bancos no mejora al mismo banco", READ_DELAY);
            errors = errors + 1;
        end

        // ---- 5. Trafico aleatorio con pausas, lecturas y escrituras ------
        // Dura varios periodos de refresco, asi que el vaciado con peticiones
        // dentro tambien se ejercita.
        for (k = 0; k < RANDOM_REQUESTS; k = k + 1) begin
            r = $random(seed_v);
            row = (r >> 3) & 1;
            bank = (r >> 8) & 3;
            blk = (r >> 12) & 63;
            w = ((r >> 20) & 3) == 0 || ((r >> 20) & 3) == 1;
            msk = ((r >> 24) & 3) == 0 ? ($random(seed_v) & 16'hffff) : 16'hffff;
            pat = {$random(seed_v), $random(seed_v), $random(seed_v), $random(seed_v)};
            send(w, make_addr(row, bank, blk), pat, msk);
            // De vez en cuando, una pausa: la tuberia tiene que vaciarse y
            // volver a llenarse sin perder el hilo.
            gap = ($random(seed_v) & 31) == 0 ? ($random(seed_v) & 63) : 0;
            if (gap != 0) begin
                stop_sending;
                repeat (gap) @(negedge clk);
            end
        end
        stop_sending;
        drain;

        // ---- 6. Nada se ha corrompido: leer todo y comparar -------------
        for (k = 0; k < 4 * 64; k = k + 1)
            send(1'b0, make_addr(0, k % 4, k / 4), 128'd0, 16'h0000);
        for (k = 0; k < 4 * 64; k = k + 1)
            send(1'b0, make_addr(1, k % 4, k / 4), 128'd0, 16'h0000);
        stop_sending;
        drain;

        if (refreshes < 8 + 3) begin
            $display("[RD=%0d] FALLO: solo %0d refrescos en toda la prueba", READ_DELAY,
                     refreshes);
            errors = errors + 1;
        end
        if (mem.errors != 0) begin
            $display("[RD=%0d] FALLO: el modelo conto %0d violaciones JEDEC", READ_DELAY,
                     mem.errors);
            errors = errors + 1;
        end
        errors = errors + data_errors + bus_errors;

        $display("[RD=%0d] %0d respuestas, %0d ACTIVE, %0d columnas, %0d refrescos",
                 READ_DELAY, completions, active_count, col_count, refreshes - 8);
        finished = 1'b1;
    end
endmodule

module sdram_bank_parallel_tb;
    reg clk = 0;
    reg reset = 1;
    always #5 clk = ~clk;

    wire fin0, fin1;
    integer err0, err1;
    integer guard;

    sdram_bank_unit #(.READ_DELAY(0), .SEED(11)) unit0 (
        .clk(clk), .reset(reset), .finished(fin0), .errors(err0));
    sdram_bank_unit #(.READ_DELAY(1), .SEED(22)) unit1 (
        .clk(clk), .reset(reset), .finished(fin1), .errors(err1));

    initial begin
        repeat (4) @(negedge clk);
        reset = 0;

        guard = 0;
        while (!(fin0 && fin1) && guard < 2_000_000) begin
            @(negedge clk);
            guard = guard + 1;
        end
        if (!(fin0 && fin1))
            $fatal(1, "el banco no termino (%b %b)", fin0, fin1);
        if (err0 != 0 || err1 != 0)
            $fatal(1, "%0d + %0d comprobaciones fallaron", err0, err1);
        $display("PASS: sdram_bank_parallel");
        $finish;
    end
endmodule

`default_nettype wire
