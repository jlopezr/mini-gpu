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
  // El programa es `MOVHI R1, base_hi` + `LOAD/STORE R2, R1, offset` + HALT.
  //
  // `base_hi` es un REGISTRO desde MMIO v2: antes bastaba con 0x8000 fijo,
  // porque los dieciseis dispositivos vivian en la misma pagina de 4 KiB y un
  // offset de 16 bits los alcanzaba todos. Ahora los bloques estan a
  // megabytes, asi que cada uno necesita su propia mitad alta.
  reg [15:0] base_hi=16'h8020;
  reg [15:0] offset=0;
  reg writing=0;
  wire [31:0] instruction = imem_address==0 ? {16'h5c20,base_hi} :
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
  wire [31:0] mmio_address;
  wire [3:0] mmio_mask;
  wire [31:0] mmio_wdata,mmio_rdata;
  // Los mismos parametros que `top.v`. Tienen que coincidir: este banco
  // comprueba valores concretos de SYSTEM, y un banco con otra configuracion
  // probaria un decodificador que no es el que se sintetiza.
  mmio_decoder #(.FOLDER(8'd18),.HAS_SERIAL(0),
    .VIDEO_REGISTERS(64'h3ff),.ISA_PROFILE(32'h0000_0003),
    .DEVICES(32'h0000_0225),
    .MEM_BASE(32'h0000_0000),.MEM_SIZE(32'h0200_0000),
    .MONITOR_VERSION(32'h0000_0312)) decoder(
    .select(mmio_select),.write(mmio_write),.write_mask(mmio_mask),.address(mmio_address),
    .read_data(mmio_rdata),.error(mmio_error),
    .video_select(video_select),.video_read_data(32'd0),.video_error(1'b0),
    .serial_select(serial_select),.serial_read_data(32'd0),.perf_select(),.perf_read_data(32'd0));
  wire c_req,c_ack,c_wr,m_req,m_ack,m_wr,wb_dirty;
  wire [31:0] c_addr,m_addr;
  wire [3:0] c_mask,m_mask;
  wire [31:0] c_data,m_data;
  cpu_dmem_adapter data_adapter(.clk(clk),.reset(reset),.init_done(1'b1),.cpu_halted(halted),
    .dmem_valid(dmem_valid),.dmem_address(dmem_address),.dmem_write_data(dmem_write_data),
    .dmem_write_enable(dmem_write_enable),.dmem_read_data(dmem_read_data),
    .dmem_ready(dmem_ready),.dmem_error(dmem_error),.wb_dirty(wb_dirty),
    .mmio_req(c_req),.mmio_ack(c_ack),.mmio_write(c_wr),.mmio_address(c_addr),
    .mmio_write_mask(c_mask),.mmio_write_data(c_data),
    .mmio_read_data(mmio_rdata),.mmio_error(mmio_error),
    .req_ready(1'b0),.rsp_valid(1'b0),.rsp_rdata(128'd0),.rsp_error(1'b0));
  monitor_mem_adapter_128 host_adapter(.clk(clk),.reset(reset),.init_done(1'b1),
    .cpu_halted(halted),.wb_dirty(wb_dirty),.mem_address(mon_address),.mem_write_data(8'd0),
    // El monitor escribe MMIO con WRITE_WORD, no byte a byte: desde v2 una
    // escritura sub-palabra a un periferico es error (§4.1 y §16.2). Antes
    // este banco usaba el puerto de byte y la politica coincidia por
    // casualidad, porque todo lo que probaba daba error igual.
    .mem_write_enable(1'b0),
      .mem_write_word(32'hA5A5_A5A0), .mem_write_word_enable(mon_write),
      .mem_read_enable(mon_read),.mem_read_word(mon_word),
    .mem_ready(mon_ready),.mem_error(mon_error),
    .mmio_req(m_req),.mmio_ack(m_ack),.mmio_write(m_wr),.mmio_address(m_addr),
    .mmio_write_mask(m_mask),.mmio_write_data(m_data),
    .mmio_read_data(mmio_rdata),.mmio_error(mmio_error),
    .req_ready(1'b0),.rsp_valid(1'b0),.rsp_rdata(128'd0),.rsp_error(1'b0));
  mmio_mux mux(.clk(clk),.reset(reset),
    .a_req(m_req),.a_ack(m_ack),.a_write(m_wr),.a_address(m_addr),.a_write_mask(m_mask),.a_write_data(m_data),
    .b_req(c_req),.b_ack(c_ack),.b_write(c_wr),.b_address(c_addr),.b_write_mask(c_mask),.b_write_data(c_data),
    .select(mmio_select),.write(mmio_write),.address(mmio_address),.write_mask(mmio_mask),.write_data(mmio_wdata));
  integer effects=0,guard;
  always @(posedge clk) if(!reset && (video_select || serial_select)) effects<=effects+1;
  task check(input [15:0] blk,input [15:0] addr,input wr,input bad);
    begin
      @(negedge clk);reset=1;base_hi=blk;offset=addr;writing=wr;effects=0;
      repeat(3) @(negedge clk);reset=0;
      @(negedge clk);run_request=1;
      @(negedge clk);run_request=0;
      guard=0;
      while(!halted && guard<300) begin @(negedge clk);guard=guard+1;end
      if(!halted || error!==bad) $fatal(1,"CPU offset %h wr %b error %b",addr,wr,error);
      repeat(2) @(negedge clk); // pc_restore se aplica en STATE_HALTED.
      if(bad && (error_code!==8'd2 || debug_pc!==32'd4 || effects!=0))
        $fatal(1,"fault %h wr %b code %h pc %h efectos %0d",addr,wr,error_code,debug_pc,effects);
      // DEVICES ya no lee cero: en v2 lo declara el top (§5.4). Que valga
      // exactamente lo que dice el mapa es lo que separa "el bloque SYSTEM
      // contesta" de "el bus devuelve basura que parece un bitmap".
      if(!bad && !wr && blk==16'h8000 && addr==16'h000c && debug_data!==32'h0000_0225)
        $fatal(1,"DEVICES = %h, esperado 00000225",debug_data);
      if(!bad && !wr && blk==16'h8000 && addr==16'h0000 && debug_data!==32'h4d47_4155)
        $fatal(1,"MAGIC = %h, esperado 4d474155",debug_data);
      // El monitor debe ver exactamente la misma politica, incluido write
      // retenido durante ack (antes se perdia el fault de solo lectura).
      @(negedge clk);mon_address={blk,addr};mon_write=wr;mon_read=!wr;
      @(negedge clk);mon_write=0;mon_read=0;guard=0;
      while(!mon_ready && guard<100) begin @(negedge clk);guard=guard+1;end
      if(!mon_ready || mon_error!==bad) $fatal(1,"monitor offset %h wr %b error %b",addr,wr,mon_error);
      @(negedge clk);
    end
  endtask
  integer w,k;
  initial begin
    // w=0 lectura, w=1 escritura. `bad` dice si ese acceso debe dar error.
    for(w=0;w<2;w=w+1) begin
      // ---- bloques SIN dispositivo: error siempre -----------------------
      // Son huecos reservados del mapa (§2), y §4.3 exige error y no cero.
      // El de GPU importa en esta carpeta precisamente porque NO hay GPU: un
      // binario compartido que la toque tiene que parar, no leer basura.
      check(16'h8001,16'h0000,w,1);      // FABRIC, sin registros
      check(16'h8002,16'h0000,w,1);      // SDRAM, sin registros
      check(16'h8030,16'h0000,w,1);      // TIMER, no existe
      check(16'h8040,16'h0000,w,1);      // INTC
      check(16'h8050,16'h0000,w,1);      // DMA
      check(16'h8100,16'h0000,w,1);      // CPU CORE, todavia sin registros
      check(16'h8200,16'h0000,w,1);      // GPU CORE: esta carpeta no tiene
      check(16'h8201,16'h0000,w,1);      // GPU WARPS
      // Fuera del espacio asignado del todo.
      check(16'h8800,16'h0000,w,1);
      check(16'hC000,16'h0000,w,1);

      // ---- SYSTEM: siete palabras, SOLO LECTURA -------------------------
      for(k=16'h0000;k<16'h001c;k=k+4) check(16'h8000,k[15:0],w,w!=0);
      check(16'h8000,16'h001c,w,1);      // la octava no existe
      check(16'h8000,16'h0100,w,1);      // fuera de las siete, no es alias
      check(16'h8000,16'h7ffc,w,1);

      // ---- SERIAL: NO EXISTE en esta carpeta ----------------------------
      // `HAS_SERIAL(0)`, igual que en su `top.v`, asi que el bloque entero es
      // un hueco y da error como cualquier otro. Es la unica diferencia de
      // politica entre este banco y el de la 19, y conviene que este probada:
      // el bit 4 de DEVICES esta a cero y §4.3 dice que lo que no existe da
      // error, no cero. Un binario compartido con la 19 que use el puerto
      // serie tiene que parar aqui.
      check(16'h8010,16'h0000,w,1);
      check(16'h8010,16'h0004,w,1);
      check(16'h8010,16'h0008,w,1);
      check(16'h8010,16'h000c,w,1);
      check(16'h8010,16'h0100,w,1);

      // ---- VIDEO: diez registros (VIDEO_REGISTERS = 0x3ff) --------------
      check(16'h8020,16'h0000,w,0);      // CTRL, ahora en +0x00
      check(16'h8020,16'h0024,w,0);      // VIDEO_TX, el ultimo
      check(16'h8020,16'h0028,w,1);      // el siguiente ya no existe
      check(16'h8020,16'h0100,w,1);

      // ---- CPU PERFORMANCE (§12.6) --------------------------------------
      // El array llega hasta +0x0FC y el control va DETRAS, en +0x100. Que
      // +0x100 se pueda ESCRIBIR es la diferencia con v1, donde el bloque
      // entero era de solo lectura.
      check(16'h8101,16'h0000,w,0);      // CYCLES
      check(16'h8101,16'h0004,w,0);      // RETIRED
      check(16'h8101,16'h0008,w,1);      // ranura sin contador
      check(16'h8101,16'h00fc,w,1);      // ultima ranura del array, vacia
      check(16'h8101,16'h0100,w,0);      // PERF_CTRL
      check(16'h8101,16'h0108,w,0);      // PERF_OVF1
      check(16'h8101,16'h010c,w,1);      // detras del control no hay nada
    end
    $display("PASS: errores MMIO llegan a CPU y monitor");$finish;
  end
  initial begin #1000000;$fatal(1,"timeout");end
endmodule
`default_nettype wire
