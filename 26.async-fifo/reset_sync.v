`default_nettype none
module reset_sync (
    input  wire clk,
    input  wire arst_n,
    output wire srst_n
);

    (* async_reg = "true" *)
    reg [1:0] sync_ff;

    always @(posedge clk or negedge arst_n) begin
        if (!arst_n)
            sync_ff <= 2'b00;
        else
            sync_ff <= {sync_ff[0], 1'b1};
    end

    assign srst_n = sync_ff[1];

endmodule
`default_nettype wire