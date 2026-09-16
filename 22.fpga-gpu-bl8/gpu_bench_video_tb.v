`default_nettype none
`timescale 1ns/1ps
// Corre examples/smoke.bin en el sistema BL8 exactamente como lo hace
// run-board: reset de GPU (ocho warps llenos a PC=0), cargar el programa byte
// a byte por el host, arrancar, y leer R1. Sin fixtures ni config words, que es
// justo lo que hace la placa.
//
// Existe para separar "el programa esta mal" de "solo falla en placa".
module gpu_bench_video_tb;
    reg clk=0;
    always #20 clk=~clk;
    reg reset=1,gpu_reset=0,run_request=0,halt_request=0,step_request=0;
    wire halted,error,retired;
    wire [7:0] error_code;
    reg [31:0] host_address=0;
    reg [7:0] host_write_data=0;
    reg host_write_enable=0,host_read_enable=0;
    wire [7:0] host_read_data;
    wire host_ready,host_error;
    reg [4:0] debug_register=0;
    wire [31:0] debug_data,debug_pc;
    `include "sim/system_memory_bl8.vh"
    wire v_valid,v_ready,v_write,v_urgent,v_rsp_valid,v_rsp_error;
    wire [31:0] v_addr;
    wire [127:0] v_wdata,v_rsp_rdata;
    wire [15:0] v_wmask;
    wire [31:0] v_tx;
    // VIDEO=1 enciende el trafico sintetico de scanout.
    reg video_on=0;
    // Puertos de video que llegaron con la ventana MMIO. Este banco no los usa,
    // pero .* exige que existan en el ambito.
    wire [1:0] video_mode;
    wire [23:0] video_fb_base;
    wire video_underflow_clear;
    wire video_underflow = 1'b0;
    wire video_frame_pulse = 1'b0;
    gpu_system_bl8 dut(.*,.instruction_retired(retired),
        .p2_req_valid(v_valid),.p2_req_ready(v_ready),.p2_req_write(v_write),
        .p2_req_addr(v_addr),.p2_req_wdata(v_wdata),.p2_req_wmask(v_wmask),
        .p2_urgent(v_urgent),.p2_rsp_valid(v_rsp_valid),.p2_rsp_ready(1'b1),
        .p2_rsp_rdata(v_rsp_rdata),.p2_rsp_error(v_rsp_error));
    video_traffic_gen video(.clk(clk),.reset(reset),.enable(video_on),
        .req_valid(v_valid),.req_ready(v_ready),.req_write(v_write),
        .req_addr(v_addr),.req_wdata(v_wdata),.req_wmask(v_wmask),.urgent(v_urgent),
        .rsp_valid(v_rsp_valid),.rsp_ready(),.rsp_rdata(v_rsp_rdata),
        .rsp_error(v_rsp_error),.transactions(v_tx));

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

    // Transacciones de 16 bytes completadas, para sacar el coste real por
    // transaccion y de ahi el ancho de banda del canal.
    integer tx_done=0, run_cycles=0;
    reg counting=0;
    always @(posedge clk) if(!reset && counting && mem_done) tx_done=tx_done+1;

    initial begin
        for(i=0;i<256;i=i+1) program_words[i]=32'h0;
        // examples/bench.bin, ensamblado con 1.isa/miniisa_asm.py.
        $readmemh("examples/bench.hex",program_words);

        repeat(4) @(negedge clk); reset=0;
        @(negedge clk); gpu_reset=1;
        @(negedge clk); gpu_reset=0;
        wait(halted); @(negedge clk);

        for(i=0;i<16;i=i+1) write_word(i*4,program_words[i]);

        video_on=1;
        counting=1;
        @(negedge clk); run_request=1;
        @(negedge clk); run_request=0;
        cycles=0;
        while(!halted && cycles<20000000) begin @(negedge clk); cycles=cycles+1; end
        counting=0;
        $display("halted=%b error=%b code=%h pc=%h cycles=%0d",
                 halted,error,error_code,debug_pc,cycles);

        // R1 = tid, solo para confirmar que corrio.
        access(1,32'h80000100,8'd0);
        @(negedge clk); debug_register=1;
        repeat(3) @(negedge clk);
        $display("R1 = %h", debug_data);
        $display("BENCH: R1(tid)=%h", debug_data);
        $display("BENCH+VIDEO: tx_totales=%0d de_video=%0d ciclos/tx=%0d", tx_done, v_tx, run_cycles/tx_done);
        $finish;
    end
    initial begin #5000000000; $fatal(1,"BENCH: timeout"); end
endmodule
`default_nettype wire
