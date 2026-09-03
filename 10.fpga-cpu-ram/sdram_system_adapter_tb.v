`timescale 1ns/1ps
`default_nettype none

module sdram_system_adapter_tb;
  reg clk=0, reset=1, init_done=1;
  reg [31:0] monitor_address=0; reg [7:0] monitor_write_data=0;
  reg monitor_write_enable=0, monitor_read_enable=0;
  wire [7:0] monitor_read_data; wire monitor_ready, monitor_error;
  reg cpu_halted=1;
  reg cpu_imem_valid=0; reg [31:0] cpu_imem_address=0;
  wire [31:0] cpu_imem_read_data; wire cpu_imem_ready;
  reg cpu_dmem_valid=0; reg [31:0] cpu_dmem_address=0;
  reg [31:0] cpu_dmem_write_data=0; reg [3:0] cpu_dmem_write_enable=0;
  wire [31:0] cpu_dmem_read_data; wire cpu_dmem_ready,cpu_dmem_error;
  wire req_valid,req_write; wire [23:0] req_addr;
  wire [15:0] req_wdata; wire [1:0] req_wmask;
  reg req_ready=1,done=0; reg [15:0] rdata=0;
  reg [15:0] program_words[0:31];
  reg [15:0] data_words[0:31];
  integer i;
  always #5 clk=~clk;

  sdram_system_adapter dut(.*);

  always @(posedge clk) begin
    done<=0;
    if(req_valid && req_ready) begin
      if(req_write) begin
        if(req_addr[23]) begin
          if(req_wmask[0]) data_words[req_addr[4:0]][7:0]<=req_wdata[7:0];
          if(req_wmask[1]) data_words[req_addr[4:0]][15:8]<=req_wdata[15:8];
        end else begin
          if(req_wmask[0]) program_words[req_addr[4:0]][7:0]<=req_wdata[7:0];
          if(req_wmask[1]) program_words[req_addr[4:0]][15:8]<=req_wdata[15:8];
        end
      end else
        rdata <= req_addr[23] ? data_words[req_addr[4:0]] :
                                program_words[req_addr[4:0]];
      done<=1;
    end
  end

  task monitor_write(input [31:0] address,input [7:0] value);
    begin
      @(negedge clk); monitor_address=address; monitor_write_data=value;
      monitor_write_enable=1;
      @(negedge clk); monitor_write_enable=0;
      wait(monitor_ready); @(negedge clk);
      if(monitor_error) $fatal(1,"monitor write failed at %08x",address);
    end
  endtask

  task monitor_read_check(input [31:0] address,input [7:0] expected);
    begin
      @(negedge clk); monitor_address=address; monitor_read_enable=1;
      @(negedge clk); monitor_read_enable=0;
      wait(monitor_ready);
      if(monitor_error || monitor_read_data!==expected)
        $fatal(1,"monitor read %08x got %02x expected %02x",
               address,monitor_read_data,expected);
      @(negedge clk);
    end
  endtask

  initial begin
    for(i=0;i<32;i=i+1) begin program_words[i]=16'hcafe; data_words[i]=0; end
    repeat(2) @(negedge clk); reset=0;
    monitor_write(32'h0000_0000,8'h44);
    monitor_write(32'h0000_0001,8'h33);
    monitor_read_check(32'h0000_0000,8'h44);
    monitor_read_check(32'h0000_0001,8'h33);

    cpu_halted=0;
    @(negedge clk); cpu_imem_address=0; cpu_imem_valid=1;
    wait(cpu_imem_ready);
    if(cpu_imem_read_data!==32'hcafe_3344)
      $fatal(1,"instruction word assembly failed: %08x",cpu_imem_read_data);
    @(negedge clk); cpu_imem_valid=0;

    @(negedge clk); cpu_dmem_address=4; cpu_dmem_write_data=32'h1234_abcd;
    cpu_dmem_write_enable=4'b1111; cpu_dmem_valid=1;
    wait(cpu_dmem_ready); @(negedge clk); cpu_dmem_valid=0;
    cpu_dmem_write_enable=0;
    @(negedge clk); cpu_dmem_valid=1;
    wait(cpu_dmem_ready);
    if(cpu_dmem_error || cpu_dmem_read_data!==32'h1234_abcd)
      $fatal(1,"data word round-trip failed: %08x",cpu_dmem_read_data);
    @(negedge clk); cpu_dmem_valid=0;

    @(negedge clk); monitor_address=0; monitor_read_enable=1;
    @(negedge clk); monitor_read_enable=0; wait(monitor_ready);
    if(!monitor_error) $fatal(1,"monitor accessed SDRAM while CPU was running");
    $display("PASS: monitor and CPU SDRAM frontend"); $finish;
  end
endmodule

`default_nettype wire
