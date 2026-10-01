`default_nettype none
// 8 warp contexts x 32 registers. Synchronous reads permit EBR inference.
// Initialization is a 256-cycle sweep driven by the SM, not a RAM reset.
module gpu_register_file (
    input clk,
    input [7:0] read_address_a, read_address_b,
    output reg [31:0] read_data_a, read_data_b,
    input write_enable,
    input [7:0] write_address,
    input [31:0] write_data
);
    reg [31:0] words[0:255];
    always @(posedge clk) begin
        read_data_a <= words[read_address_a];
        read_data_b <= words[read_address_b];
        if (write_enable) words[write_address] <= write_data;
    end
endmodule
`default_nettype wire
