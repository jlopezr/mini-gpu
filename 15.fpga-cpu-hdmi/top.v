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
  localparam integer CLK_FREQ_HZ = 120_000_000;
  localparam integer UART_CLOCKS_PER_BIT = 40;
  localparam integer UART_MAX_BAUD = 3_000_000;
  localparam integer UART_DIVISOR = UART_CLOCKS_PER_BIT;

  wire clk, pll_locked;
  pll_120 pll_i(.clkin(clk_25mhz), .clkout0(clk), .locked(pll_locked));

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
  wire mem_write_enable, mem_read_enable, mem_ready, mem_error, monitor_busy;
  wire cpu_run_request, cpu_halt_request, cpu_step_request, cpu_reset_request;
  wire cpu_halted, cpu_error, cpu_instruction_retired;
  wire [7:0] cpu_error_code;
  wire [4:0] cpu_debug_register_address;
  wire [31:0] cpu_debug_register_data, cpu_pc;

  monitor monitor_i(
      .clk(clk), .reset(reset), .rx_data(monitor_rx_data),
      .rx_strobe(monitor_rx_strobe),
      .tx_data(uart_tx_data), .tx_strobe(uart_tx_strobe), .tx_ready(uart_tx_ready),
      .mem_address(mem_address), .mem_write_data(mem_write_data),
      .mem_write_enable(mem_write_enable), .mem_read_enable(mem_read_enable),
      .mem_read_data(mem_read_data), .mem_ready(mem_ready), .mem_error(mem_error),
      .cpu_run_request(cpu_run_request), .cpu_halt_request(cpu_halt_request),
      .cpu_step_request(cpu_step_request), .cpu_reset_request(cpu_reset_request),
      .cpu_halted(cpu_halted), .cpu_error(cpu_error),
      .cpu_error_code(cpu_error_code), .cpu_pc(cpu_pc),
      .cpu_debug_register_address(cpu_debug_register_address),
      .cpu_debug_register_data(cpu_debug_register_data),
      .last_command(last_command), .busy(monitor_busy));

  // Register both directions of the monitor memory port. Besides making the
  // interface timing-independent, this prevents the monitor FSM, arbitration
  // and response handling from becoming one long combinational path.
  reg [31:0] adapter_monitor_address;
  reg [7:0] adapter_monitor_write_data;
  reg adapter_monitor_write_enable, adapter_monitor_read_enable;
  wire [7:0] adapter_monitor_read_data;
  wire adapter_monitor_ready, adapter_monitor_error;
  reg [7:0] registered_mem_read_data;
  reg registered_mem_ready, registered_mem_error;
  always @(posedge clk) begin
    if (reset) begin
      adapter_monitor_address <= 32'h0000_0000;
      adapter_monitor_write_data <= 8'h00;
      adapter_monitor_write_enable <= 1'b0;
      adapter_monitor_read_enable <= 1'b0;
      registered_mem_read_data <= 8'h00;
      registered_mem_ready <= 1'b0;
      registered_mem_error <= 1'b0;
    end else begin
      adapter_monitor_address <= mem_address;
      adapter_monitor_write_data <= mem_write_data;
      adapter_monitor_write_enable <= mem_write_enable;
      adapter_monitor_read_enable <= mem_read_enable;
      registered_mem_read_data <= adapter_monitor_read_data;
      registered_mem_ready <= adapter_monitor_ready;
      registered_mem_error <= adapter_monitor_error;
    end
  end
  assign mem_read_data = registered_mem_read_data;
  assign mem_ready = registered_mem_ready;
  assign mem_error = registered_mem_error;

  wire cpu_imem_valid, cpu_imem_ready;
  wire [31:0] cpu_imem_address, cpu_imem_read_data;
  wire cpu_dmem_valid, cpu_dmem_ready, cpu_dmem_error;
  wire [31:0] cpu_dmem_address, cpu_dmem_write_data, cpu_dmem_read_data;
  wire [3:0] cpu_dmem_write_enable;
  cpu cpu_i(
      .clk(clk), .reset(reset || cpu_reset_request),
      .run_request(cpu_run_request), .halt_request(cpu_halt_request),
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

  wire req_valid, req_write, req_ready, sdram_done, init_done, sdram_busy;
  wire [23:0] req_addr;
  wire [15:0] req_wdata, sdram_rdata;
  wire [1:0] req_wmask;
  sdram_system_adapter adapter_i(
      .clk(clk), .reset(reset), .init_done(init_done),
      .monitor_address(adapter_monitor_address),
      .monitor_write_data(adapter_monitor_write_data),
      .monitor_write_enable(adapter_monitor_write_enable),
      .monitor_read_enable(adapter_monitor_read_enable),
      .monitor_read_data(adapter_monitor_read_data),
      .monitor_ready(adapter_monitor_ready),
      .monitor_error(adapter_monitor_error), .cpu_halted(cpu_halted),
      .cpu_imem_valid(cpu_imem_valid), .cpu_imem_address(cpu_imem_address),
      .cpu_imem_read_data(cpu_imem_read_data), .cpu_imem_ready(cpu_imem_ready),
      .cpu_dmem_valid(cpu_dmem_valid), .cpu_dmem_address(cpu_dmem_address),
      .cpu_dmem_write_data(cpu_dmem_write_data),
      .cpu_dmem_write_enable(cpu_dmem_write_enable),
      .cpu_dmem_read_data(cpu_dmem_read_data), .cpu_dmem_ready(cpu_dmem_ready),
      .cpu_dmem_error(cpu_dmem_error), .req_valid(req_valid),
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

  wire frame = (sy == V_RES && sx == 0);

  // Scanout con doble line buffer. Los sincronismos que salen de aqui llevan un
  // ciclo de retraso, el que cuesta leer el line buffer, y son la referencia de
  // tiempo de los dos modos.
  wire [7:0] scan_r, scan_g, scan_b;
  wire scan_de, scan_hsync, scan_vsync, video_underflow;
  wire fill_start, fill_we, fill_done;
  wire [7:0] fill_line;
  wire [8:0] fill_addr;
  wire [15:0] fill_data;

  video_scanout scanout_i(
      .clk_pix(clk_pix), .rst_pix(rst_pix), .sx(sx), .sy(sy),
      .de_in(de), .hsync_in(hsync), .vsync_in(vsync),
      .r(scan_r), .g(scan_g), .b(scan_b),
      .de_out(scan_de), .hsync_out(scan_hsync), .vsync_out(scan_vsync),
      .underflow(video_underflow),
      .clk_sys(clk), .rst_sys(reset),
      .fill_start(fill_start), .fill_line(fill_line), .fill_we(fill_we),
      .fill_addr(fill_addr), .fill_data(fill_data), .fill_done(fill_done));

  // Productor del hito B. En el hito C se sustituye por el lector de SDRAM.
  video_line_source_pattern source_i(
      .clk(clk), .reset(reset), .fill_start(fill_start), .fill_line(fill_line),
      .fill_we(fill_we), .fill_addr(fill_addr), .fill_data(fill_data),
      .fill_done(fill_done));

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
