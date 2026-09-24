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

    // ------------------------------------------------------------
    // Memory
    // ------------------------------------------------------------

    reg [DATA_WIDTH-1:0] mem [0:(1 << ADDR_WIDTH)-1];

    // ------------------------------------------------------------
    // Binary / Gray pointers
    // ------------------------------------------------------------

    reg [PTR_WIDTH-1:0] wr_ptr_bin;
    reg [PTR_WIDTH-1:0] wr_ptr_gray;

    reg [PTR_WIDTH-1:0] rd_ptr_bin;
    reg [PTR_WIDTH-1:0] rd_ptr_gray;

    // ------------------------------------------------------------
    // CDC synchronizers
    // ------------------------------------------------------------

    (* async_reg = "true" *)
    reg [PTR_WIDTH-1:0] rd_ptr_gray_sync1;
    (* async_reg = "true" *)
    reg [PTR_WIDTH-1:0] rd_ptr_gray_sync2;

    (* async_reg = "true" *)
    reg [PTR_WIDTH-1:0] wr_ptr_gray_sync1;
    (* async_reg = "true" *)
    reg [PTR_WIDTH-1:0] wr_ptr_gray_sync2;

    // ------------------------------------------------------------
    // Gray conversion
    // ------------------------------------------------------------

    function [PTR_WIDTH-1:0] bin_to_gray;
        input [PTR_WIDTH-1:0] bin;
        begin
            bin_to_gray = (bin >> 1) ^ bin;
        end
    endfunction

    // ------------------------------------------------------------
    // Accepted transactions
    // ------------------------------------------------------------

    wire wr_fire;
    wire rd_fire;

    assign wr_fire = wr_en && !full;
    assign rd_fire = rd_en && !empty;

    // ------------------------------------------------------------
    // Next write pointer
    // ------------------------------------------------------------

    wire [PTR_WIDTH-1:0] wr_ptr_bin_next;
    wire [PTR_WIDTH-1:0] wr_ptr_gray_next;

    assign wr_ptr_bin_next =
        wr_ptr_bin + {{(PTR_WIDTH-1){1'b0}}, wr_fire};

    assign wr_ptr_gray_next =
        bin_to_gray(wr_ptr_bin_next);

    // ------------------------------------------------------------
    // Next read pointer
    // ------------------------------------------------------------

    wire [PTR_WIDTH-1:0] rd_ptr_bin_next;
    wire [PTR_WIDTH-1:0] rd_ptr_gray_next;

    assign rd_ptr_bin_next =
        rd_ptr_bin + {{(PTR_WIDTH-1){1'b0}}, rd_fire};

    assign rd_ptr_gray_next =
        bin_to_gray(rd_ptr_bin_next);

    // ------------------------------------------------------------
    // FULL detection
    //
    // For Gray pointers, full occurs when next write pointer equals
    // synchronized read pointer with its two MSBs inverted.
    //
    // Requires ADDR_WIDTH >= 2.
    // ------------------------------------------------------------

    wire full_next;

    assign full_next =
        (wr_ptr_gray_next ==
         {
            ~rd_ptr_gray_sync2[ADDR_WIDTH:ADDR_WIDTH-1],
             rd_ptr_gray_sync2[ADDR_WIDTH-2:0]
         });

    // ------------------------------------------------------------
    // EMPTY detection
    // ------------------------------------------------------------

    wire empty_next;

    assign empty_next =
        (rd_ptr_gray_next == wr_ptr_gray_sync2);

    // ------------------------------------------------------------
    // Write domain
    // ------------------------------------------------------------

    always @(posedge clk_wr or negedge rst_wr_n) begin
        if (!rst_wr_n) begin
            wr_ptr_bin  <= {PTR_WIDTH{1'b0}};
            wr_ptr_gray <= {PTR_WIDTH{1'b0}};
            full        <= 1'b0;
        end else begin

            if (wr_fire) begin
                mem[wr_ptr_bin[ADDR_WIDTH-1:0]] <= data_in;
            end

            wr_ptr_bin  <= wr_ptr_bin_next;
            wr_ptr_gray <= wr_ptr_gray_next;
            full        <= full_next;
        end
    end

    // ------------------------------------------------------------
    // Read domain
    // ------------------------------------------------------------

    always @(posedge clk_rd or negedge rst_rd_n) begin
        if (!rst_rd_n) begin
            rd_ptr_bin  <= {PTR_WIDTH{1'b0}};
            rd_ptr_gray <= {PTR_WIDTH{1'b0}};

            data_out    <= {DATA_WIDTH{1'b0}};
            rd_valid    <= 1'b0;

            empty       <= 1'b1;
        end else begin

            rd_valid <= rd_fire;

            if (rd_fire) begin
                data_out <= mem[rd_ptr_bin[ADDR_WIDTH-1:0]];
            end

            rd_ptr_bin  <= rd_ptr_bin_next;
            rd_ptr_gray <= rd_ptr_gray_next;
            empty       <= empty_next;
        end
    end

    // ------------------------------------------------------------
    // Synchronize read pointer into write clock domain
    // ------------------------------------------------------------

    always @(posedge clk_wr or negedge rst_wr_n) begin
        if (!rst_wr_n) begin
            rd_ptr_gray_sync1 <= {PTR_WIDTH{1'b0}};
            rd_ptr_gray_sync2 <= {PTR_WIDTH{1'b0}};
        end else begin
            rd_ptr_gray_sync1 <= rd_ptr_gray;
            rd_ptr_gray_sync2 <= rd_ptr_gray_sync1;
        end
    end

    // ------------------------------------------------------------
    // Synchronize write pointer into read clock domain
    // ------------------------------------------------------------

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