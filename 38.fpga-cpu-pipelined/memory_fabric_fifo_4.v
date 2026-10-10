`default_nettype none

module memory_fabric_fifo_4 #(
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000
)(
    input wire clk,
    input wire reset,

    // ================================================================
    // PORT 0
    // ================================================================
    input  wire         p0_req_empty,
    output wire         p0_req_rd_en,
    input  wire         p0_req_rd_valid,
    input  wire [177:0] p0_req_data,

    input  wire         p0_rsp_full,
    output wire         p0_rsp_wr_en,
    output wire [128:0] p0_rsp_data,

    // ================================================================
    // PORT 1
    // ================================================================
    input  wire         p1_req_empty,
    output wire         p1_req_rd_en,
    input  wire         p1_req_rd_valid,
    input  wire [177:0] p1_req_data,

    input  wire         p1_rsp_full,
    output wire         p1_rsp_wr_en,
    output wire [128:0] p1_rsp_data,

    // ================================================================
    // PORT 2
    // ================================================================
    input  wire         p2_req_empty,
    output wire         p2_req_rd_en,
    input  wire         p2_req_rd_valid,
    input  wire [177:0] p2_req_data,

    input  wire         p2_rsp_full,
    output wire         p2_rsp_wr_en,
    output wire [128:0] p2_rsp_data,

    // ================================================================
    // PORT 3
    // ================================================================
    input  wire         p3_req_empty,
    output wire         p3_req_rd_en,
    input  wire         p3_req_rd_valid,
    input  wire [177:0] p3_req_data,

    input  wire         p3_rsp_full,
    output wire         p3_rsp_wr_en,
    output wire [128:0] p3_rsp_data,

    // ================================================================
    // SDRAM controller
    // ================================================================
    output wire         sdram_req_valid,
    input  wire         sdram_req_ready,
    output wire         sdram_req_write,
    output wire [23:0]  sdram_req_addr,
    output wire [127:0] sdram_req_wdata,
    output wire [15:0]  sdram_req_wmask,

    input  wire         sdram_done,
    input  wire [127:0] sdram_rdata,

    output wire         busy
);

    // ================================================================
    // Packet formats
    //
    // Request:
    //
    //   [177]     urgent
    //   [176]     write
    //   [175:144] byte address
    //   [143:16]  write data
    //   [15:0]    write mask
    //
    // Response:
    //
    //   [128]     error
    //   [127:0]   read data
    // ================================================================

    localparam MASTER_0 = 2'd0;
    localparam MASTER_1 = 2'd1;
    localparam MASTER_2 = 2'd2;
    localparam MASTER_3 = 2'd3;

    localparam ST_IDLE    = 3'd0;
    localparam ST_CAPTURE = 3'd1;
    localparam ST_CHECK   = 3'd2;
    localparam ST_ISSUE   = 3'd3;
    localparam ST_WAIT    = 3'd4;
    localparam ST_RESP    = 3'd5;

    reg [2:0] state;

    reg [1:0] grant; reg grant_valid; reg [1:0] active_master;

    // ================================================================
    // One prefetched request per port
    // ================================================================

    reg [177:0] head0_data;
    reg [177:0] head1_data;
    reg [177:0] head2_data;
    reg [177:0] head3_data;

    reg head0_valid;
    reg head1_valid;
    reg head2_valid;
    reg head3_valid;

    // A read has been issued to the FIFO but rd_valid has not arrived yet.
    reg prefetch0_pending;
    reg prefetch1_pending;
    reg prefetch2_pending;
    reg prefetch3_pending;

    // Start a FIFO read whenever its head register is free.
    //
    // pending prevents issuing several reads while waiting for the
    // synchronous FIFO read result.
    assign p0_req_rd_en =
        !head0_valid && !prefetch0_pending && !p0_req_empty;

    assign p1_req_rd_en =
        !head1_valid && !prefetch1_pending && !p1_req_empty;

    assign p2_req_rd_en =
        !head2_valid && !prefetch2_pending && !p2_req_empty;

    assign p3_req_rd_en =
        !head3_valid && !prefetch3_pending && !p3_req_empty;

    // ================================================================
    // Prefetch engines
    // ================================================================

    always @(posedge clk) begin
        if (reset) begin
            head0_valid      <= 1'b0;
            prefetch0_pending <= 1'b0;
        end else begin

            if (p0_req_rd_en)
                prefetch0_pending <= 1'b1;

            if (p0_req_rd_valid) begin
                head0_data         <= p0_req_data;
                head0_valid        <= 1'b1;
                prefetch0_pending  <= 1'b0;
            end

            if (state == ST_CAPTURE &&
                active_master == MASTER_0)
                head0_valid <= 1'b0;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            head1_valid       <= 1'b0;
            prefetch1_pending <= 1'b0;
        end else begin

            if (p1_req_rd_en)
                prefetch1_pending <= 1'b1;

            if (p1_req_rd_valid) begin
                head1_data         <= p1_req_data;
                head1_valid        <= 1'b1;
                prefetch1_pending  <= 1'b0;
            end

            if (state == ST_CAPTURE &&
                active_master == MASTER_1)
                head1_valid <= 1'b0;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            head2_valid       <= 1'b0;
            prefetch2_pending <= 1'b0;
        end else begin

            if (p2_req_rd_en)
                prefetch2_pending <= 1'b1;

            if (p2_req_rd_valid) begin
                head2_data         <= p2_req_data;
                head2_valid        <= 1'b1;
                prefetch2_pending  <= 1'b0;
            end

            if (state == ST_CAPTURE &&
                active_master == MASTER_2)
                head2_valid <= 1'b0;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            head3_valid       <= 1'b0;
            prefetch3_pending <= 1'b0;
        end else begin

            if (p3_req_rd_en)
                prefetch3_pending <= 1'b1;

            if (p3_req_rd_valid) begin
                head3_data         <= p3_req_data;
                head3_valid        <= 1'b1;
                prefetch3_pending  <= 1'b0;
            end

            if (state == ST_CAPTURE &&
                active_master == MASTER_3)
                head3_valid <= 1'b0;
        end
    end

    // ================================================================
    // Arbitration
    // ================================================================

    reg [1:0] rr_next;

    wire urgent0 = head0_valid && head0_data[177];
    wire urgent1 = head1_valid && head1_data[177];
    wire urgent2 = head2_valid && head2_data[177];
    wire urgent3 = head3_valid && head3_data[177];

    // First choose among urgent requests using the same RR ordering.
    // If there are no urgent requests, choose among all requests.

    always @* begin
        grant       = rr_next;
        grant_valid = 1'b0;

        // ------------------------------------------------------------
        // Urgent pass
        // ------------------------------------------------------------

        case (rr_next)
            MASTER_0: begin
                if      (urgent0) begin grant=MASTER_0; grant_valid=1'b1; end
                else if (urgent1) begin grant=MASTER_1; grant_valid=1'b1; end
                else if (urgent2) begin grant=MASTER_2; grant_valid=1'b1; end
                else if (urgent3) begin grant=MASTER_3; grant_valid=1'b1; end
            end

            MASTER_1: begin
                if      (urgent1) begin grant=MASTER_1; grant_valid=1'b1; end
                else if (urgent2) begin grant=MASTER_2; grant_valid=1'b1; end
                else if (urgent3) begin grant=MASTER_3; grant_valid=1'b1; end
                else if (urgent0) begin grant=MASTER_0; grant_valid=1'b1; end
            end

            MASTER_2: begin
                if      (urgent2) begin grant=MASTER_2; grant_valid=1'b1; end
                else if (urgent3) begin grant=MASTER_3; grant_valid=1'b1; end
                else if (urgent0) begin grant=MASTER_0; grant_valid=1'b1; end
                else if (urgent1) begin grant=MASTER_1; grant_valid=1'b1; end
            end

            default: begin
                if      (urgent3) begin grant=MASTER_3; grant_valid=1'b1; end
                else if (urgent0) begin grant=MASTER_0; grant_valid=1'b1; end
                else if (urgent1) begin grant=MASTER_1; grant_valid=1'b1; end
                else if (urgent2) begin grant=MASTER_2; grant_valid=1'b1; end
            end
        endcase

        // ------------------------------------------------------------
        // Normal RR pass
        // ------------------------------------------------------------

        if (!grant_valid) begin
            case (rr_next)
                MASTER_0: begin
                    if      (head0_valid) begin grant=MASTER_0; grant_valid=1'b1; end
                    else if (head1_valid) begin grant=MASTER_1; grant_valid=1'b1; end
                    else if (head2_valid) begin grant=MASTER_2; grant_valid=1'b1; end
                    else if (head3_valid) begin grant=MASTER_3; grant_valid=1'b1; end
                end

                MASTER_1: begin
                    if      (head1_valid) begin grant=MASTER_1; grant_valid=1'b1; end
                    else if (head2_valid) begin grant=MASTER_2; grant_valid=1'b1; end
                    else if (head3_valid) begin grant=MASTER_3; grant_valid=1'b1; end
                    else if (head0_valid) begin grant=MASTER_0; grant_valid=1'b1; end
                end

                MASTER_2: begin
                    if      (head2_valid) begin grant=MASTER_2; grant_valid=1'b1; end
                    else if (head3_valid) begin grant=MASTER_3; grant_valid=1'b1; end
                    else if (head0_valid) begin grant=MASTER_0; grant_valid=1'b1; end
                    else if (head1_valid) begin grant=MASTER_1; grant_valid=1'b1; end
                end

                default: begin
                    if      (head3_valid) begin grant=MASTER_3; grant_valid=1'b1; end
                    else if (head0_valid) begin grant=MASTER_0; grant_valid=1'b1; end
                    else if (head1_valid) begin grant=MASTER_1; grant_valid=1'b1; end
                    else if (head2_valid) begin grant=MASTER_2; grant_valid=1'b1; end
                end
            endcase
        end
    end

    // ================================================================
    // Selected head
    // ================================================================

    wire [177:0] active_head_data =
        (active_master == MASTER_0) ? head0_data :
        (active_master == MASTER_1) ? head1_data :
        (active_master == MASTER_2) ? head2_data :
                              head3_data;

    // ================================================================
    // Active transaction
    // ================================================================

    reg         active_write;
    reg [31:0]  active_addr;
    reg [127:0] active_wdata;
    reg [15:0]  active_wmask;

    reg [127:0] response_rdata;
    reg         response_error;

    wire active_rsp_full =
        (active_master == MASTER_0) ? p0_rsp_full :
        (active_master == MASTER_1) ? p1_rsp_full :
        (active_master == MASTER_2) ? p2_rsp_full :
                                      p3_rsp_full;

    // ================================================================
    // SDRAM
    // ================================================================

    assign sdram_req_valid = (state == ST_ISSUE);
    assign sdram_req_write = active_write;
    assign sdram_req_addr  = active_addr[24:1];
    assign sdram_req_wdata = active_wdata;
    assign sdram_req_wmask = active_wmask;

    assign busy = (state != ST_IDLE);

    // ================================================================
    // Response FIFO
    // ================================================================

    wire response_fire = (state == ST_RESP) && !active_rsp_full;

    assign p0_rsp_wr_en =
        response_fire && active_master == MASTER_0;

    assign p1_rsp_wr_en =
        response_fire && active_master == MASTER_1;

    assign p2_rsp_wr_en =
        response_fire && active_master == MASTER_2;

    assign p3_rsp_wr_en =
        response_fire && active_master == MASTER_3;

    assign p0_rsp_data = {response_error,response_rdata};
    assign p1_rsp_data = {response_error,response_rdata};
    assign p2_rsp_data = {response_error,response_rdata};
    assign p3_rsp_data = {response_error,response_rdata};

    // ================================================================
    // Main FSM
    // ================================================================

    always @(posedge clk) begin
        if (reset) begin
            state          <= ST_IDLE;
            rr_next        <= MASTER_0;
            active_master  <= MASTER_0;

            active_write   <= 1'b0;
            active_addr    <= 32'd0;
            active_wdata   <= 128'd0;
            active_wmask   <= 16'd0;

            response_rdata <= 128'd0;
            response_error <= 1'b0;

        end else begin
            case (state)

                // ----------------------------------------------------
                // The FIFO read latency has already happened in the
                // prefetch engines. Arbitration sees complete requests.
                // ----------------------------------------------------
                ST_IDLE: begin
                    if (grant_valid) begin
                        active_master <= grant;

                        state <= ST_CAPTURE;
                    end
                end

                // ----------------------------------------------------
                // Select the complete request using the registered
                // master. This separates urgent/RR arbitration from the
                // 178-bit payload mux that feeds the active registers.
                // The corresponding head remains valid until this edge.
                // ----------------------------------------------------
                ST_CAPTURE: begin

                    active_write <= active_head_data[176];
                    active_addr  <= active_head_data[175:144];
                    active_wdata <= active_head_data[143:16];
                    active_wmask <= active_head_data[15:0];

                    state <= ST_CHECK;
                end

                // ----------------------------------------------------
                // Validate the registered request.  Keeping this in a
                // separate cycle breaks the path through the 178-bit
                // grant mux, address comparator and state update.
                // ----------------------------------------------------
                ST_CHECK: begin

                    // Byte address must be inside SDRAM and aligned
                    // to the 16-byte fabric transaction.
                    if ((active_addr >= SDRAM_SIZE_BYTES) ||
                        (active_addr[3:0] != 4'b0000)) begin

                        response_rdata <= 128'd0;
                        response_error <= 1'b1;
                        state <= ST_RESP;

                    end else begin
                        response_error <= 1'b0;
                        state <= ST_ISSUE;
                    end
                end

                // ----------------------------------------------------
                // Hold the request until the SDRAM controller accepts.
                // ----------------------------------------------------
                ST_ISSUE: begin
                    if (sdram_req_ready)
                        state <= ST_WAIT;
                end

                // ----------------------------------------------------
                // Wait for completion.
                // ----------------------------------------------------
                ST_WAIT: begin
                    if (sdram_done) begin
                        response_rdata <= sdram_rdata;
                        response_error <= 1'b0;
                        state <= ST_RESP;
                    end
                end

                // ----------------------------------------------------
                // Wait for room in the corresponding response FIFO.
                // ----------------------------------------------------
                ST_RESP: begin
                    if (!active_rsp_full) begin
                        case (active_master)
                            MASTER_0: rr_next <= MASTER_1;
                            MASTER_1: rr_next <= MASTER_2;
                            MASTER_2: rr_next <= MASTER_3;
                            MASTER_3: rr_next <= MASTER_0;
                        endcase

                        state <= ST_IDLE;
                    end
                end

                default:
                    state <= ST_IDLE;

            endcase
        end
    end

endmodule

`default_nettype wire
