`default_nettype none
`timescale 1ns/1ps
// Corre examples/smoke.bin en el sistema BL8 exactamente como lo hace
// run-board: reset de GPU (ocho warps llenos a PC=0), cargar el programa byte
// a byte por el host, arrancar, y leer R1. Sin fixtures ni config words, que es
// justo lo que hace la placa.
//
// Existe para separar "el programa esta mal" de "solo falla en placa".
module gpu_smoke_tb;
    reg clk=0;
    always #20 clk=~clk;
    reg reset=1,gpu_reset=0,run_request=0,halt_request=0,step_request=0;
    wire halted,error,retired;
    wire [7:0] error_code;
    reg [31:0] host_address=0;
    reg [7:0] host_write_data=0;
  // WRITE_WORD. La instanciacion es .*, asi que estas dos tienen que
  // existir con el nombre exacto del puerto o el banco no elabora.
  reg [31:0] host_write_word=0; reg host_write_word_enable=0;
    reg host_write_enable=0,host_read_enable=0;
    wire [7:0] host_read_data;
    wire [31:0] host_read_word;   // la misma lectura sin trocear
    wire host_ready,host_error;
    reg [4:0] debug_register=0;
    wire [31:0] debug_data,debug_pc;
    `include "sim/system_memory_bl8.vh"
    // Puertos de video que llegaron con la ventana MMIO. Este banco no los usa,
    // pero .* exige que existan en el ambito.
    wire [1:0] video_mode;
    wire [23:0] video_fb_base;
    wire video_underflow_clear;
    wire video_underflow = 1'b0;
    wire video_frame_pulse = 1'b0;
    // Puerto 2 del fabric, el del scanout. Este banco no lo ejercita, pero la
    // conexion por comodin exige que los identificadores existan en el ambito.
    wire p2_req_valid = 1'b0, p2_req_write = 1'b0, p2_urgent = 1'b0;
    wire p2_rsp_ready = 1'b1;
    wire [31:0] p2_req_addr = 32'd0;
    wire [127:0] p2_req_wdata = 128'd0;
    wire [15:0] p2_req_wmask = 16'd0;
    wire p2_req_ready, p2_rsp_valid, p2_rsp_error;
    wire [127:0] p2_rsp_rdata;

    gpu_system_bl8 dut(.*,.instruction_retired(retired));

    reg [31:0] program_words[0:255];
    reg [7:0] byte_result;
    integer i,cycles;

    task access;
        input wr;
        input [31:0] addr;
        input [7:0] data;
        begin
            @(negedge clk); host_address=addr; host_write_data=data;
            host_write_enable=wr; host_read_enable=!wr;
            @(negedge clk); host_write_enable=0; host_read_enable=0;
            cycles=0;
            while(!host_ready && cycles<100) begin @(negedge clk); cycles=cycles+1; end
            if(!host_ready || host_error) $fatal(1,"host access failed %h",addr);
            byte_result=host_read_data;
        end
    endtask
    task write_word;
        input [31:0] addr,data;
        integer j;
        begin for(j=0;j<4;j=j+1) access(1,addr+j,data[j*8 +: 8]); end
    endtask

    initial begin
        for(i=0;i<256;i=i+1) program_words[i]=32'h0;
        // Las mismas tres palabras que ensambla examples/smoke.asm.
        program_words[0]=32'h4020_0007;  // MOVI R1, 7
        program_words[1]=32'hc800_0000;  // BAR
        program_words[2]=32'hfc00_0000;  // HALT

        repeat(4) @(negedge clk); reset=0;
        @(negedge clk); gpu_reset=1;
        @(negedge clk); gpu_reset=0;
        wait(halted); @(negedge clk);

        for(i=0;i<4;i=i+1) write_word(i*4,program_words[i]);

        @(negedge clk); run_request=1;
        @(negedge clk); run_request=0;
        cycles=0;
        while(!halted && cycles<200000) begin @(negedge clk); cycles=cycles+1; end
        $display("halted=%b error=%b code=%h pc=%h cycles=%0d",
                 halted,error,error_code,debug_pc,cycles);

        // Leer R1 de warp 0, lane 0.
        access(1,32'h82020000,8'd0);
        @(negedge clk); debug_register=1;
        repeat(3) @(negedge clk);
        $display("R1 = %h", debug_data);
        if(error) $fatal(1,"SMOKE: FALLO, error_code=%h", error_code);
        else if(debug_data===32'd7) $display("SMOKE: OK, R1=7");
        else $fatal(1,"SMOKE: FALLO, R1=%h y esperaba 7", debug_data);
        $finish;
    end
    initial begin #50000000; $fatal(1,"SMOKE: timeout"); end
endmodule
`default_nettype wire
