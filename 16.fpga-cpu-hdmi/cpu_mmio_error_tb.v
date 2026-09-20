`default_nettype none
`timescale 1ns/1ps
// Instrucciones reales y accesos del monitor por el mismo decodificador.
// Comprueba codigo y PC del fault, el bloque SYSTEM y ausencia de efectos.
//
// REESCRITO PARA MMIO v2. El banco anterior estaba construido entero sobre la
// pagina de 4 KiB: un `offset` de 16 bits alcanzaba los dieciseis dispositivos
// de 256 B, asi que `check` tomaba una sola direccion. Con los bloques a
// megabytes hace falta ademas la mitad alta, y por eso `check` toma dos
// argumentos. Es la misma reescritura que hizo la 21.
//
// Lo que esta carpeta NO comparte con la 18, la 19 y la 21: aqui no hay
// `mmio_mux` ni `cpu_dmem_adapter`. El arbitraje entre CPU y monitor y la
// deteccion de MMIO viven dentro de `sdram_system_adapter.v`, que es el bloque
// unico de la 16 Y el que se sintetiza. Por eso este banco lo monta a el y no
// la pareja de adaptadores mas el mux.
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
  mmio_decoder #(.FOLDER(8'd16),.HAS_SERIAL(0),
    .VIDEO_REGISTERS(64'h3ff),.ISA_PROFILE(32'h0000_0003),
    .DEVICES(32'h0000_0225),
    .MEM_BASE(32'h0000_0000),.MEM_SIZE(32'h0200_0000),
    .MONITOR_VERSION(32'h0000_0310)) decoder(
    .select(mmio_select),.write(mmio_write),.write_mask(mmio_mask),.address(mmio_address),
    .read_data(mmio_rdata),.error(mmio_error),
    .video_select(video_select),.video_read_data(32'd0),.video_error(1'b0),
    .serial_select(serial_select),.serial_read_data(32'd0),.perf_select(),.perf_read_data(32'd0));
  sdram_system_adapter adapter(.clk(clk),.reset(reset),.init_done(1'b1),
    .cpu_halted(halted),.cpu_imem_valid(1'b0),.cpu_imem_address(32'd0),
    .cpu_dmem_valid(dmem_valid),.cpu_dmem_address(dmem_address),
    .cpu_dmem_write_data(dmem_write_data),.cpu_dmem_write_enable(dmem_write_enable),
    .cpu_dmem_read_data(dmem_read_data),.cpu_dmem_ready(dmem_ready),.cpu_dmem_error(dmem_error),
    .monitor_address(mon_address),.monitor_write_data(8'd0),
    // El monitor escribe MMIO con WRITE_WORD, no byte a byte: desde v2 una
    // escritura sub-palabra a un periferico es error (secciones 4.1 y 16.2).
    // El banco anterior usaba el puerto de byte y la politica coincidia por
    // casualidad, porque todo lo que probaba daba error igual.
    .monitor_write_enable(1'b0),
    .monitor_write_word(32'hA5A5_A5A0), .monitor_write_word_enable(mon_write),
    .monitor_read_enable(mon_read),
    .monitor_ready(mon_ready),.monitor_error(mon_error),.monitor_read_word(mon_word),
    .mmio_select(mmio_select),.mmio_write(mmio_write),.mmio_address(mmio_address),
    .mmio_write_mask(mmio_mask),.mmio_write_data(mmio_wdata),
    .mmio_read_data(mmio_rdata),.mmio_error(mmio_error),
    .video_req(1'b0),.video_addr(24'd0),.req_ready(1'b0),.done(1'b0),.rdata(16'd0));
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
      if(!halted || error!==bad) $fatal(1,"CPU %h:%h wr %b error %b",blk,addr,wr,error);
      repeat(2) @(negedge clk); // pc_restore se aplica en STATE_HALTED.
      if(bad && (error_code!==8'd2 || debug_pc!==32'd4 || effects!=0))
        $fatal(1,"fault %h:%h wr %b code %h pc %h efectos %0d",blk,addr,wr,error_code,debug_pc,effects);
      // DEVICES ya no lee cero: en v2 lo declara el top (seccion 5.4). Que
      // valga exactamente lo que dice el mapa es lo que separa "el bloque
      // SYSTEM contesta" de "el bus devuelve basura que parece un bitmap".
      if(!bad && !wr && blk==16'h8000 && addr==16'h000c && debug_data!==32'h0000_0225)
        $fatal(1,"DEVICES = %h, esperado 00000225",debug_data);
      if(!bad && !wr && blk==16'h8000 && addr==16'h0000 && debug_data!==32'h4d47_4155)
        $fatal(1,"MAGIC = %h, esperado 4d474155",debug_data);
      if(!bad && !wr && blk==16'h8000 && addr==16'h0018 && debug_data!==32'h0000_0310)
        $fatal(1,"MONITOR_VERSION = %h, esperado 00000310",debug_data);
      // El monitor debe ver exactamente la misma politica, incluido write
      // retenido durante ack (antes se perdia el fault de solo lectura).
      @(negedge clk);mon_address={blk,addr};mon_write=wr;mon_read=!wr;
      @(negedge clk);mon_write=0;mon_read=0;guard=0;
      while(!mon_ready && guard<100) begin @(negedge clk);guard=guard+1;end
      if(!mon_ready || mon_error!==bad) $fatal(1,"monitor %h:%h wr %b error %b",blk,addr,wr,mon_error);
      @(negedge clk);
    end
  endtask
  integer w,k;
  initial begin
    // w=0 lectura, w=1 escritura. `bad` dice si ese acceso debe dar error.
    for(w=0;w<2;w=w+1) begin
      // ---- bloques SIN dispositivo: error siempre -----------------------
      // Son huecos reservados del mapa (seccion 2), y la 4.3 exige error y no
      // cero. SERIAL es el caso negativo propio de esta carpeta: existe en el
      // mapa, pero aqui HAS_SERIAL = 0 y su bit de DEVICES es cero, asi que
      // tiene que dar error igual que un bloque que no existe. Eso no lo
      // comprueba ninguna otra carpeta de las que ya estan migradas salvo la
      // 18, y es lo unico que se mide con el hardware delante.
      check(16'h8001,16'h0000,w,1);      // FABRIC, sin registros
      check(16'h8002,16'h0000,w,1);      // SDRAM, sin registros
      check(16'h8010,16'h0000,w,1);      // SERIAL: esta carpeta NO lo tiene
      check(16'h8010,16'h0004,w,1);
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

      // ---- VIDEO: diez registros (VIDEO_REGISTERS = 0x3ff) --------------
      // Esta carpeta pasa de cinco a diez al migrar. El 0x4f de v1 tenia un
      // hueco en los indices 4 y 5; el de v2 es contiguo.
      check(16'h8020,16'h0000,w,0);      // CTRL, ahora en +0x00
      check(16'h8020,16'h0024,w,0);      // VIDEO_TX, el ultimo
      check(16'h8020,16'h0028,w,1);      // el siguiente ya no existe
      check(16'h8020,16'h0100,w,1);

      // ---- CPU PERFORMANCE (seccion 12.6) -------------------------------
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
