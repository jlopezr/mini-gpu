`default_nettype none

module top (
    input  wire       clk_25mhz,
    input  wire [6:0] btn,
    output wire [7:0] led,
    output wire       wifi_gpio0
);

    // Evita que el ESP32 reinicie la placa.
    assign wifi_gpio0 = 1'b1;

    reg [31:0] counter = 32'd0;

    always @(posedge clk_25mhz) begin
        counter <= counter + 1'b1;
    end

    assign led[7]   = 1'b1;
    assign led[6]   = btn[1];
    assign led[5:0] = counter[23:18];

endmodule

`default_nettype wire