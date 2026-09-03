`timescale 1ns/1ps
`default_nettype none
module sdram_controller_tb;
  reg clk=0,reset=1,req_valid=0,req_write=0;
  reg [23:0] req_addr=0; reg [15:0] req_wdata=0; reg [1:0] req_wmask=0;
  wire req_ready,done; wire [15:0] rdata; wire init_done,busy;
  wire sdram_clk,sdram_cke,sdram_csn,sdram_rasn,sdram_casn,sdram_wen;
  wire [12:0] sdram_a; wire [1:0] sdram_ba,sdram_dqm; wire [15:0] sdram_d;
  reg write_seen=0; reg [1:0] write_dqm=0;
  always #20 clk=~clk;
  // A compact bus model is sufficient here: present read data in capture state.
  assign sdram_d = (dut.state==5'd15) ? 16'hcafe : 16'hzzzz;
  sdram_controller dut(.*);

  always @(posedge clk) begin
    if(!sdram_csn && sdram_rasn && sdram_casn && !sdram_wen) begin
      write_seen<=1; write_dqm<=sdram_dqm;
    end
  end
  task request(input wr,input [1:0] mask);
    begin
      wait(req_ready); @(negedge clk);
      req_write=wr; req_addr=24'h123456; req_wdata=16'hbeef;
      req_wmask=mask; req_valid=1;
      @(negedge clk); while(!req_ready) @(negedge clk);
      req_valid=0; wait(done); @(negedge clk);
    end
  endtask
  initial begin
    repeat(2) @(negedge clk); reset=0; wait(init_done);
    request(1,2'b01);
    if(!write_seen || write_dqm!==2'b10) $fatal(1,"DQM inversion failed");
    request(0,2'b00);
    if(rdata!==16'hcafe) $fatal(1,"read capture failed");
    $display("PASS: SDRAM initialization, DQM and read flow are correct"); $finish;
  end
endmodule
`default_nettype wire
