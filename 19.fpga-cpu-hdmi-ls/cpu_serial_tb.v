`timescale 1ns/1ps
`default_nettype none

/*
 * El lazo completo del puerto serie, sin placa.
 *
 *   banco --SEND_BYTES--> monitor --> cola RX --LOAD--> CPU
 *   banco <--RECV_BYTES-- monitor <-- cola TX <--STORE-- CPU
 *
 * Es el unico banco que monta el `monitor` de verdad junto al camino de memoria
 * de verdad y un programa de verdad corriendo. `monitor_tb.v` prueba los dos
 * paquetes contra la cola, pero sin CPU; `serial_port_tb.v` la cola sola. Lo
 * que solo se ve aqui es que las dos mitades se encuentran: que el monitor
 * atiende los paquetes MIENTRAS la CPU ejecuta, que el `mmio_decoder` manda el
 * acceso al dispositivo 2 y no al video, y que `mmio_mux` serializa a los dos
 * clientes sin perder ninguno.
 *
 * El programa devuelve el byte MAS UNO, no el byte. Un eco a secas pasaria
 * igual si las dos colas fueran en realidad la misma, que es un error de
 * cableado facil de cometer y dificil de ver. Sumar uno obliga a que el byte
 * haya pasado por el banco de registros de la CPU.
 *
 * Lo que este banco NO prueba: la serializacion de la UART. Se conduce al
 * monitor byte a byte, como hace `monitor_tb.v`, porque meter la UART en medio
 * multiplica el tiempo de simulacion por ochocientos --80 ciclos por bit-- sin
 * cubrir nada que la placa no cubra ya.
 */
module cpu_serial_tb;
  localparam integer CLK_HZ = 100_000_000;
  localparam integer POWERUP_US = 2;

  localparam [7:0] CMD_SEND_BYTES = 8'h38;
  localparam [7:0] CMD_RECV_BYTES = 8'h39;
  localparam [7:0] RSP_SEND_BYTES = 8'hb8;
  localparam [7:0] RSP_RECV_BYTES = 8'hb9;

  reg clk = 0;
  reg reset = 1;
  always #5 clk = ~clk;

  integer errors = 0;
  integer guard;
  integer i;

  // -- CPU --------------------------------------------------------------------
  wire halted, cpu_error, instruction_retired;
  wire [7:0] cpu_error_code;
  wire imem_valid, imem_ready;
  wire [31:0] imem_address, imem_read_data;
  wire dmem_valid, dmem_ready, dmem_error;
  wire [31:0] dmem_address, dmem_write_data, dmem_read_data;
  wire [3:0] dmem_write_enable;
  wire [31:0] debug_register_data, debug_pc;

  wire cpu_run_request, cpu_halt_request, cpu_step_request, cpu_reset_request;
  wire [4:0] cpu_debug_register_address;

  cpu cpu_i (
      .clk(clk), .reset(reset), .run_request(cpu_run_request),
      .halt_request(cpu_halt_request), .step_request(cpu_step_request),
      .halted(halted), .error(cpu_error), .error_code(cpu_error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid), .imem_address(imem_address),
      .imem_read_data(imem_read_data), .imem_ready(imem_ready),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data), .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(dmem_error),
      .debug_register_address(cpu_debug_register_address),
      .debug_register_data(debug_register_data), .debug_pc(debug_pc));

  // -- Monitor de verdad, conducido byte a byte -------------------------------
  reg [7:0] rx_data = 0;
  reg rx_strobe = 0;
  reg tx_ready = 1;
  wire [7:0] tx_data;
  wire tx_strobe, monitor_busy;
  wire [7:0] last_command;

  wire [31:0] mon_address;
  wire [7:0] mon_write_data;
  wire mon_write_enable, mon_read_enable;
  wire [7:0] mon_read_data;
  wire mon_ready, mon_error;

  wire serial_host_push, serial_host_pop;
  wire [7:0] serial_host_push_data;
  wire [7:0] serial_host_rx_free, serial_host_tx_data, serial_host_tx_count;

  monitor monitor_i (
      .clk(clk), .reset(reset),
      .rx_data(rx_data), .rx_strobe(rx_strobe),
      .tx_data(tx_data), .tx_strobe(tx_strobe), .tx_ready(tx_ready),
      .mem_address(mon_address), .mem_write_data(mon_write_data),
      .mem_write_enable(mon_write_enable), .mem_read_enable(mon_read_enable),
      .mem_read_data(mon_read_data), .mem_ready(mon_ready),
      .mem_error(mon_error),
      .cpu_run_request(cpu_run_request), .cpu_halt_request(cpu_halt_request),
      .cpu_step_request(cpu_step_request), .cpu_reset_request(cpu_reset_request),
      .cpu_halted(halted), .cpu_error(cpu_error),
      .cpu_error_code(cpu_error_code), .cpu_pc(debug_pc),
      .cpu_cycles(32'd0), .cpu_instructions(32'd0),
      .cpu_debug_register_address(cpu_debug_register_address),
      .cpu_debug_register_data(debug_register_data),
      .serial_push(serial_host_push), .serial_push_data(serial_host_push_data),
      .serial_rx_free(serial_host_rx_free),
      .serial_pop(serial_host_pop), .serial_tx_data(serial_host_tx_data),
      .serial_tx_count(serial_host_tx_count),
      .last_command(last_command), .busy(monitor_busy));

  // -- Puertos del arbitro ----------------------------------------------------
  wire p0_valid, p0_ready, p0_write, p0_rsp_valid, p0_rsp_ready, p0_rsp_error;
  wire [31:0] p0_addr;
  wire [127:0] p0_wdata, p0_rsp_rdata;
  wire [15:0] p0_wmask;

  wire p1_valid, p1_ready, p1_write, p1_rsp_valid, p1_rsp_ready, p1_rsp_error;
  wire [31:0] p1_addr;
  wire [127:0] p1_wdata, p1_rsp_rdata;
  wire [15:0] p1_wmask;

  wire p3_valid, p3_ready, p3_write, p3_rsp_valid, p3_rsp_ready, p3_rsp_error;
  wire [31:0] p3_addr;
  wire [127:0] p3_wdata, p3_rsp_rdata;
  wire [15:0] p3_wmask;

  // -- MMIO -------------------------------------------------------------------
  wire mon_mmio_req, mon_mmio_ack, mon_mmio_write;
  wire [3:0] mon_mmio_mask;
  wire [11:0] mon_mmio_addr;
  wire [31:0] mon_mmio_wdata;
  wire cpu_mmio_req, cpu_mmio_ack, cpu_mmio_write;
  wire [3:0] cpu_mmio_mask;
  wire [11:0] cpu_mmio_addr;
  wire [31:0] cpu_mmio_wdata;
  wire mmio_select, mmio_write;
  wire [3:0] mmio_write_mask;
  wire [11:0] mmio_address;
  wire [31:0] mmio_write_data, mmio_read_data;
  wire mmio_video_select, mmio_serial_select;
  wire [31:0] mmio_video_read_data, mmio_serial_read_data;
  wire [31:0] ibuf_hits, ibuf_misses;
  wire wb_dirty;
  wire [31:0] wb_merges, wb_flushes;

  // -- SDRAM ------------------------------------------------------------------
  wire s_req_valid, s_req_ready, s_req_write, s_done;
  wire [23:0] s_req_addr;
  wire [127:0] s_req_wdata, s_rdata;
  wire [15:0] s_req_wmask;
  wire init_done, ctrl_busy, fabric_busy, sdram_clk_unused;
  wire cke, csn, rasn, casn, wen;
  wire [12:0] sdram_a;
  wire [1:0] sdram_ba, sdram_dqm;
  wire [15:0] sdram_dq;

  cpu_dmem_adapter dmem_adapter_i (
      .clk(clk), .reset(reset), .init_done(init_done),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data),
      .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(dmem_error), .cpu_halted(halted),
      .wb_dirty(wb_dirty), .merge_count(wb_merges), .flush_count(wb_flushes),
      .mmio_req(cpu_mmio_req), .mmio_ack(cpu_mmio_ack),
      .mmio_write(cpu_mmio_write), .mmio_write_mask(cpu_mmio_mask),
      .mmio_address(cpu_mmio_addr), .mmio_write_data(cpu_mmio_wdata),
      .mmio_read_data(mmio_read_data),
      .req_valid(p0_valid), .req_ready(p0_ready), .req_write(p0_write),
      .req_addr(p0_addr), .req_wdata(p0_wdata), .req_wmask(p0_wmask),
      .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
      .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));

  instruction_buffer #(.LINES(4), .INDEX_BITS(2)) ibuf_i (
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(halted),
      .cpu_imem_valid(imem_valid), .cpu_imem_address(imem_address),
      .cpu_imem_read_data(imem_read_data), .cpu_imem_ready(imem_ready),
      .req_valid(p1_valid), .req_ready(p1_ready), .req_write(p1_write),
      .req_addr(p1_addr), .req_wdata(p1_wdata), .req_wmask(p1_wmask),
      .rsp_valid(p1_rsp_valid), .rsp_ready(p1_rsp_ready),
      .rsp_rdata(p1_rsp_rdata), .rsp_error(p1_rsp_error),
      .hit_count(ibuf_hits), .miss_count(ibuf_misses));

  monitor_mem_adapter_128 monitor_adapter_i (
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(halted),
      .wb_dirty(wb_dirty),
      .mem_address(mon_address), .mem_write_data(mon_write_data),
      .mem_write_enable(mon_write_enable), .mem_read_enable(mon_read_enable),
      .mem_read_data(mon_read_data), .mem_ready(mon_ready),
      .mem_error(mon_error),
      .mmio_req(mon_mmio_req), .mmio_ack(mon_mmio_ack),
      .mmio_write(mon_mmio_write), .mmio_write_mask(mon_mmio_mask),
      .mmio_address(mon_mmio_addr), .mmio_write_data(mon_mmio_wdata),
      .mmio_read_data(mmio_read_data),
      .req_valid(p3_valid), .req_ready(p3_ready), .req_write(p3_write),
      .req_addr(p3_addr), .req_wdata(p3_wdata), .req_wmask(p3_wmask),
      .rsp_valid(p3_rsp_valid), .rsp_ready(p3_rsp_ready),
      .rsp_rdata(p3_rsp_rdata), .rsp_error(p3_rsp_error));

  mmio_mux mmio_mux_i (
      .clk(clk), .reset(reset),
      .a_req(mon_mmio_req), .a_ack(mon_mmio_ack), .a_write(mon_mmio_write),
      .a_write_mask(mon_mmio_mask), .a_address(mon_mmio_addr),
      .a_write_data(mon_mmio_wdata),
      .b_req(cpu_mmio_req), .b_ack(cpu_mmio_ack), .b_write(cpu_mmio_write),
      .b_write_mask(cpu_mmio_mask), .b_address(cpu_mmio_addr),
      .b_write_data(cpu_mmio_wdata),
      .select(mmio_select), .write(mmio_write),
      .write_mask(mmio_write_mask), .address(mmio_address),
      .write_data(mmio_write_data));

  mmio_decoder mmio_decoder_i (
      .select(mmio_select), .address(mmio_address),
      .video_select(mmio_video_select), .video_read_data(mmio_video_read_data),
      .serial_select(mmio_serial_select),
      .serial_read_data(mmio_serial_read_data),
      .read_data(mmio_read_data));

  video_registers registers_i (
      .clk(clk), .reset(reset),
      .select(mmio_video_select), .write(mmio_write),
      .write_mask(mmio_write_mask), .address(mmio_address[7:0]),
      .write_data(mmio_write_data), .read_data(mmio_video_read_data),
      .fill_start(1'b0), .fill_first(1'b0), .fb_base(),
      .underflow_pix(1'b0), .underflow_clear(),
      .halt_request(), .debug_front(), .debug_back());

  serial_port serial_i (
      .clk(clk), .reset(reset),
      .select(mmio_serial_select), .write(mmio_write),
      .write_mask(mmio_write_mask), .address(mmio_address[7:0]),
      .write_data(mmio_write_data), .read_data(mmio_serial_read_data),
      .host_push(serial_host_push), .host_push_data(serial_host_push_data),
      .host_rx_free(serial_host_rx_free),
      .host_pop(serial_host_pop), .host_tx_data(serial_host_tx_data),
      .host_tx_count(serial_host_tx_count));

  memory_fabric_4 fabric_i (
      .clk(clk), .reset(reset),
      .p0_req_valid(p0_valid), .p0_req_ready(p0_ready),
      .p0_req_write(p0_write), .p0_req_addr(p0_addr),
      .p0_req_wdata(p0_wdata), .p0_req_wmask(p0_wmask),
      .p0_rsp_valid(p0_rsp_valid), .p0_rsp_ready(p0_rsp_ready),
      .p0_rsp_rdata(p0_rsp_rdata), .p0_rsp_error(p0_rsp_error),

      .p1_req_valid(p1_valid), .p1_req_ready(p1_ready),
      .p1_req_write(p1_write), .p1_req_addr(p1_addr),
      .p1_req_wdata(p1_wdata), .p1_req_wmask(p1_wmask),
      .p1_rsp_valid(p1_rsp_valid), .p1_rsp_ready(p1_rsp_ready),
      .p1_rsp_rdata(p1_rsp_rdata), .p1_rsp_error(p1_rsp_error),

      .p2_req_valid(1'b0), .p2_req_ready(), .p2_req_write(1'b0),
      .p2_req_addr(32'd0), .p2_req_wdata(128'd0), .p2_req_wmask(16'd0),
      .p2_urgent(1'b0), .p2_rsp_valid(), .p2_rsp_ready(1'b1),
      .p2_rsp_rdata(), .p2_rsp_error(),

      .p3_req_valid(p3_valid), .p3_req_ready(p3_ready),
      .p3_req_write(p3_write), .p3_req_addr(p3_addr),
      .p3_req_wdata(p3_wdata), .p3_req_wmask(p3_wmask),
      .p3_rsp_valid(p3_rsp_valid), .p3_rsp_ready(p3_rsp_ready),
      .p3_rsp_rdata(p3_rsp_rdata), .p3_rsp_error(p3_rsp_error),

      .sdram_req_valid(s_req_valid), .sdram_req_ready(s_req_ready),
      .sdram_req_write(s_req_write), .sdram_req_addr(s_req_addr),
      .sdram_req_wdata(s_req_wdata), .sdram_req_wmask(s_req_wmask),
      .sdram_done(s_done), .sdram_rdata(s_rdata), .busy(fabric_busy));

  sdram_controller_128 #(
      .CLK_FREQ_HZ(CLK_HZ), .POWERUP_DELAY_US(POWERUP_US)
  ) ctrl (
      .clk(clk), .reset(reset),
      .req_valid(s_req_valid), .req_write(s_req_write), .req_addr(s_req_addr),
      .req_wdata(s_req_wdata), .req_wmask(s_req_wmask),
      .req_ready(s_req_ready), .done(s_done), .rdata(s_rdata),
      .init_done(init_done), .busy(ctrl_busy),
      .sdram_clk(sdram_clk_unused), .sdram_cke(cke), .sdram_csn(csn),
      .sdram_rasn(rasn), .sdram_casn(casn), .sdram_wen(wen),
      .sdram_a(sdram_a), .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm),
      .sdram_d(sdram_dq));

  sdram_model #(
      .POWERUP_DELAY_NS(POWERUP_US * 1000), .READ_DELAY_CYCLES(1)
  ) mem (
      .clk(clk), .cke(cke), .csn(csn), .rasn(rasn), .casn(casn), .wen(wen),
      .a(sdram_a), .ba(sdram_ba), .dqm(sdram_dqm), .dq(sdram_dq));

  // ---------------------------------------------------------------------------
  // Lado del PC: bytes hacia el monitor y respuestas recogidas.
  // ---------------------------------------------------------------------------
  reg [7:0] received[0:255];
  integer received_count = 0;
  integer busy_cycles = 0;

  always @(posedge clk) begin
    if (reset) begin
      tx_ready <= 1'b1;
      busy_cycles <= 0;
    end else if (tx_strobe && tx_ready) begin
      received[received_count] <= tx_data;
      received_count <= received_count + 1;
      tx_ready <= 1'b0;
      busy_cycles <= 2;
    end else if (busy_cycles > 0) begin
      busy_cycles <= busy_cycles - 1;
      if (busy_cycles == 1) tx_ready <= 1'b1;
    end
  end

  integer base;
  reg [7:0] respuesta;
  // El paquete que se va a mandar. Es del modulo y no un argumento porque
  // Verilog-2001 no pasa arrays a una task.
  reg [7:0] entrada[0:31];

  task send_byte;
    input [7:0] value;
    begin
      @(negedge clk);
      rx_data = value;
      rx_strobe = 1'b1;
      @(negedge clk);
      rx_strobe = 1'b0;
      repeat (4) @(negedge clk);
    end
  endtask

  task load_word;
    input [31:0] address;
    input [31:0] value;
    integer k;
    begin
      for (k = 0; k < 4; k = k + 1) begin
        base = received_count;
        wait (!monitor_busy && tx_ready);
        send_byte(8'h10);                      // WRITE_BYTE
        send_byte(address[31:24]); send_byte(address[23:16]);
        send_byte(address[15:8]);  send_byte(address[7:0] + k[7:0]);
        send_byte(value[8*k +: 8]);
        wait (received_count == base + 1);
        if (received[base] !== 8'h90)
          $fatal(1, "la carga del programa fallo en %08x", address + k);
      end
    end
  endtask

  // Manda los `n` primeros bytes de `entrada` y deja en `respuesta` cuantos
  // aceptaron.
  task send_bytes;
    input integer n;
    integer k;
    begin
      base = received_count;
      wait (!monitor_busy && tx_ready);
      send_byte(CMD_SEND_BYTES);
      send_byte(n[7:0]);
      for (k = 0; k < n; k = k + 1) send_byte(entrada[k]);
      wait (received_count == base + 2);
      if (received[base] !== RSP_SEND_BYTES)
        $fatal(1, "SEND_BYTES respondio %02x", received[base]);
      respuesta = received[base+1];
    end
  endtask

  initial begin
    $dumpvars(0, cpu_serial_tb);

    repeat (4) @(negedge clk);
    reset = 0;
    wait (init_done);
    repeat (10) @(negedge clk);

    // -----------------------------------------------------------------------
    // echo.asm: espera a que haya algo en RX, lo lee, le suma uno y lo mete en
    // TX. Ver la cabecera sobre por que suma uno.
    //
    //     MOVHI R20, 0x8000
    //     ORI   R20, R20, 0x0200     ; base del dispositivo serie
    //     MOVI  R3, 0
    // loop: LOAD  R4, R20, 4         ; STATUS
    //     ANDI  R5, R4, 0x00FF       ; rx_count
    //     BEQ   R5, R3, loop         ; nada que leer
    //     LOAD  R6, R20, 0           ; DATA saca un byte
    //     ADDI  R6, R6, 1
    //     STORE R6, R20, 0           ; y lo devuelve
    //     BRA   loop
    // -----------------------------------------------------------------------
    load_word(32'h0000_0000, 32'h5E80_8000);
    load_word(32'h0000_0004, 32'h4E94_0200);
    load_word(32'h0000_0008, 32'h4060_0000);
    load_word(32'h0000_000c, 32'h5494_0004);
    load_word(32'h0000_0010, 32'h48A4_00FF);
    load_word(32'h0000_0014, 32'h80A3_FFFD);
    load_word(32'h0000_0018, 32'h54D4_0000);
    load_word(32'h0000_001c, 32'h44C6_0001);
    load_word(32'h0000_0020, 32'h58D4_0000);
    load_word(32'h0000_0024, 32'hBFFF_FFF9);

    // Arrancar la CPU. A partir de aqui gira en su bucle de espera, y todo lo
    // que sigue ocurre con ella EN MARCHA.
    base = received_count;
    wait (!monitor_busy && tx_ready);
    send_byte(8'h30);                          // RUN
    wait (received_count == base + 1);
    if (received[base] !== 8'hb0) $fatal(1, "RUN fallo");
    repeat (200) @(negedge clk);
    if (halted) $fatal(1, "la CPU se paro nada mas arrancar: error %02x en %08x",
                       cpu_error_code, debug_pc);

    // -----------------------------------------------------------------------
    // 1. Tres bytes de ida, tres de vuelta con uno mas.
    // -----------------------------------------------------------------------
    entrada[0] = 8'h41;  // 'A'
    entrada[1] = 8'h42;  // 'B'
    entrada[2] = 8'h43;  // 'C'
    send_bytes(3);
    if (respuesta !== 8'd3) $fatal(1, "SEND_BYTES acepto %0d de 3", respuesta);

    // Dejar que el programa los procese. No hay nada que sincronizar: la CPU
    // gira sobre STATUS y el monitor no la para.
    repeat (3000) @(negedge clk);

    base = received_count;
    wait (!monitor_busy && tx_ready);
    send_byte(CMD_RECV_BYTES);
    send_byte(8'd16);
    wait (received_count == base + 5);
    if (received[base] !== RSP_RECV_BYTES) $fatal(1, "RECV_BYTES respuesta");
    if (received[base+1] !== 8'd3) begin
      $display("FALLO: volvieron %0d bytes, esperados 3", received[base+1]);
      errors = errors + 1;
    end
    if (received[base+2] !== 8'h42 || received[base+3] !== 8'h43 ||
        received[base+4] !== 8'h44) begin
      $display("FALLO: eco = %02x %02x %02x, esperado 42 43 44",
               received[base+2], received[base+3], received[base+4]);
      errors = errors + 1;
    end

    // -----------------------------------------------------------------------
    // 2. La CPU sigue viva y el lazo se puede repetir.
    // -----------------------------------------------------------------------
    if (halted) begin
      $display("FALLO: la CPU se paro tras el primer eco");
      errors = errors + 1;
    end

    entrada[0] = 8'h7A;  // 'z'
    send_bytes(1);
    if (respuesta !== 8'd1) $fatal(1, "el segundo paquete no entro");
    repeat (2000) @(negedge clk);

    base = received_count;
    wait (!monitor_busy && tx_ready);
    send_byte(CMD_RECV_BYTES);
    send_byte(8'd16);
    wait (received_count == base + 3);
    if (received[base+1] !== 8'd1 || received[base+2] !== 8'h7B) begin
      $display("FALLO: segundo eco = %0d bytes, %02x", received[base+1],
               received[base+2]);
      errors = errors + 1;
    end

    // -----------------------------------------------------------------------
    // 3. Los registros de video siguen respondiendo donde estaban.
    //
    // Es la comprobacion de que anadir un dispositivo no movio el otro: el
    // monitor lee FB_FRONT por la misma ventana que usa la CPU para el serie,
    // y el decodificador tiene que mandar cada uno a su sitio.
    // -----------------------------------------------------------------------
    base = received_count;
    wait (!monitor_busy && tx_ready);
    send_byte(8'h11);                          // READ_BYTE
    send_byte(8'h80); send_byte(8'h00); send_byte(8'h00); send_byte(8'h03);
    wait (received_count == base + 2);
    if (received[base] !== 8'h91 || received[base+1] !== 8'h01) begin
      $display("FALLO: FB_FRONT[31:24] = %02x, esperado 01", received[base+1]);
      errors = errors + 1;
    end

    if (mem.errors != 0) begin
      $display("FALLO: el modelo de SDRAM conto %0d violaciones JEDEC", mem.errors);
      errors = errors + 1;
    end

    if (errors != 0) $fatal(1, "%0d comprobaciones fallaron", errors);
    $display("PASS: cpu_serial, el lazo completo con la CPU en marcha");
    $finish;
  end

  initial begin
    #20_000_000;
    $fatal(1, "timeout");
  end
endmodule

`default_nettype wire
