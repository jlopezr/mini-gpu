`timescale 1ns/1ps
`default_nettype none

module cpu_sdram_system_tb;
  reg clk=0, reset=1, init_done=1;
  reg run_request=0,halt_request=0,step_request=0;
  wire halted,error; wire [7:0] error_code; wire instruction_retired;
  wire imem_valid; wire [31:0] imem_address,imem_read_data; wire imem_ready;
  wire dmem_valid; wire [31:0] dmem_address,dmem_write_data,dmem_read_data;
  wire [3:0] dmem_write_enable; wire dmem_ready,dmem_error;
  reg [4:0] debug_register_address=0;
  wire [31:0] debug_register_data,debug_pc;
  reg [31:0] monitor_address=0; reg [7:0] monitor_write_data=0;
  reg monitor_write_enable=0,monitor_read_enable=0;
  wire [7:0] monitor_read_data; wire monitor_ready,monitor_error;
  wire req_valid,req_write; wire [23:0] req_addr;
  wire [15:0] req_wdata; wire [1:0] req_wmask;
  reg req_ready=1,done=0; reg [15:0] rdata=0;
  reg [15:0] program_words[0:31]; reg [15:0] data_words[0:31];
  integer i,cycles;
  always #5 clk=~clk;

  cpu cpu_i(.clk(clk),.reset(reset),.run_request(run_request),
      .halt_request(halt_request),.step_request(step_request),.halted(halted),
      .error(error),.error_code(error_code),
      .instruction_retired(instruction_retired),.imem_valid(imem_valid),
      .imem_address(imem_address),.imem_read_data(imem_read_data),
      .imem_ready(imem_ready),.dmem_valid(dmem_valid),.dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data),.dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data),.dmem_ready(dmem_ready),
      .dmem_error(dmem_error),.debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data),.debug_pc(debug_pc));

  sdram_system_adapter adapter_i(
      .clk(clk),.reset(reset),.init_done(init_done),
      .monitor_address(monitor_address),.monitor_write_data(monitor_write_data),
      .monitor_write_enable(monitor_write_enable),
      .monitor_read_enable(monitor_read_enable),.monitor_read_data(monitor_read_data),
      .monitor_ready(monitor_ready),.monitor_error(monitor_error),
      .cpu_halted(halted),.cpu_imem_valid(imem_valid),
      .cpu_imem_address(imem_address),.cpu_imem_read_data(imem_read_data),
      .cpu_imem_ready(imem_ready),.cpu_dmem_valid(dmem_valid),
      .cpu_dmem_address(dmem_address),.cpu_dmem_write_data(dmem_write_data),
      .cpu_dmem_write_enable(dmem_write_enable),.cpu_dmem_read_data(dmem_read_data),
      .cpu_dmem_ready(dmem_ready),.cpu_dmem_error(dmem_error),
      .req_valid(req_valid),.req_write(req_write),.req_addr(req_addr),
      .req_wdata(req_wdata),.req_wmask(req_wmask),.req_ready(req_ready),
      .done(done),.rdata(rdata));

  always @(posedge clk) begin
    done<=0;
    if(req_valid && req_ready) begin
      if(req_write) begin
        if(req_addr[23:5] == 19'h04000) begin
          if(req_wmask[0]) data_words[req_addr[4:0]][7:0]<=req_wdata[7:0];
          if(req_wmask[1]) data_words[req_addr[4:0]][15:8]<=req_wdata[15:8];
        end else begin
          if(req_wmask[0]) program_words[req_addr[4:0]][7:0]<=req_wdata[7:0];
          if(req_wmask[1]) program_words[req_addr[4:0]][15:8]<=req_wdata[15:8];
        end
      end else rdata<=req_addr[23:5] == 19'h04000 ?
                       data_words[req_addr[4:0]] : program_words[req_addr[4:0]];
      done<=1;
    end
  end

  task write_byte(input [31:0] address,input [7:0] value);
    begin
      @(negedge clk); monitor_address=address;monitor_write_data=value;
      monitor_write_enable=1;
      @(negedge clk);monitor_write_enable=0;wait(monitor_ready);@(negedge clk);
      if(monitor_error)$fatal(1,"loader write failed");
    end
  endtask
  task write_word(input [31:0] address,input [31:0] value);
    begin
      write_byte(address,value[7:0]); write_byte(address+1,value[15:8]);
      write_byte(address+2,value[23:16]); write_byte(address+3,value[31:24]);
    end
  endtask

  initial begin
    for(i=0;i<32;i=i+1) begin program_words[i]=0;data_words[i]=0;end
    repeat(2) @(negedge clk);reset=0;
    write_word(32'h0000_0000,32'h4020_1234); // MOVI R1,0x1234
    write_word(32'h0000_0004,32'h5c80_0010); // MOVHI R4,0x0010
    write_word(32'h0000_0008,32'h4484_0004); // ADDI R4,R4,4
    write_word(32'h0000_000c,32'h5824_0000); // STORE R1,R4,0
    write_word(32'h0000_0010,32'h5444_0000); // LOAD R2,R4,0
    write_word(32'h0000_0014,32'hfc00_0000); // HALT
    @(negedge clk);run_request=1;@(negedge clk);run_request=0;
    cycles=0;
    while(!halted && cycles<500) begin @(negedge clk);cycles=cycles+1;end
    if(!halted || error)$fatal(1,"CPU failed: halted=%b error=%b code=%02x",halted,error,error_code);
    if(debug_pc!==32'h0000_0018)$fatal(1,"unexpected PC %08x",debug_pc);
    debug_register_address=2;repeat(3)@(negedge clk);
    if(debug_register_data!==32'h0000_1234)$fatal(1,"R2 mismatch %08x",debug_register_data);
    if(data_words[2]!==16'h1234 || data_words[3]!==16'h0000)
      $fatal(1,"STORE did not reach data SDRAM bank");
    $display("PASS: monitor load -> SDRAM fetch -> STORE/LOAD -> HALT");$finish;
  end
endmodule

`default_nettype wire
