`timescale 1ns/1ps
`default_nettype none
module sdram_byte_adapter_tb;
  reg clk=0, reset=1, init_done=1;
  reg [31:0] address=0; reg [7:0] write_data=0;
  reg write_enable=0, read_enable=0;
  wire [7:0] read_data; wire ready,error;
  wire req_valid,req_write; wire [23:0] req_addr;
  wire [15:0] req_wdata; wire [1:0] req_wmask;
  reg req_ready=1,done=0; reg [15:0] rdata=0;
  reg [15:0] words[0:15]; integer i;
  always #5 clk=~clk;

  sdram_byte_adapter dut(.*);

  always @(posedge clk) begin
    done<=0;
    if (req_valid && req_ready) begin
      if (req_write) begin
        if (req_wmask[0]) words[req_addr][7:0]<=req_wdata[7:0];
        if (req_wmask[1]) words[req_addr][15:8]<=req_wdata[15:8];
      end else rdata<=words[req_addr];
      done<=1;
    end
  end

  task write_byte(input [31:0] a,input [7:0] d);
    begin
      @(negedge clk); address=a; write_data=d; write_enable=1;
      @(negedge clk); write_enable=0; wait(ready); @(negedge clk);
    end
  endtask
  task check_byte(input [31:0] a,input [7:0] expected);
    begin
      @(negedge clk); address=a; read_enable=1;
      @(negedge clk); read_enable=0; wait(ready);
      if (error || read_data!==expected) $fatal(1,"read %08x: got %02x expected %02x",a,read_data,expected);
      @(negedge clk);
    end
  endtask

  initial begin
    for(i=0;i<16;i=i+1) words[i]=16'hcafe;
    repeat(2) @(negedge clk); reset=0;
    write_byte(0,8'h12);
    if(words[0]!==16'hca12) $fatal(1,"low-byte DQM failed");
    write_byte(1,8'h34);
    if(words[0]!==16'h3412) $fatal(1,"high-byte DQM failed");
    check_byte(0,8'h12); check_byte(1,8'h34);
    @(negedge clk); address=32'h02000000; read_enable=1;
    @(negedge clk); read_enable=0; wait(ready);
    if(!error) $fatal(1,"out-of-range access accepted");
    $display("PASS: byte adapter and DQM masks are correct"); $finish;
  end
endmodule
`default_nettype wire

