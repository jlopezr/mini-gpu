`timescale 1ns/1ps
`default_nettype none

/*
 * El lazo completo de INPUT, sin placa.
 *
 *   banco --INPUT_EVENTS / INPUT_PRESENCE--> monitor --> input_registers --LOAD--> CPU
 *
 * Es el equivalente de cpu_serial_tb.v para INPUT: el unico banco que monta el
 * `monitor` de verdad junto al camino de memoria de verdad y un programa de
 * verdad corriendo. monitor_input_tb.v prueba los comandos contra la FIFO sin
 * CPU, y mmio_input_ack_tb.v los accesos MMIO sin monitor. Lo que solo se ve
 * aqui es que las dos mitades se encuentran: que el monitor atiende los
 * comandos MIENTRAS la CPU ejecuta, que el decodificador manda el acceso al
 * dispositivo, y que mmio_mux serializa a los dos clientes sin perder ninguno.
 *
 * El programa lee STATUS, y si hay un evento lo saca de EVENT_DATA, lee
 * KEY_STATE0 y MOUSE_BUTTONS, y cuenta los eventos en R9. Para ver lo que ha
 * leido el banco PARA la CPU y lee los registros con READ_REGISTER:
 *
 *     R6  el ultimo STATUS que leyo el bucle (la FIFO ya vacia)
 *     R7  el ultimo evento
 *     R9  cuantos eventos ha sacado
 *     R10 KEY_STATE0 tras el ultimo
 *     R11 MOUSE_BUTTONS tras el ultimo
 *
 * El ultimo evento de cada tanda es lo que demuestra el orden: si el monitor
 * entregara las palabras cambiadas de sitio, R7 seria otra.
 */
module cpu_input_tb;
  localparam integer CLK_HZ = 100_000_000;
  localparam integer POWERUP_US = 2;

  reg clk = 0;
  reg reset = 1;
  always #5 clk = ~clk;

  integer errors = 0;

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
  wire [31:0] mon_read_word;
  wire [31:0] mon_write_word;
  wire mon_write_word_enable;
  wire mon_ready, mon_error;

  wire input_event_valid, input_presence_write;
  wire input_presence_keyboard, input_presence_mouse;
  wire [31:0] input_event_word;
  wire [4:0] input_free_slots;

  monitor #(.VERSION_MAJOR(8'd5),.VERSION_MINOR(8'd30),
      .HAS_INPUT(1),
      .RAM_END(33'h0_0200_0000),
      .WINDOW0_BASE(33'h0_8000_0000),.WINDOW0_END(33'h0_8001_0000),  // SYSTEM
      .WINDOW1_BASE(33'h0_8010_0000),.WINDOW1_END(33'h0_8011_0000),  // SERIAL
      .WINDOW2_BASE(33'h0_8020_0000),.WINDOW2_END(33'h0_8021_0000),  // VIDEO
      .WINDOW3_BASE(33'h0_8101_0000),.WINDOW3_END(33'h0_8102_0000),  // CPU PERF
      .WINDOW4_BASE(33'h0_8060_0000),.WINDOW4_END(33'h0_8061_0000))  // INPUT
    monitor_i (
      .clk(clk), .reset(reset),
      .rx_data(rx_data), .rx_strobe(rx_strobe),
      .tx_data(tx_data), .tx_strobe(tx_strobe), .tx_ready(tx_ready),
      .mem_address(mon_address), .mem_write_data(mon_write_data),
      .mem_write_enable(mon_write_enable),
      .mem_write_word(mon_write_word),
      .mem_write_word_enable(mon_write_word_enable),
      .mem_read_enable(mon_read_enable),
      .mem_read_data(mon_read_data), .mem_read_word(mon_read_word), .mem_ready(mon_ready),
      .mem_error(mon_error),
      .cpu_run_request(cpu_run_request), .cpu_halt_request(cpu_halt_request),
      .cpu_step_request(cpu_step_request), .cpu_reset_request(cpu_reset_request),
      .cpu_halted(halted), .cpu_error(cpu_error),
      .cpu_error_code(cpu_error_code), .cpu_pc(debug_pc),
      .cpu_debug_register_address(cpu_debug_register_address),
      .cpu_debug_register_data(debug_register_data),
      .serial_rx_free(8'd0), .serial_tx_data(8'd0), .serial_tx_count(8'd0),
      .input_event_valid(input_event_valid), .input_event_word(input_event_word),
      .input_presence_write(input_presence_write),
      .input_presence_keyboard(input_presence_keyboard),
      .input_presence_mouse(input_presence_mouse),
      .input_free_slots(input_free_slots),
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
  wire [31:0] mon_mmio_addr;
  wire [31:0] mon_mmio_wdata;
  wire cpu_mmio_req, cpu_mmio_ack, cpu_mmio_write;
  wire [3:0] cpu_mmio_mask;
  wire [31:0] cpu_mmio_addr;
  wire [31:0] cpu_mmio_wdata;
  wire mmio_select, mmio_write;
  wire [3:0] mmio_write_mask;
  wire [31:0] mmio_address;
  wire [31:0] mmio_write_data, mmio_read_data;
  wire mmio_error;
  wire mmio_input_select, mmio_input_error;
  wire [31:0] mmio_input_read_data;
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
      .mmio_read_data(mmio_read_data), .mmio_error(mmio_error),
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
      .mem_write_enable(mon_write_enable),
      .mem_write_word(mon_write_word), .mem_write_word_enable(mon_write_word_enable), .mem_read_enable(mon_read_enable),
      .mem_read_data(mon_read_data), .mem_read_word(mon_read_word), .mem_ready(mon_ready),
      .mem_error(mon_error),
      .mmio_req(mon_mmio_req), .mmio_ack(mon_mmio_ack),
      .mmio_write(mon_mmio_write), .mmio_write_mask(mon_mmio_mask),
      .mmio_address(mon_mmio_addr), .mmio_write_data(mon_mmio_wdata),
      .mmio_read_data(mmio_read_data), .mmio_error(mmio_error),
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

  mmio_decoder #(.HAS_SERIAL(0), .HAS_INPUT(1)) mmio_decoder_i (
      .clk(clk),
      .select(mmio_select), .write(mmio_write), .write_mask(mmio_write_mask), .address(mmio_address),
      .video_select(), .video_read_data(32'd0), .video_error(1'b0),
      .serial_select(), .serial_read_data(32'd0),
      .input_select(mmio_input_select), .input_read_data(mmio_input_read_data),
      .input_error(mmio_input_error),
      .perf_select(), .perf_read_data(32'd0),
      .read_data(mmio_read_data), .error(mmio_error));

  input_registers input_i (
      .clk(clk), .reset(reset),
      .select(mmio_input_select), .write(mmio_write),
      .write_mask(mmio_write_mask), .address(mmio_address[7:0]),
      .write_data(mmio_write_data), .read_data(mmio_input_read_data),
      .input_error(mmio_input_error),
      .event_valid(input_event_valid), .event_word(input_event_word),
      .presence_write(input_presence_write),
      .presence_keyboard(input_presence_keyboard),
      .presence_mouse(input_presence_mouse), .free_slots(input_free_slots));

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
  reg [31:0] registro;

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

  task send_word;
    input [31:0] w;
    begin
      send_byte(w[7:0]); send_byte(w[15:8]); send_byte(w[23:16]); send_byte(w[31:24]);
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

  // Comando de un solo byte con respuesta de un byte (RUN, HALT).
  task simple_command;
    input [7:0] command;
    input [7:0] expected;
    begin
      base = received_count;
      wait (!monitor_busy && tx_ready);
      send_byte(command);
      wait (received_count == base + 1);
      @(negedge clk);
      if (received[base] !== expected) begin
        $display("FALLO: comando %02x respondio %02x, esperado %02x",
                 command, received[base], expected);
        errors = errors + 1;
      end
    end
  endtask

  // Para la CPU y espera a que lo este: READ_REGISTER solo contesta parada.
  task halt_cpu;
    begin
      simple_command(8'h31, 8'hb1);
      wait (halted);
      repeat (10) @(negedge clk);
    end
  endtask

  task read_register;
    input [4:0] index;
    begin
      base = received_count;
      wait (!monitor_busy && tx_ready);
      send_byte(8'h34);
      send_byte({3'b000, index});
      wait (received_count == base + 5);
      @(negedge clk);
      if (received[base] !== 8'hb4) begin
        $display("FALLO: READ_REGISTER R%0d respondio %02x", index, received[base]);
        errors = errors + 1;
      end
      registro = {received[base+1], received[base+2], received[base+3], received[base+4]};
    end
  endtask

  task expect_register;
    input [4:0] index;
    input [31:0] expected;
    begin
      read_register(index);
      if (registro !== expected) begin
        $display("FALLO: R%0d = %08x, esperado %08x", index, registro, expected);
        errors = errors + 1;
      end
    end
  endtask

  // Un comando de INPUT: respuesta bb/bc y huecos libres.
  task expect_input_response;
    input [7:0] head;
    input [7:0] free;
    begin
      wait (received_count == base + 2);
      @(negedge clk);
      if (received[base] !== head || received[base+1] !== free) begin
        $display("FALLO: respuesta %02x %02x, esperado %02x %02x",
                 received[base], received[base+1], head, free);
        errors = errors + 1;
      end
    end
  endtask

  initial begin
    $dumpvars(0, cpu_input_tb);

    repeat (4) @(negedge clk);
    reset = 0;
    wait (init_done);
    repeat (10) @(negedge clk);

    // Programa (ensamblado con 1.isa/mini_asm.py):
    //
    //         MOVHI R21, 0x8060          ; INPUT
    //   loop: LOAD  R6, R21, 4           ; STATUS
    //         ANDI  R5, R6, 0xFF         ; COUNT
    //         BEQ   R5, R0, loop         ; nada que leer
    //         LOAD  R7, R21, 0           ; EVENT_DATA saca un evento
    //         LOAD  R10, R21, 0x10       ; KEY_STATE0
    //         LOAD  R11, R21, 0x30       ; MOUSE_BUTTONS
    //         ADDI  R9, R9, 1
    //         BRA   loop
    load_word(32'h0000_0000, 32'h5EA08060);
    load_word(32'h0000_0004, 32'h54D50004);
    load_word(32'h0000_0008, 32'h48A600FF);
    load_word(32'h0000_000c, 32'h80A0FFFD);
    load_word(32'h0000_0010, 32'h54F50000);
    load_word(32'h0000_0014, 32'h55550010);
    load_word(32'h0000_0018, 32'h55750030);
    load_word(32'h0000_001c, 32'h45290001);
    load_word(32'h0000_0020, 32'hBFFFFFF8);

    simple_command(8'h30, 8'hb0);              // RUN
    repeat (200) @(negedge clk);
    if (halted) $fatal(1, "la CPU se paro nada mas arrancar: error %02x en %08x",
                       cpu_error_code, debug_pc);

    // -----------------------------------------------------------------------
    // 1. Presencia, y un evento con la CPU en marcha.
    // -----------------------------------------------------------------------
    base = received_count;
    wait (!monitor_busy && tx_ready);
    send_byte(8'h3c); send_byte(8'h03);
    expect_input_response(8'hbc, 8'd16);

    base = received_count;
    wait (!monitor_busy && tx_ready);
    send_byte(8'h3b); send_byte(8'h01);
    send_word(32'h0002_0104);                  // A pulsada con shift izquierdo
    expect_input_response(8'hbb, 8'd15);       // la CPU aun no lo ha sacado

    repeat (3000) @(negedge clk);
    halt_cpu;
    expect_register(5'd9, 32'd1);
    expect_register(5'd7, 32'h0002_0104);
    expect_register(5'd10, 32'h0000_0010);     // KEY_STATE0: el bit de la A
    // R6 es el ULTIMO STATUS que leyo el bucle, ya con la FIFO vacia: ambos
    // dispositivos presentes (bits 17 y 18) y COUNT = 0.
    expect_register(5'd6, 32'h0006_0000);
    if (cpu_error) begin
      $display("FALLO: la CPU dio error %02x", cpu_error_code);
      errors = errors + 1;
    end
    simple_command(8'h30, 8'hb0);

    // -----------------------------------------------------------------------
    // 2. Tres eventos en UN comando: el ultimo demuestra el orden.
    // -----------------------------------------------------------------------
    base = received_count;
    wait (!monitor_busy && tx_ready);
    send_byte(8'h3b); send_byte(8'h03);
    send_word(32'h0100_0100);                  // boton 0 pulsado
    send_word(32'h02FF_D005);                  // movimiento (+5, -3)
    send_word(32'h0100_0000);                  // boton 0 soltado
    wait (received_count == base + 2);

    repeat (3000) @(negedge clk);
    halt_cpu;
    expect_register(5'd9, 32'd4);
    expect_register(5'd7, 32'h0100_0000);      // el ultimo enviado
    expect_register(5'd11, 32'h0000_0000);     // el boton ya esta suelto
    expect_register(5'd10, 32'h0000_0010);     // la A sigue pulsada

    // -----------------------------------------------------------------------
    // 3. Con la CPU PARADA el monitor sigue atendiendo INPUT: los eventos se
    // quedan en la FIFO y los huecos libres bajan.
    // -----------------------------------------------------------------------
    base = received_count;
    wait (!monitor_busy && tx_ready);
    send_byte(8'h3b); send_byte(8'h02);
    send_word(32'h0000_0004);                  // A soltada
    send_word(32'h0200_0001);                  // movimiento (+1, 0)
    expect_input_response(8'hbb, 8'd14);

    simple_command(8'h30, 8'hb0);
    repeat (3000) @(negedge clk);
    halt_cpu;
    expect_register(5'd9, 32'd6);
    expect_register(5'd7, 32'h0200_0001);
    expect_register(5'd10, 32'h0000_0000);     // la A se soltó

    // Sondeo final: la FIFO esta vacia, 16 huecos.
    base = received_count;
    wait (!monitor_busy && tx_ready);
    send_byte(8'h3b); send_byte(8'h00);
    expect_input_response(8'hbb, 8'd16);

    $display("");
    if (errors == 0) $display("cpu_input_tb PASS");
    else             $display("cpu_input_tb FAIL: %0d errores", errors);
    $finish;
  end

  initial begin
    #200000000;
    $display("cpu_input_tb TIMEOUT");
    $finish;
  end
endmodule

`default_nettype wire
