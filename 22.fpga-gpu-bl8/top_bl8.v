`default_nettype none
module top_bl8(input clk_25mhz, output [7:0] led, output wifi_gpio0,
    input ftdi_txd, output ftdi_rxd,
    output sdram_clk, sdram_cke, sdram_csn, sdram_rasn, sdram_casn, sdram_wen,
    output [12:0] sdram_a, output [1:0] sdram_ba, sdram_dqm,
    inout [15:0] sdram_d,
    output [3:0] gpdi_dp);
    // 25 MHz nativos para el sistema: la GPU, el monitor, la UART y la SDRAM
    // van en clk_25mhz. El PLL de abajo genera clk_pix y clk_pix_5x, que son
    // solo del scanout HDMI y no tocan este reloj.
    //
    // El divisor de la UART cumple las mismas DOS condiciones que en los cores
    // de CPU -- ver 21.fpga-cpu-hdmi-alu/top.v, donde estan razonadas --, y
    // conviene que quede escrito en vez de heredado:
    //
    //   1. Multiplo de 4, porque uart.v alimenta la recepcion con DIVISOR/4 y
    //      la division es entera. `uart.v` lo comprueba en elaboracion.
    //   2. Un baudio que el FTDI sepa generar exacto: 250 k = 3 MHz / 12.
    localparam integer CLK_FREQ_HZ = 25_000_000;
    localparam integer UART_CLOCKS_PER_BIT = 100;
    localparam integer UART_MAX_BAUD = 250_000;
    localparam integer UART_DIVISOR = UART_CLOCKS_PER_BIT;
    reg [7:0] power_on=0;
    wire reset=!(&power_on);
    always @(posedge clk_25mhz) if(reset) power_on<=power_on+1'b1;
    assign wifi_gpio0=1;
    wire [7:0] rx_data,tx_data,last_command;
    wire rx_strobe,tx_strobe,tx_ready,busy;
    uart #(.DIVISOR(UART_DIVISOR)) uart_i (.clk(clk_25mhz),.reset(reset),
        .serial_txd(ftdi_rxd),.serial_rxd(ftdi_txd),.rxd(rx_data),.rxd_strobe(rx_strobe),
        .txd(tx_data),.txd_strobe(tx_strobe),.txd_ready(tx_ready));
    wire [31:0] address,debug_data,pc;
    wire [7:0] write_data,read_data,error_code;
    // La misma lectura sin trocear, para READ_WORD.
    wire [31:0] read_word;
    wire we,re,ready,mem_error,run_req,halt_req,step_req,reset_req,halted,error,retired;
    wire [4:0] debug_register;
    // Las ventanas son la GEMELA de MONITOR_REGIONS en monitor.py, y las cuatro
    // estan pobladas: esta es la unica de la familia con video y contadores.
    monitor #(.VERSION_MAJOR(8'd1),.VERSION_MINOR(8'd22),
        .RAM_END(33'h0_0200_0000),
        .WINDOW0_BASE(33'h0_8000_0000),.WINDOW0_END(33'h0_8000_001c),
        .WINDOW1_BASE(33'h0_8000_0100),.WINDOW1_END(33'h0_8000_0118),
        .WINDOW2_BASE(33'h0_8000_0300),.WINDOW2_END(33'h0_8000_0320),
        .WINDOW3_BASE(33'h0_8000_1000),.WINDOW3_END(33'h0_8000_1080),
        // Identificacion: SYS_ID, CONTRACT, DEV_BITMAP e ISA_PROFILE.
        .WINDOW4_BASE(33'h0_8000_0f00),.WINDOW4_END(33'h0_8000_0f10))
      monitor_i (.clk(clk_25mhz),.reset(reset),.rx_data(rx_data),.rx_strobe(rx_strobe),
        .tx_data(tx_data),.tx_strobe(tx_strobe),.tx_ready(tx_ready),
        .mem_address(address),.mem_write_data(write_data),.mem_write_enable(we),
        .mem_read_enable(re),.mem_read_data(read_data),.mem_read_word(read_word),.mem_ready(ready),.mem_error(mem_error),
        .cpu_run_request(run_req),.cpu_halt_request(halt_req),.cpu_step_request(step_req),
        .cpu_reset_request(reset_req),.cpu_halted(halted),.cpu_error(error),.cpu_error_code(error_code),
        .cpu_pc(pc),.cpu_debug_register_address(debug_register),.cpu_debug_register_data(debug_data),
        .last_command(last_command),.busy(busy));
    wire init_done,mem_req_valid,mem_req_ready,mem_req_write,mem_done;
    wire [23:0] mem_req_addr;
    wire [127:0] mem_req_wdata,mem_rdata;
    wire [15:0] mem_req_wmask;
    wire [1:0] video_mode;
    wire [23:0] video_fb_base;
    wire video_underflow_clear, video_underflow;
    wire video_frame_pulse;
    wire p2_valid,p2_ready,p2_write,p2_urgent,p2_rsp_valid,p2_rsp_ready,p2_rsp_error;
    wire [31:0] p2_addr;
    wire [127:0] p2_wdata,p2_rsp_rdata;
    wire [15:0] p2_wmask;

    // READ_DELAY_CYCLES NO se pasa: el controlador lo deriva de CLK_FREQ_HZ.
    // A 25 MHz sale 0, que es lo correcto aqui; el 1 fijo que traia por
    // defecto es el de 21, que corre a 80 MHz.
    sdram_controller_128 #(.CLK_FREQ_HZ(25_000_000)) controller (
        .clk(clk_25mhz),.reset(reset),.req_valid(mem_req_valid),.req_ready(mem_req_ready),
        .req_write(mem_req_write),.req_addr(mem_req_addr),.req_wdata(mem_req_wdata),
        .req_wmask(mem_req_wmask),.done(mem_done),.rdata(mem_rdata),
        .init_done(init_done),.busy(),.sdram_clk(sdram_clk),.sdram_cke(sdram_cke),
        .sdram_csn(sdram_csn),.sdram_rasn(sdram_rasn),.sdram_casn(sdram_casn),
        .sdram_wen(sdram_wen),.sdram_a(sdram_a),.sdram_ba(sdram_ba),
        .sdram_dqm(sdram_dqm),.sdram_d(sdram_d));
    gpu_system_bl8 gpu (.clk(clk_25mhz),.reset(reset),.gpu_reset(reset_req),
        .run_request(run_req),.halt_request(halt_req),.step_request(step_req),
        .halted(halted),.error(error),.error_code(error_code),.instruction_retired(retired),
        .host_address(address),.host_write_data(write_data),.host_write_enable(we),.host_read_enable(re),
        .host_read_data(read_data),.host_read_word(read_word),.host_ready(ready),.host_error(mem_error),
        .debug_register(debug_register),.debug_data(debug_data),.debug_pc(pc),.init_done(init_done),
        .p2_req_valid(p2_valid),.p2_req_ready(p2_ready),.p2_req_write(p2_write),
        .p2_req_addr(p2_addr),.p2_req_wdata(p2_wdata),.p2_req_wmask(p2_wmask),
        .p2_urgent(p2_urgent),
        .p2_rsp_valid(p2_rsp_valid),.p2_rsp_ready(p2_rsp_ready),
        .p2_rsp_rdata(p2_rsp_rdata),.p2_rsp_error(p2_rsp_error),
        .video_mode(video_mode),.video_fb_base(video_fb_base),
        .video_underflow_clear(video_underflow_clear),
        .video_underflow(video_underflow),.video_frame_pulse(video_frame_pulse),
        .mem_req_valid(mem_req_valid),.mem_req_ready(mem_req_ready),.mem_req_write(mem_req_write),
        .mem_req_addr(mem_req_addr),.mem_req_wdata(mem_req_wdata),.mem_req_wmask(mem_req_wmask),
        .mem_done(mem_done),.mem_rdata(mem_rdata));
    // =======================================================================
    // Subsistema de video
    //
    // Estructura calcada de 21, con UNA diferencia de fondo: alli el patron se
    // elige con un boton y el scanout sigue leyendo SDRAM igualmente, asi que
    // tapar la imagen no ahorra ancho de banda. Aqui el modo lo manda
    // VIDEO_CTRL (0x80000018) y el mux es entre las dos FUENTES DE LINEA, de
    // forma que en BLANK y PATTERN no se emite ni una peticion al fabric.
    // Ese es el punto entero: el scanout cuesta un 37% del rendimiento de la
    // GPU (ver video-scanout.md) y se quiere poder recuperarlo desde software.
    //
    //   625 MHz VCO / 5  = 125,0 MHz  -> reloj serie TMDS
    //   625 MHz VCO / 25 =  25,0 MHz  -> reloj de pixel
    // =======================================================================
    localparam [1:0] MODE_PATTERN=2'd1, MODE_SCANOUT=2'd2;

    wire clk_pix, clk_pix_5x, clk_pix_locked;
    clock2_gen #(.CLKI_DIV(1),.CLKFB_DIV(5),.CLKOP_DIV(5),.CLKOP_CPHASE(2),
                 .CLKOS_DIV(25),.CLKOS_CPHASE(12)) clock_pix_i(
        .clk_in(clk_25mhz),.clk_5x_out(clk_pix_5x),.clk_out(clk_pix),
        .clk_locked(clk_pix_locked));
    wire rst_pix=!clk_pix_locked;

    wire [11:0] sx, sy;
    wire hsync, vsync, de;
    simple_480p display_i(.clk_pix(clk_pix),.rst_pix(rst_pix),.sx(sx),.sy(sy),
        .hsync(hsync),.vsync(vsync),.de(de));
    wire frame=(sy==12'd480 && sx==12'd0);

    wire [7:0] scan_r,scan_g,scan_b;
    wire scan_de,scan_hsync,scan_vsync;
    wire fill_start,fill_first;
    wire [7:0] fill_line;
    wire fill_we,fill_done;
    wire [8:0] fill_addr;
    wire [15:0] fill_data;

    video_scanout scanout_i(
        .clk_pix(clk_pix),.rst_pix(rst_pix),.sx(sx),.sy(sy),
        .de_in(de),.hsync_in(hsync),.vsync_in(vsync),
        .r(scan_r),.g(scan_g),.b(scan_b),
        .de_out(scan_de),.hsync_out(scan_hsync),.vsync_out(scan_vsync),
        .underflow(video_underflow),
        .clk_sys(clk_25mhz),.rst_sys(reset),
        .underflow_clear(video_underflow_clear),
        .fill_start(fill_start),.fill_line(fill_line),.fill_first(fill_first),
        .fill_we(fill_we),.fill_addr(fill_addr),.fill_data(fill_data),
        .fill_done(fill_done));

    // Las dos fuentes comparten contrato de relleno. Solo arranca la del modo
    // activo: la otra nunca ve `fill_start` y por tanto no pide nada. Eso es lo
    // que hace que BLANK y PATTERN salgan gratis.
    //
    // El mux NO se puentea con `video_mode` directamente. Va en
    // video_line_source_mux, que muestrea el modo en el `fill_start` y lo
    // sostiene hasta el final de la linea. Puentearlo en vivo colgaba el video
    // si el software cambiaba VIDEO_CTRL a media linea; el porque esta en la
    // cabecera de ese modulo y lo comprueba gpu_video_mode_switch_tb.
    wire burst_we,burst_done,pat_we,pat_done;
    wire [8:0] burst_addr,pat_addr;
    wire [15:0] burst_data,pat_data;
    wire start_sdram,start_pattern;

    video_line_source_mux source_mux_i(
        .clk(clk_25mhz),.reset(reset),
        .video_mode(video_mode),.fill_start(fill_start),
        .start_sdram(start_sdram),.start_pattern(start_pattern),
        .burst_we(burst_we),.burst_addr(burst_addr),
        .burst_data(burst_data),.burst_done(burst_done),
        .pat_we(pat_we),.pat_addr(pat_addr),
        .pat_data(pat_data),.pat_done(pat_done),
        .fill_we(fill_we),.fill_addr(fill_addr),
        .fill_data(fill_data),.fill_done(fill_done));

    video_line_source_burst source_sdram_i(
        .clk(clk_25mhz),.reset(reset),.fb_base(video_fb_base),
        .fill_start(start_sdram),.fill_line(fill_line),
        .fill_we(burst_we),.fill_addr(burst_addr),.fill_data(burst_data),
        .fill_done(burst_done),
        .req_valid(p2_valid),.req_ready(p2_ready),.req_write(p2_write),
        .req_addr(p2_addr),.req_wdata(p2_wdata),.req_wmask(p2_wmask),
        .urgent(p2_urgent),
        .rsp_valid(p2_rsp_valid),.rsp_ready(p2_rsp_ready),
        .rsp_rdata(p2_rsp_rdata),.rsp_error(p2_rsp_error));

    video_line_source_pattern source_pat_i(
        .clk(clk_25mhz),.reset(reset),
        .fill_start(start_pattern),.fill_line(fill_line),
        .fill_we(pat_we),.fill_addr(pat_addr),.fill_data(pat_data),
        .fill_done(pat_done));

    // video_mode vive en el dominio de sistema y aqui se usa en el de pixel.
    reg [1:0] mode_pix_0, mode_pix_1;
    always @(posedge clk_pix) begin
        mode_pix_0<=video_mode;
        mode_pix_1<=mode_pix_0;
    end

    wire [7:0] paint_r,paint_g,paint_b;
    video_pattern pattern_i(.clk_pix(clk_pix),.rst_pix(rst_pix),.sx(sx),.sy(sy),
        .de(de),.frame(frame),.r(paint_r),.g(paint_g),.b(paint_b));
    // El patron es combinacional desde sx; el scanout llega un ciclo mas tarde.
    reg [7:0] paint_r_d,paint_g_d,paint_b_d;
    always @(posedge clk_pix) begin
        paint_r_d<=paint_r; paint_g_d<=paint_g; paint_b_d<=paint_b;
    end

    reg [7:0] dvi_r,dvi_g,dvi_b;
    reg dvi_hsync,dvi_vsync,dvi_de;
    always @(posedge clk_pix) begin
        dvi_hsync<=scan_hsync; dvi_vsync<=scan_vsync; dvi_de<=scan_de;
        case(mode_pix_1)
            MODE_SCANOUT: begin dvi_r<=scan_r; dvi_g<=scan_g; dvi_b<=scan_b; end
            MODE_PATTERN: begin dvi_r<=paint_r_d; dvi_g<=paint_g_d; dvi_b<=paint_b_d; end
            // BLANK y el reservado: negro, pero CON sincronismos validos.
            // Apagar el reloj de pixel ahorraria mas y haria que el monitor
            // perdiera el enganche durante segundos; no compensa.
            default: begin dvi_r<=8'd0; dvi_g<=8'd0; dvi_b<=8'd0; end
        endcase
    end

    dvi_generator dvi_i(
        .clk_pix(clk_pix),.clk_pix_5x(clk_pix_5x),.rst_pix(rst_pix),
        .de(dvi_de),
        .data_in_ch0(dvi_b),.data_in_ch1(dvi_g),.data_in_ch2(dvi_r),
        .ctrl_in_ch0({dvi_vsync,dvi_hsync}),.ctrl_in_ch1(2'b00),.ctrl_in_ch2(2'b00),
        .tmds_ch0_serial(gpdi_dp[0]),.tmds_ch1_serial(gpdi_dp[1]),
        .tmds_ch2_serial(gpdi_dp[2]),.tmds_clk_serial(gpdi_dp[3]));

    // Un pulso por vsync, cruzado al dominio de sistema para el contador de
    // frames de VIDEO_STATUS.
    reg vsync_sys_0,vsync_sys_1,vsync_sys_2;
    always @(posedge clk_25mhz) begin
        vsync_sys_0<=dvi_vsync; vsync_sys_1<=vsync_sys_0; vsync_sys_2<=vsync_sys_1;
    end
    assign video_frame_pulse=vsync_sys_1 && !vsync_sys_2;

    // led[0] vigila el underflow del line buffer: en pantalla solo se ve como
    // una imagen rota, que se confunde con muchas otras cosas.
    assign led={busy,error,halted,last_command[3:0],video_underflow};
endmodule
`default_nettype wire