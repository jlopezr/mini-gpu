`default_nettype none

module divide_by_n #(
    parameter integer N = 216
)(
    input  wire clk,
    input  wire reset,
    output reg  out
);
    integer count;

    initial begin
        count = 0;
        out = 1'b0;
    end

    always @(posedge clk) begin
        if (reset) begin
            count <= 0;
            out   <= 1'b0;
        end else if (count >= N-1) begin
            count <= 0;
            out   <= 1'b1;
        end else begin
            count <= count + 1;
            out   <= 1'b0;
        end
    end
endmodule

`default_nettype wire
