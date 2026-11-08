`timescale 1ns / 1ps
`default_nettype none

/*
 * Banco de fabric_fifo_bridge: relojes asincronos y resets liberados en
 * momentos distintos, en los dos ordenes.
 *   - mientras falte un lado: req_ready=0 (maestro) y mem_req_empty=1 /
 *     mem_rsp_full=1 (memoria), sin importar que el maestro tenga req_valid;
 *   - cuando los dos estan arriba: una peticion cruza, el lado de memoria la
 *     lee y devuelve una respuesta que el maestro recibe.
 */
module fabric_fifo_bridge_tb;
    reg mclk = 0, fclk = 0;
    reg mrst = 1, frst = 1;
    always #5   mclk = ~mclk;     // 100 MHz
    always #3.7 fclk = ~fclk;     // ~135 MHz, sin relacion con mclk

    reg         req_valid = 0;
    wire        req_ready;
    reg [127:0] wdata = 128'h0123456789abcdef_0011223344556677;
    wire        rsp_valid;
    wire [127:0] rsp_rdata;
    wire        rsp_error;
    wire        mem_empty, mem_rd_valid, mem_rsp_full;
    wire [177:0] mem_data;
    reg         mem_rd_en = 0, mem_wr_en = 0;
    reg  [128:0] mem_rsp = 0;
    integer errors = 0;

    fabric_fifo_bridge dut(
        .master_clk(mclk), .master_reset(mrst),
        .req_valid(req_valid), .req_ready(req_ready), .req_urgent(1'b0),
        .req_write(1'b1), .req_addr(32'h100), .req_wdata(wdata), .req_wmask(16'hffff),
        .rsp_valid(rsp_valid), .rsp_ready(1'b1),
        .rsp_rdata(rsp_rdata), .rsp_error(rsp_error),
        .mem_clk(fclk), .mem_reset(frst),
        .mem_req_empty(mem_empty), .mem_req_rd_en(mem_rd_en),
        .mem_req_rd_valid(mem_rd_valid), .mem_req_data(mem_data),
        .mem_rsp_full(mem_rsp_full), .mem_rsp_wr_en(mem_wr_en), .mem_rsp_data(mem_rsp),
        .dbg_req_ptrs(), .dbg_rsp());

    task check(input cond, input [255:0] what);
        if (!cond) begin errors = errors + 1; $display("FALLO: %0s (t=%0t)", what, $time); end
    endtask

    // Hasta que ambos lados esten arriba no debe haber aceptacion ni visibilidad.
    task wait_both_up_checking(input first_is_master);
        integer i;
        begin
            req_valid = 1;
            for (i = 0; i < 40; i = i + 1) begin
                @(posedge mclk);
                #0.1;
                if (first_is_master) begin
                    // el lado de memoria sigue en reset
                    check(!req_ready, "req_ready=0 con el lado de memoria en reset");
                    check(mem_empty && mem_rsp_full, "memoria no ve trafico en reset");
                end
            end
            req_valid = 0;
        end
    endtask

    integer n;
    initial begin
        repeat (6) @(posedge mclk);

        // --- Caso A: el maestro sale primero; memoria sigue en reset ---
        @(negedge mclk) mrst = 0;
        wait_both_up_checking(1);
        // La peticion no debe haberse colado: tras salir memoria, la FIFO esta vacia.
        @(negedge fclk) frst = 0;
        repeat (12) @(posedge fclk);
        check(mem_empty, "FIFO vacia tras liberar memoria (nada se colo en reset)");

        // --- Respuesta FANTASMA: llega una respuesta sin peticion ---
        // En la placa pasaba tras programarla; el consumidor la tomaba por la
        // contestacion a su primera peticion y todo llegaba corrido una posicion.
        // Debe tirarse sin llegar a verse.
        @(posedge fclk); #1 mem_rsp = {1'b0, 128'hbad0_bad0_bad0_bad0_bad0_bad0_bad0_bad0}; mem_wr_en = 1;
        @(posedge fclk); #1 mem_wr_en = 0;
        n = 0;
        repeat (40) begin
            @(posedge mclk); #1;
            if (rsp_valid) n = n + 1;
        end
        check(n == 0, "una respuesta sin peticion no se ensena al maestro");

        // --- Peticion normal con los dos arriba ---
        @(posedge mclk); #1 req_valid = 1;
        n = 0;
        while (!req_ready && n < 50) begin @(posedge mclk); #1; n = n + 1; end
        check(req_ready, "req_ready=1 con los dos lados arriba");
        @(posedge mclk); #1 req_valid = 0;
        n = 0;
        while (mem_empty && n < 50) begin @(posedge fclk); #1; n = n + 1; end
        check(!mem_empty, "la peticion llega al lado de memoria");
        mem_rd_en = 1; @(posedge fclk); #1 mem_rd_en = 0;
        n = 0;
        while (!mem_rd_valid && n < 10) begin @(posedge fclk); #1; n = n + 1; end
        check(mem_rd_valid && mem_data[143:16] === wdata, "datos de escritura intactos");
        mem_rsp = {1'b0, 128'hdeadbeef_cafef00d_12345678_9abcdef0};
        mem_wr_en = 1; @(posedge fclk); #1 mem_wr_en = 0;
        n = 0;
        while (!rsp_valid && n < 50) begin @(posedge mclk); #1; n = n + 1; end
        check(rsp_valid && rsp_rdata === 128'hdeadbeef_cafef00d_12345678_9abcdef0,
              "respuesta recibida por el maestro");

        // --- Caso B: memoria sale primero ---
        mrst = 1; frst = 1;
        repeat (6) @(posedge mclk);
        @(negedge fclk) frst = 0;
        repeat (30) @(posedge fclk);
        check(mem_empty && mem_rsp_full, "memoria no ve trafico con el maestro en reset");
        @(negedge mclk) mrst = 0;
        repeat (12) @(posedge mclk);
        #1 check(req_ready, "req_ready=1 tras salir tambien el maestro");

        if (errors == 0) $display("PASS: fabric_fifo_bridge");
        else $display("FAIL: fabric_fifo_bridge (%0d errores)", errors);
        $finish;
    end
endmodule

`default_nettype wire
