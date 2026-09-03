`default_nettype none

module memory_test #(
    parameter integer TEST_ADDR_BITS = 16
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        init_done,
    output reg         req_valid,
    output reg         req_write,
    output reg  [23:0] req_addr,
    output reg  [15:0] req_wdata,
    input  wire        req_ready,
    input  wire        done,
    input  wire [15:0] rdata,
    output wire        testing_write,
    output wire        testing_read,
    output reg         pass,
    output reg         fail,
    output wire [2:0]  progress
);
    localparam [2:0] S_WAIT=0, S_WRITE_REQ=1, S_WRITE_DONE=2,
                     S_READ_REQ=3, S_READ_DONE=4, S_PASS=5, S_FAIL=6;
    reg [2:0] state;
    reg [TEST_ADDR_BITS-1:0] address;
    reg [1:0] pattern_number;
    reg [23:0] first_error_addr;
    reg [15:0] first_error_expected;
    reg [15:0] first_error_actual;

    function [15:0] pattern;
        input [1:0] number;
        input [23:0] addr;
        begin
            case (number)
                2'd0: pattern = 16'h0000;
                2'd1: pattern = 16'hffff;
                2'd2: pattern = addr[15:0] ^ 16'ha5a5;
                default: pattern = addr[0] ? 16'haa55 : 16'h55aa;
            endcase
        end
    endfunction

    assign testing_write = (state == S_WRITE_REQ) || (state == S_WRITE_DONE);
    assign testing_read  = (state == S_READ_REQ) || (state == S_READ_DONE);
    assign progress = address[TEST_ADDR_BITS-1 -: 3];

    always @(posedge clk) begin
        if (reset) begin
            state <= S_WAIT;
            address <= 0;
            pattern_number <= 0;
            req_valid <= 0;
            req_write <= 0;
            req_addr <= 0;
            req_wdata <= 0;
            pass <= 0;
            fail <= 0;
            first_error_addr <= 0;
            first_error_expected <= 0;
            first_error_actual <= 0;
        end else begin
            case (state)
                S_WAIT: if (init_done) begin address <= 0; state <= S_WRITE_REQ; end
                S_WRITE_REQ: begin
                    req_valid <= 1;
                    req_write <= 1;
                    req_addr <= {{(24-TEST_ADDR_BITS){1'b0}}, address};
                    req_wdata <= pattern(pattern_number, {{(24-TEST_ADDR_BITS){1'b0}}, address});
                    if (req_valid && req_ready) begin req_valid <= 0; state <= S_WRITE_DONE; end
                end
                S_WRITE_DONE: if (done) begin
                    if (&address) begin address <= 0; state <= S_READ_REQ; end
                    else begin address <= address + 1'b1; state <= S_WRITE_REQ; end
                end
                S_READ_REQ: begin
                    req_valid <= 1;
                    req_write <= 0;
                    req_addr <= {{(24-TEST_ADDR_BITS){1'b0}}, address};
                    if (req_valid && req_ready) begin req_valid <= 0; state <= S_READ_DONE; end
                end
                S_READ_DONE: if (done) begin
                    if (rdata != pattern(pattern_number, {{(24-TEST_ADDR_BITS){1'b0}}, address})) begin
                        first_error_addr <= {{(24-TEST_ADDR_BITS){1'b0}}, address};
                        first_error_expected <= pattern(pattern_number, {{(24-TEST_ADDR_BITS){1'b0}}, address});
                        first_error_actual <= rdata;
                        fail <= 1;
                        state <= S_FAIL;
                    end else if (&address) begin
                        address <= 0;
                        if (pattern_number == 2'd3) begin pass <= 1; state <= S_PASS; end
                        else begin pattern_number <= pattern_number + 1'b1; state <= S_WRITE_REQ; end
                    end else begin address <= address + 1'b1; state <= S_READ_REQ; end
                end
                S_PASS: begin req_valid <= 0; end
                S_FAIL: begin req_valid <= 0; end
                default: state <= S_WAIT;
            endcase
        end
    end
endmodule

`default_nettype wire
