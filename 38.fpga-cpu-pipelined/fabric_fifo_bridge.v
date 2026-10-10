`default_nettype none

module fabric_fifo_bridge #(
    parameter FIFO_ADDR_WIDTH = 2   // depth = 4
)(
    // ================================================================
    // Master clock domain
    // ================================================================
    input wire master_clk,
    input wire master_reset,

    input  wire         req_valid,
    output wire         req_ready,
    input  wire         req_urgent,
    input  wire         req_write,
    input  wire [31:0]  req_addr,
    input  wire [127:0] req_wdata,
    input  wire [15:0]  req_wmask,

    output wire         rsp_valid,
    input  wire         rsp_ready,
    output wire [127:0] rsp_rdata,
    output wire         rsp_error,

    // ================================================================
    // Memory clock domain
    // ================================================================
    input wire mem_clk,
    input wire mem_reset,

    // Request FIFO -> memory fabric
    output wire         mem_req_empty,
    input  wire         mem_req_rd_en,
    output wire         mem_req_rd_valid,
    output wire [177:0] mem_req_data,

    // Response FIFO <- memory fabric
    output wire         mem_rsp_full,
    input  wire         mem_rsp_wr_en,
    input  wire [128:0] mem_rsp_data
);

    // ================================================================
    // Request FIFO
    //
    // master -> memory
    //
    // [177]     urgent
    // [176]     write
    // [175:144] address
    // [143:16]  write data
    // [15:0]    write mask
    // ================================================================

    wire         req_fifo_full;
    wire         req_fifo_empty;
    wire [177:0] req_fifo_data_out;
    wire         req_fifo_rd_valid;

    wire [177:0] req_fifo_data_in = {
        req_urgent,
        req_write,
        req_addr,
        req_wdata,
        req_wmask
    };

    assign req_ready = !req_fifo_full;

    wire req_fifo_wr_en =
        req_valid && req_ready;

    async_fifo #(
        .DATA_WIDTH (178),
        .ADDR_WIDTH (FIFO_ADDR_WIDTH)
    ) u_req_fifo (
        .clk_wr    (master_clk),
        .clk_rd    (mem_clk),

        .rst_wr_n  (~master_reset),
        .rst_rd_n  (~mem_reset),

        .wr_en     (req_fifo_wr_en),
        .rd_en     (mem_req_rd_en),

        .data_in   (req_fifo_data_in),
        .data_out  (req_fifo_data_out),

        .rd_valid  (req_fifo_rd_valid),
        .full      (req_fifo_full),
        .empty     (req_fifo_empty)
    );

    assign mem_req_empty    = req_fifo_empty;
    assign mem_req_rd_valid = req_fifo_rd_valid;
    assign mem_req_data     = req_fifo_data_out;

    // ================================================================
    // Response FIFO
    //
    // memory -> master
    //
    // [128]     error
    // [127:0]   read data
    // ================================================================

    wire         rsp_fifo_full;
    wire         rsp_fifo_empty;
    wire [128:0] rsp_fifo_data_out;
    wire         rsp_fifo_rd_valid;

    // A response that has left the async FIFO and is being held for
    // the master.
    reg          rsp_hold_valid;
    reg [128:0]  rsp_hold_data;

    // A synchronous FIFO read has already been requested and we're
    // waiting for rd_valid.
    reg rsp_read_pending;

    wire rsp_fifo_rd_en =
        !rsp_hold_valid &&
        !rsp_read_pending &&
        !rsp_fifo_empty;

    async_fifo #(
        .DATA_WIDTH (129),
        .ADDR_WIDTH (FIFO_ADDR_WIDTH)
    ) u_rsp_fifo (
        .clk_wr    (mem_clk),
        .clk_rd    (master_clk),

        .rst_wr_n  (~mem_reset),
        .rst_rd_n  (~master_reset),

        .wr_en     (mem_rsp_wr_en),
        .rd_en     (rsp_fifo_rd_en),

        .data_in   (mem_rsp_data),
        .data_out  (rsp_fifo_data_out),

        .rd_valid  (rsp_fifo_rd_valid),
        .full      (rsp_fifo_full),
        .empty     (rsp_fifo_empty)
    );

    assign mem_rsp_full = rsp_fifo_full;

    // ================================================================
    // Master-side response holding register
    //
    // async_fifo has synchronous read semantics:
    //
    //   rd_en
    //      |
    //      +--- one read cycle ---> rd_valid + data_out
    //
    // Once received, hold the response until rsp_ready.
    // ================================================================

    always @(posedge master_clk) begin
        if (master_reset) begin
            rsp_hold_valid  <= 1'b0;
            rsp_hold_data   <= 129'd0;
            rsp_read_pending <= 1'b0;
        end else begin

            if (rsp_fifo_rd_en)
                rsp_read_pending <= 1'b1;

            if (rsp_fifo_rd_valid) begin
                rsp_hold_data    <= rsp_fifo_data_out;
                rsp_hold_valid   <= 1'b1;
                rsp_read_pending <= 1'b0;
            end

            if (rsp_hold_valid && rsp_ready)
                rsp_hold_valid <= 1'b0;
        end
    end

    assign rsp_valid = rsp_hold_valid;
    assign rsp_error = rsp_hold_data[128];
    assign rsp_rdata = rsp_hold_data[127:0];

endmodule

`default_nettype wire