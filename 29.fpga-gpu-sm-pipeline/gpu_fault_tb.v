`timescale 1ns/1ps
`default_nettype none

// Regresion del bloqueo que aparecia con NOP; TRAP; HALT: TRAP no se retira,
// pero sus lanes deben completar el token de X para que el fallo llegue al SM.
module gpu_fault_tb;
    reg clk=0; always #5 clk=~clk;
    reg reset=1, run_request=0, halt_request=0, step_request=0;
    wire halted, error, instruction_retired, error_lane_valid, no_warp_stall;
    wire [7:0] error_code, retired_lanes;
    wire [2:0] error_warp, error_lane;
    wire [31:0] error_pc, retired_count, debug_warp_retired_count;
    reg [2:0] debug_warp=0, debug_lane=0;
    reg [4:0] debug_register=0, cfg_word=0;
    reg [1:0] cfg_bank=0;           // 0: descriptores (§14.2)
    wire [31:0] debug_data, debug_pc, cfg_read_data;
    reg cfg_write=0;
    reg [31:0] cfg_data=0;
    reg [3:0] cfg_strobe=0;

    wire imem_valid, imem_rsp_ready;
    wire [31:0] imem_address;
    reg imem_rsp_valid=0, imem_error=0;
    wire imem_ready=!imem_rsp_valid;
    reg [31:0] imem_data=0;

    wire lsu_valid, lsu_rsp_ready;
    reg lsu_ready=1, lsu_rsp_valid=0;
    wire [2:0] lsu_tag;
    reg [2:0] lsu_rsp_tag=0;
    wire [7:0] lsu_mask;
    wire lsu_write, lsu_signed;
    wire [1:0] lsu_size;
    wire [255:0] lsu_address, lsu_data;
    reg [255:0] lsu_rsp_data=0;
    reg [7:0] lsu_rsp_error=0, lsu_occupied=0;

    gpu_sm dut(.*);

    always @(posedge clk) begin
        if (reset) begin
            imem_rsp_valid<=0;
        end else begin
            if (imem_rsp_valid && imem_rsp_ready) imem_rsp_valid<=0;
            if (imem_valid && imem_ready) begin
                imem_rsp_valid<=1;
                case (imem_address)
                    0: imem_data<=32'h00000000; // NOP
                    4: imem_data<=32'hf8000000; // TRAP
                    default: imem_data<=32'hfc000000; // HALT, no alcanzable
                endcase
            end
        end
    end

    integer cycles;
    initial begin
        repeat(4) @(negedge clk);
        reset=0;
        wait(halted);
        @(negedge clk); run_request=1;
        @(negedge clk); run_request=0;

        cycles=0;
        while(!halted && cycles<2000) begin
            @(negedge clk);
            cycles=cycles+1;
        end
        if(!halted) $fatal(1,"TRAP dejo el cauce bloqueado");
        if(!error || error_code!==8'h03 || error_pc!==32'd4)
            $fatal(1,"fallo TRAP incorrecto: error=%b code=%h pc=%h",
                   error,error_code,error_pc);
        $display("PASS: TRAP global vacia X y detiene el SM");
        $finish;
    end

    initial begin #1000000; $fatal(1,"gpu_fault_tb watchdog"); end
endmodule

`default_nettype wire
