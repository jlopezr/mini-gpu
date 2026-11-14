
`default_nettype none

/*
 * Arbitro local MONITOR / DMA para compartir un puerto del fabric.
 *
 * Ambos maestros usan la interfaz de 128 bits de fabric_fifo_bridge.
 * Las respuestas llegan en el mismo orden que las solicitudes.
 *
 * - Prioridad al monitor.
 * - Varias solicitudes pendientes.
 * - FIFO de propietarios para enrutar las respuestas.
 * - Backpressure completo.
 * - Un solo dominio de reloj (clk de MiniCPU).
 *
 * No modifica el fabric ni el controlador SDRAM.
 */
module dma_monitor_arbiter #(
    parameter integer TAG_DEPTH = 8
)(
    input wire clk,
    input wire reset,

    // ------------------------------------------------------------
    // Maestro 0: monitor
    // ------------------------------------------------------------
    input  wire         mon_req_valid,
    output wire         mon_req_ready,
    input  wire         mon_req_write,
    input  wire [31:0]  mon_req_addr,
    input  wire [127:0] mon_req_wdata,
    input  wire [15:0]  mon_req_wmask,

    output wire         mon_rsp_valid,
    input  wire         mon_rsp_ready,
    output wire [127:0] mon_rsp_rdata,
    output wire         mon_rsp_error,

    // ------------------------------------------------------------
    // Maestro 1: DMA
    // ------------------------------------------------------------
    input  wire         dma_req_valid,
    output wire         dma_req_ready,
    input  wire         dma_req_write,
    input  wire [31:0]  dma_req_addr,
    input  wire [127:0] dma_req_wdata,
    input  wire [15:0]  dma_req_wmask,

    output wire         dma_rsp_valid,
    input  wire         dma_rsp_ready,
    output wire [127:0] dma_rsp_rdata,
    output wire         dma_rsp_error,

    // ------------------------------------------------------------
    // Salida al fabric_fifo_bridge p3
    // ------------------------------------------------------------
    output wire         req_valid,
    input  wire         req_ready,
    output wire         req_urgent,
    output wire         req_write,
    output wire [31:0]  req_addr,
    output wire [127:0] req_wdata,
    output wire [15:0]  req_wmask,

    input  wire         rsp_valid,
    output wire         rsp_ready,
    input  wire [127:0] rsp_rdata,
    input  wire         rsp_error
);

    // Se exige una profundidad potencia de dos.
    localparam integer PTR_BITS = $clog2(TAG_DEPTH);
    localparam integer CNT_BITS = PTR_BITS + 1;

    // 0 = monitor, 1 = DMA.
    reg tag_fifo [0:TAG_DEPTH-1];

    reg [PTR_BITS-1:0] wr_ptr;
    reg [PTR_BITS-1:0] rd_ptr;
    reg [CNT_BITS-1:0] tag_count;

    wire tags_empty = (tag_count == 0);
    wire tags_full  = (tag_count == TAG_DEPTH);

    // ------------------------------------------------------------
    // Seleccion de solicitudes
    // ------------------------------------------------------------

    wire select_mon = mon_req_valid;
    wire select_dma = !mon_req_valid && dma_req_valid;

    // No aceptar peticiones sin poder guardar su propietario.
    // En FIFO llena se espera una retirada antes de aceptar otra.
    wire can_accept = !reset && !tags_full;

    assign req_valid = can_accept && (select_mon || select_dma);

    assign req_urgent = 1'b0;

    assign req_write = select_mon ? mon_req_write : dma_req_write;
    assign req_addr  = select_mon ? mon_req_addr  : dma_req_addr;
    assign req_wdata = select_mon ? mon_req_wdata : dma_req_wdata;
    assign req_wmask = select_mon ? mon_req_wmask : dma_req_wmask;

    assign mon_req_ready = can_accept && select_mon && req_ready;

    assign dma_req_ready = can_accept && select_dma && req_ready;

    wire push = req_valid && req_ready;

    // ------------------------------------------------------------
    // Enrutamiento de respuestas
    // ------------------------------------------------------------

    wire response_owner = tag_fifo[rd_ptr];

    wire response_to_mon = !tags_empty && !response_owner;
    wire response_to_dma = !tags_empty &&  response_owner;

    assign mon_rsp_valid = !reset && rsp_valid && response_to_mon;
    assign dma_rsp_valid = !reset && rsp_valid && response_to_dma;

    assign mon_rsp_rdata = rsp_rdata;
    assign dma_rsp_rdata = rsp_rdata;

    assign mon_rsp_error = rsp_error;
    assign dma_rsp_error = rsp_error;

    assign rsp_ready = !reset &&
                       !tags_empty &&
                       (response_owner ? dma_rsp_ready
                                       : mon_rsp_ready);

    wire pop = rsp_valid && rsp_ready;

    // ------------------------------------------------------------
    // FIFO de propietarios
    // ------------------------------------------------------------

    always @(posedge clk) begin
        if (reset) begin
            wr_ptr    <= {PTR_BITS{1'b0}};
            rd_ptr    <= {PTR_BITS{1'b0}};
            tag_count <= {CNT_BITS{1'b0}};
        end else begin

            if (push) begin
                tag_fifo[wr_ptr] <= select_dma;
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
