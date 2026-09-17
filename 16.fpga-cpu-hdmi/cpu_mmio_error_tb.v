`default_nettype none
`timescale 1ns/1ps
// Instrucciones reales y accesos del monitor por el mismo decodificador.
// Comprueba codigo y PC del fault, permisos de SYS_ID y ausencia de efectos.
module cpu_mmio_error_tb;
  reg clk=0, reset=1, run_request=0;
  always #5 clk=~clk;
  wire halted,error;
  wire [7:0] error_code;
  wire [31:0] debug_pc,debug_data,imem_address;
  wire imem_valid,dmem_valid,dmem_ready,dmem_error;
  wire [31:0] dmem_address,dmem_write_data,dmem_read_data;
  wire [3:0] dmem_write_enable;
  reg [15:0] offset=0;
  reg writing=0;
  wire [31:0] instruction = imem_address==0 ? 32'h5c208000 :
    imem_address==4 ? {(writing ? 6'h16 : 6'h15),5'd2,5'd1,offset} : 32'hfc000000;
  cpu core(.clk(clk),.reset(reset),.run_request(run_request),
    .halt_request(1'b0),.step_request(1'b0),.halted(halted),.error(error),
    .error_code(error_code),.imem_valid(imem_valid),.imem_address(imem_address),
    .imem_read_data(instruction),.imem_ready(imem_valid),
    .dmem_valid(dmem_valid),.dmem_address(dmem_address),
    .dmem_write_data(dmem_write_data),.dmem_write_enable(dmem_write_enable),
    .dmem_read_data(dmem_read_data),.dmem_ready(dmem_ready),.dmem_error(dmem_error),
    .debug_register_address(5'd2),.debug_register_data(debug_data),.debug_pc(debug_pc));
  reg [31:0] mon_address=0;
  reg mon_read=0,mon_write=0;
  wire mon_ready,mon_error;
  wire [31:0] mon_word;
  wire mmio_select,mmio_write,mmio_error,video_select,serial_select;
  wire [11:0] mmio_address;
  wire [3:0] mmio_mask;
  wire [31:0] mmio_wdata,mmio_rdata;
  mmio_decoder #(.FOLDER(8'd16),.HAS_SERIAL(0),
    .VIDEO_REGISTERS(64'h4f)) decoder(
    .select(mmio_select),.write(mmio_write),.address(mmio_address),
    .read_data(mmio_rdata),.error(mmio_error),
    .video_select(video_select),.video_read_data(32'd0),
    .serial_select(serial_select),.serial_read_data(32'd0),.perf_read_data(32'd0));
  sdram_system_adapter adapter(.clk(clk),.reset(reset),.init_done(1'b1),
    .cpu_halted(halted),.cpu_imem_valid(1'b0),.cpu_imem_address(32'd0),
    .cpu_dmem_valid(dmem_valid),.cpu_dmem_address(dmem_address),
    .cpu_dmem_write_data(dmem_write_data),.cpu_dmem_write_enable(dmem_write_enable),
    .cpu_dmem_read_data(dmem_read_data),.cpu_dmem_ready(dmem_ready),.cpu_dmem_error(dmem_error),
    .monitor_address(mon_address),.monitor_write_data(8'd0),
    .monitor_write_enable(mon_write),
      .monitor_write_word(32'd0), .monitor_write_word_enable(1'b0),.monitor_read_enable(mon_read),
    .monitor_ready(mon_ready),.monitor_error(mon_error),.monitor_read_word(mon_word),
    .mmio_select(mmio_select),.mmio_write(mmio_write),.mmio_address(mmio_address),
    .mmio_write_mask(mmio_mask),.mmio_write_data(mmio_wdata),
    .mmio_read_data(mmio_rdata),.mmio_error(mmio_error),
    .video_req(1'b0),.video_addr(24'd0),.req_ready(1'b0),.done(1'b0),.rdata(16'd0));
  integer effects=0,guard;
  always @(posedge clk) if(!reset && (video_select || serial_select)) effects<=effects+1;
  task check(input [15:0] addr,input wr,input bad);
    begin
      @(negedge clk);reset=1;offset=addr;writing=wr;effects=0;
      repeat(3) @(negedge clk);reset=0;
      @(negedge clk);run_request=1;
      @(negedge clk);run_request=0;
      guard=0;
      while(!halted && guard<300) begin @(negedge clk);guard=guard+1;end
      if(!halted || error!==bad) $fatal(1,"CPU offset %h wr %b error %b",addr,wr,error);
      repeat(2) @(negedge clk); // pc_restore se aplica en STATE_HALTED.
      if(bad && (error_code!==8'd2 || debug_pc!==32'd4 || effects!=0))
        $fatal(1,"fault %h wr %b code %h pc %h efectos %0d",addr,wr,error_code,debug_pc,effects);
      if(!bad && !wr && addr==16'hf08 && debug_data!==0) $fatal(1,"bitmap cero invalido");
      // El monitor debe ver exactamente la misma politica, incluido write
      // retenido durante ack (antes se perdia el fault de solo lectura).
      @(negedge clk);mon_address={16'h8000,addr};mon_write=wr;mon_read=!wr;
      @(negedge clk);mon_write=0;mon_read=0;guard=0;
      while(!mon_ready && guard<100) begin @(negedge clk);guard=guard+1;end
      if(!mon_ready || mon_error!==bad) $fatal(1,"monitor offset %h wr %b error %b",addr,wr,mon_error);
      @(negedge clk);
    end
  endtask
  integer w,k;
  initial begin
    for(w=0;w<2;w=w+1) begin
      check(16'h400,w,1);check(16'h1000,w,1);
      check(16'h01c,w,1);check(16'h20c,w,1);check(16'h308,w,1);
      for(k=16'hf10;k<16'h1000;k=k+16) check(k,w,1);
      check(16'hffc,w,1);
      for(k=16'hf00;k<16'hf10;k=k+4) check(k,w,w!=0);
      check(16'h300,w,w!=0);check(16'h304,w,w!=0);
      check(16'h000,w,0);check(16'h018,w,0);
      check(16'h200,w,!0);
      check(16'h010,w,1);check(16'h014,w,1);
    end
    $display("PASS: errores MMIO llegan a CPU y monitor");$finish;
  end
  initial begin #1000000;$fatal(1,"timeout");end
endmodule
`default_nettype wire
