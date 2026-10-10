`default_nettype none

/*
 * Control experimental de fase del reloj externo de SDRAM.
 *
 * Vive en clk_mem. La peticion llega por toggle; req_steps permanece estable
 * desde antes del toggle hasta que ack_toggle vuelve al dominio de origen. El
 * PHASESTEP del EHXPLLL se captura en el flanco de bajada y Lattice exige al
 * menos cuatro ciclos de VCO entre pasos. Un pulso bajo y otro alto, cada uno
 * de un ciclo de clk_mem (100 MHz), dejan 20 ns entre flancos de bajada.
 *
 * Solo se retrasa CLKOS: PHASEDIR=0 y PHASESEL=00. Adelantar puede producir
 * glitches. Con VCO=600 MHz hay 48 pasos de 1/(8*VCO)=208,33 ps por vuelta.
 */
module pll_phase_ctl #(
    parameter [5:0] PHASE_STEPS = 6'd48,
    parameter [7:0] GUARD_CYCLES = 8'd8,
    parameter [7:0] RESET_CYCLES = 8'd16
) (
    input  wire       clk,
    input  wire       reset,

    input  wire       req_toggle_async,
    input  wire [5:0] req_steps_async,
    output reg        ack_toggle,

    // Todo el trafico previo debe haber drenado antes de tocar el PLL.
    input  wire       safe_idle,
    input  wire       controller_init_done,
    input  wire       pll_locked,

    output reg        phasestep,
    output wire       phasedir,
    output wire [1:0] phasesel,
    output wire       phaseloadreg,
    output reg        controller_reset,
    output reg        traffic_block,
    output reg        busy,
    output reg        err,
    output reg  [5:0] phase_pos,
    output wire [5:0] phase_pos_gray
);
    localparam [3:0] ST_IDLE       = 4'd0;
    localparam [3:0] ST_DRAIN      = 4'd1;
    localparam [3:0] ST_STEP_LOW   = 4'd2;
    localparam [3:0] ST_STEP_HIGH  = 4'd3;
    localparam [3:0] ST_GUARD      = 4'd4;
    localparam [3:0] ST_RESET      = 4'd5;
    localparam [3:0] ST_WAIT_INIT  = 4'd6;
    localparam [3:0] ST_COMPLETE   = 4'd7;

    reg req_meta, req_sync, req_seen;
    reg [5:0] steps_left;
    reg [7:0] wait_count;
    reg [3:0] state;

    assign phasedir = 1'b0;       // 0 = delay/lag, unico modo sin glitches.
    assign phasesel = 2'b00;      // CLKOS, no CLKOP (que es el feedback).
    assign phaseloadreg = 1'b1;
    assign phase_pos_gray = phase_pos ^ (phase_pos >> 1);

    always @(posedge clk) begin
        req_meta <= req_toggle_async;
        req_sync <= req_meta;

        if (reset) begin
            req_meta <= 1'b0;
            req_sync <= 1'b0;
            req_seen <= 1'b0;
            ack_toggle <= 1'b0;
            phasestep <= 1'b1;
            controller_reset <= 1'b0;
            traffic_block <= 1'b0;
            busy <= 1'b0;
            err <= 1'b0;
            phase_pos <= 6'd0;
            steps_left <= 6'd0;
            wait_count <= 8'd0;
            state <= ST_IDLE;
        end else begin
            phasestep <= 1'b1;

            case (state)
                ST_IDLE: begin
                    busy <= 1'b0;
                    controller_reset <= 1'b0;
                    traffic_block <= 1'b0;
                    if (req_sync != req_seen) begin
                        req_seen <= req_sync;
                        busy <= 1'b1;
                        err <= 1'b0;
                        // 1..48 son validos. Cero no significa 64 ni no-op:
                        // se rechaza para descubrir errores del host.
                        if (req_steps_async == 0 || req_steps_async > PHASE_STEPS) begin
                            err <= 1'b1;
                            state <= ST_COMPLETE;
                        end else begin
                            steps_left <= req_steps_async;
                            state <= ST_DRAIN;
                        end
                    end
                end

                ST_DRAIN: begin
                    if (!pll_locked) begin
                        err <= 1'b1;
                        state <= ST_COMPLETE;
                    end else if (safe_idle) begin
                        traffic_block <= 1'b1;
                        state <= ST_STEP_LOW;
                    end
                end

                ST_STEP_LOW: begin
                    phasestep <= 1'b0;
                    state <= ST_STEP_HIGH;
                end

                ST_STEP_HIGH: begin
                    if (phase_pos == PHASE_STEPS - 1'b1)
                        phase_pos <= 6'd0;
                    else
                        phase_pos <= phase_pos + 1'b1;

                    if (steps_left == 1) begin
                        wait_count <= GUARD_CYCLES - 1'b1;
                        state <= ST_GUARD;
                    end else begin
                        steps_left <= steps_left - 1'b1;
                        state <= ST_STEP_LOW;
                    end
                end

                ST_GUARD: begin
                    if (wait_count == 0) begin
                        controller_reset <= 1'b1;
                        wait_count <= RESET_CYCLES - 1'b1;
                        state <= ST_RESET;
                    end else begin
                        wait_count <= wait_count - 1'b1;
                    end
                end

                ST_RESET: begin
                    controller_reset <= 1'b1;
                    if (wait_count == 0) begin
                        controller_reset <= 1'b0;
                        state <= ST_WAIT_INIT;
                    end else begin
                        wait_count <= wait_count - 1'b1;
                    end
                end

                ST_WAIT_INIT: begin
                    if (!pll_locked) begin
                        err <= 1'b1;
                        state <= ST_COMPLETE;
                    end else if (controller_init_done) begin
                        state <= ST_COMPLETE;
                    end
                end

                ST_COMPLETE: begin
                    busy <= 1'b0;
                    controller_reset <= 1'b0;
                    traffic_block <= 1'b0;
                    ack_toggle <= req_seen;
                    state <= ST_IDLE;
                end

                default: begin
                    err <= 1'b1;
                    state <= ST_COMPLETE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
