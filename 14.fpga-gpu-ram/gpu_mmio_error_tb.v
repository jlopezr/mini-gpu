`timescale 1ns/1ps
module gpu_mmio_error_tb;
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
    `include "sim/system_memory.vh"
    gpu_system dut(.*,.instruction_retired(retired));
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

`include "sim/sdram_model.vh"
