`default_nettype none

module async_fifo #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 4
)(
    input  wire                  clk_wr,
    input  wire                  clk_rd,
    input  wire                  rst_wr_n,
    input  wire                  rst_rd_n,
    input  wire                  wr_en,
    input  wire                  rd_en,
    input  wire [DATA_WIDTH-1:0] data_in,
    output reg  [DATA_WIDTH-1:0] data_out,
    output reg                   rd_valid,
    output reg                   full,
    output reg                   empty
);

    localparam PTR_WIDTH = ADDR_WIDTH + 1;

    // Storage. Intentionally has no reset: FIFO validity is controlled by pointers.
    reg [DATA_WIDTH-1:0] mem [0:(1 << ADDR_WIDTH)-1];

    reg [PTR_WIDTH-1:0] wr_ptr_bin;
    reg [PTR_WIDTH-1:0] wr_ptr_gray;
    reg [PTR_WIDTH-1:0] rd_ptr_bin;
    reg [PTR_WIDTH-1:0] rd_ptr_gray;

    (* async_reg = "true" *) reg [PTR_WIDTH-1:0] rd_ptr_gray_sync1;
    (* async_reg = "true" *) reg [PTR_WIDTH-1:0] rd_ptr_gray_sync2;
    (* async_reg = "true" *) reg [PTR_WIDTH-1:0] wr_ptr_gray_sync1;
    (* async_reg = "true" *) reg [PTR_WIDTH-1:0] wr_ptr_gray_sync2;

    function [PTR_WIDTH-1:0] bin_to_gray;
        input [PTR_WIDTH-1:0] bin;
        begin
            bin_to_gray = (bin >> 1) ^ bin;
        end
    endfunction

    wire wr_fire = wr_en && !full;
    wire rd_fire = rd_en && !empty;

    wire [PTR_WIDTH-1:0] wr_ptr_bin_next =
        wr_ptr_bin + {{(PTR_WIDTH-1){1'b0}}, wr_fire};
    wire [PTR_WIDTH-1:0] wr_ptr_gray_next = bin_to_gray(wr_ptr_bin_next);

    wire [PTR_WIDTH-1:0] rd_ptr_bin_next =
        rd_ptr_bin + {{(PTR_WIDTH-1){1'b0}}, rd_fire};
    wire [PTR_WIDTH-1:0] rd_ptr_gray_next = bin_to_gray(rd_ptr_bin_next);

    // Standard Gray-pointer full test for power-of-two depth.
    // Requires ADDR_WIDTH >= 2.
    wire full_next =
        (wr_ptr_gray_next ==
         {~rd_ptr_gray_sync2[ADDR_WIDTH:ADDR_WIDTH-1],
           rd_ptr_gray_sync2[ADDR_WIDTH-2:0]});

    wire empty_next = (rd_ptr_gray_next == wr_ptr_gray_sync2);

    // Simple write port, friendly to memory inference.
    always @(posedge clk_wr) begin
        if (wr_fire)
            mem[wr_ptr_bin[ADDR_WIDTH-1:0]] <= data_in;
    end

    // Simple synchronous read port. rd_valid marks the corresponding data_out.
    always @(posedge clk_rd) begin
        if (rd_fire)
            data_out <= mem[rd_ptr_bin[ADDR_WIDTH-1:0]];
    end

    always @(posedge clk_wr or negedge rst_wr_n) begin
        if (!rst_wr_n) begin
            wr_ptr_bin  <= {PTR_WIDTH{1'b0}};
            wr_ptr_gray <= {PTR_WIDTH{1'b0}};
            full        <= 1'b0;
        end else begin
            wr_ptr_bin  <= wr_ptr_bin_next;
            wr_ptr_gray <= wr_ptr_gray_next;
            full        <= full_next;
        end
    end

    always @(posedge clk_rd or negedge rst_rd_n) begin
        if (!rst_rd_n) begin
            rd_ptr_bin  <= {PTR_WIDTH{1'b0}};
            rd_ptr_gray <= {PTR_WIDTH{1'b0}};
            rd_valid    <= 1'b0;
            empty       <= 1'b1;
        end else begin
            rd_ptr_bin  <= rd_ptr_bin_next;
            rd_ptr_gray <= rd_ptr_gray_next;
            rd_valid    <= rd_fire;
            empty       <= empty_next;
        end
    end

    // Read pointer -> write domain.
    always @(posedge clk_wr or negedge rst_wr_n) begin
        if (!rst_wr_n) begin
            rd_ptr_gray_sync1 <= {PTR_WIDTH{1'b0}};
            rd_ptr_gray_sync2 <= {PTR_WIDTH{1'b0}};
        end else begin
            rd_ptr_gray_sync1 <= rd_ptr_gray;
            rd_ptr_gray_sync2 <= rd_ptr_gray_sync1;
        end
    end

    // Write pointer -> read domain.
    always @(posedge clk_rd or negedge rst_rd_n) begin
        if (!rst_rd_n) begin
            wr_ptr_gray_sync1 <= {PTR_WIDTH{1'b0}};
            wr_ptr_gray_sync2 <= {PTR_WIDTH{1'b0}};
        end else begin
            wr_ptr_gray_sync1 <= wr_ptr_gray;
            wr_ptr_gray_sync2 <= wr_ptr_gray_sync1;
        end
    end

endmodule

`default_nettype wire
