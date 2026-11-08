`timescale 1ns/1ps
`default_nettype none

module pll_phase_ctl_tb;
    reg clk = 0;
    reg reset = 1;
    always #5 clk = ~clk;

    reg req_toggle = 0;
    reg [5:0] req_steps = 0;
    wire ack_toggle;
    reg safe_idle = 1;
    reg init_done = 1;
    reg pll_locked = 1;
    wire phasestep, phasedir, phaseloadreg, controller_reset;
    wire traffic_block, busy, err;
    wire [1:0] phasesel;
    wire [5:0] phase_pos, phase_pos_gray;

    pll_phase_ctl #(.GUARD_CYCLES(2), .RESET_CYCLES(3)) dut (
        .clk(clk), .reset(reset),
        .req_toggle_async(req_toggle), .req_steps_async(req_steps),
        .ack_toggle(ack_toggle), .safe_idle(safe_idle),
        .controller_init_done(init_done), .pll_locked(pll_locked),
        .phasestep(phasestep), .phasedir(phasedir), .phasesel(phasesel),
        .phaseloadreg(phaseloadreg), .controller_reset(controller_reset),
        .traffic_block(traffic_block), .busy(busy), .err(err),
        .phase_pos(phase_pos), .phase_pos_gray(phase_pos_gray));

    integer low_pulses = 0;
    integer reset_cycles = 0;
    reg saw_block = 0;
    reg saw_reset = 0;

    always @(negedge phasestep) low_pulses = low_pulses + 1;
    always @(posedge clk) begin
        if (traffic_block) saw_block <= 1;
        if (controller_reset) begin
            saw_reset <= 1;
            reset_cycles <= reset_cycles + 1;
            init_done <= 0;
        end else if (saw_reset && !init_done) begin
            // Modelo abreviado de la reinicializacion del controlador SDRAM.
            init_done <= 1;
        end
        if (busy && traffic_block && !safe_idle)
            $fatal(1, "traffic_block solo puede empezar tras safe_idle");
    end

    task request_steps;
        input [5:0] count;
        begin
            req_steps = count;
            req_toggle = ~req_toggle;
            wait (busy);
            wait (ack_toggle == req_toggle);
            repeat (3) @(posedge clk);
        end
    endtask

    initial begin
        repeat (4) @(posedge clk);
        reset = 0;
        repeat (3) @(posedge clk);

        request_steps(6'd3);
        if (phase_pos != 3 || low_pulses != 3 || err)
            $fatal(1, "tres pasos: pos=%0d pulsos=%0d err=%0d", phase_pos, low_pulses, err);
        if (!saw_block || !saw_reset || reset_cycles != 3)
            $fatal(1, "no se observo bloqueo/reset correcto");
        if (phasedir !== 0 || phasesel !== 0 || phaseloadreg !== 1)
            $fatal(1, "seleccion/direccion del PLL incorrecta");

        // 3 + 45 = 48: una vuelta completa vuelve a cero.
        saw_reset = 0;
        reset_cycles = 0;
        request_steps(6'd45);
        if (phase_pos != 0 || low_pulses != 48 || err)
            $fatal(1, "wrap: pos=%0d pulsos=%0d err=%0d", phase_pos, low_pulses, err);

        // Una peticion invalida se completa con error y sin tocar la fase.
        request_steps(6'd0);
        if (!err || phase_pos != 0 || low_pulses != 48)
            $fatal(1, "peticion invalida no rechazada");

        // Tras el reset/reinit el camino vuelve a estar disponible.
        if (busy || traffic_block || controller_reset || !init_done)
            $fatal(1, "el subsistema no quedo operativo");

        $display("PASS: pll_phase_ctl");
        $finish;
    end
endmodule

`default_nettype wire
