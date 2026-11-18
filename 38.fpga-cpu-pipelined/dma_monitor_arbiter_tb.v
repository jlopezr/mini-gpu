
`timescale 1ns/1ps
`default_nettype none

module dma_monitor_arbiter_tb;

    localparam TAG_DEPTH = 8;

    reg clk = 0;
    always #5 clk = ~clk;

    reg reset = 1;

    reg mon_req_valid = 0;
    wire mon_req_ready;
    reg mon_req_write = 0;
    reg [31:0] mon_req_addr = 0;
    reg [127:0] mon_req_wdata = 0;
    reg [15:0] mon_req_wmask = 0;

    wire mon_rsp_valid;
    reg mon_rsp_ready = 1;
    wire [127:0] mon_rsp_rdata;
    wire mon_rsp_error;

    reg dma_req_valid = 0;
    wire dma_req_ready;
    reg dma_req_write = 0;
    reg [31:0] dma_req_addr = 0;
    reg [127:0] dma_req_wdata = 0;
    reg [15:0] dma_req_wmask = 0;

    wire dma_rsp_valid;
    reg dma_rsp_ready = 1;
    wire [127:0] dma_rsp_rdata;
    wire dma_rsp_error;

    wire req_valid, req_urgent, req_write;
    reg req_ready = 0;
    wire [31:0] req_addr;
    wire [127:0] req_wdata;
    wire [15:0] req_wmask;

    wire rsp_ready;
    wire rsp_valid;
    wire [127:0] rsp_rdata;
    wire rsp_error;

    dma_monitor_arbiter #(
        .TAG_DEPTH(TAG_DEPTH)
    ) dut (
        .clk(clk), .reset(reset),

        .mon_req_valid(mon_req_valid),
        .mon_req_ready(mon_req_ready),
        .mon_req_write(mon_req_write),
        .mon_req_addr(mon_req_addr),
        .mon_req_wdata(mon_req_wdata),
        .mon_req_wmask(mon_req_wmask),
        .mon_rsp_valid(mon_rsp_valid),
        .mon_rsp_ready(mon_rsp_ready),
        .mon_rsp_rdata(mon_rsp_rdata),
        .mon_rsp_error(mon_rsp_error),

        .dma_req_valid(dma_req_valid),
        .dma_req_ready(dma_req_ready),
        .dma_req_write(dma_req_write),
        .dma_req_addr(dma_req_addr),
        .dma_req_wdata(dma_req_wdata),
        .dma_req_wmask(dma_req_wmask),
        .dma_rsp_valid(dma_rsp_valid),
        .dma_rsp_ready(dma_rsp_ready),
        .dma_rsp_rdata(dma_rsp_rdata),
        .dma_rsp_error(dma_rsp_error),

        .req_valid(req_valid),
        .req_ready(req_ready),
        .req_urgent(req_urgent),
        .req_write(req_write),
        .req_addr(req_addr),
        .req_wdata(req_wdata),
        .req_wmask(req_wmask),

        .rsp_valid(rsp_valid),
        .rsp_ready(rsp_ready),
        .rsp_rdata(rsp_rdata),
        .rsp_error(rsp_error)
    );

    // ----------------------------------------------------------
    // Modelo del puerto de memoria.
    // Cada petición produce exactamente una respuesta, en orden.
    // ----------------------------------------------------------

    reg expected_owner [0:2047];  // 0 monitor, 1 DMA
    reg [127:0] expected_data [0:2047];
    reg expected_error [0:2047];

    integer head = 0;
    integer tail = 0;
    integer count = 0;

    reg allow_response = 0;

    assign rsp_valid = (count != 0) && allow_response;
    assign rsp_rdata = (count != 0) ? expected_data[head] : 128'd0;
    assign rsp_error = (count != 0) ? expected_error[head] : 1'b0;

    // Cada dirección de prueba genera una respuesta reconocible.
    function [127:0] response_data(input [31:0] addr);
        response_data = {4{addr ^ 32'hA5C3_197E}};
    endfunction

    integer accepted_mon = 0;
    integer accepted_dma = 0;
    integer completed_mon = 0;
    integer completed_dma = 0;
    integer simultaneous = 0;
    integer full_cycles = 0;
    integer stalled_responses = 0;
    integer concurrent_push_pop = 0;

    reg mon_fire = 0;
    reg dma_fire = 0;
    reg push, pop;

    integer discarded_mon = 0;
    integer discarded_dma = 0;
    integer resets_with_pending = 0;
    integer n;

    // Comprobador y modelo de memoria.
    always @(posedge clk) begin
        if (reset) begin
            if (count > 0)
                resets_with_pending = resets_with_pending + 1;

            for (n = head; n < tail; n = n + 1) begin
                if (expected_owner[n])
                    discarded_dma = discarded_dma + 1;
                else
                    discarded_mon = discarded_mon + 1;
            end

            head = 0;
            tail = 0;
            count = 0;
            mon_fire = 0;
            dma_fire = 0;
        end else begin
            mon_fire = mon_req_valid && mon_req_ready;
            dma_fire = dma_req_valid && dma_req_ready;
            push = req_valid && req_ready;
            pop = rsp_valid && rsp_ready;

            if (req_urgent !== 1'b0)
                $fatal(1, "El DMA/monitor no debe ser urgente");

            if (mon_req_ready && dma_req_ready)
                $fatal(1, "Dos concesiones simultaneas");

            if (mon_req_valid && dma_req_valid && req_ready &&
                count < TAG_DEPTH) begin
                simultaneous = simultaneous + 1;
                if (!mon_fire || dma_fire)
                    $fatal(1, "Fallo de prioridad del monitor");
            end

            if (push !== (mon_fire || dma_fire))
                $fatal(1, "Handshake de salida inconsistente");

            if (count == TAG_DEPTH) begin
                full_cycles = full_cycles + 1;
                if (push)
                    $fatal(1, "Aceptacion con FIFO llena");
            end

            if (rsp_valid && !rsp_ready)
                stalled_responses = stalled_responses + 1;

            if (push && pop)
                concurrent_push_pop = concurrent_push_pop + 1;

            // Comprobar respuesta antes de retirar su propietario.
            if (rsp_valid) begin
                if (count == 0)
                    $fatal(1, "Respuesta sin solicitud");

                if (expected_owner[head] == 1'b0) begin
                    if (!mon_rsp_valid || dma_rsp_valid)
                        $fatal(1, "Respuesta encaminada al DMA en vez del monitor");

                    if (rsp_ready !== mon_rsp_ready)
                        $fatal(1, "Backpressure del monitor incorrecto");

                    if (mon_rsp_rdata !== expected_data[head] ||
                        mon_rsp_error !== expected_error[head])
                        $fatal(1, "Datos/error del monitor incorrectos");

                end else begin
                    if (!dma_rsp_valid || mon_rsp_valid)
                        $fatal(1, "Respuesta encaminada al monitor en vez del DMA");

                    if (rsp_ready !== dma_rsp_ready)
                        $fatal(1, "Backpressure del DMA incorrecto");

                    if (dma_rsp_rdata !== expected_data[head] ||
                        dma_rsp_error !== expected_error[head])
                        $fatal(1, "Datos/error del DMA incorrectos");
                end
            end else if (mon_rsp_valid || dma_rsp_valid) begin
                $fatal(1, "Respuesta espuria");
            end

            if (pop) begin
                if (expected_owner[head])
                    completed_dma = completed_dma + 1;
                else
                    completed_mon = completed_mon + 1;

                head = head + 1;
                count = count - 1;
            end

            if (push) begin
                expected_owner[tail] = dma_fire;
                expected_data[tail] = response_data(req_addr);
                expected_error[tail] = req_addr[4];

                if (mon_fire) begin
                    if (req_addr !== mon_req_addr ||
                        req_write !== mon_req_write ||
                        req_wdata !== mon_req_wdata ||
                        req_wmask !== mon_req_wmask)
                        $fatal(1, "Solicitud de monitor alterada");
                    accepted_mon = accepted_mon + 1;
                end else begin
                    if (req_addr !== dma_req_addr ||
                        req_write !== dma_req_write ||
                        req_wdata !== dma_req_wdata ||
                        req_wmask !== dma_req_wmask)
                        $fatal(1, "Solicitud de DMA alterada");
                    accepted_dma = accepted_dma + 1;
                end

                tail = tail + 1;
                count = count + 1;
            end

            if (count > TAG_DEPTH || count < 0)
                $fatal(1, "Numero de pendientes fuera de rango");
        end
    end

    // ----------------------------------------------------------
    // Estímulos.
    // Los productores mantienen VALID hasta recibir READY.
    // ----------------------------------------------------------

    integer cycle;
    integer mon_id = 0;
    integer dma_id = 0;

    initial begin
        $dumpvars(0, dma_monitor_arbiter_tb);

        for (cycle = 0; cycle < 700; cycle = cycle + 1) begin
            @(negedge clk);

            // Reset inicial y otro con transacciones pendientes.
            reset = (cycle < 4 || cycle == 300 ||
                     cycle == 301);

            if (reset) begin
                mon_req_valid = 0;
                dma_req_valid = 0;
                mon_id = 0;
                dma_id = 0;
            end else begin
                if (mon_fire)
                    mon_req_valid = 0;

                if (dma_fire)
                    dma_req_valid = 0;

                // No emitir nuevas solicitudes durante el drenado final.
                if (cycle < 620) begin
                    if (!mon_req_valid && cycle % 5 == 0) begin
                        mon_req_valid = 1;
                        mon_req_addr = 32'h0010_0000 + mon_id * 16;
                        mon_req_write = mon_id[0];
                        mon_req_wdata = {4{mon_id}};
                        mon_req_wmask = 16'h00FF;
                        mon_id = mon_id + 1;
                    end

                    if (!dma_req_valid) begin
                        dma_req_valid = 1;
                        dma_req_addr = 32'h0020_0000 + dma_id * 16;
                        dma_req_write = dma_id[0];
                        dma_req_wdata = {4{dma_id ^ 32'h12345678}};
                        dma_req_wmask = 16'hFFFF;
                        dma_id = dma_id + 1;
                    end
                end
            end

            // Simular que el bridge no siempre puede aceptar.
            req_ready = (cycle % 13 != 0);

            // Forzar acumulacion de solicitudes antes del reset.
            allow_response = (cycle >= 4) &&
                             (cycle < 270 || cycle > 301) &&
                             (cycle % 47 >= 11);

            mon_rsp_ready = (cycle % 31 >= 7);
            dma_rsp_ready = (cycle % 23 >= 5);
        end

        // Comprobaciones finales.
        if (count != 0)
            $fatal(1, "Respuestas pendientes al terminar");

        if (simultaneous == 0 || full_cycles == 0 ||
            stalled_responses == 0 || concurrent_push_pop == 0)
            $fatal(1, "Falta cobertura de escenarios");

        if (accepted_mon == 0 || accepted_dma == 0 ||
            completed_mon == 0 || completed_dma == 0)
            $fatal(1, "Un maestro no ha participado");

        if (accepted_mon != completed_mon + discarded_mon)
            $fatal(1,
                "MONITOR: aceptadas=%0d completadas=%0d descartadas=%0d",
                accepted_mon, completed_mon, discarded_mon);

        if (accepted_dma != completed_dma + discarded_dma)
            $fatal(1,
                "DMA: aceptadas=%0d completadas=%0d descartadas=%0d",
                accepted_dma, completed_dma, discarded_dma);

        if (resets_with_pending == 0)
            $fatal(1, "No se ha probado reset con peticiones pendientes");

        if (count != 0)
            $fatal(1, "Quedan %0d respuestas pendientes", count);

        $display("PASS dma_monitor_arbiter");
        $display("Monitor: %0d aceptadas, %0d completadas",
                 accepted_mon, completed_mon);
        $display("DMA: %0d aceptadas, %0d completadas",
                 accepted_dma, completed_dma);
        $display("Simultaneas: %0d  FIFO llena: %0d",
                 simultaneous, full_cycles);
        $display("Respuestas bloqueadas: %0d  Push+pop: %0d",
                 stalled_responses, concurrent_push_pop);

        $display("Monitor: %0d aceptadas, %0d completadas, %0d descartadas",
                 accepted_mon, completed_mon, discarded_mon);

        $display("DMA: %0d aceptadas, %0d completadas, %0d descartadas",
                 accepted_dma, completed_dma, discarded_dma);

        $finish;
    end

endmodule

`default_nettype wire
