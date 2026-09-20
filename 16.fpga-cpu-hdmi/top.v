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
  localparam integer CLK_FREQ_HZ = 100_000_000;
  localparam integer UART_CLOCKS_PER_BIT = 100;
  localparam integer UART_MAX_BAUD = 1_000_000;
  localparam integer UART_DIVISOR = UART_CLOCKS_PER_BIT;

  wire clk, pll_locked;
  pll_cpu pll_i(.clkin(clk_25mhz), .clkout0(clk), .locked(pll_locked));

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
  assign wifi_gpio0 = 1'b1;

  wire [7:0] uart_rx_data, uart_tx_data;
  wire uart_rx_strobe, uart_tx_strobe, uart_tx_ready;
  uart #(.DIVISOR(UART_DIVISOR)) uart_i(
      .clk(clk), .reset(reset), .serial_rxd(ftdi_txd), .serial_txd(ftdi_rxd),
      .rxd(uart_rx_data), .rxd_strobe(uart_rx_strobe),
      .txd(uart_tx_data), .txd_strobe(uart_tx_strobe), .txd_ready(uart_tx_ready));

  // Keep UART receive routing and the monitor's large command FSM on separate
  // timing stages. The strobe is delayed with its byte, preserving semantics.
  (* keep = "true" *) reg [7:0] monitor_rx_data;
  (* keep = "true" *) reg monitor_rx_strobe;
  always @(posedge clk) begin
    if (reset) begin
      monitor_rx_data <= 8'h00;
      monitor_rx_strobe <= 1'b0;
    end else begin
      monitor_rx_data <= uart_rx_data;
      monitor_rx_strobe <= uart_rx_strobe;
    end
  end

  wire [31:0] mem_address;
  wire [7:0] mem_write_data, mem_read_data, last_command;
  wire [31:0] mem_read_word;   // la misma lectura sin trocear
  wire [31:0] mem_write_word;  // la palabra entera, para WRITE_WORD
  wire mem_write_enable, mem_write_word_enable;
  wire mem_read_enable, mem_ready, mem_error, monitor_busy;
  wire cpu_run_request, cpu_halt_request, cpu_step_request, cpu_reset_request;
  wire cpu_halted, cpu_error, cpu_instruction_retired;
  wire [7:0] cpu_error_code;
  wire [4:0] cpu_debug_register_address;
  wire [31:0] cpu_debug_register_data, cpu_pc;

  // MAYOR = juego de comandos (1 = base), MENOR = numero de carpeta.
  // Ver docs/unificacion-mmio.md fase 5.
  //
  // 1.7 anadio el subsistema de video sobre el mapa unificado de la 10.
  // BACKPORT DE R0 CABLEADO A CERO: ver 1.isa/isa.md seccion 1.
  //
  // La ventana es la PAGINA ENTERA de MMIO, los mismos 4 KiB que decodifica
  // mmio_decoder.v (`address[31:12] == 20'h80000`, dieciseis dispositivos de
  // 256 B). Declarar la pagina y no cada dispositivo es deliberado: el
  // decodificador ya sabe cuales existen, y una lista por dispositivo seria una
  // tercera gemela que mantener. Gemela de MONITOR_REGIONS en monitor.py.
  monitor #(.VERSION_MAJOR(8'd3),.VERSION_MINOR(8'd16),
      .RAM_END(33'h0_0200_0000),
      // Tres ventanas, no cuatro: esta carpeta no tiene puerto serie, y abrir
      // la de SERIAL solo dejaria pasar accesos que el decodificador va a
      // rechazar. Cada una es el bloque ENTERO de 64 KiB, no el subconjunto de
      // registros que existen hoy: un subconjunto seria una tercera gemela que
      // mantener, y ya se quedo atras una vez.
      .WINDOW0_BASE(33'h0_8000_0000),.WINDOW0_END(33'h0_8001_0000),  // SYSTEM
      .WINDOW1_BASE(33'h0_8020_0000),.WINDOW1_END(33'h0_8021_0000),  // VIDEO
      .WINDOW2_BASE(33'h0_8101_0000),.WINDOW2_END(33'h0_8102_0000))  // CPU PERF
    monitor_i (
      .clk(clk), .reset(reset), .rx_data(monitor_rx_data),
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
      // Sin puerto serie: HAS_SERIAL = 0 y las entradas a cero. Las
      // salidas se quedan al aire y la sintesis se las lleva.
      .serial_rx_free(8'd0), .serial_tx_data(8'd0),
      .serial_tx_count(8'd0),
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
  // La misma lectura sin trocear, para READ_WORD. El adaptador ya la producia;
  // este top la declaraba, se la pasaba al monitor y no la conducia NADIE, asi
  // que READ_WORD latia una X. No saltaba porque monitor_tb conduce esa senal
  // el mismo, siendo un reg del propio banco.
  wire [31:0] adapter_monitor_read_word;
  wire adapter_monitor_ready, adapter_monitor_error;
  reg [7:0] registered_mem_read_data;
  reg [31:0] registered_mem_read_word;
  reg registered_mem_ready, registered_mem_error;
  always @(posedge clk) begin
    if (reset) begin
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

  wire cpu_imem_valid, cpu_imem_ready;
  wire [31:0] cpu_imem_address, cpu_imem_read_data;
  wire cpu_dmem_valid, cpu_dmem_ready, cpu_dmem_error;
  wire [31:0] cpu_dmem_address, cpu_dmem_write_data, cpu_dmem_read_data;
  wire [3:0] cpu_dmem_write_enable;
  // Borrado del underflow y parada por HALT_AT. Los dos nacen en el bloque de
  // registros de video, que se instancia mucho mas abajo, y cruzan a otro
  // sitio: el primero al dominio de pixel y el segundo a la CPU.
  wire video_underflow_clear, video_halt_request;
  cpu cpu_i(
      .clk(clk), .reset(reset || cpu_reset_request),
      .run_request(cpu_run_request),
      // Dos fuentes de parada: el monitor, y el registro HALT_AT del bloque de
      // video, que la para al llegar al frame numero N. Lo segundo es lo que
      // hace repetible una captura de frame, y es la capacidad que esta
      // carpeta GANA al pasar a MMIO v2.
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
  wire video_req, video_ready;
  wire [23:0] video_addr;
  wire [15:0] video_read_data;
  wire mmio_select, mmio_write;
  wire [3:0] mmio_write_mask;
  // El espacio MMIO entero, en bloques de 64 KiB separados por megabytes
  // (MMIO v2, 1.isa/mmio.md seccion 2). Ya no es una pagina de 4 KiB con
  // dieciseis ranuras de 256 B, asi que la direccion va ENTERA: el
  // decodificador elige bloque con `address[26:16]` y con doce bits no cabe ni
  // la base de VIDEO. Truncarla es el fallo de la 18, que Verilog conecta sin
  // un aviso; `test_top_wiring.py` compara esta anchura contra el puerto.
  wire [31:0] mmio_address;
  wire [31:0] mmio_write_data, mmio_read_data;
  wire mmio_error;

  wire req_valid, req_write, req_ready, sdram_done, init_done, sdram_busy;
  wire [23:0] req_addr;
  wire [15:0] req_wdata, sdram_rdata;
  wire [1:0] req_wmask;
  sdram_system_adapter adapter_i(
      .clk(clk), .reset(reset), .init_done(init_done),
      .monitor_address(adapter_monitor_address),
      .monitor_write_data(adapter_monitor_write_data),
      .monitor_write_enable(adapter_monitor_write_enable),
      .monitor_write_word(adapter_monitor_write_word),
      .monitor_write_word_enable(adapter_monitor_write_word_enable),
      .monitor_read_enable(adapter_monitor_read_enable),
      .monitor_read_data(adapter_monitor_read_data),
      .monitor_read_word(adapter_monitor_read_word),
      .monitor_ready(adapter_monitor_ready),
      .monitor_error(adapter_monitor_error), .cpu_halted(cpu_halted),
      .cpu_imem_valid(cpu_imem_valid), .cpu_imem_address(cpu_imem_address),
      .cpu_imem_read_data(cpu_imem_read_data), .cpu_imem_ready(cpu_imem_ready),
      .cpu_dmem_valid(cpu_dmem_valid), .cpu_dmem_address(cpu_dmem_address),
      .cpu_dmem_write_data(cpu_dmem_write_data),
      .cpu_dmem_write_enable(cpu_dmem_write_enable),
      .cpu_dmem_read_data(cpu_dmem_read_data), .cpu_dmem_ready(cpu_dmem_ready),
      .cpu_dmem_error(cpu_dmem_error),
      .mmio_select(mmio_select), .mmio_write(mmio_write),
      .mmio_write_mask(mmio_write_mask), .mmio_address(mmio_address),
      .mmio_write_data(mmio_write_data), .mmio_read_data(mmio_read_data), .mmio_error(mmio_error),
      .video_req(video_req), .video_addr(video_addr),
      .video_read_data(video_read_data), .video_ready(video_ready),
      .req_valid(req_valid),
      .req_write(req_write), .req_addr(req_addr), .req_wdata(req_wdata),
      .req_wmask(req_wmask), .req_ready(req_ready), .done(sdram_done),
      .rdata(sdram_rdata));

  sdram_controller #(.CLK_FREQ_HZ(CLK_FREQ_HZ)) controller_i(
      .clk(clk), .reset(reset), .req_valid(req_valid), .req_write(req_write),
      .req_addr(req_addr), .req_wdata(req_wdata), .req_wmask(req_wmask),
      .req_ready(req_ready), .done(sdram_done), .rdata(sdram_rdata),
      .init_done(init_done), .busy(sdram_busy), .sdram_clk(sdram_clk),
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
      .clk_sys(clk), .rst_sys(reset),
      .underflow_clear(video_underflow_clear),
      .fill_start(fill_start), .fill_line(fill_line), .fill_first(fill_first),
      .fill_we(fill_we), .fill_addr(fill_addr), .fill_data(fill_data),
      .fill_done(fill_done));

  // Productor del hito C: lee el framebuffer de la SDRAM. El generador de
  // Dos productores de linea, y un mux que elige entre ellos segun VIDEO_CTRL.
  //
  // El generador de patron llevaba desde el hito C sin instanciarse: existia en
  // el arbol solo por su banco de pruebas. Vuelve porque ahora hace falta un
  // modo que NO lea memoria -- que es la razon de ser de VIDEO_CTRL.
  //
  // El mux NO se puentea con `video_mode` directamente. Ver la cabecera de
  // video_line_source_mux.v: cambiar de modo a media linea dejaba a la fuente
  // entrante sin `fill_start` y a la saliente sin poder entregar su
  // `fill_done`, y el video se quedaba ENCALLADO para siempre. Lo comprueba
  // video_mode_switch_tb.
  wire start_sdram, start_pattern;
  wire burst_we, pat_we, burst_done, pat_done;
  wire [8:0] burst_addr, pat_addr;
  wire [15:0] burst_data, pat_data;

  video_line_source_sdram source_i(
      .clk(clk), .reset(reset), .fb_base(fb_base),
      .fill_start(start_sdram), .fill_line(fill_line),
      .fill_we(burst_we), .fill_addr(burst_addr), .fill_data(burst_data),
      .fill_done(burst_done),
      .video_req(video_req), .video_addr(video_addr),
      .video_read_data(video_read_data), .video_ready(video_ready));

  video_line_source_pattern pattern_source_i(
      .clk(clk), .reset(reset),
      .fill_start(start_pattern), .fill_line(fill_line),
      .fill_we(pat_we), .fill_addr(pat_addr), .fill_data(pat_data),
      .fill_done(pat_done));

  video_line_source_mux source_mux_i(
      .clk(clk), .reset(reset), .video_mode(video_mode),
      .fill_start(fill_start),
      .start_sdram(start_sdram), .start_pattern(start_pattern),
      .burst_we(burst_we), .burst_addr(burst_addr),
      .burst_data(burst_data), .burst_done(burst_done),
      .pat_we(pat_we), .pat_addr(pat_addr),
      .pat_data(pat_data), .pat_done(pat_done),
      .fill_we(fill_we), .fill_addr(fill_addr),
      .fill_data(fill_data), .fill_done(fill_done));

  // Reparto del espacio MMIO entre bloques. El mapa esta en mmio_decoder.v:
  // SYSTEM en 0x80000000, VIDEO en 0x80200000 y CPU PERFORMANCE en
  // 0x81010000. El video se MUEVE: ya no esta en 0x80000000, que ahora es el
  // bloque de identificacion.
  //
  // ISA_PROFILE: MUL y DIV. Ni subpalabra --esta carpeta no tiene
  // STOREB/LOADB-- ni el bit 3 de SIMT, que aunque `cpu.v` decodifique SSY y
  // BAR aqui son NO-OP, puestos para poder compartir binarios con la GPU.
  //
  // Esta carpeta no tiene puerto serie: su `select` se queda sin conectar, su
  // dato leido es cero y su bit de DEVICES es cero, o sea que un acceso a
  // 0x80100000 da error en vez de contestar (seccion 4.3).
  //
  // VIDEO_REGISTERS pasa de 0x4f a 0x3ff, y no es un renombrado: esta carpeta
  // GANA los cinco registros de v2. Ver docs/migracion-v2.md, "la decision del
  // bitmap". El valor tiene que ser el de lo que `video_registers.v`
  // implementa de verdad, y hay un test que lo deriva de sus `localparam
  // REG_*` en vez de creerse este numero.
  //
  // MONITOR_VERSION no se deduce de nada: es (mayor << 8) | menor con los
  // MISMOS numeros que el `monitor #(...)` de arriba, o sea 3.16. Copiar el de
  // otra carpeta es un numero perfectamente valido que hace que el bloque
  // SYSTEM declare un juego de comandos que esta carpeta no implementa, y no
  // lo dice ningun test.
  wire mmio_video_select, mmio_video_error, mmio_perf_select;
  wire [31:0] mmio_video_read_data;
  wire [31:0] mmio_perf_read_data;
  mmio_decoder #(.FOLDER(`SYSID_FOLDER), .HAS_SERIAL(0), .VIDEO_REGISTERS(64'h3ff),
      .ISA_PROFILE(`SYSID_ISA_PROFILE),
      // Seccion 5.4: bit 0 SYSTEM, bit 2 SDRAM, bit 5 VIDEO, bit 9 CPU. Sin
      // el bit 4, que es SERIAL. Es el mismo 0x225 de la 18, y por lo mismo.
      .DEVICES(`SYSID_DEVICES),
      .MEM_BASE(`SYSID_MEM_BASE), .MEM_SIZE(`SYSID_MEM_SIZE),
      .MONITOR_VERSION(`SYSID_MONITOR_VERSION))   // 3.16, el mismo que monitor_i
    mmio_decoder_i(
      .select(mmio_select), .write(mmio_write), .write_mask(mmio_write_mask),
      .address(mmio_address),
      .video_select(mmio_video_select), .video_read_data(mmio_video_read_data),
      .video_error(mmio_video_error),
      .serial_select(), .serial_read_data(32'd0),
      .perf_select(mmio_perf_select), .perf_read_data(mmio_perf_read_data),
      .read_data(mmio_read_data), .error(mmio_error));

  // Contadores de rendimiento en 0x81010000 (CPU PERFORMANCE, seccion 13.2).
  // `restart` es `cpu_run_request`: cada `run` empieza una medida nueva, que
  // es lo que estos contadores hacian ya cuando vivian en este fichero.
  cpu_perf_counters perf_i(
      .clk(clk), .reset(reset),
      .select(mmio_perf_select), .write(mmio_write),
      .write_mask(mmio_write_mask),
      .address(mmio_address[15:0]), .write_data(mmio_write_data),
      .read_data(mmio_perf_read_data),
      .running(!cpu_halted), .retired(cpu_instruction_retired),
      .restart(cpu_run_request));

  // Registros de video en 0x80200000, y con ellos el doble framebuffer.
  video_registers registers_i(
      .clk(clk), .reset(reset),
      .select(mmio_video_select), .write(mmio_write),
      .write_mask(mmio_write_mask),
      .address(mmio_address[7:0]), .write_data(mmio_write_data),
      .read_data(mmio_video_read_data),
      .error(mmio_video_error),
      .running(!cpu_halted),
      .fill_start(fill_start), .fill_first(fill_first), .fb_base(fb_base),
      .underflow_pix(video_underflow),
      .underflow_clear(video_underflow_clear),
      .halt_request(video_halt_request),
      .video_mode(video_mode),
      .debug_front(), .debug_back());

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

  reg [7:0] dvi_r, dvi_g, dvi_b;
  reg dvi_hsync, dvi_vsync, dvi_de;
  always @(posedge clk_pix) begin
    dvi_hsync <= scan_hsync;
    dvi_vsync <= scan_vsync;
    dvi_de <= scan_de;
    dvi_r <= show_pattern ? paint_r_d : scan_r;
    dvi_g <= show_pattern ? paint_g_d : scan_g;
    dvi_b <= show_pattern ? paint_b_d : scan_b;
  end

  dvi_generator dvi_i(
      .clk_pix(clk_pix), .clk_pix_5x(clk_pix_5x), .rst_pix(rst_pix),
      .de(dvi_de),
      .data_in_ch0(dvi_b), .data_in_ch1(dvi_g), .data_in_ch2(dvi_r),
      .ctrl_in_ch0({dvi_vsync, dvi_hsync}), .ctrl_in_ch1(2'b00),
      .ctrl_in_ch2(2'b00),
      .tmds_ch0_serial(gpdi_dp[0]), .tmds_ch1_serial(gpdi_dp[1]),
      .tmds_ch2_serial(gpdi_dp[2]), .tmds_clk_serial(gpdi_dp[3]));

  // led[0] deja de mostrar `last_command[0]` para vigilar el subsistema de
  // video: un underflow del line buffer es pegajoso y en pantalla solo se ve
  // como una imagen rota, que puede confundirse con muchas otras cosas.
  assign led = {cpu_error, cpu_halted, init_done, sdram_busy,
                monitor_busy, last_command[1:0], video_underflow};
endmodule

`default_nettype wire
