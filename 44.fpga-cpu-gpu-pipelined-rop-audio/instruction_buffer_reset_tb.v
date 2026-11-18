`timescale 1ns / 1ps
`default_nettype none

/*
 * El reset de instruction_buffer debe invalidar las lineas, aunque `cpu_halted`
 * no llegue a subir. Y, con peticion y respuesta separadas, cuatro peticiones
 * seguidas que aciertan se responden en cuatro ciclos seguidos, cada una dos
 * ciclos despues de aceptarse (prueba 5).
 *
 * Con la cache en EBR la consulta va en dos ciclos, asi que cuando una
 * peticion falla la siguiente ya esta aceptada y hay que repetirla despues del
 * relleno: las pruebas 6 a 9 cubren ese caso con un modelo de memoria
 * automatico, y la 10 la vuelta de la epoca (2 bits: tres invalidaciones).
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
    // Las respuestas las da la tarea `fetch` (pruebas 1 a 5) o el modelo
    // automatico (pruebas 6 en adelante).
    reg          auto_mem = 0;
    reg          man_rsp_valid = 0;
    reg  [127:0] man_rsp_rdata = 0;
    reg          auto_rsp_valid = 0;
    reg  [127:0] auto_rsp_rdata = 0;
    wire         rsp_valid = auto_mem ? auto_rsp_valid : man_rsp_valid;
    wire [127:0] rsp_rdata = auto_mem ? auto_rsp_rdata : man_rsp_rdata;
    wire         rsp_ready;

    wire hit_event, miss_event;
    instruction_buffer #(.LINES(4), .INDEX_BITS(2), .EPOCH_BITS(2)) dut(
        .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(cpu_halted),
        .cpu_imem_valid(imem_valid), .cpu_imem_address(imem_address),
        .cpu_imem_ready(imem_ready), .cpu_imem_read_data(imem_data),
        .cpu_imem_rvalid(imem_rvalid),
        .req_valid(req_valid), .req_ready(req_ready), .req_write(), .req_addr(req_addr),
        .req_wdata(), .req_wmask(),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(1'b0),
        .hit_count(), .miss_count(), .hit_event(hit_event), .miss_event(miss_event));

    integer errors = 0;
    integer n, misses;
    integer accept_cycle;

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
                    #1 man_rsp_rdata = line; man_rsp_valid = 1;
                    @(posedge clk); #1 man_rsp_valid = 0;
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
    reg [31:0] response_data[0:63];
    integer response_cycle[0:63];
    always @(posedge clk) begin
        cycle <= cycle + 1;
        if (imem_rvalid) begin
            response_data[responses] <= imem_data;
            response_cycle[responses] <= cycle;
            responses <= responses + 1;
        end
    end

    // -- Modelo automatico de memoria ------------------------------------------
    // Cada palabra vale {version, 8'h00, direccion[15:0]}: si la memoria
    // "cambia por detras" (el monitor carga otro programa) basta con subir
    // `version`. Contesta 3 ciclos despues de aceptar.
    reg [7:0] version = 8'h01;
    integer requests = 0;
    reg [31:0] auto_addr;
    integer auto_wait = 0;
    function [31:0] word_at(input [31:0] a);
        word_at = {version, 8'h00, a[15:0]};
    endfunction
    always @(posedge clk) begin
        auto_rsp_valid <= 1'b0;
        if (auto_wait > 1) auto_wait <= auto_wait - 1;
        if (auto_wait == 1) begin
            auto_wait <= 0;
            auto_rsp_valid <= 1'b1;
            auto_rsp_rdata <= {word_at({auto_addr[31:4], 4'hC}), word_at({auto_addr[31:4], 4'h8}),
                               word_at({auto_addr[31:4], 4'h4}), word_at({auto_addr[31:4], 4'h0})};
        end
        if (auto_mem && req_valid && req_ready) begin
            requests = requests + 1;
            auto_addr <= req_addr;
            auto_wait <= 3;
        end
    end
    integer hits = 0, misses_seen = 0;
    always @(posedge clk) begin
        if (hit_event) hits = hits + 1;
        if (miss_event) misses_seen = misses_seen + 1;
    end

    // Una secuencia de peticiones como las hace la CPU: `valid` alto y la
    // direccion siguiente en cuanto se acepta la anterior. `ready` sale de un
    // registro, asi que su valor a mitad de ciclo es el del flanco.
    reg [31:0] seq_addr[0:31];
    integer k;
    task run_sequence(input integer n);
        integer t;
        begin
            @(negedge clk); responses = 0; k = 0; t = 0;
            while (k < n && t < 400) begin
                imem_address = seq_addr[k]; imem_valid = 1;
                @(negedge clk);
                if (imem_ready === 1'b1) k = k + 1;   // aceptada en el flanco de en medio
                t = t + 1;
            end
            imem_valid = 0;
            t = 0;
            while (responses < n && t < 400) begin @(posedge clk); t = t + 1; end
            repeat (2) @(posedge clk); #1;
        end
    endtask
    // Compara la respuesta i con lo que hay en la direccion de la peticion i.
    task check_sequence(input integer n, input [8*24-1:0] name);
        integer j;
        begin
            if (responses !== n) begin
                errors = errors + 1; $display("FALLO %0s: %0d respuestas, esperaba %0d", name, responses, n);
            end
            for (j = 0; j < n; j = j + 1) begin
                if (seq_addr[j][31:25] != 0) begin
                    if (response_data[j] !== 32'hf800_0000) begin
                        errors = errors + 1; $display("FALLO %0s: respuesta %0d = %h, esperaba f8000000", name, j, response_data[j]);
                    end
                end else if (response_data[j] !== word_at(seq_addr[j])) begin
                    errors = errors + 1; $display("FALLO %0s: respuesta %0d = %h, esperaba %h", name, j, response_data[j], word_at(seq_addr[j]));
                end
            end
        end
    endtask
    integer req_before, hits_before, misses_before;
    task expect_requests(input integer n, input [8*24-1:0] name);
        begin
            if (requests - req_before !== n) begin
                errors = errors + 1; $display("FALLO %0s: %0d lineas pedidas, esperaba %0d", name, requests - req_before, n);
            end
            req_before = requests;
        end
    endtask

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
            if (n == 0) accept_cycle = cycle;
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
        // El acierto tarda DOS ciclos: aceptada en el flanco t, `rvalid` en el
        // ciclo que acaba en t + 2 (la respuesta sale registrada).
        if (response_cycle[0] - accept_cycle !== 1) begin
            errors = errors + 1;
            $display("FALLO 5e: el acierto tarda %0d ciclos, esperaba 2",
                     response_cycle[0] - accept_cycle + 1);
        end

        // ---- Modelo automatico a partir de aqui ----
        repeat (3) @(posedge clk);
        auto_mem = 1; req_before = requests;

        // 6) Flujo continuo de 12 busquedas sobre tres lineas que no estan:
        //    cada fallo tiene la busqueda siguiente ya aceptada detras, que
        //    acierta al repetirse (es de la misma linea). Tres lineas pedidas.
        for (n = 0; n < 12; n = n + 1) seq_addr[n] = 32'h0000_0200 + 4 * n;
        run_sequence(12);
        check_sequence(12, "6 flujo");
        expect_requests(3, "6 flujo");

        // 7) Lo mismo otra vez: todo acierta, sin pedir nada, una por ciclo.
        run_sequence(12);
        check_sequence(12, "7 flujo en cache");
        expect_requests(0, "7 flujo en cache");
        if (response_cycle[11] - response_cycle[0] !== 11) begin
            errors = errors + 1; $display("FALLO 7: 12 aciertos en %0d ciclos", response_cycle[11] - response_cycle[0] + 1);
        end

        // 8) Fallo con la de detras en OTRA linea que si esta: B acierta tras
        //    repetirse. Y al reves: A acierta y B falla. Con 4 lineas el indice
        //    son los bits [5:4]: 0x200-0x22C ocupan los indices 0 a 2, y todo
        //    lo de esta prueba y la 9 va al 3 para no expulsarlas.
        seq_addr[0] = 32'h0000_0330; seq_addr[1] = 32'h0000_0204;
        seq_addr[2] = 32'h0000_0208; seq_addr[3] = 32'h0000_0370;
        run_sequence(4);
        check_sequence(4, "8 detras en otra linea");
        expect_requests(2, "8 detras en otra linea");

        // 9) Fallo con la de detras FUERA de rango: opcode invalido, en orden.
        seq_addr[0] = 32'h0000_03B0; seq_addr[1] = 32'h0400_0000;
        seq_addr[2] = 32'h0000_03B4;
        run_sequence(3);
        check_sequence(3, "9 detras fuera de rango");
        expect_requests(1, "9 detras fuera de rango");

        // 10) La vuelta de la epoca con `cpu_halted`: la memoria cambia por
        //     detras y tras tres paradas (vuelta y barrido) se ve lo nuevo. Sin
        //     el barrido la linea resucitaria con la version vieja.
        for (n = 0; n < 4; n = n + 1) seq_addr[n] = 32'h0000_0200 + 4 * n;
        run_sequence(4);
        expect_requests(0, "10 en cache");
        for (n = 0; n < 3; n = n + 1) begin
            version = version + 1;
            repeat (3) begin
                @(negedge clk); cpu_halted = 1; repeat (5) @(negedge clk); cpu_halted = 0;
            end
            run_sequence(4);
            check_sequence(4, "10 tras la vuelta");
            expect_requests(1, "10 tras la vuelta");
        end

        // 11) Contadores: un pulso por busqueda cacheable.
        hits_before = hits; misses_before = misses_seen;
        seq_addr[0] = 32'h0000_0530; seq_addr[1] = 32'h0000_0534; seq_addr[2] = 32'h0000_0538;
        run_sequence(3);
        if (hits - hits_before !== 2 || misses_seen - misses_before !== 1) begin
            errors = errors + 1;
            $display("FALLO 11: %0d aciertos y %0d fallos, esperaba 2 y 1", hits - hits_before, misses_seen - misses_before);
        end

        if (errors == 0) $display("PASS: instruction_buffer_reset");
        else             $display("FAIL: instruction_buffer_reset (%0d errores)", errors);
        $finish;
    end
endmodule

`default_nettype wire
