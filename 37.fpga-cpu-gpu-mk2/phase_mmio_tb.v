`timescale 1ns/1ps
`default_nettype none

module phase_mmio_tb;
    reg clk = 0;
    always #6.25 clk = ~clk;
    reg reset = 1;
    reg select = 0, write = 0;
    reg [3:0] write_mask = 4'hf;
    reg [15:0] address = 0;
    reg [31:0] write_data = 0;
    wire [31:0] read_data;
    wire error;
    wire req_toggle;
    wire [5:0] req_steps;
    reg ack_toggle = 0, phase_busy = 0, phase_err = 0;
    reg [5:0] phase_pos_gray = 0;
    reg pll_locked = 1, init_done = 1;
    wire quiesce;

    phase_mmio dut (
        .clk(clk), .reset(reset), .select(select), .write(write),
        .write_mask(write_mask), .address(address), .write_data(write_data),
        .read_data(read_data), .error(error),
        .req_toggle(req_toggle), .req_steps(req_steps),
        .ack_toggle_async(ack_toggle), .phase_busy_async(phase_busy),
        .phase_err_async(phase_err), .phase_pos_gray_async(phase_pos_gray),
        .pll_locked_async(pll_locked), .init_done_async(init_done),
        .quiesce(quiesce));

    task mmio_write;
        input [15:0] addr;
        input [31:0] data;
        begin
            @(negedge clk);
            address = addr;
            write_data = data;
            write = 1;
            select = 1;
            @(posedge clk);
            #1;
            select = 0;
            write = 0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        reset = 0;
        repeat (4) @(posedge clk);

        mmio_write(16'h0000, 32'h0000_0301); // START, 3 pasos, delay.
        if (error || !quiesce || req_steps != 3 || req_toggle != 1)
            $fatal(1, "primera peticion no aceptada");

        // Sigue pendiente: no debe cambiar toggle ni sobrescribir pasos.
        mmio_write(16'h0000, 32'h0000_0201);
        if (!error || req_toggle != 1 || req_steps != 3)
            $fatal(1, "peticion durante busy no rechazada");

        // Ack asincrono: dos ciclos de sincronizacion y se libera quiesce.
        ack_toggle = req_toggle;
        repeat (5) @(posedge clk);
        if (quiesce)
            $fatal(1, "ack no libero la peticion");

        // DIR=1 (avance) esta prohibido por riesgo de glitches.
        mmio_write(16'h0000, 32'h0000_0103);
        if (!error || req_toggle != 1)
            $fatal(1, "avance no rechazado");

        $display("PASS: phase_mmio");
        $finish;
    end
endmodule

`default_nettype wire
