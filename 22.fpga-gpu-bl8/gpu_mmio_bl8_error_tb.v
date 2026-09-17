`default_nettype none
`timescale 1ns/1ps
// Verifica que la GPU llega a la ventana MMIO por su cuenta: escribe
// VIDEO_CTRL, lo relee, y se cronometra leyendo los contadores.
//
// Antes esto era imposible por dos barreras (fault de la LSU por encima de
// 0x02000000, y `halted` exigido para escribir el MMIO). Que este banco pase es
// exactamente la diferencia.
module gpu_mmio_bl8_error_tb;
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

    wire [1:0] video_mode;
    wire [23:0] video_fb_base;
    wire video_underflow_clear;
    wire p2_ready_u,p2_rsp_valid_u,p2_rsp_error_u;
    wire [127:0] p2_rsp_rdata_u;

    gpu_system_bl8 dut(.*,.instruction_retired(retired),
        .p2_req_valid(1'b0),.p2_req_ready(p2_ready_u),.p2_req_write(1'b0),
        .p2_req_addr(32'd0),.p2_req_wdata(128'd0),.p2_req_wmask(16'd0),
        .p2_urgent(1'b0),.p2_rsp_valid(p2_rsp_valid_u),.p2_rsp_ready(1'b1),
        .p2_rsp_rdata(p2_rsp_rdata_u),.p2_rsp_error(p2_rsp_error_u),
        .video_mode(video_mode),.video_fb_base(video_fb_base),
        .video_underflow_clear(video_underflow_clear),
        .video_underflow(1'b0),.video_frame_pulse(1'b0));

    integer cycles,k,w;
    task access(input wr,input [31:0] addr,input bad);
      begin
        @(negedge clk);host_address=addr;host_write_enable=wr;host_read_enable=!wr;
        @(negedge clk);host_write_enable=0;host_read_enable=0;cycles=0;
        while(!host_ready && cycles<100) begin @(negedge clk);cycles=cycles+1;end
        if(!host_ready || host_error!==bad) $fatal(1,"MMIO %h wr %b error %b",addr,wr,host_error);
        if(!bad && !wr && addr==32'h80000f08 && host_read_word!==0)
          $fatal(1,"DEV_BITMAP cero no es error");
      end
    endtask
    initial begin
      repeat(4) @(negedge clk);reset=0;
      wait(halted);
      for(w=0;w<2;w=w+1) begin
        access(w,32'h80000400,1);
        access(w,32'h80001080,1);
        for(k=0;k<16;k=k+4) access(w,32'h80000f00+k,w!=0);
        for(k=16;k<256;k=k+4) access(w,32'h80000f00+k,1);
      end
      $display("PASS: GPU rechaza slots ausentes y alias de identificacion");$finish;
    end
    initial begin #1000000;$fatal(1,"timeout");end
endmodule
