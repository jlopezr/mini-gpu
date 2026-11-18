`timescale 1ns / 1ps
`default_nettype none

/*
 * Banco de ESTRES de fabric_fifo_bridge (async_fifo de peticion y de respuesta).
 *
 * Busca el fallo que veiamos en la placa: la CPU recibe una linea de
 * instrucciones corrida una entrada (16 B) de la FIFO. El banco normal
 * (fabric_fifo_bridge_tb) manda UNA peticion; la CPU, al rellenar una linea,
 * manda rafagas de peticiones seguidas y llena y vacia la FIFO.
 *
 * Que hace, repetido para muchas combinaciones de reloj:
 *   - relojes con periodos y fases distintos, y con jitter ciclo a ciclo, para
 *     recorrer alineaciones raras entre los dos dominios;
 *   - el maestro manda peticiones en rafagas (1..8 seguidas) con huecos
 *     aleatorios, sin esperar a las respuestas;
 *   - el lado de memoria las saca de la FIFO a ritmo aleatorio, las contesta
 *     con retardo aleatorio y puede quedarse sin sitio (mem_rsp_full);
 *   - el maestro acepta las respuestas a ritmo aleatorio (rsp_ready).
 *
 * Comprueba, por cada peticion: que llega a memoria en el MISMO ORDEN, con SUS
 * datos y direccion, y que su respuesta vuelve en orden con el dato esperado.
 * Cualquier entrada repetida, saltada o corrida da FALLO con el numero de
 * peticion. Solo prueba la LOGICA: no modela metaestabilidad ni skew fisico.
 */
module fabric_fifo_bridge_stress_tb;
    localparam integer CONFIGS = 40;     // combinaciones de reloj
    localparam integer REQS    = 4000;   // peticiones por combinacion

    reg mclk = 0, fclk = 0;
    reg mrst = 1, frst = 1;

    // Medio periodo de cada reloj (ns) y amplitud de jitter, cambian por config.
    real m_half = 5.0, f_half = 5.0;
    real m_jit  = 0.0, f_jit  = 0.0;
    integer seed = 32'h1234abcd;

    function real jitter(input real half, input real amp);
        integer rr;
        begin
            rr = $random(seed);
            jitter = half * (1.0 + amp * (((rr & 32'hffff) / 65535.0) - 0.5) * 2.0);
        end
    endfunction

    always begin #(jitter(m_half, m_jit)) mclk = ~mclk; end
    always begin #(jitter(f_half, f_jit)) fclk = ~fclk; end

    // ---------------- DUT ----------------
    reg          req_valid = 0;
    wire         req_ready;
    reg  [31:0]  req_addr = 0;
    reg  [127:0] req_wdata = 0;
    wire         rsp_valid;
    reg          rsp_ready = 0;
    wire [127:0] rsp_rdata;
    wire         rsp_error;

    wire         mem_empty, mem_rd_valid, mem_rsp_full;
    wire [177:0] mem_data;
    reg          mem_rd_en = 0;
    wire         mem_wr_en;
    wire [128:0] mem_rsp;

    fabric_fifo_bridge dut(
        .master_clk(mclk), .master_reset(mrst),
        .req_valid(req_valid), .req_ready(req_ready), .req_urgent(1'b0),
        .req_write(1'b0), .req_addr(req_addr), .req_wdata(req_wdata), .req_wmask(16'hffff),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
        .rsp_rdata(rsp_rdata), .rsp_error(rsp_error),
        .mem_clk(fclk), .mem_reset(frst),
        .mem_req_empty(mem_empty), .mem_req_rd_en(mem_rd_en),
        .mem_req_rd_valid(mem_rd_valid), .mem_req_data(mem_data),
        .mem_rsp_full(mem_rsp_full), .mem_rsp_wr_en(mem_wr_en), .mem_rsp_data(mem_rsp),
        .dbg_req_ptrs(), .dbg_rsp());

    // Dato esperado de cada peticion: depende del numero, para que una entrada
    // corrida o repetida no pueda pasar por buena.
    function [127:0] pat(input integer n);
        reg [31:0] a, b, c, d, k;
        begin
            k = n;
            a = 32'hA5000000 ^ k;
            b = 32'h5A000000 + k * 32'd3;
            c = 32'hC3000000 ^ (k * 32'd7);
            d = k * 32'h9E3779B1;
            pat = {a, b, c, d};
        end
    endfunction

    integer errors = 0;
    integer cfg;
    integer r;

    // ---------------- Maestro: genera peticiones en rafagas ----------------
    integer sent;
    integer burst_left, gap_left;
    integer s_next;
    reg     v;
    always @(posedge mclk) begin
        if (!mrst) begin
            s_next = sent;
            v      = req_valid;
            if (v && req_ready) begin          // se acepto la que estaba puesta
                s_next = s_next + 1;
                v      = 1'b0;
            end
            if (!v && s_next < REQS) begin
                if (burst_left > 0) begin
                    burst_left = burst_left - 1;
                    v = 1'b1;
                end else if (gap_left > 0) begin
                    gap_left = gap_left - 1;
                end else begin
                    r = $random(seed);
                    burst_left = 1 + ((r >>> 4) & 7);
                    gap_left   = ((r & 3) == 0) ? ((r >>> 8) & 15) : 0;
                end
            end
            if (v && (!req_valid || req_ready)) begin   // peticion nueva (tambien encadenada)
                req_addr  <= s_next;
                req_wdata <= pat(s_next);
            end
            req_valid <= v;
            sent = s_next;
        end
    end

    // ---------------- Memoria: saca peticiones y las contesta ----------------
    // Cola de respuestas pendientes (numero de peticion), con retardo aleatorio.
    // El estado se actualiza con asignaciones NO bloqueantes y la escritura de la
    // respuesta es COMBINACIONAL en `mem_rsp_full`, como en el fabric real: si no,
    // se escribiria en un ciclo en que la FIFO ya se lleno y la entrada se perderia.
    integer pend [0:63];
    integer pend_head, pend_tail, pend_cnt;
    integer delay_left;
    integer expect_req, got_req;
    integer r2;

    wire do_wr = !frst && (pend_cnt > 0) && (delay_left == 0) && !mem_rsp_full;
    assign mem_wr_en = do_wr;
    assign mem_rsp   = {1'b0, ~pat(pend[pend_head])};

    always @(posedge fclk) begin
        if (!frst) begin
            // Captura del dato leido (lectura sincrona: rd_valid un ciclo despues de rd_en).
            if (mem_rd_valid) begin
                if (mem_data[175:144] !== expect_req || mem_data[143:16] !== pat(expect_req)) begin
                    errors = errors + 1;
                    if (errors < 20)
                        $display("FALLO cfg %0d: peticion en memoria: esperaba #%0d, llego addr=%0d dato=%h (t=%0t)",
                                 cfg, expect_req, mem_data[175:144], mem_data[143:16], $time);
                end
                pend[pend_tail] <= expect_req;
                pend_tail  <= (pend_tail + 1) % 64;
                expect_req = expect_req + 1;
                got_req    = got_req + 1;
            end
            pend_cnt <= pend_cnt + (mem_rd_valid ? 1 : 0) - (do_wr ? 1 : 0);

            // Pedir lectura a ritmo aleatorio, sin desbordar la cola de pendientes.
            r2 = $random(seed);
            mem_rd_en <= (!mem_empty) && (pend_cnt < 40) && ((r2 & 3) != 0);

            // Retardo aleatorio entre respuestas.
            if (do_wr) begin
                pend_head <= (pend_head + 1) % 64;
                r2 = $random(seed);
                delay_left <= ((r2 & 3) == 0) ? ((r2 >>> 4) & 7) : 0;
            end else if (delay_left > 0 && pend_cnt > 0) begin
                delay_left <= delay_left - 1;
            end
        end
    end
    // ---------------- Maestro: recibe respuestas en orden ----------------
    integer expect_rsp, got_rsp;
    integer r3;
    always @(posedge mclk) begin
        if (!mrst) begin
            r3 = $random(seed);
            rsp_ready <= ((r3 & 3) != 0);
            if (rsp_valid && rsp_ready) begin
                if (rsp_rdata !== ~pat(expect_rsp)) begin
                    errors = errors + 1;
                    if (errors < 20)
                        $display("FALLO cfg %0d: respuesta: esperaba #%0d (%h), llego %h (t=%0t)",
                                 cfg, expect_rsp, ~pat(expect_rsp), rsp_rdata, $time);
                end
                expect_rsp = expect_rsp + 1;
                got_rsp    = got_rsp + 1;
            end
        end
    end

    // ---------------- Control de configuraciones ----------------
    integer timeout;
    integer start_errors;
    initial begin
        for (cfg = 0; cfg < CONFIGS; cfg = cfg + 1) begin
            // Periodos entre 7 y 28 ns por reloj; las tres primeras son
            // combinaciones utiles fijas (80/100 MHz, 25/100 MHz, iguales).
            case (cfg)
                0: begin m_half = 6.25; f_half = 5.0;  end   // 80 / 100 MHz (placa)
                1: begin m_half = 20.0; f_half = 5.0;  end   // 25 / 100 MHz (GPU)
                2: begin m_half = 5.0;  f_half = 5.0;  end   // iguales
                default: begin
                    r = $random(seed); m_half = 3.5 + ((r & 32'hfff) / 4095.0) * 10.5;
                    r = $random(seed); f_half = 3.5 + ((r & 32'hfff) / 4095.0) * 10.5;
                end
            endcase
            m_jit = (cfg % 3 == 0) ? 0.0 : 0.08;
            f_jit = (cfg % 3 == 1) ? 0.0 : 0.08;

            // Reset limpio de todo el entorno.
            mrst = 1; frst = 1;
            req_valid = 0; mem_rd_en = 0; rsp_ready = 0;
            sent = 0; got_req = 0; got_rsp = 0;
            burst_left = 0; gap_left = 0;
            pend_head = 0; pend_tail = 0; pend_cnt = 0; delay_left = 0;
            expect_req = 0; expect_rsp = 0;
            start_errors = errors;
            #(7.3 * 6);
            @(negedge mclk) mrst = 0;
            #(3.1 + cfg);
            @(negedge fclk) frst = 0;

            timeout = 0;
            while ((got_rsp < REQS) && (timeout < 400000)) begin
                @(posedge mclk);
                timeout = timeout + 1;
            end
            if (got_rsp < REQS) begin
                errors = errors + 1;
                $display("FALLO cfg %0d: se quedo colgado: enviadas=%0d en_memoria=%0d respuestas=%0d (m=%0.2f ns, f=%0.2f ns)",
                         cfg, sent, got_req, got_rsp, 2*m_half, 2*f_half);
            end
            if (errors == start_errors)
                $display("ok  cfg %2d: m=%6.2f ns f=%6.2f ns  %0d peticiones", cfg, 2*m_half, 2*f_half, REQS);
            else
                $display("MAL cfg %2d: m=%6.2f ns f=%6.2f ns  errores=%0d", cfg, 2*m_half, 2*f_half, errors - start_errors);
            mrst = 1; frst = 1;
            #50;
        end
        if (errors == 0) $display("PASS: fabric_fifo_bridge_stress (%0d configuraciones)", CONFIGS);
        else             $display("FAIL: fabric_fifo_bridge_stress (%0d errores)", errors);
        $finish;
    end
endmodule

`default_nettype wire
