`default_nettype none
module top(input clk_25mhz, output [7:0] led, output wifi_gpio0,
    input ftdi_txd, output ftdi_rxd);
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
    wire [4:0] debug_register;
    // BACKPORT DE R0 CABLEADO A CERO. `R0` paso a valer siempre cero y a
    // descartar las escrituras, que es un cambio INCOMPATIBLE: un programa que
    // lo use como registro general no para con error, da otro resultado en
    // silencio. Sube la version aunque el protocolo no cambie ni un byte, por
    // lo mismo que subieron las cinco de MiniCPU. Ver 1.isa/isa.md seccion 1.
    //
    // Las ventanas son la GEMELA de MONITOR_REGIONS en monitor.py. Esta no
    // tiene video ni contadores, asi que esas dos ranuras van al centinela.
    monitor #(.VERSION_MAJOR(8'h02),.VERSION_MINOR(8'h05),
        .RAM_END(33'h0_0002_0000),
        .WINDOW0_BASE(33'h1_ffff_ffff),.WINDOW0_END(33'h0_0000_0000),
        .WINDOW1_BASE(33'h0_8000_0100),.WINDOW1_END(33'h0_8000_0118),
        .WINDOW2_BASE(33'h1_ffff_ffff),.WINDOW2_END(33'h0_0000_0000),
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
    gpu_system gpu (.clk(clk_25mhz),.reset(reset),.gpu_reset(reset_req),
        .run_request(run_req),.halt_request(halt_req),.step_request(step_req),
        .halted(halted),.error(error),.error_code(error_code),.instruction_retired(retired),
        .host_address(address),.host_write_data(write_data),.host_write_enable(we),.host_read_enable(re),
        .host_read_data(read_data),.host_read_word(read_word),.host_ready(ready),.host_error(mem_error),
        .debug_register(debug_register),.debug_data(debug_data),.debug_pc(pc));
    assign led={busy,error,halted,last_command[4:0]};
endmodule
`default_nettype wire
