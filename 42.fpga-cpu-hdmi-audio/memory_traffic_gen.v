`default_nettype none

// ============================================================================
// memory_traffic_gen
//
// Simple 128-bit memory traffic generator / checker.
//
// For every 16-byte line:
//
//      WRITE pattern
//      READ  same address
//      CHECK returned data
//      advance to next line
//
// The generator wraps inside [BASE_ADDR, BASE_ADDR + REGION_SIZE).
//
// Intended uses:
//   - exercise fabric_fifo_bridge
//   - exercise memory fabric arbitration
//   - exercise async CDC
//   - stress SDRAM while the monitor is active
//
// One transaction outstanding at a time.
// ============================================================================

module memory_traffic_gen #(
    parameter [31:0] BASE_ADDR   = 32'h0010_0000,
    parameter [31:0] REGION_SIZE = 32'h0010_0000,
    parameter [31:0] SEED        = 32'h1234_5678
)(
    input wire clk,
    input wire reset,

    // ----------------------------------------------------------------
    // Control
    // ----------------------------------------------------------------

    input wire enable,
    input wire urgent_enable,
    input wire clear_stats,

    // ----------------------------------------------------------------
    // Fabric master request
    // ----------------------------------------------------------------

    output wire         req_valid,
    input  wire         req_ready,

    output wire         req_urgent,
    output wire         req_write,
    output wire [31:0]  req_addr,
    output wire [127:0] req_wdata,
    output wire [15:0]  req_wmask,

    // ----------------------------------------------------------------
    // Fabric master response
    // ----------------------------------------------------------------

    input  wire         rsp_valid,
    output wire         rsp_ready,
    input  wire [127:0] rsp_rdata,
    input  wire         rsp_error,

    // ----------------------------------------------------------------
    // Status / statistics
    // ----------------------------------------------------------------

    output wire         active,

    output reg [31:0] request_count,
    output reg [31:0] write_count,
    output reg [31:0] read_count,

    output reg [31:0] response_error_count,
    output reg [31:0] mismatch_count,
    output reg        response_error_seen,
    output reg        mismatch_seen,

    output reg [31:0] current_addr,
    output reg [31:0] loop_count,

    output reg [31:0] last_error_addr,
    output reg [127:0] last_expected,
    output reg [127:0] last_received
);

    // ========================================================================
    // States
    // ========================================================================

    localparam ST_WRITE_REQ  = 3'd0;
    localparam ST_WRITE_WAIT = 3'd1;

    localparam ST_READ_REQ   = 3'd2;
    localparam ST_READ_WAIT  = 3'd3;

    reg [2:0] state;

    // ========================================================================
    // Pattern generation
    //
    // Include the address so every line gets different contents.
    //
    // This also means that after wrapping around the region we write the
    // same deterministic value again, which makes debugging from the
    // monitor straightforward.
    // ========================================================================

    wire [31:0] pattern0 =
        current_addr ^ SEED;

    wire [31:0] pattern1 =
        current_addr ^ SEED ^ 32'h1357_9BDF;

    wire [31:0] pattern2 =
        current_addr ^ SEED ^ 32'h2468_ACE0;

    wire [31:0] pattern3 =
        current_addr ^ SEED ^ 32'hA5A5_5A5A;

    wire [127:0] expected_data = {
        pattern3,
        pattern2,
        pattern1,
        pattern0
    };

    // ========================================================================
    // Request interface
    // ========================================================================

    assign req_valid =
        enable &&
        ((state == ST_WRITE_REQ) ||
         (state == ST_READ_REQ));

    assign req_write =
        (state == ST_WRITE_REQ);

    assign req_addr = current_addr;

    assign req_wdata = expected_data;

    // All 16 bytes are written.
    assign req_wmask = 16'hFFFF;

    assign req_urgent = urgent_enable;

    // ========================================================================
    // Response interface
    //
    // We are always capable of accepting the response while waiting for it.
    // ========================================================================

    assign rsp_ready =
        (state == ST_WRITE_WAIT) ||
        (state == ST_READ_WAIT);

    assign active = enable;

    // ========================================================================
    // Address advance
    // ========================================================================

    wire [31:0] region_last_addr =
        BASE_ADDR + REGION_SIZE - 32'd16;

    // ========================================================================
    // Main state machine
    // ========================================================================

    always @(posedge clk) begin
        if (reset) begin

            state <= ST_WRITE_REQ;

            current_addr <= BASE_ADDR;
            loop_count   <= 32'd0;

            request_count        <= 32'd0;
            write_count          <= 32'd0;
            read_count           <= 32'd0;
            response_error_count <= 32'd0;
            mismatch_count       <= 32'd0;
            response_error_seen  <= 1'b0;
            mismatch_seen        <= 1'b0;

            last_error_addr <= 32'd0;
            last_expected   <= 128'd0;
            last_received   <= 128'd0;

        end else begin

            // ------------------------------------------------------------
            // Statistics reset
            // ------------------------------------------------------------

            if (clear_stats) begin
                request_count        <= 32'd0;
                write_count          <= 32'd0;
                read_count           <= 32'd0;
                response_error_count <= 32'd0;
                mismatch_count       <= 32'd0;
                response_error_seen  <= 1'b0;
                mismatch_seen        <= 1'b0;

                last_error_addr <= 32'd0;
                last_expected   <= 128'd0;
                last_received   <= 128'd0;
            end

            // ------------------------------------------------------------
            // Generator FSM
            // ------------------------------------------------------------

            case (state)

                // ========================================================
                // WRITE
                // ========================================================

                ST_WRITE_REQ: begin

                    if (enable && req_ready) begin

                        request_count <= request_count + 32'd1;
                        write_count   <= write_count + 32'd1;

                        state <= ST_WRITE_WAIT;
                    end
                end

                ST_WRITE_WAIT: begin

                    if (rsp_valid) begin

                        if (rsp_error) begin
                            response_error_count <=
                                response_error_count + 32'd1;
                            response_error_seen <= 1'b1;

                            last_error_addr <= current_addr;
                        end

                        // Whether the write succeeded or failed, perform
                        // the read. This makes failures visible in both
                        // the response-error and data-check paths.
                        state <= ST_READ_REQ;
                    end
                end

                // ========================================================
                // READ
                // ========================================================

                ST_READ_REQ: begin

                    if (enable && req_ready) begin

                        request_count <= request_count + 32'd1;
                        read_count    <= read_count + 32'd1;

                        state <= ST_READ_WAIT;
                    end
                end

                ST_READ_WAIT: begin

                    if (rsp_valid) begin

                        if (rsp_error) begin

                            response_error_count <=
                                response_error_count + 32'd1;
                            response_error_seen <= 1'b1;

                            last_error_addr <= current_addr;

                        end else if (rsp_rdata != expected_data) begin

                            mismatch_count <=
                                mismatch_count + 32'd1;
                            mismatch_seen <= 1'b1;

                            last_error_addr <= current_addr;
                            last_expected   <= expected_data;
                            last_received   <= rsp_rdata;
                        end

                        // --------------------------------------------
                        // Advance to next 16-byte line
                        // --------------------------------------------

                        if (current_addr >= region_last_addr) begin
                            current_addr <= BASE_ADDR;
                            loop_count   <= loop_count + 32'd1;
                        end else begin
                            current_addr <= current_addr + 32'd16;
                        end

                        state <= ST_WRITE_REQ;
                    end
                end

                default: begin
                    state <= ST_WRITE_REQ;
                end

            endcase
        end
    end

endmodule

`default_nettype wire
