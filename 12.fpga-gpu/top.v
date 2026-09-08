`default_nettype none
module top(input clk_25mhz, output [7:0] led, output wifi_gpio0,
    input ftdi_txd, output ftdi_rxd);
    // Conservative first implementation: native 25 MHz, UART 250 kbaud.
    reg [7:0] power_on=0;
    wire reset=!(&power_on);
    always @(posedge clk_25mhz) if(reset) power_on<=power_on+1'b1;
    assign wifi_gpio0=1;
    wire [7:0] rx_data,tx_data,last_command;
    wire rx_strobe,tx_strobe,tx_ready,busy;
    uart #(.DIVISOR(100)) uart_i (.clk(clk_25mhz),.reset(reset),
        .serial_txd(ftdi_rxd),.serial_rxd(ftdi_txd),.rxd(rx_data),.rxd_strobe(rx_strobe),
        .txd(tx_data),.txd_strobe(tx_strobe),.txd_ready(tx_ready));
    wire [31:0] address,debug_data,pc;
    wire [7:0] write_data,read_data,error_code;
    wire we,re,ready,mem_error,run_req,halt_req,step_req,reset_req,halted,error,retired;
    wire [4:0] debug_register;
    monitor monitor_i (.clk(clk_25mhz),.reset(reset),.rx_data(rx_data),.rx_strobe(rx_strobe),
        .tx_data(tx_data),.tx_strobe(tx_strobe),.tx_ready(tx_ready),
        .mem_address(address),.mem_write_data(write_data),.mem_write_enable(we),
        .mem_read_enable(re),.mem_read_data(read_data),.mem_ready(ready),.mem_error(mem_error),
        .cpu_run_request(run_req),.cpu_halt_request(halt_req),.cpu_step_request(step_req),
        .cpu_reset_request(reset_req),.cpu_halted(halted),.cpu_error(error),.cpu_error_code(error_code),
        .cpu_pc(pc),.cpu_debug_register_address(debug_register),.cpu_debug_register_data(debug_data),
        .last_command(last_command),.busy(busy));
    gpu_system gpu (.clk(clk_25mhz),.reset(reset),.gpu_reset(reset_req),
        .run_request(run_req),.halt_request(halt_req),.step_request(step_req),
        .halted(halted),.error(error),.error_code(error_code),.instruction_retired(retired),
        .host_address(address),.host_write_data(write_data),.host_write_enable(we),.host_read_enable(re),
        .host_read_data(read_data),.host_ready(ready),.host_error(mem_error),
        .debug_register(debug_register),.debug_data(debug_data),.debug_pc(pc));
    assign led={busy,error,halted,last_command[4:0]};
endmodule
`default_nettype wire
