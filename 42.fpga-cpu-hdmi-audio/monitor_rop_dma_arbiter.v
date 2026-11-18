`default_nettype none

/*
 * Arbitro local de tres maestros para un puerto del fabric.
 *
 * Prioridad fija: monitor > ROP > DMA. Las respuestas del fabric son en
 * orden, por lo que una FIFO de propietarios de dos bits basta para devolver
 * cada una al maestro que la emitio.
 */
module monitor_rop_dma_arbiter #(
    parameter integer TAG_DEPTH = 8
)(
    input wire clk, input wire reset,

    input wire mon_req_valid, output wire mon_req_ready,
    input wire mon_req_write, input wire [31:0] mon_req_addr,
    input wire [127:0] mon_req_wdata, input wire [15:0] mon_req_wmask,
    output wire mon_rsp_valid, input wire mon_rsp_ready,
    output wire [127:0] mon_rsp_rdata, output wire mon_rsp_error,

    input wire rop_req_valid, output wire rop_req_ready,
    input wire rop_req_write, input wire [31:0] rop_req_addr,
    input wire [127:0] rop_req_wdata, input wire [15:0] rop_req_wmask,
    output wire rop_rsp_valid, input wire rop_rsp_ready,
    output wire [127:0] rop_rsp_rdata, output wire rop_rsp_error,

    input wire dma_req_valid, output wire dma_req_ready,
    input wire dma_req_write, input wire [31:0] dma_req_addr,
    input wire [127:0] dma_req_wdata, input wire [15:0] dma_req_wmask,
    output wire dma_rsp_valid, input wire dma_rsp_ready,
    output wire [127:0] dma_rsp_rdata, output wire dma_rsp_error,

    output wire req_valid, input wire req_ready, output wire req_urgent,
    output wire req_write, output wire [31:0] req_addr,
    output wire [127:0] req_wdata, output wire [15:0] req_wmask,
    input wire rsp_valid, output wire rsp_ready,
    input wire [127:0] rsp_rdata, input wire rsp_error
);
    localparam integer PTR_BITS = $clog2(TAG_DEPTH);
    localparam integer CNT_BITS = PTR_BITS + 1;
    localparam [1:0] OWNER_MON = 2'd0;
    localparam [1:0] OWNER_ROP = 2'd1;
    localparam [1:0] OWNER_DMA = 2'd2;

    reg [1:0] tag_fifo [0:TAG_DEPTH-1];
    reg [PTR_BITS-1:0] wr_ptr, rd_ptr;
    reg [CNT_BITS-1:0] tag_count;
    wire tags_empty = (tag_count == 0);
    wire tags_full = (tag_count == TAG_DEPTH);
    wire can_accept = !reset && !tags_full;

    wire select_mon = mon_req_valid;
    wire select_rop = !mon_req_valid && rop_req_valid;
    wire select_dma = !mon_req_valid && !rop_req_valid && dma_req_valid;
    wire [1:0] selected_owner = select_mon ? OWNER_MON :
                                select_rop ? OWNER_ROP : OWNER_DMA;

    assign req_valid = can_accept && (select_mon || select_rop || select_dma);
    assign req_urgent = 1'b0;
    assign req_write = select_mon ? mon_req_write :
                       select_rop ? rop_req_write : dma_req_write;
    assign req_addr = select_mon ? mon_req_addr :
                      select_rop ? rop_req_addr : dma_req_addr;
    assign req_wdata = select_mon ? mon_req_wdata :
                       select_rop ? rop_req_wdata : dma_req_wdata;
    assign req_wmask = select_mon ? mon_req_wmask :
                       select_rop ? rop_req_wmask : dma_req_wmask;
    assign mon_req_ready = can_accept && select_mon && req_ready;
    assign rop_req_ready = can_accept && select_rop && req_ready;
    assign dma_req_ready = can_accept && select_dma && req_ready;

    wire [1:0] response_owner = tag_fifo[rd_ptr];
    wire response_to_mon = !tags_empty && (response_owner == OWNER_MON);
    wire response_to_rop = !tags_empty && (response_owner == OWNER_ROP);
    wire response_to_dma = !tags_empty && (response_owner == OWNER_DMA);
    assign mon_rsp_valid = !reset && rsp_valid && response_to_mon;
    assign rop_rsp_valid = !reset && rsp_valid && response_to_rop;
    assign dma_rsp_valid = !reset && rsp_valid && response_to_dma;
    assign mon_rsp_rdata = rsp_rdata;
    assign rop_rsp_rdata = rsp_rdata;
    assign dma_rsp_rdata = rsp_rdata;
    assign mon_rsp_error = rsp_error;
    assign rop_rsp_error = rsp_error;
    assign dma_rsp_error = rsp_error;
    assign rsp_ready = !reset && !tags_empty &&
                       (response_to_mon ? mon_rsp_ready :
                        response_to_rop ? rop_rsp_ready : dma_rsp_ready);

    wire push = req_valid && req_ready;
    wire pop = rsp_valid && rsp_ready;
    always @(posedge clk) begin
        if (reset) begin
            wr_ptr <= {PTR_BITS{1'b0}};
            rd_ptr <= {PTR_BITS{1'b0}};
            tag_count <= {CNT_BITS{1'b0}};
        end else begin
            if (push) begin
                tag_fifo[wr_ptr] <= selected_owner;
                wr_ptr <= wr_ptr + 1'b1;
            end
            if (pop)
                rd_ptr <= rd_ptr + 1'b1;
            case ({push, pop})
                2'b10: tag_count <= tag_count + 1'b1;
                2'b01: tag_count <= tag_count - 1'b1;
                default: ;
            endcase
        end
    end
endmodule

`default_nettype wire
