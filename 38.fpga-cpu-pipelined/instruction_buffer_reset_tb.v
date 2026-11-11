`timescale 1ns / 1ps
`default_nettype none

/*
 * El reset de instruction_buffer debe invalidar las lineas, aunque `cpu_halted`
 * no llegue a subir. Y, con peticion y respuesta separadas, cuatro peticiones
 * seguidas que aciertan se responden en cuatro ciclos seguidos (prueba 5).
 *
 * Es lo que le pasa a la GPU tras un error: el warp se queda vivo y el SM no
 * llega a `halted` (GPU_STATUS = 0x108), asi que el vaciado por `cpu_halted` no
 * ocurre. El arnes manda GPU_CONTROL.RESET antes de cada kernel, que llega aqui
 * como `reset`. Si el reset no invalida, el kernel siguiente acierta en una
 * linea del anterior y ejecuta su codigo viejo.
 */
module instruction_buffer_reset_tb;
    reg clk = 0;
    always #5 clk = ~clk;

    reg reset = 1, init_done = 1, cpu_halted = 0;
    reg         imem_valid = 0;
    reg  [31:0] imem_address = 0;
    wire [31:0] imem_data;
    wire        imem_ready;
    wire        imem_rvalid;

    wire         req_valid;
    reg          req_ready = 1;
    wire [31:0]  req_addr;
    reg          rsp_valid = 0;
    wire         rsp_ready;
    reg  [127:0] rsp_rdata = 0;

    instruction_buffer #(.LINES(4), .INDEX_BITS(2)) dut(
        .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(cpu_halted),
        .cpu_imem_valid(imem_valid), .cpu_imem_address(imem_address),
        .cpu_imem_ready(imem_ready), .cpu_imem_read_data(imem_data),
        .cpu_imem_rvalid(imem_rvalid),
        .req_valid(req_valid), .req_ready(req_ready), .req_write(), .req_addr(req_addr),
        .req_wdata(), .req_wmask(),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(1'b0),
        .hit_count(), .miss_count(), .hit_event(), .miss_event());

    integer errors = 0;
    integer n, misses;

    // Hace una busqueda y, si falla, contesta con `line`. Devuelve si hubo fallo.
    // La peticion se acepta en el flanco en que `ready` esta alto; la respuesta
    // llega despues con `rvalid`.
    task fetch(input [31:0] addr, input [127:0] line, output reg missed, output reg [31:0] got);
        integer t;
        begin
            missed = 0;
            @(negedge clk); imem_address = addr; imem_valid = 1;
            while (!imem_ready) @(negedge clk);
            @(posedge clk); #1 imem_valid = 0;          // aceptada en este flanco
            t = 0;
            while (!imem_rvalid && t < 60) begin
                if (req_valid) missed = 1;
                if (req_valid && req_ready) begin
                    // la respuesta llega un par de ciclos despues
                    repeat (2) @(posedge clk);
                    #1 rsp_rdata = line; rsp_valid = 1;
                    @(posedge clk); #1 rsp_valid = 0;
                end else begin
                    @(posedge clk); #1;
                end
                t = t + 1;
            end
            got = imem_data;
            repeat (3) @(posedge clk);
        end
    endtask

    // Respuestas, con el ciclo en que llegan, para la prueba 5.
    integer cycle = 0, responses = 0;
    reg [31:0] response_data[0:7];
    integer response_cycle[0:7];
    always @(posedge clk) begin
        cycle <= cycle + 1;
        if (imem_rvalid) begin
            response_data[responses] <= imem_data;
            response_cycle[responses] <= cycle;
            responses <= responses + 1;
        end
    end

    reg m; reg [31:0] g;
    initial begin
        repeat (4) @(posedge clk);
        reset = 0;
        repeat (2) @(posedge clk);

        // 1) kernel A: la linea de 0x0 se llena con el codigo de A
        fetch(32'h0, {32'hAAAA0003, 32'hAAAA0002, 32'hAAAA0001, 32'hAAAA0000}, m, g);
        if (!m || g !== 32'hAAAA0000) begin errors = errors + 1; $display("FALLO 1: primera busqueda (miss=%b dato=%h)", m, g); end

        // 2) misma direccion otra vez: acierta, sin pedir nada
        fetch(32'h0, {32'hDEAD0003, 32'hDEAD0002, 32'hDEAD0001, 32'hDEAD0000}, m, g);
        if (m || g !== 32'hAAAA0000) begin errors = errors + 1; $display("FALLO 2: debia acertar (miss=%b dato=%h)", m, g); end

        // 3) GPU_CONTROL.RESET con la GPU SIN halted: solo `reset`, sin cpu_halted
        @(negedge clk); reset = 1;
        repeat (3) @(posedge clk);
        @(negedge clk); reset = 0;
        repeat (2) @(posedge clk);

        // 4) kernel B en la MISMA direccion: debe FALLAR y traer el codigo de B
        fetch(32'h0, {32'hBBBB0003, 32'hBBBB0002, 32'hBBBB0001, 32'hBBBB0000}, m, g);
        if (!m)               begin errors = errors + 1; $display("FALLO 4a: acerto tras el reset (linea vieja)"); end
        if (g !== 32'hBBBB0000) begin errors = errors + 1; $display("FALLO 4b: dato viejo/erroneo %h, esperaba bbbb0000", g); end

        // 5) cuatro peticiones en cuatro ciclos seguidos a la linea de B, que ya
        //    esta: cuatro respuestas en cuatro ciclos seguidos, en orden.
        @(negedge clk); responses = 0;
        for (n = 0; n < 4; n = n + 1) begin
            imem_address = 4 * n; imem_valid = 1;
            @(negedge clk);
            if (!imem_ready) begin errors = errors + 1; $display("FALLO 5a: ready bajo en la peticion %0d", n); end
        end
        imem_valid = 0;
        repeat (3) @(posedge clk); #1;
        if (responses !== 4) begin errors = errors + 1; $display("FALLO 5b: %0d respuestas, esperaba 4", responses); end
        for (n = 0; n < 4; n = n + 1) begin
            if (response_data[n] !== (32'hBBBB0000 | n)) begin
                errors = errors + 1; $display("FALLO 5c: respuesta %0d = %h", n, response_data[n]);
            end
            if (n > 0 && response_cycle[n] !== response_cycle[0] + n) begin
                errors = errors + 1; $display("FALLO 5d: respuesta %0d no llega en el ciclo siguiente", n);
            end
        end

        if (errors == 0) $display("PASS: instruction_buffer_reset");
        else             $display("FAIL: instruction_buffer_reset (%0d errores)", errors);
        $finish;
    end
endmodule

`default_nettype wire
