// Identidad del prototipo (MMIO v2 §5). GENERADO por `tools/generate-sysid`
// desde el RTL de esta carpeta. §5.4 lo pide asi: «no se escribe a mano en
// cada `top.v` [...]. Un bitmap escrito a mano seria una tercera gemela junto
// a las ventanas del decodificador y la lista del cliente Python».
`include "sysid_params.vh"
`default_nettype none

module top (
    input wire clk_25mhz, input wire btn_pwr_n, input wire btn_fire1,
    output wire [7:0] led, output wire wifi_gpio0,
    input wire ftdi_txd, output wire ftdi_rxd,
    output wire sdram_clk, output wire sdram_cke, output wire sdram_csn,
    output wire sdram_rasn, output wire sdram_casn, output wire sdram_wen,
    output wire [12:0] sdram_a, output wire [1:0] sdram_ba,
    output wire [1:0] sdram_dqm, inout wire [15:0] sdram_d,
    output wire [3:0] gpdi_dp
);
  // 100 MHz, no 120: con el subsistema de video dentro ninguna semilla de
  // nextpnr alcanza los 120. El razonamiento esta en `pll_cpu.v` y en README.md.
  //
  // El baudio baja de 3 a 1 Mbaud como consecuencia, y el divisor tiene que
  // cumplir DOS condiciones a la vez:
  //
  //   1. Multiplo de 4. `uart.v` alimenta la recepcion con DIVISOR/4 porque
  //      sobremuestrea 4 veces, y la division es entera. Un divisor de 50 da
  //      12 en vez de 12,5: la recepcion queda un 4,2 % rapida, casi medio bit
  //      de deriva en una trama de 10, y el enlace falla la mitad de las veces.
  //      Esto paso de verdad entre los hitos C y D.
  //   2. Un baudio que el FTDI sepa generar exacto, o sea 3 MHz partido por 1,
  //      1,5, o multiplos de 0,125 a partir de 2.
  //
  // Entre 40 y 200, el unico divisor que cumple las dos es 100:
  //
  //   divisor  40 -> 2,5   Mbaud   mult. de 4, pero 3/1,2  no existe en el FTDI
  //   divisor  48 -> 2,083 Mbaud   mult. de 4, pero 3/1,44 no existe
  //   divisor  50 -> 2     Mbaud   3/1,5 existe, pero NO es multiplo de 4
  //   divisor  64 -> 1,563 Mbaud   mult. de 4, pero 3/1,92 no existe
  //   divisor 100 -> 1     Mbaud   multiplo de 4 y 3/3 exacto
  // 80 MHz desde la 18: el camino de memoria de 128 bits no cumple 100 en
  // ninguna semilla. El razonamiento completo esta en `pll_cpu.v`.
  //
  // Y el baudio se conserva, que no es casualidad sino la razon de elegir 80 y
  // no otra frecuencia: divisor 80, multiplo de cuatro, y 80/80 = 1 Mbaud, que
  // el FTDI genera exacto como 3/3. Las dos condiciones de abajo se siguen
  // cumpliendo sin tocar monitor.py.
  localparam integer CLK_FREQ_HZ = 80_000_000;
  localparam integer UART_CLOCKS_PER_BIT = 80;
  localparam integer UART_MAX_BAUD = 1_000_000;
  localparam integer UART_DIVISOR = UART_CLOCKS_PER_BIT;

  wire clk, pll_locked;
  pll_cpu pll_i(.clkin(clk_25mhz), .clkout0(clk), .locked(pll_locked));

  wire clk_mem, pll_mem_locked;
  pll_mem pll_mem_i(
      .clkin(clk_25mhz), .clkout0(clk_mem), .locked(pll_mem_locked));

  // Shifted reset avoids a counter terminal-count path on the high-fanout
  // reset net. Sixteen clean clocks are sufficient; the SDRAM controller then
  // performs its own JEDEC power-up delay before asserting init_done.
  reg [15:0] reset_shift = 16'hffff;
  wire reset = reset_shift[15];
  always @(posedge clk) begin
    if (!pll_locked || !btn_pwr_n) begin
      reset_shift <= 16'hffff;
    end else begin
      reset_shift <= {reset_shift[14:0], 1'b0};
    end
  end

  // Copias del reset, una por bloque. Con un solo `reset` el fan-out llegaba a
  // todo el chip, y en la 36 el camino critico de la CPU era esa red: 8,5 ns de
  // ruteo, distancia 154, hasta el FSM de la CPU. Cada copia se registra con la
  // misma condicion que `reset_shift[15]` --mismo instante, mismo valor-- y
  // `keep` impide que la sintesis las vuelva a fusionar en una.
  (* keep = "true" *) reg reset_mon = 1'b1, reset_cpu = 1'b1, reset_bus = 1'b1, reset_vid = 1'b1;
  always @(posedge clk) begin
    if (!pll_locked || !btn_pwr_n) begin
      reset_mon <= 1'b1; reset_cpu <= 1'b1; reset_bus <= 1'b1; reset_vid <= 1'b1;
    end else begin
      reset_mon <= reset_shift[14]; reset_cpu <= reset_shift[14];
      reset_bus <= reset_shift[14]; reset_vid <= reset_shift[14];
    end
  end

  reg [15:0] reset_mem_shift = 16'hffff;
  wire reset_mem = reset_mem_shift[15];
  always @(posedge clk_mem) begin
    if (!pll_mem_locked || !btn_pwr_n)
      reset_mem_shift <= 16'hffff;
    else
      reset_mem_shift <= {reset_mem_shift[14:0], 1'b0};
  end

  // Dos copias de `reset_mem`, igual que las del reloj de la CPU: una red unica
  // llegaba al controlador SDRAM y al fabric desde el otro lado del chip, y en la
  // 36 el camino critico de sdram_clk era esa red (7,7 ns de ruteo, distancia
  // 141, 94,7 MHz). Misma condicion que `reset_mem_shift[15]`, `keep` contra la
  // fusion.
  (* keep = "true" *) reg reset_ctl = 1'b1, reset_fab = 1'b1;
  always @(posedge clk_mem) begin
    if (!pll_mem_locked || !btn_pwr_n) begin
      reset_ctl <= 1'b1; reset_fab <= 1'b1;
    end else begin
      reset_ctl <= reset_mem_shift[14]; reset_fab <= reset_mem_shift[14];
    end
  end
  assign wifi_gpio0 = 1'b1;

  wire [7:0] uart_rx_data, uart_tx_data;
  wire uart_rx_strobe, uart_tx_strobe, uart_tx_ready;
  uart #(.DIVISOR(UART_DIVISOR)) uart_i(
      .clk(clk), .reset(reset_mon), .serial_rxd(ftdi_txd), .serial_txd(ftdi_rxd),
      .rxd(uart_rx_data), .rxd_strobe(uart_rx_strobe),
      .txd(uart_tx_data), .txd_strobe(uart_tx_strobe), .txd_ready(uart_tx_ready));

  // Keep UART receive routing and the monitor's large command FSM on separate
  // timing stages. The strobe is delayed with its byte, preserving semantics.
  (* keep = "true" *) reg [7:0] monitor_rx_data;
  (* keep = "true" *) reg monitor_rx_strobe;
  always @(posedge clk) begin
    if (reset_mon) begin
      monitor_rx_data <= 8'h00;
      monitor_rx_strobe <= 1'b0;
    end else begin
      monitor_rx_data <= uart_rx_data;
      monitor_rx_strobe <= uart_rx_strobe;
    end
  end

  wire [31:0] mem_address;
  wire [7:0] mem_write_data, mem_read_data, last_command;
  wire [31:0] mem_read_word;   // la misma lectura sin trocear, para READ_WORD
  wire [31:0] mem_write_word;  // la palabra entera, para WRITE_WORD
  wire mem_write_enable, mem_write_word_enable;
  wire mem_read_enable, mem_ready, mem_error, monitor_busy;
  wire cpu_run_request, cpu_halt_request, cpu_step_request, cpu_reset_request;
  wire cpu_halted, cpu_error, cpu_instruction_retired;
  wire [7:0] cpu_error_code;
  wire [4:0] cpu_debug_register_address;
  wire [31:0] cpu_debug_register_data, cpu_pc;

  // Lado del monitor del puerto serie: lo que desencapsulan SEND_BYTES y
  // RECV_BYTES. No hay pin ni baudio propio, es el mismo enlace del monitor.
  wire serial_host_push, serial_host_pop;
  wire [7:0] serial_host_push_data;
  wire [7:0] serial_host_rx_free, serial_host_tx_data, serial_host_tx_count;

  // Lado del monitor de INPUT: los eventos ya formados que manda el PC con
  // INPUT_EVENTS e INPUT_PRESENCE. El adaptador es el software del PC; este
  // bloque solo guarda STATE y la FIFO. Ver input_registers.v.
  wire input_event_valid, input_presence_write;
  wire input_presence_keyboard, input_presence_mouse;
  wire [31:0] input_event_word;
  wire [4:0] input_free_slots;
  // Los contadores de rendimiento vivian AQUI, como dos registros que solo
  // leia el host con los comandos 0x36/0x37. Ahora son un dispositivo MMIO en
  // 0x81010000 --el bloque CPU PERFORMANCE de MMIO v2-- y el programa se mide
  // a si mismo sin parar ni pasar por el puerto serie. Ver cpu_perf_counters.v.

  // MAYOR = 5: juego base MAS puerto serie MAS INPUT, diecisiete comandos. Los
  // MAYORES son 3 (base), 4 (base + serie) y 5 (base + serie + INPUT): la 30 es
  // la unica con los dos comandos de INPUT, asi que es la unica que sube. MENOR
  // = numero de carpeta. Las demas carpetas reciben el mismo monitor.v con
  // HAS_INPUT = 0 y contestan `ff` a esos comandos, o sea que su protocolo no
  // cambia y su MAYOR tampoco.
  //
  // 1.15 fue la ALU completa: MULHI, DIVU, REM y REMU (0x0B, 0x0D..0x0F), los
  // desplazamientos con cantidad inmediata (bit 10 de SHL/SHR/SAR) y R0 cableado
  // a cero. El PROTOCOLO no cambia, igual que en 1.13, y subio por la misma
  // razon con un motivo mas: R0 no es un cambio aditivo sino INCOMPATIBLE --un
  // programa que lo use como registro general da resultados distintos sin parar
  // con error-- asi que el runner tiene que poder distinguir los dos bitstreams.
  //
  // Las ventanas que el monitor acepta, una por bloque de MMIO v2. Antes era
  // UNA sola --la pagina de 4 KiB entera-- porque todos los dispositivos
  // cabian dentro; ahora estan a megabytes unos de otros y hacen falta cuatro.
  //
  // `monitor.v` NO se toca: ya tenia cinco ranuras parametrizadas, y esa es la
  // razon de que la migracion no necesite partir el fichero que las diez
  // carpetas comparten byte a byte. Lo que cambia son los valores, que viven
  // aqui.
  //
  // Siguen siendo gemelas de MONITOR_REGIONS en monitor.py, que es la lista
  // que §16.4 quiere derivar de DEVICES en vez de mantener a mano. Eso es
  // trabajo aparte; de momento las dos listas dicen lo mismo y hay un test.
  monitor #(.VERSION_MAJOR(8'd5),.VERSION_MINOR(8'd36),
      .HAS_SERIAL(1), .HAS_INPUT(1),
      .RAM_END(33'h0_0200_0000),
      .WINDOW0_BASE(33'h0_8000_0000),.WINDOW0_END(33'h0_8001_0000),  // SYSTEM
      .WINDOW1_BASE(33'h0_8010_0000),.WINDOW1_END(33'h0_8011_0000),  // SERIAL
      .WINDOW2_BASE(33'h0_8020_0000),.WINDOW2_END(33'h0_8021_0000),  // VIDEO
      .WINDOW3_BASE(33'h0_8101_0000),.WINDOW3_END(33'h0_8102_0000),  // CPU PERF
      .WINDOW4_BASE(33'h0_8060_0000),.WINDOW4_END(33'h0_8061_0000))  // INPUT
    monitor_i (
      .clk(clk), .reset(reset_mon), .rx_data(monitor_rx_data),
      .rx_strobe(monitor_rx_strobe),
      .tx_data(uart_tx_data), .tx_strobe(uart_tx_strobe), .tx_ready(uart_tx_ready),
      .mem_address(mem_address), .mem_write_data(mem_write_data),
      .mem_write_enable(mem_write_enable),
      .mem_write_word(mem_write_word),
      .mem_write_word_enable(mem_write_word_enable),
      .mem_read_enable(mem_read_enable),
      .mem_read_data(mem_read_data), .mem_read_word(mem_read_word), .mem_ready(mem_ready), .mem_error(mem_error),
      .cpu_run_request(cpu_run_request), .cpu_halt_request(cpu_halt_request),
      .cpu_step_request(cpu_step_request), .cpu_reset_request(cpu_reset_request),
      .cpu_halted(cpu_halted), .cpu_error(cpu_error),
      .cpu_error_code(cpu_error_code), .cpu_pc(cpu_pc),
      .cpu_debug_register_address(cpu_debug_register_address),
      .cpu_debug_register_data(cpu_debug_register_data),
      .serial_push(serial_host_push), .serial_push_data(serial_host_push_data),
      .serial_rx_free(serial_host_rx_free),
      .serial_pop(serial_host_pop), .serial_tx_data(serial_host_tx_data),
      .serial_tx_count(serial_host_tx_count),
      .input_event_valid(input_event_valid), .input_event_word(input_event_word),
      .input_presence_write(input_presence_write),
      .input_presence_keyboard(input_presence_keyboard),
      .input_presence_mouse(input_presence_mouse),
      .input_free_slots(input_free_slots),
      .last_command(last_command), .busy(monitor_busy));

  // Register both directions of the monitor memory port. Besides making the
  // interface timing-independent, this prevents the monitor FSM, arbitration
  // and response handling from becoming one long combinational path.
  reg [31:0] adapter_monitor_address;
  reg [7:0] adapter_monitor_write_data;
  reg [31:0] adapter_monitor_write_word;
  reg adapter_monitor_write_enable, adapter_monitor_write_word_enable;
  reg adapter_monitor_read_enable;
  wire [7:0] adapter_monitor_read_data;
  wire [31:0] adapter_monitor_read_word;   // la misma lectura sin trocear
  wire adapter_monitor_ready, adapter_monitor_error;
  reg [7:0] registered_mem_read_data;
  reg [31:0] registered_mem_read_word;
  reg registered_mem_ready, registered_mem_error;
  always @(posedge clk) begin
    if (reset_mon) begin
      adapter_monitor_address <= 32'h0000_0000;
      adapter_monitor_write_data <= 8'h00;
      adapter_monitor_write_word <= 32'h0000_0000;
      adapter_monitor_write_enable <= 1'b0;
      adapter_monitor_write_word_enable <= 1'b0;
      adapter_monitor_read_enable <= 1'b0;
      registered_mem_read_data <= 8'h00;
      registered_mem_read_word <= 32'h0000_0000;
      registered_mem_ready <= 1'b0;
      registered_mem_error <= 1'b0;
    end else begin
      adapter_monitor_address <= mem_address;
      adapter_monitor_write_data <= mem_write_data;
      adapter_monitor_write_word <= mem_write_word;
      adapter_monitor_write_enable <= mem_write_enable;
      adapter_monitor_write_word_enable <= mem_write_word_enable;
      adapter_monitor_read_enable <= mem_read_enable;
      registered_mem_read_data <= adapter_monitor_read_data;
      registered_mem_read_word <= adapter_monitor_read_word;
      registered_mem_ready <= adapter_monitor_ready;
      registered_mem_error <= adapter_monitor_error;
    end
  end
  assign mem_read_data = registered_mem_read_data;
  assign mem_read_word = registered_mem_read_word;
  assign mem_ready = registered_mem_ready;
  assign mem_error = registered_mem_error;

  // Borrado del underflow y parada por HALT_AT. Los dos nacen en el bloque de
  // registros de video, que se instancia mucho mas abajo, y cruzan a otro
  // sitio: el primero al dominio de pixel y el segundo a la CPU.
  wire video_underflow_clear, video_halt_request;

  wire cpu_imem_valid, cpu_imem_ready;
  wire [31:0] cpu_imem_address, cpu_imem_read_data;
  wire cpu_dmem_valid, cpu_dmem_ready, cpu_dmem_error;
  wire [31:0] cpu_dmem_address, cpu_dmem_write_data, cpu_dmem_read_data;
  wire [3:0] cpu_dmem_write_enable;
  cpu cpu_i(
      .clk(clk), .reset(reset_cpu || cpu_reset_request),
      .run_request(cpu_run_request),
      // Dos fuentes de parada: el monitor, y el registro HALT_AT del bloque de
      // video, que la para al completar el intercambio numero N. Lo segundo es
      // lo que hace repetible una captura de frame.
      .halt_request(cpu_halt_request || video_halt_request),
      .step_request(cpu_step_request), .halted(cpu_halted), .error(cpu_error),
      .error_code(cpu_error_code), .instruction_retired(cpu_instruction_retired),
      .imem_valid(cpu_imem_valid), .imem_address(cpu_imem_address),
      .imem_read_data(cpu_imem_read_data), .imem_ready(cpu_imem_ready),
      .dmem_valid(cpu_dmem_valid), .dmem_address(cpu_dmem_address),
      .dmem_write_data(cpu_dmem_write_data),
      .dmem_write_enable(cpu_dmem_write_enable),
      .dmem_read_data(cpu_dmem_read_data), .dmem_ready(cpu_dmem_ready),
      .dmem_error(cpu_dmem_error),
      .debug_register_address(cpu_debug_register_address),
      .debug_register_data(cpu_debug_register_data), .debug_pc(cpu_pc));

  // Puertos de video del adaptador. Se declaran aqui porque el adaptador se
  // instancia antes que el subsistema de video.
  // El lector de video frena al arbitro mientras vacia una rafaga en el line
  // buffer, asi que su `rsp_ready` sale de el y no es constante.
  wire video_rsp_ready;
  wire mmio_select, mmio_write;
  wire [3:0] mmio_write_mask;
  // Doce bits: la ventana pasa de 32 bytes a 4 KiB, repartidos en dieciseis
  // La direccion va ENTERA hasta el decodificador: en v2 los bloques estan a
  // megabytes unos de otros. Ver mmio_decoder.v para el mapa y su coste.
  wire [31:0] mmio_address;
  wire [31:0] mmio_write_data, mmio_read_data;
  wire mmio_error;
  wire mmio_video_select, mmio_serial_select, mmio_input_select;
  wire [31:0] mmio_video_read_data, mmio_video_core_read_data;
  wire [31:0] mmio_console_read_data, mmio_serial_read_data, mmio_input_read_data;
  wire mmio_input_error;
  wire mmio_video_error, mmio_video_core_error, mmio_console_error;
  wire mmio_perf_select;
  // GPU: el bloque 0x8200_0000..0x8203_FFFF llega por `gpu_mmio_bridge`.
  wire mmio_gpu_select, gpu_bridge_done, gpu_bridge_error;
  wire [31:0] gpu_bridge_read_data;
  assign mmio_video_read_data = mmio_video_core_read_data
                                | mmio_console_read_data;
  assign mmio_video_error = mmio_video_core_error | mmio_console_error;


  // ===========================================================================
  // Camino de memoria en rafagas BL8
  //
  // La 16 tenia un solo bloque, `sdram_system_adapter`, que arbitraba monitor,
  // CPU y video contra un controlador de 16 bits. Aqui el bus es de 128 bits y
  // el reparto cambia de forma: cada cliente tiene su propio adaptador y su
  // propio puerto del arbitro.
  //
  //                       ┌── p0  cpu_dmem_adapter      ── dmem 32 bits + MMIO
  //   sdram_controller_128┤── p1  instruction_buffer    ── imem 32 bits
  //           ▲           ├── p2  video_line_source_burst  (nativo, urgent)
  //           │           └── p3  monitor_mem_adapter_128 ── monitor, byte a byte
  //     memory_fabric_4
  //
  // El puerto 1 del arbitro esta pensado en `pruebas/sdram` para una GPU; aqui
  // lo ocupa el bufer de instrucciones, que es el cliente de solo lectura que
  // mas trafico mueve. Cuando llegue la GPU habra que ensanchar el arbitro, y
  // esa conversacion es mejor tenerla con el reparto ya medido.
  //
  // Lo que se queda sin instanciar pero no se borra: `sdram_controller` (BL1) y
  // `sdram_system_adapter`, que siguen siendo la linea base contra la que se
  // compara este camino, y los bancos que los miden siguen pasando.
  // ===========================================================================
  wire init_done, sdram_busy;
  // Alto mientras el bufer de combinacion de escrituras tenga algo sin volcar.
  wire wb_dirty;

  // Puerto comun del arbitro hacia el controlador.
  wire fab_req_valid, fab_req_ready, fab_req_write;
  wire [23:0] fab_req_addr;
  wire [127:0] fab_req_wdata, fab_rdata;
  wire [15:0] fab_req_wmask;
  wire fab_done, fabric_busy;

  // Puerto 0: datos de la CPU.
  wire p0_valid, p0_ready, p0_write, p0_rsp_valid, p0_rsp_ready, p0_rsp_error;
  wire [31:0] p0_addr;
  wire [127:0] p0_wdata, p0_rsp_rdata;
  wire [15:0] p0_wmask;

  // Puerto 1: instrucciones.
  wire p1_valid, p1_ready, p1_write, p1_rsp_valid, p1_rsp_ready, p1_rsp_error;
  wire [31:0] p1_addr;
  wire [127:0] p1_wdata, p1_rsp_rdata;
  wire [15:0] p1_wmask;

  // Puerto 2: video.
  wire p2_valid, p2_ready, p2_write, p2_urgent, p2_rsp_valid, p2_rsp_error;
  wire [31:0] p2_addr;
  wire [127:0] p2_wdata, p2_rsp_rdata;
  wire [15:0] p2_wmask;

  // Puerto 3: monitor.
  wire p3_valid, p3_ready, p3_write, p3_rsp_valid, p3_rsp_ready, p3_rsp_error;
  wire [31:0] p3_addr;
  wire [127:0] p3_wdata, p3_rsp_rdata;
  wire [15:0] p3_wmask;

  // Los dos clientes de la ventana de registros de video.
  wire mon_mmio_req, mon_mmio_ack, mon_mmio_write;
  wire [3:0] mon_mmio_mask;
  wire [31:0] mon_mmio_addr;
  wire [31:0] mon_mmio_wdata;
  wire cpu_mmio_req, cpu_mmio_ack, cpu_mmio_write;
  wire [3:0] cpu_mmio_mask;
  wire [31:0] cpu_mmio_addr;
  wire [31:0] cpu_mmio_wdata;

  cpu_dmem_adapter dmem_adapter_i(
      .clk(clk), .reset(reset_cpu), .init_done(init_done),
      .dmem_valid(cpu_dmem_valid), .dmem_address(cpu_dmem_address),
      .dmem_write_data(cpu_dmem_write_data),
      .dmem_write_enable(cpu_dmem_write_enable),
      .dmem_read_data(cpu_dmem_read_data), .dmem_ready(cpu_dmem_ready),
      .dmem_error(cpu_dmem_error), .cpu_halted(cpu_halted),
      // Los contadores son para los bancos; la sintesis los quita.
      .wb_dirty(wb_dirty), .merge_count(), .flush_count(),
      .mmio_req(cpu_mmio_req), .mmio_ack(cpu_mmio_ack),
      .mmio_write(cpu_mmio_write), .mmio_write_mask(cpu_mmio_mask),
      .mmio_address(cpu_mmio_addr), .mmio_write_data(cpu_mmio_wdata),
      .mmio_read_data(mmio_read_data), .mmio_error(mmio_error),
      .req_valid(p0_valid), .req_ready(p0_ready), .req_write(p0_write),
      .req_addr(p0_addr), .req_wdata(p0_wdata), .req_wmask(p0_wmask),
      .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
      .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));

  // Cuatro lineas de 16 bytes, y cada linea es exactamente una rafaga BL8. El
  // vaciado cuelga de `cpu_halted`, no de `reset`: el monitor reescribe la
  // memoria de programa con la CPU parada, y un reset de CPU tambien la deja
  // parada, asi que los dos casos quedan cubiertos por la misma senal.
  //
  // `hit_count`/`miss_count` no se conectan: existen para los bancos de prueba
  // y la sintesis los quita. Los contadores de rendimiento de la CPU
  // (IMEM_HITS, IMEM_MISSES) cuelgan de los pulsos `hit_event`/`miss_event`.
  wire ibuf_hit, ibuf_miss;
  instruction_buffer #(.LINES(4), .INDEX_BITS(2)) instruction_buffer_i(
      .clk(clk), .reset(reset_cpu), .init_done(init_done),
      .cpu_halted(cpu_halted),
      .cpu_imem_valid(cpu_imem_valid), .cpu_imem_address(cpu_imem_address),
      .cpu_imem_read_data(cpu_imem_read_data), .cpu_imem_ready(cpu_imem_ready),
      .req_valid(p1_valid), .req_ready(p1_ready), .req_write(p1_write),
      .req_addr(p1_addr), .req_wdata(p1_wdata), .req_wmask(p1_wmask),
      .rsp_valid(p1_rsp_valid), .rsp_ready(p1_rsp_ready),
      .rsp_rdata(p1_rsp_rdata), .rsp_error(p1_rsp_error),
      .hit_count(), .miss_count(),
      .hit_event(ibuf_hit), .miss_event(ibuf_miss));

  monitor_mem_adapter_128 monitor_adapter_i(
      .clk(clk), .reset(reset_mon), .init_done(init_done),
      .cpu_halted(cpu_halted), .wb_dirty(wb_dirty),
      .mem_address(adapter_monitor_address),
      .mem_write_data(adapter_monitor_write_data),
      .mem_write_enable(adapter_monitor_write_enable),
      .mem_write_word(adapter_monitor_write_word),
      .mem_write_word_enable(adapter_monitor_write_word_enable),
      .mem_read_enable(adapter_monitor_read_enable),
      .mem_read_data(adapter_monitor_read_data),.mem_read_word(adapter_monitor_read_word),
      .mem_ready(adapter_monitor_ready), .mem_error(adapter_monitor_error),
      .mmio_req(mon_mmio_req), .mmio_ack(mon_mmio_ack),
      .mmio_write(mon_mmio_write), .mmio_write_mask(mon_mmio_mask),
      .mmio_address(mon_mmio_addr), .mmio_write_data(mon_mmio_wdata),
      .mmio_read_data(mmio_read_data), .mmio_error(mmio_error),
      .req_valid(p3_valid), .req_ready(p3_ready), .req_write(p3_write),
      .req_addr(p3_addr), .req_wdata(p3_wdata), .req_wmask(p3_wmask),
      .rsp_valid(p3_rsp_valid), .rsp_ready(p3_rsp_ready),
      .rsp_rdata(p3_rsp_rdata), .rsp_error(p3_rsp_error));

  // El monitor va primero: sus peticiones son raras, las de la CPU son un bucle
  // que puede esperar un ciclo, y asi un SWAP escrito desde el PC no se queda
  // detras de un programa que dibuja a toda velocidad.
  mmio_mux mmio_mux_i(
      .clk(clk), .reset(reset_bus),
      .a_req(mon_mmio_req), .a_ack(mon_mmio_ack), .a_write(mon_mmio_write),
      .a_write_mask(mon_mmio_mask), .a_address(mon_mmio_addr),
      .a_write_data(mon_mmio_wdata),
      .b_req(cpu_mmio_req), .b_ack(cpu_mmio_ack), .b_write(cpu_mmio_write),
      .b_write_mask(cpu_mmio_mask), .b_address(cpu_mmio_addr),
      .b_write_data(cpu_mmio_wdata),
      .slow_start(mmio_gpu_select), .slow_done(gpu_bridge_done),
      .select(mmio_select), .write(mmio_write), .write_mask(mmio_write_mask),
      .address(mmio_address), .write_data(mmio_write_data));

  wire [5:0] m_req_valid, m_req_ready, m_req_urgent, m_req_write;
  wire [31:0] m_req_addr [0:5];
  wire [127:0] m_req_wdata [0:5];
  wire [15:0] m_req_wmask [0:5];
  wire [5:0] m_rsp_valid, m_rsp_ready, m_rsp_error;
  wire [127:0] m_rsp_rdata [0:5];

  // ---------------------------------------------------------------------------
  // GPU (36). Su propio dominio de reloj: el oscilador de la placa (25 MHz), sin
  // PLL, con el mismo patron que la CPU y que la memoria: un reset desplazado y
  // un puente asincrono por cada puerto del fabric. La GPU ocupa los puertos 4
  // (LSU, datos) y 5 (busqueda de instrucciones), donde la 35 tenia dos
  // generadores de trafico de prueba.
  //
  // La GPU no es maestro de MMIO y no tiene video propio: el unico bloque VIDEO
  // es el de la CPU. La CPU llega a sus registros por 0x8200_0000..0x8203_FFFF
  // (`gpu_mmio_bridge`). El kernel y los datos van en la RAM compartida.
  // ---------------------------------------------------------------------------
  wire clk_gpu = clk_25mhz;
  reg [15:0] reset_gpu_shift = 16'hffff;
  wire reset_gpu = reset_gpu_shift[15];
  always @(posedge clk_gpu) begin
    if (!btn_pwr_n) reset_gpu_shift <= 16'hffff;
    else reset_gpu_shift <= {reset_gpu_shift[14:0], 1'b0};
  end

  // `init_done` nace en el dominio de la CPU; la GPU lo sincroniza.
  reg init_done_gpu1, init_done_gpu2;
  always @(posedge clk_gpu) begin
    if (reset_gpu) begin
      init_done_gpu1 <= 1'b0;
      init_done_gpu2 <= 1'b0;
    end else begin
      init_done_gpu1 <= init_done;
      init_done_gpu2 <= init_done_gpu1;
    end
  end

  wire gpu_h_valid, gpu_h_write, gpu_h_done, gpu_h_error;
  wire [31:0] gpu_h_addr, gpu_h_wdata, gpu_h_rdata;
  gpu_mmio_bridge gpu_bridge_i(
      .clk(clk), .reset(reset_bus),
      .start(mmio_gpu_select), .write(mmio_write), .address(mmio_address),
      .write_data(mmio_write_data),
      .done(gpu_bridge_done), .read_data(gpu_bridge_read_data), .error(gpu_bridge_error),
      .gclk(clk_gpu), .greset(reset_gpu),
      .h_valid(gpu_h_valid), .h_write(gpu_h_write), .h_addr(gpu_h_addr),
      .h_wdata(gpu_h_wdata), .h_done(gpu_h_done), .h_rdata(gpu_h_rdata),
      .h_error(gpu_h_error));

  wire        g4_valid, g4_ready, g4_write, g4_rsp_valid, g4_rsp_ready, g4_rsp_error;
  wire [31:0] g4_addr;
  wire [127:0] g4_wdata, g4_rsp_rdata;
  wire [15:0] g4_wmask;
  wire        g5_valid, g5_ready, g5_write, g5_rsp_valid, g5_rsp_ready, g5_rsp_error;
  wire [31:0] g5_addr;
  wire [127:0] g5_wdata, g5_rsp_rdata;
  wire [15:0] g5_wmask;
  wire gpu_halted, gpu_error;

  gpu_system gpu_i(
      .clk(clk_gpu), .reset(reset_gpu), .init_done(init_done_gpu2),
      .h_valid(gpu_h_valid), .h_write(gpu_h_write), .h_addr(gpu_h_addr),
      .h_wdata(gpu_h_wdata), .h_done(gpu_h_done), .h_rdata(gpu_h_rdata),
      .h_error(gpu_h_error),
      .p0_req_valid(g4_valid), .p0_req_ready(g4_ready), .p0_req_write(g4_write),
      .p0_req_addr(g4_addr), .p0_req_wdata(g4_wdata), .p0_req_wmask(g4_wmask),
      .p0_rsp_valid(g4_rsp_valid), .p0_rsp_ready(g4_rsp_ready),
      .p0_rsp_rdata(g4_rsp_rdata), .p0_rsp_error(g4_rsp_error),
      .p1_req_valid(g5_valid), .p1_req_ready(g5_ready), .p1_req_write(g5_write),
      .p1_req_addr(g5_addr), .p1_req_wdata(g5_wdata), .p1_req_wmask(g5_wmask),
      .p1_rsp_valid(g5_rsp_valid), .p1_rsp_ready(g5_rsp_ready),
      .p1_rsp_rdata(g5_rsp_rdata), .p1_rsp_error(g5_rsp_error),
      .gpu_halted(gpu_halted), .gpu_error(gpu_error));

  assign m_req_valid[4] = g4_valid;
  assign g4_ready = m_req_ready[4];
  assign m_req_urgent[4] = 1'b0;
  assign m_req_write[4] = g4_write;
  assign m_req_addr[4] = g4_addr;
  assign m_req_wdata[4] = g4_wdata;
  assign m_req_wmask[4] = g4_wmask;
  assign g4_rsp_valid = m_rsp_valid[4];
  assign m_rsp_ready[4] = g4_rsp_ready;
  assign g4_rsp_rdata = m_rsp_rdata[4];
  assign g4_rsp_error = m_rsp_error[4];

  assign m_req_valid[5] = g5_valid;
  assign g5_ready = m_req_ready[5];
  assign m_req_urgent[5] = 1'b0;
  assign m_req_write[5] = g5_write;
  assign m_req_addr[5] = g5_addr;
  assign m_req_wdata[5] = g5_wdata;
  assign m_req_wmask[5] = g5_wmask;
  assign g5_rsp_valid = m_rsp_valid[5];
  assign m_rsp_ready[5] = g5_rsp_ready;
  assign g5_rsp_rdata = m_rsp_rdata[5];
  assign g5_rsp_error = m_rsp_error[5];

  // CPU datos e instrucciones conservan puertos independientes, como en la
  // 30. Asi un miss de instrucciones y una operacion de datos pueden estar en
  // las colas del fabric simultaneamente.
  assign m_req_valid[0] = p0_valid;
  assign p0_ready = m_req_ready[0];
  assign m_req_urgent[0] = 1'b0;
  assign m_req_write[0] = p0_write;
  assign m_req_addr[0] = p0_addr;
  assign m_req_wdata[0] = p0_wdata;
  assign m_req_wmask[0] = p0_wmask;
  assign p0_rsp_valid = m_rsp_valid[0];
  assign m_rsp_ready[0] = p0_rsp_ready;
  assign p0_rsp_rdata = m_rsp_rdata[0];
  assign p0_rsp_error = m_rsp_error[0];

  assign m_req_valid[1] = p1_valid;
  assign p1_ready = m_req_ready[1];
  assign m_req_urgent[1] = 1'b0;
  assign m_req_write[1] = p1_write;
  assign m_req_addr[1] = p1_addr;
  assign m_req_wdata[1] = p1_wdata;
  assign m_req_wmask[1] = p1_wmask;
  assign p1_rsp_valid = m_rsp_valid[1];
  assign m_rsp_ready[1] = p1_rsp_ready;
  assign p1_rsp_rdata = m_rsp_rdata[1];
  assign p1_rsp_error = m_rsp_error[1];

  assign m_req_valid[2] = p2_valid;
  assign p2_ready = m_req_ready[2];
  assign m_req_urgent[2] = p2_urgent;
  assign m_req_write[2] = p2_write;
  assign m_req_addr[2] = p2_addr;
  assign m_req_wdata[2] = p2_wdata;
  assign m_req_wmask[2] = p2_wmask;
  assign p2_rsp_valid = m_rsp_valid[2];
  assign m_rsp_ready[2] = video_rsp_ready;
  assign p2_rsp_rdata = m_rsp_rdata[2];
  assign p2_rsp_error = m_rsp_error[2];

  assign m_req_valid[3] = p3_valid;
  assign p3_ready = m_req_ready[3];
  assign m_req_urgent[3] = 1'b0;
  assign m_req_write[3] = p3_write;
  assign m_req_addr[3] = p3_addr;
  assign m_req_wdata[3] = p3_wdata;
  assign m_req_wmask[3] = p3_wmask;
  assign p3_rsp_valid = m_rsp_valid[3];
  assign m_rsp_ready[3] = p3_rsp_ready;
  assign p3_rsp_rdata = m_rsp_rdata[3];
  assign p3_rsp_error = m_rsp_error[3];

  wire [5:0] req_empty, req_rd_en, req_rd_valid;
  wire [177:0] req_data [0:5];
  wire [5:0] rsp_full, rsp_wr_en;
  wire [128:0] rsp_data [0:5];
  genvar bridge_index;
  generate
    for (bridge_index = 0; bridge_index < 6; bridge_index = bridge_index + 1) begin : g_bridge
      // Los puertos 4 y 5 son de la GPU y van en su reloj (ver mas arriba).
      fabric_fifo_bridge #(.FIFO_ADDR_WIDTH(2)) bridge_i(
          .master_clk(bridge_index >= 4 ? clk_gpu : clk),
          .master_reset(bridge_index >= 4 ? reset_gpu : reset),
          .req_valid(m_req_valid[bridge_index]), .req_ready(m_req_ready[bridge_index]),
          .req_urgent(m_req_urgent[bridge_index]), .req_write(m_req_write[bridge_index]),
          .req_addr(m_req_addr[bridge_index]), .req_wdata(m_req_wdata[bridge_index]),
          .req_wmask(m_req_wmask[bridge_index]),
          .rsp_valid(m_rsp_valid[bridge_index]), .rsp_ready(m_rsp_ready[bridge_index]),
          .rsp_rdata(m_rsp_rdata[bridge_index]), .rsp_error(m_rsp_error[bridge_index]),
          .mem_clk(clk_mem), .mem_reset(reset_fab),
          .mem_req_empty(req_empty[bridge_index]),
          .mem_req_rd_en(req_rd_en[bridge_index]),
          .mem_req_rd_valid(req_rd_valid[bridge_index]),
          .mem_req_data(req_data[bridge_index]),
          .mem_rsp_full(rsp_full[bridge_index]),
          .mem_rsp_wr_en(rsp_wr_en[bridge_index]),
          .mem_rsp_data(rsp_data[bridge_index]));
    end
  endgenerate

  memory_fabric_fifo_6 fabric_i(
      .clk(clk_mem), .reset(reset_fab),
      .p0_req_empty(req_empty[0]), .p0_req_rd_en(req_rd_en[0]), .p0_req_rd_valid(req_rd_valid[0]), .p0_req_data(req_data[0]), .p0_rsp_full(rsp_full[0]), .p0_rsp_wr_en(rsp_wr_en[0]), .p0_rsp_data(rsp_data[0]),
      .p1_req_empty(req_empty[1]), .p1_req_rd_en(req_rd_en[1]), .p1_req_rd_valid(req_rd_valid[1]), .p1_req_data(req_data[1]), .p1_rsp_full(rsp_full[1]), .p1_rsp_wr_en(rsp_wr_en[1]), .p1_rsp_data(rsp_data[1]),
      .p2_req_empty(req_empty[2]), .p2_req_rd_en(req_rd_en[2]), .p2_req_rd_valid(req_rd_valid[2]), .p2_req_data(req_data[2]), .p2_rsp_full(rsp_full[2]), .p2_rsp_wr_en(rsp_wr_en[2]), .p2_rsp_data(rsp_data[2]),
      .p3_req_empty(req_empty[3]), .p3_req_rd_en(req_rd_en[3]), .p3_req_rd_valid(req_rd_valid[3]), .p3_req_data(req_data[3]), .p3_rsp_full(rsp_full[3]), .p3_rsp_wr_en(rsp_wr_en[3]), .p3_rsp_data(rsp_data[3]),
      .p4_req_empty(req_empty[4]), .p4_req_rd_en(req_rd_en[4]), .p4_req_rd_valid(req_rd_valid[4]), .p4_req_data(req_data[4]), .p4_rsp_full(rsp_full[4]), .p4_rsp_wr_en(rsp_wr_en[4]), .p4_rsp_data(rsp_data[4]),
      .p5_req_empty(req_empty[5]), .p5_req_rd_en(req_rd_en[5]), .p5_req_rd_valid(req_rd_valid[5]), .p5_req_data(req_data[5]), .p5_rsp_full(rsp_full[5]), .p5_rsp_wr_en(rsp_wr_en[5]), .p5_rsp_data(rsp_data[5]),
      .sdram_req_valid(fab_req_valid), .sdram_req_ready(fab_req_ready),
      .sdram_req_write(fab_req_write), .sdram_req_addr(fab_req_addr),
      .sdram_req_wdata(fab_req_wdata), .sdram_req_wmask(fab_req_wmask),
      .sdram_done(fab_done), .sdram_rdata(fab_rdata), .busy(fabric_busy));

  wire init_done_mem;
  reg init_done_sync1, init_done_sync2;
  always @(posedge clk) begin
    if (reset) begin
      init_done_sync1 <= 1'b0;
      init_done_sync2 <= 1'b0;
    end else begin
      init_done_sync1 <= init_done_mem;
      init_done_sync2 <= init_done_sync1;
    end
  end
  assign init_done = init_done_sync2;

  sdram_controller_128 #(.CLK_FREQ_HZ(100_000_000)) controller_i(
      .clk(clk_mem), .reset(reset_ctl),
      .req_valid(fab_req_valid), .req_write(fab_req_write),
      .req_addr(fab_req_addr), .req_wdata(fab_req_wdata),
      .req_wmask(fab_req_wmask), .req_ready(fab_req_ready),
      .done(fab_done), .rdata(fab_rdata),
      .init_done(init_done_mem), .busy(sdram_busy), .sdram_clk(sdram_clk),
      .sdram_cke(sdram_cke), .sdram_csn(sdram_csn), .sdram_rasn(sdram_rasn),
      .sdram_casn(sdram_casn), .sdram_wen(sdram_wen), .sdram_a(sdram_a),
      .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm), .sdram_d(sdram_d));


  // ---------------------------------------------------------------------------
  // Subsistema de video (hitos A y B)
  //
  // Dominio de reloj propio. En el hito B tampoco hay conexion con la CPU ni
  // con la SDRAM: las lineas las genera `video_line_source_pattern`, y lo que
  // se valida es el cruce de dominios y el doble line buffer. En el hito C ese
  // productor se sustituye por un lector de SDRAM con el mismo contrato, y esta
  // es la unica linea de `top` que cambiara.
  //
  // El unico recurso compartido con la CPU es `clk_25mhz`, que alimenta los dos
  // PLL.
  //
  //   625 MHz VCO / 5  = 125,0 MHz  -> reloj serie TMDS
  //   625 MHz VCO / 25 =  25,0 MHz  -> reloj de pixel
  //
  // Los 25,0 MHz son un 0,7 % mas lentos que los 25,175 MHz nominales de
  // 640x480p60. Esta dentro de lo que aceptan los monitores y evita un VCO
  // incomodo; es la misma aproximacion que hacia 13.hdmi con 74 frente a
  // 74,25 MHz para 720p, pero aqui el margen de temporizacion es mucho mayor
  // porque el reloj serie baja de 370 a 125 MHz.
  // ---------------------------------------------------------------------------
  wire clk_pix, clk_pix_5x, clk_pix_locked;
  clock2_gen #(
      .CLKI_DIV(1),
      .CLKFB_DIV(5),
      .CLKOP_DIV(5),
      .CLKOP_CPHASE(2),
      .CLKOS_DIV(25),
      .CLKOS_CPHASE(12)
  ) clock_pix_i(
      .clk_in(clk_25mhz), .clk_5x_out(clk_pix_5x), .clk_out(clk_pix),
      .clk_locked(clk_pix_locked));

  // El reset del dominio de pixel no puede venir del dominio de 120 MHz: se
  // sincroniza el pulsador, que ya es asincrono de por si.
  reg btn_pwr_n_sync_0, btn_pwr_n_sync_1;
  always @(posedge clk_pix) begin
    btn_pwr_n_sync_0 <= btn_pwr_n;
    btn_pwr_n_sync_1 <= btn_pwr_n_sync_0;
  end
  wire rst_pix = !clk_pix_locked || !btn_pwr_n_sync_1;

  localparam integer V_RES = 480;
  wire [11:0] sx, sy;
  wire hsync, vsync, de;
  simple_480p display_i(
      .clk_pix(clk_pix), .rst_pix(rst_pix), .sx(sx), .sy(sy),
      .hsync(hsync), .vsync(vsync), .de(de));

  wire frame = (sy == V_RES[11:0] && sx == 12'd0);

  // Scanout con doble line buffer. Los sincronismos que salen de aqui llevan un
  // ciclo de retraso, el que cuesta leer el line buffer, y son la referencia de
  // tiempo de los dos modos.
  wire [7:0] scan_r, scan_g, scan_b;
  wire scan_de, scan_hsync, scan_vsync, video_underflow;
  wire fill_start, fill_first, fill_we, fill_done;
  // Modo de salida, de video_registers al mux de fuentes de linea. Se declara
  // aqui porque el bloque de registros se instancia mas abajo que el mux.
  wire [1:0] video_mode;
  wire [7:0] fill_line;
  wire [23:0] fb_base;
  wire [8:0] fill_addr;
  wire [15:0] fill_data;

  video_scanout scanout_i(
      .clk_pix(clk_pix), .rst_pix(rst_pix), .sx(sx), .sy(sy),
      .de_in(de), .hsync_in(hsync), .vsync_in(vsync),
      .r(scan_r), .g(scan_g), .b(scan_b),
      .de_out(scan_de), .hsync_out(scan_hsync), .vsync_out(scan_vsync),
      .underflow(video_underflow),
      .clk_sys(clk), .rst_sys(reset_vid),
      .underflow_clear(video_underflow_clear),
      .fill_start(fill_start), .fill_line(fill_line), .fill_first(fill_first),
      .fill_we(fill_we), .fill_addr(fill_addr), .fill_data(fill_data),
      .fill_done(fill_done));

  // Dos productores de linea, y un mux que elige entre ellos segun VIDEO_CTRL.
  //
  // El generador de patron llevaba desde el hito C sin instanciarse: existia en
  // el arbol solo por su banco de pruebas. Vuelve porque ahora hace falta un
  // modo que NO lea memoria -- que es la razon de ser de VIDEO_CTRL: arrancar
  // sin scanout, para que las bases de framebuffer puedan dejar de venir
  // cableadas en el reset.
  //
  // El mux NO se puentea con `video_mode` directamente. Ver la cabecera de
  // video_line_source_mux.v: `video_mode` cambia cuando el software escribe
  // VIDEO_CTRL, sin relacion con el llenado en curso, y hacerlo a media linea
  // dejaba a la fuente entrante sin `fill_start` y a la saliente sin poder
  // entregar su `fill_done` -- el video se quedaba ENCALLADO para siempre, y en
  // placa solo se recuperaba reprogramando la FPGA.
  wire start_sdram, start_pattern;
  wire burst_we, pat_we, burst_done, pat_done;
  wire [8:0] burst_addr, pat_addr;
  wire [15:0] burst_data, pat_data;

  video_line_source_burst source_i(
      .clk(clk), .reset(reset_vid), .fb_base(fb_base),
      .fill_start(start_sdram), .fill_line(fill_line),
      .fill_we(burst_we), .fill_addr(burst_addr), .fill_data(burst_data),
      .fill_done(burst_done),
      .req_valid(p2_valid), .req_ready(p2_ready), .req_write(p2_write),
      .req_addr(p2_addr), .req_wdata(p2_wdata), .req_wmask(p2_wmask),
      .urgent(p2_urgent),
      .rsp_valid(p2_rsp_valid), .rsp_ready(video_rsp_ready),
      .rsp_rdata(p2_rsp_rdata), .rsp_error(p2_rsp_error));

  video_line_source_pattern pattern_source_i(
      .clk(clk), .reset(reset_vid),
      .fill_start(start_pattern), .fill_line(fill_line),
      .fill_we(pat_we), .fill_addr(pat_addr), .fill_data(pat_data),
      .fill_done(pat_done));

  video_line_source_mux source_mux_i(
      .clk(clk), .reset(reset_vid), .video_mode(video_mode),
      .fill_start(fill_start),
      .start_sdram(start_sdram), .start_pattern(start_pattern),
      .burst_we(burst_we), .burst_addr(burst_addr),
      .burst_data(burst_data), .burst_done(burst_done),
      .pat_we(pat_we), .pat_addr(pat_addr),
      .pat_data(pat_data), .pat_done(pat_done),
      .fill_we(fill_we), .fill_addr(fill_addr),
      .fill_data(fill_data), .fill_done(fill_done));

  // Reparto del espacio MMIO entre dispositivos. El mapa esta en
  // mmio_decoder.v. Con MMIO v2 el video se MUEVE de 0x80000000 a 0x80200000,
  // y 0x80000000 pasa a ser el bloque SYSTEM.
  //
  // ISA_PROFILE: MUL, DIV y accesos de subpalabra. El bit 3 (SIMT) va a CERO
  // aunque `cpu.v` decodifique SSY y BAR: aqui son NO-OP, puestos para poder
  // compartir binarios con la GPU. Encenderlo diria al host que este nucleo
  // diverge y reconverge, que es falso.
  //
  // DEVICES (§5.4) no se escribe aqui: sale de `sysid_params.vh`, que genera
  // tools/generate-sysid desde este RTL. Hoy son SYSTEM(0) + FABRIC(1) +
  // SDRAM(2) + SERIAL(4) + VIDEO(5) + CPU(9) + INPUT(11) = 0x0A37; el bit
  // INPUT sale de la capacidad `input_device` (existe input_registers.v).
  wire [31:0] mmio_perf_read_data;
  mmio_decoder #(.FOLDER(`SYSID_FOLDER), .HAS_SERIAL(1), .HAS_INPUT(1), .HAS_GPU(1),
      // Ocho contadores en CPU PERFORMANCE: los mismos que `cpu_perf_counters`.
      .PERF_SLOTS(8),
      .VIDEO_REGISTERS(64'h0000_0000_0001_03ff),
      .ISA_PROFILE(`SYSID_ISA_PROFILE),
      .DEVICES(`SYSID_DEVICES),
      .MEM_BASE(`SYSID_MEM_BASE), .MEM_SIZE(`SYSID_MEM_SIZE),
      .MONITOR_VERSION(`SYSID_MONITOR_VERSION))   // 5.36, el mismo que monitor_i
    mmio_decoder_i(
      .clk(clk),
      .select(mmio_select), .write(mmio_write), .write_mask(mmio_write_mask), .address(mmio_address),
      .video_select(mmio_video_select), .video_read_data(mmio_video_read_data),
      .video_error(mmio_video_error),
      .serial_select(mmio_serial_select), .serial_read_data(mmio_serial_read_data),
      .input_select(mmio_input_select), .input_read_data(mmio_input_read_data),
      .input_error(mmio_input_error),
      .perf_select(mmio_perf_select), .perf_read_data(mmio_perf_read_data),
      .gpu_select(mmio_gpu_select), .gpu_read_data(gpu_bridge_read_data),
      .gpu_error(gpu_bridge_error),
      .read_data(mmio_read_data), .error(mmio_error));

  // Contadores de rendimiento en 0x81010000 (CPU PERFORMANCE, mmio.md §13.2).
  // `restart` es `cpu_run_request`: cada `run` empieza una medida nueva, que
  // es lo que estos contadores hacian ya cuando vivian en este fichero.
  //
  // La direccion son DIECISEIS bits, no ocho: PERF_CTRL vive en +0x100, fuera
  // de lo que alcanzan ocho, porque el array se reserva entero delante (§12.6).
  cpu_perf_counters perf_i(
      .clk(clk), .reset(reset_bus),
      .select(mmio_perf_select), .write(mmio_write),
      .write_mask(mmio_write_mask),
      .address(mmio_address[15:0]), .write_data(mmio_write_data),
      .read_data(mmio_perf_read_data),
      .running(!cpu_halted), .retired(cpu_instruction_retired),
      .restart(cpu_run_request),
      // Esperas de la CPU. Un acceso a datos es MMIO con el mismo criterio que
      // `cpu_dmem_adapter` (`address_is_mmio`), y todo esto va a registros
      // dentro del bloque: ver la cabecera de cpu_perf_counters.v.
      .imem_valid(cpu_imem_valid), .imem_ready(cpu_imem_ready),
      .dmem_valid(cpu_dmem_valid), .dmem_ready(cpu_dmem_ready),
      .dmem_is_mmio(cpu_dmem_address[31] && cpu_dmem_address[1:0] == 2'b00),
      .imem_hit(ibuf_hit), .imem_miss(ibuf_miss),
      .mem_req0(p0_valid), .mem_req1(p1_valid));

  wire text_enable;

  // Registros de video en 0x80200000, y con ellos el doble framebuffer.
  video_registers registers_i(
      .clk(clk), .reset(reset_bus),
      .select(mmio_video_select), .write(mmio_write),
      .write_mask(mmio_write_mask),
      .address(mmio_address[15:0]), .write_data(mmio_write_data),
      .read_data(mmio_video_core_read_data),
      .error(mmio_video_core_error),
      .running(!cpu_halted),
      .fill_start(fill_start), .fill_first(fill_first), .fb_base(fb_base),
      .underflow_pix(video_underflow),
      .underflow_clear(video_underflow_clear),
      .halt_request(video_halt_request),
      .video_mode(video_mode),
      .text_enable(text_enable),
      .debug_front(), .debug_back());

  // Puerto serie en 0x80000200. Los bytes llegan y salen en paquetes del
  // monitor, no por esta ventana: ver serial_port.v.
  serial_port serial_i(
      .clk(clk), .reset(reset_bus),
      .select(mmio_serial_select), .write(mmio_write),
      .write_mask(mmio_write_mask),
      .address(mmio_address[7:0]), .write_data(mmio_write_data),
      .read_data(mmio_serial_read_data),
      .host_push(serial_host_push), .host_push_data(serial_host_push_data),
      .host_rx_free(serial_host_rx_free),
      .host_pop(serial_host_pop), .host_tx_data(serial_host_tx_data),
      .host_tx_count(serial_host_tx_count));

  // INPUT (teclado y raton) en 0x80600000. No hay ningun teclado ni raton
  // conectado a la FPGA: los eventos llegan del PC por el monitor. La presencia
  // tambien: la manda el PC con INPUT_PRESENCE.
  input_registers input_i(
      .clk(clk), .reset(reset_bus),
      .select(mmio_input_select), .write(mmio_write),
      .write_mask(mmio_write_mask),
      .address(mmio_address[7:0]), .write_data(mmio_write_data),
      .read_data(mmio_input_read_data), .input_error(mmio_input_error),
      .event_valid(input_event_valid), .event_word(input_event_word),
      .presence_write(input_presence_write),
      .presence_keyboard(input_presence_keyboard),
      .presence_mouse(input_presence_mouse),
      .free_slots(input_free_slots));

  // Modo de reserva: el patron del hito A, generado por logica pura sin tocar
  // el line buffer. Con FIRE1 pulsado se muestra ese y no el scanout. Es el
  // instrumento de depuracion que separa "falla la cadena HDMI" de "falla el
  // camino de datos": si con FIRE1 se ve bien y sin FIRE1 no, el problema esta
  // del line buffer hacia dentro.
  reg btn_fire1_sync_0, btn_fire1_sync_1;
  always @(posedge clk_pix) begin
    btn_fire1_sync_0 <= btn_fire1;
    btn_fire1_sync_1 <= btn_fire1_sync_0;
  end
  wire show_pattern = btn_fire1_sync_1;

  wire [7:0] paint_r, paint_g, paint_b;
  video_pattern pattern_i(
      .clk_pix(clk_pix), .rst_pix(rst_pix), .sx(sx), .sy(sy), .de(de),
      .frame(frame), .r(paint_r), .g(paint_g), .b(paint_b));

  // El patron es combinacional desde `sx`, mientras que el scanout llega un
  // ciclo mas tarde. Se retrasa para que los dos modos compartan sincronismos.
  reg [7:0] paint_r_d, paint_g_d, paint_b_d;
  always @(posedge clk_pix) begin
    paint_r_d <= paint_r;
    paint_g_d <= paint_g;
    paint_b_d <= paint_b;
  end

  wire [7:0] text_r, text_g, text_b;
  wire text_de, text_hsync, text_vsync;
  wire [7:0] base_r = show_pattern ? paint_r_d : scan_r;
  wire [7:0] base_g = show_pattern ? paint_g_d : scan_g;
  wire [7:0] base_b = show_pattern ? paint_b_d : scan_b;

  text_console console_i(
      .clk_sys(clk), .reset_sys(reset_bus),
      .select(mmio_video_select), .write(mmio_write),
      .write_mask(mmio_write_mask), .address(mmio_address[15:0]),
      .write_data(mmio_write_data), .read_data(mmio_console_read_data),
      .error(mmio_console_error),
      .clk_pix(clk_pix), .reset_pix(rst_pix), .enable(text_enable),
      .sx(sx), .sy(sy), .r_in(base_r), .g_in(base_g), .b_in(base_b),
      .de_in(scan_de), .hsync_in(scan_hsync), .vsync_in(scan_vsync),
      .r_out(text_r), .g_out(text_g), .b_out(text_b), .de_out(text_de),
      .hsync_out(text_hsync), .vsync_out(text_vsync));

  reg [7:0] dvi_r, dvi_g, dvi_b;
  reg dvi_hsync, dvi_vsync, dvi_de;
  always @(posedge clk_pix) begin
    dvi_hsync <= text_hsync;
    dvi_vsync <= text_vsync;
    dvi_de <= text_de;
    dvi_r <= text_r;
    dvi_g <= text_g;
    dvi_b <= text_b;
  end

  dvi_generator dvi_i(
      .clk_pix(clk_pix), .clk_pix_5x(clk_pix_5x), .rst_pix(rst_pix),
      .de(dvi_de),
      .data_in_ch0(dvi_b), .data_in_ch1(dvi_g), .data_in_ch2(dvi_r),
      .ctrl_in_ch0({dvi_vsync, dvi_hsync}), .ctrl_in_ch1(2'b00),
      .ctrl_in_ch2(2'b00),
      .tmds_ch0_serial(gpdi_dp[0]), .tmds_ch1_serial(gpdi_dp[1]),
      .tmds_ch2_serial(gpdi_dp[2]), .tmds_clk_serial(gpdi_dp[3]));

  // led[6] y led[5] eran los fallos pegajosos de los generadores de trafico de
  // la 35; ahora llevan el estado de la GPU (error y parada), que es lo que
  // interesa ver con el kernel en marcha.
  assign led = {cpu_error, gpu_error, gpu_halted,
                init_done, sdram_busy, monitor_busy, cpu_halted,
                video_underflow};
endmodule

`default_nettype wire
