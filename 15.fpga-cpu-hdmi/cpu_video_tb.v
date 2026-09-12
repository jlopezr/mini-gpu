`timescale 1ns/1ps
`default_nettype none

// Integracion del hito D: la CPU real manejando los registros de video.
//
// Los otros bancos prueban las piezas por separado -- `video_registers_tb.v` la
// semantica del swap, `sdram_system_adapter_tb.v` el decodificado MMIO -- pero
// ninguno ejecuta instrucciones. Aqui corre `swap_smoke.asm` de verdad: lee
// FB_FRONT y FB_BACK, pide un intercambio, gira en un bucle de espera hasta
// que el hardware lo aplica, y vuelve a leer los dos registros.
//
// Eso cubre lo que no cubre nada mas: que `LOAD` y `STORE` sobre 0x80000000
// funcionan desde la CPU, que el bucle de espera termina, y que el programa no
// se queda colgado si el frame tarda en llegar.
//
// El intercambio lo dispara este banco pulsando `fill_start`/`fill_first`, que
// es lo que hace el scanout al empezar cada frame.

module cpu_video_tb;
  reg clk=0, reset=1, init_done=1;
  reg run_request=0, halt_request=0, step_request=0;
  wire halted, error; wire [7:0] error_code; wire instruction_retired;
  wire imem_valid; wire [31:0] imem_address, imem_read_data; wire imem_ready;
  wire dmem_valid; wire [31:0] dmem_address, dmem_write_data, dmem_read_data;
  wire [3:0] dmem_write_enable; wire dmem_ready, dmem_error;
  reg [4:0] debug_register_address=0;
  wire [31:0] debug_register_data, debug_pc;

  reg [31:0] monitor_address=0; reg [7:0] monitor_write_data=0;
  reg monitor_write_enable=0, monitor_read_enable=0;
  wire [7:0] monitor_read_data; wire monitor_ready, monitor_error;

  wire req_valid, req_write; wire [23:0] req_addr;
  wire [15:0] req_wdata; wire [1:0] req_wmask;
  reg req_ready=1, done=0; reg [15:0] rdata=0;
  reg [15:0] program_words[0:63];

  wire mmio_select, mmio_write;
  wire [3:0] mmio_write_mask, mmio_address;
  wire [31:0] mmio_write_data, mmio_read_data;

  reg fill_start=0, fill_first=0;
  wire [23:0] fb_base;
  wire [31:0] debug_front, debug_back;

  localparam [31:0] FRONT_RESET = 32'h0100_0000;
  localparam [31:0] BACK_RESET  = 32'h0102_5800;

  integer i, cycles;
  always #5 clk=~clk;

  cpu cpu_i(.clk(clk),.reset(reset),.run_request(run_request),
      .halt_request(halt_request),.step_request(step_request),.halted(halted),
      .error(error),.error_code(error_code),
      .instruction_retired(instruction_retired),.imem_valid(imem_valid),
      .imem_address(imem_address),.imem_read_data(imem_read_data),
      .imem_ready(imem_ready),.dmem_valid(dmem_valid),
      .dmem_address(dmem_address),.dmem_write_data(dmem_write_data),
      .dmem_write_enable(dmem_write_enable),.dmem_read_data(dmem_read_data),
      .dmem_ready(dmem_ready),.dmem_error(dmem_error),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data),.debug_pc(debug_pc));

  sdram_system_adapter adapter_i(
      .clk(clk),.reset(reset),.init_done(init_done),
      .monitor_address(monitor_address),.monitor_write_data(monitor_write_data),
      .monitor_write_enable(monitor_write_enable),
      .monitor_read_enable(monitor_read_enable),
      .monitor_read_data(monitor_read_data),.monitor_ready(monitor_ready),
      .monitor_error(monitor_error),
      .cpu_halted(halted),.cpu_imem_valid(imem_valid),
      .cpu_imem_address(imem_address),.cpu_imem_read_data(imem_read_data),
      .cpu_imem_ready(imem_ready),.cpu_dmem_valid(dmem_valid),
      .cpu_dmem_address(dmem_address),.cpu_dmem_write_data(dmem_write_data),
      .cpu_dmem_write_enable(dmem_write_enable),
      .cpu_dmem_read_data(dmem_read_data),.cpu_dmem_ready(dmem_ready),
      .cpu_dmem_error(dmem_error),
      .mmio_select(mmio_select),.mmio_write(mmio_write),
      .mmio_write_mask(mmio_write_mask),.mmio_address(mmio_address),
      .mmio_write_data(mmio_write_data),.mmio_read_data(mmio_read_data),
      .video_req(1'b0),.video_addr(24'h000000),
      .video_read_data(),.video_ready(),
      .req_valid(req_valid),.req_write(req_write),.req_addr(req_addr),
      .req_wdata(req_wdata),.req_wmask(req_wmask),.req_ready(req_ready),
      .done(done),.rdata(rdata));

  video_registers #(
      .FB_FRONT_RESET(FRONT_RESET),.FB_BACK_RESET(BACK_RESET)
  ) registers_i(
      .clk(clk),.reset(reset),
      .select(mmio_select),.write(mmio_write),.write_mask(mmio_write_mask),
      .address(mmio_address),.write_data(mmio_write_data),
      .read_data(mmio_read_data),
      .fill_start(fill_start),.fill_first(fill_first),.fb_base(fb_base),
      .underflow_pix(1'b0),
      .debug_front(debug_front),.debug_back(debug_back));

  // Memoria de programa, con la misma latencia inmediata que usan los demas
  // bancos: aqui lo que se prueba no es la SDRAM.
  always @(posedge clk) begin
    done<=0;
    if(req_valid && req_ready) begin
      if(req_write) begin
        if(req_wmask[0]) program_words[req_addr[5:0]][7:0]<=req_wdata[7:0];
        if(req_wmask[1]) program_words[req_addr[5:0]][15:8]<=req_wdata[15:8];
      end else begin
        rdata<=program_words[req_addr[5:0]];
      end
      done<=1;
    end
  end

  task write_byte(input [31:0] address,input [7:0] value);
    begin
      @(negedge clk); monitor_address=address; monitor_write_data=value;
      monitor_write_enable=1;
      @(negedge clk); monitor_write_enable=0; wait(monitor_ready);
      @(negedge clk);
      if(monitor_error) $fatal(1,"loader write failed at %08x",address);
    end
  endtask

  task write_word(input [31:0] address,input [31:0] value);
    begin
      write_byte(address,value[7:0]);   write_byte(address+1,value[15:8]);
      write_byte(address+2,value[23:16]); write_byte(address+3,value[31:24]);
    end
  endtask

  task expect_register(input [4:0] number, input [31:0] expected,
                       input [255:0] name);
    begin
      debug_register_address=number; repeat(3) @(negedge clk);
      if(debug_register_data!==expected)
        $fatal(1,"%0s: R%0d = %08x, esperado %08x",
               name,number,debug_register_data,expected);
    end
  endtask

  initial begin
    $dumpvars(0, cpu_video_tb);

    for(i=0;i<64;i=i+1) program_words[i]=0;
    repeat(2) @(negedge clk); reset=0;

    // swap_smoke.asm, ensamblado con 1.isa/miniisa_asm.py
    write_word(32'h0000_0000,32'h5E80_8000); // MOVHI R20,0x8000
    write_word(32'h0000_0004,32'h5434_0000); // LOAD  R1,R20,0
    write_word(32'h0000_0008,32'h5454_0004); // LOAD  R2,R20,4
    write_word(32'h0000_000c,32'h40E0_0001); // MOVI  R7,1
    write_word(32'h0000_0010,32'h4120_0000); // MOVI  R9,0
    write_word(32'h0000_0014,32'h58F4_0008); // STORE R7,R20,8
    write_word(32'h0000_0018,32'h5514_0008); // LOAD  R8,R20,8
    write_word(32'h0000_001c,32'h8509_FFFE); // BNE   R8,R9,wait_swap
    write_word(32'h0000_0020,32'h5474_0000); // LOAD  R3,R20,0
    write_word(32'h0000_0024,32'h5494_0004); // LOAD  R4,R20,4
    write_word(32'h0000_0028,32'hFC00_0000); // HALT

    @(negedge clk); run_request=1; @(negedge clk); run_request=0;

    // El programa se queda girando en `wait_swap` hasta que llega un frame.
    // Se le deja girar un rato a proposito: si el bucle terminara sin que el
    // hardware haya intercambiado nada, la comprobacion final lo cazaria.
    cycles=0;
    while(!halted && cycles<400) begin @(negedge clk); cycles=cycles+1; end
    if(halted) $fatal(1,"el programa salio del bucle de espera sin ningun frame");

    // Primera peticion de linea de un frame: es cuando el hardware intercambia.
    @(negedge clk); fill_start=1; fill_first=1;
    @(negedge clk); fill_start=0; fill_first=0;

    cycles=0;
    while(!halted && cycles<2000) begin @(negedge clk); cycles=cycles+1; end
    if(!halted || error)
      $fatal(1,"CPU: halted=%b error=%b code=%02x pc=%08x",
             halted,error,error_code,debug_pc);

    expect_register(5'd1, FRONT_RESET, "FB_FRONT antes");
    expect_register(5'd2, BACK_RESET,  "FB_BACK antes");
    expect_register(5'd3, BACK_RESET,  "FB_FRONT despues del swap");
    expect_register(5'd4, FRONT_RESET, "FB_BACK despues del swap");

    if(debug_front!==BACK_RESET || debug_back!==FRONT_RESET)
      $fatal(1,"los registros no quedaron intercambiados: front=%08x back=%08x",
             debug_front,debug_back);

    $display("OK: la CPU pidio el swap, espero al frame y vio los buffers intercambiados");
    $finish;
  end

  initial begin
    #500_000;
    $fatal(1,"timeout");
  end
endmodule

`default_nettype wire
