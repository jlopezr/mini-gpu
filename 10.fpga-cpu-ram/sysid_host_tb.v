`default_nettype none
`timescale 1ns/1ps
// Se instancia el top real: SYS_ID en 6/10 intercepta el bus fuera del
// adaptador de RAM. Forzar reloj/reset evita depender del modelo del PLL.
module sysid_host_tb;
  reg clk=0, reset=1;
  always #5 clk=~clk;
  reg [31:0] address=0;
  reg reading=0,writing=0;
  top dut(.clk_25mhz(clk),.ftdi_txd(1'b1),.btn_pwr_n(1'b1));
  integer guard,k,w;
  initial begin
    force dut.clk=clk;
    force dut.reset=reset;
    force dut.mem_address=address;
    force dut.mem_write_enable=writing;
    force dut.mem_read_enable=reading;
    force dut.mem_write_data=8'd0;
  end
  task access(input [31:0] addr,input wr,input bad);
    begin
      @(negedge clk);address=addr;writing=wr;reading=!wr;
      @(negedge clk);writing=0;reading=0;guard=0;
      while(!dut.mem_ready && guard<100) begin @(negedge clk);guard=guard+1;end
      if(!dut.mem_ready || dut.mem_error!==bad) $fatal(1,"SYS_ID %h wr %b err %b",addr,wr,dut.mem_error);
      if(!bad && addr==32'h80000f00 && dut.mem_read_word!==32'h4d470000+10)
        $fatal(1,"identidad incorrecta %h",dut.mem_read_word);
      if(!bad && addr==32'h80000f08 && dut.mem_read_word!==0) $fatal(1,"bitmap");
      repeat(4) @(negedge clk);
    end
  endtask
  initial begin
    repeat(4) @(negedge clk);reset=0;
    repeat(4) @(negedge clk);
    for(w=0;w<2;w=w+1) begin
      for(k=0;k<16;k=k+4) access(32'h80000f00+k,w,w!=0);
      for(k=16;k<256;k=k+4) access(32'h80000f00+k,w,1);
    end
    $display("PASS: SYS_ID del top sin alias ni escrituras silenciosas");$finish;
  end
  initial begin #1000000;$fatal(1,"timeout");end
endmodule
`default_nettype wire
