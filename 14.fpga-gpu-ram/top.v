`default_nettype none
module top(input clk_25mhz, output [7:0] led, output wifi_gpio0,
    input ftdi_txd, output ftdi_rxd,
    output sdram_clk, sdram_cke, sdram_csn, sdram_rasn, sdram_casn, sdram_wen,
    output [12:0] sdram_a, output [1:0] sdram_ba, sdram_dqm,
    inout [15:0] sdram_d);
    // 25 MHz nativos: no hay PLL de sistema, y todo -- GPU, monitor, UART y
    // SDRAM -- va en clk_25mhz. (La 22 tiene un PLL, pero es solo para los
    // relojes de pixel de HDMI.)
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
      // WRITE_WORD: la palabra entera y su pulso, del monitor al puerto host.
      wire [31:0] write_word_w; wire we_word;
    wire [4:0] debug_register;
    // 2.4 y no 2.3: mismos comandos que 12, pero 32 MiB de SDRAM en vez de
    // 128 KiB de BRAM. `x.cpu-tests` necesita distinguir los dos bitstreams.
    // (Ver tambien el backport de R0 comentado en la 12.)
    //
    // Las ventanas son la GEMELA de MONITOR_REGIONS en monitor.py. Esta no
    // tiene video ni contadores, asi que esas dos ranuras van al centinela.
    monitor #(.VERSION_MAJOR(8'd3),.VERSION_MINOR(8'd14),
        .RAM_END(33'h0_0200_0000),
        .WINDOW0_BASE(33'h1_ffff_ffff),.WINDOW0_END(33'h0_0000_0000),
        .WINDOW1_BASE(33'h0_8000_0100),.WINDOW1_END(33'h0_8000_0118),
        .WINDOW2_BASE(33'h1_ffff_ffff),.WINDOW2_END(33'h0_0000_0000),
        .WINDOW3_BASE(33'h0_8000_1000),.WINDOW3_END(33'h0_8000_1080),
        // Identificacion: SYS_ID, CONTRACT, DEV_BITMAP e ISA_PROFILE.
        .WINDOW4_BASE(33'h0_8000_0f00),.WINDOW4_END(33'h0_8000_0f10))
      monitor_i (.clk(clk_25mhz),.reset(reset),.rx_data(rx_data),.rx_strobe(rx_strobe),
        .tx_data(tx_data),.tx_strobe(tx_strobe),.tx_ready(tx_ready),
        .mem_address(address),.mem_write_data(write_data),.mem_write_enable(we),
          .mem_write_word(write_word_w),.mem_write_word_enable(we_word),
        .mem_read_enable(re),.mem_read_data(read_data),.mem_read_word(read_word),.mem_ready(ready),.mem_error(mem_error),
        .cpu_run_request(run_req),.cpu_halt_request(halt_req),.cpu_step_request(step_req),
        .cpu_reset_request(reset_req),.cpu_halted(halted),.cpu_error(error),.cpu_error_code(error_code),
        .cpu_pc(pc),.cpu_debug_register_address(debug_register),.cpu_debug_register_data(debug_data),
        .last_command(last_command),.busy(busy));
    wire init_done,mem_req_valid,mem_req_ready,mem_req_write,mem_done;
    wire [23:0] mem_req_addr;
    wire [15:0] mem_req_wdata,mem_rdata;
    wire [1:0] mem_req_wmask;
    sdram_controller #(.CLK_FREQ_HZ(25_000_000)) controller (
        .clk(clk_25mhz),.reset(reset),.req_valid(mem_req_valid),.req_ready(mem_req_ready),
        .req_write(mem_req_write),.req_addr(mem_req_addr),.req_wdata(mem_req_wdata),
        .req_wmask(mem_req_wmask),.done(mem_done),.rdata(mem_rdata),
        .init_done(init_done),.busy(),.sdram_clk(sdram_clk),.sdram_cke(sdram_cke),
        .sdram_csn(sdram_csn),.sdram_rasn(sdram_rasn),.sdram_casn(sdram_casn),
        .sdram_wen(sdram_wen),.sdram_a(sdram_a),.sdram_ba(sdram_ba),
        .sdram_dqm(sdram_dqm),.sdram_d(sdram_d));
    gpu_system gpu (.clk(clk_25mhz),.reset(reset),.gpu_reset(reset_req),
        .run_request(run_req),.halt_request(halt_req),.step_request(step_req),
        .halted(halted),.error(error),.error_code(error_code),.instruction_retired(retired),
        .host_address(address),.host_write_data(write_data),.host_write_enable(we),
          .host_write_word(write_word_w),.host_write_word_enable(we_word),.host_read_enable(re),
        .host_read_data(read_data),.host_read_word(read_word),.host_ready(ready),.host_error(mem_error),
        .debug_register(debug_register),.debug_data(debug_data),.debug_pc(pc),.init_done(init_done),
        .mem_req_valid(mem_req_valid),.mem_req_ready(mem_req_ready),.mem_req_write(mem_req_write),
        .mem_req_addr(mem_req_addr),.mem_req_wdata(mem_req_wdata),.mem_req_wmask(mem_req_wmask),
        .mem_done(mem_done),.mem_rdata(mem_rdata));
    assign led={busy,error,halted,last_command[4:0]};
endmodule
`default_nettype wire
