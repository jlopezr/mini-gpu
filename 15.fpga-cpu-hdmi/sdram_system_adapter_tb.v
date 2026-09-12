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
  // Puerto de video en reposo: este banco cubre monitor y CPU. El camino de
  // video tiene el suyo en video_sdram_tb.v.
  reg video_req=0; reg [23:0] video_addr=0;
  wire mmio_select,mmio_write; wire [3:0] mmio_write_mask,mmio_address;
  wire [31:0] mmio_write_data; reg [31:0] mmio_read_data;
  // Cuatro registros de mentira en la ventana 0x80000000, suficientes para
  // comprobar el pegamento: decodificacion, mascara de byte y seleccion del
  // byte de vuelta. La semantica real vive en video_registers_tb.v.
  reg [31:0] mmio_regs[0:3];
  wire [15:0] video_read_data; wire video_ready;
  reg [15:0] program_words[0:31];
  reg [15:0] data_words[0:31];
  integer i;
  always #5 clk=~clk;

  sdram_system_adapter dut(.*);

  always @(*) mmio_read_data = mmio_regs[mmio_address[3:2]];
  always @(posedge clk) begin
    if(mmio_select && mmio_write) begin
      if(mmio_write_mask[0]) mmio_regs[mmio_address[3:2]][7:0]   <= mmio_write_data[7:0];
      if(mmio_write_mask[1]) mmio_regs[mmio_address[3:2]][15:8]  <= mmio_write_data[15:8];
      if(mmio_write_mask[2]) mmio_regs[mmio_address[3:2]][23:16] <= mmio_write_data[23:16];
      if(mmio_write_mask[3]) mmio_regs[mmio_address[3:2]][31:24] <= mmio_write_data[31:24];
    end
  end

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
      end else
        rdata <= req_addr[23:5] == 19'h04000 ?
                 data_words[req_addr[4:0]] : program_words[req_addr[4:0]];
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
    for(i=0;i<4;i=i+1) mmio_regs[i]=0;
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

    // The CPU uses the same global data address as the monitor.
    @(negedge clk); cpu_dmem_address=32'h0010_0004;
    cpu_dmem_write_data=32'h1234_abcd;
    cpu_dmem_write_enable=4'b1111; cpu_dmem_valid=1;
    wait(cpu_dmem_ready); @(negedge clk); cpu_dmem_valid=0;
    cpu_dmem_write_enable=0;
    @(negedge clk); cpu_dmem_valid=1;
    wait(cpu_dmem_ready);
    if(cpu_dmem_error || cpu_dmem_read_data!==32'h1234_abcd)
      $fatal(1,"data word round-trip failed: %08x",cpu_dmem_read_data);
    @(negedge clk); cpu_dmem_valid=0;

    cpu_halted=1;
    monitor_read_check(32'h0010_0004,8'hcd);
    monitor_read_check(32'h0010_0005,8'hab);

    // Both CPU ports see the same words, regardless of their usual purpose.
    cpu_halted=0;
    @(negedge clk); cpu_dmem_address=0; cpu_dmem_valid=1;
    wait(cpu_dmem_ready);
    if(cpu_dmem_error || cpu_dmem_read_data!==32'hcafe_3344)
      $fatal(1,"dmem could not read program region");
    @(negedge clk); cpu_dmem_valid=0;
    repeat(2) @(negedge clk);
    cpu_imem_address=32'h0010_0004; cpu_imem_valid=1;
    wait(cpu_imem_ready);
    if(cpu_imem_read_data!==32'h1234_abcd)
      $fatal(1,"imem could not read data region");
    @(negedge clk); cpu_imem_valid=0;
    repeat(2) @(negedge clk);

    // --- ventana de registros de video en 0x80000000 ----------------------
    // La CPU la usa con palabras completas.
    cpu_halted=0;
    @(negedge clk); cpu_dmem_address=32'h8000_0004;
    cpu_dmem_write_data=32'hdead_beef; cpu_dmem_write_enable=4'b1111;
    cpu_dmem_valid=1;
    wait(cpu_dmem_ready); @(negedge clk); cpu_dmem_valid=0;
    cpu_dmem_write_enable=0;
    if(mmio_regs[1]!==32'hdead_beef)
      $fatal(1,"CPU write to MMIO stored %08x",mmio_regs[1]);
    @(negedge clk); cpu_dmem_valid=1;
    wait(cpu_dmem_ready);
    if(cpu_dmem_error || cpu_dmem_read_data!==32'hdead_beef)
      $fatal(1,"CPU read from MMIO got %08x",cpu_dmem_read_data);
    @(negedge clk); cpu_dmem_valid=0;

    // El monitor accede byte a byte, y a estos registros tambien con la CPU
    // corriendo: no hay coherencia que romper y el contador de frames solo
    // sirve si se puede leer en marcha.
    monitor_read_check(32'h8000_0006,8'had);
    monitor_write(32'h8000_0007,8'h55);
    if(mmio_regs[1]!==32'h55ad_beef)
      $fatal(1,"monitor byte write clobbered the register: %08x",mmio_regs[1]);

    // Fuera de la ventana, una direccion alta sigue siendo un error.
    @(negedge clk); monitor_address=32'h9000_0000; monitor_read_enable=1;
    @(negedge clk); monitor_read_enable=0; wait(monitor_ready);
    if(!monitor_error) $fatal(1,"monitor accepted an address outside the MMIO window");
    @(negedge clk);

    @(negedge clk); monitor_address=0; monitor_read_enable=1;
    @(negedge clk); monitor_read_enable=0; wait(monitor_ready);
    if(!monitor_error) $fatal(1,"monitor accessed SDRAM while CPU was running");
    $display("PASS: monitor and CPU SDRAM frontend, plus the video MMIO window");
    $finish;
  end
endmodule

`default_nettype wire
