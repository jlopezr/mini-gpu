`default_nettype none
module fifo_test_top (
    input  wire       clk_25mhz,
    input  wire [6:0] btn,
    output wire [7:0] led
);

    // ============================================================
    // Two genuinely different clock sources
    // ============================================================

    wire clk_wr;
    wire clk_rd;

    assign clk_wr = clk_25mhz;

    // ECP5 internal oscillator.
    // DIV=16 -> roughly ~19 MHz.
    OSCG osc_internal (
        .OSC(clk_rd)
    );

    defparam osc_internal.DIV = "16";

    // ============================================================
    // Reset
    //
    // btn FIRE1, active high
    // ============================================================

    wire arst_n;

    wire rst_wr_n;
    wire rst_rd_n;

    assign arst_n = ~btn[1];

    reset_sync reset_wr_i (
        .clk    (clk_wr),
        .arst_n (arst_n),
        .srst_n (rst_wr_n)
    );

    reset_sync reset_rd_i (
        .clk    (clk_rd),
        .arst_n (arst_n),
        .srst_n (rst_rd_n)
    );

    // ============================================================
    // FIFO signals
    // ============================================================

    wire [7:0] fifo_data_out;
    wire       fifo_rd_valid;

    wire       fifo_full;
    wire       fifo_empty;

    reg  [7:0] tx_data;

    wire       wr_en;
    wire       rd_en;

    // ============================================================
    // Writer traffic generator
    //
    // 256 cycles writing
    // 256 cycles stopped
    //
    // This deliberately fills and empties the FIFO repeatedly.
    // ============================================================

    reg [8:0] wr_phase;

    assign wr_en = ~wr_phase[8];

    always @(posedge clk_wr or negedge rst_wr_n) begin
        if (!rst_wr_n) begin
            wr_phase <= 9'd0;
        end else begin
            wr_phase <= wr_phase + 1'b1;
        end
    end

    // ============================================================
    // Producer
    // ============================================================

    reg [31:0] write_count;
    reg        full_seen;

    always @(posedge clk_wr or negedge rst_wr_n) begin
        if (!rst_wr_n) begin
            tx_data     <= 8'h00;
            write_count <= 32'd0;
            full_seen   <= 1'b0;
        end else begin

            if (fifo_full)
                full_seen <= 1'b1;

            if (wr_en && !fifo_full) begin
                tx_data     <= tx_data + 1'b1;
                write_count <= write_count + 1'b1;
            end
        end
    end

    // ============================================================
    // Reader always wants data
    // ============================================================

    assign rd_en = 1'b1;

    // ============================================================
    // Consumer / checker
    // ============================================================

    reg [7:0] expected_data;

    reg [31:0] read_count;

    reg error_latched;
    reg empty_seen;

    always @(posedge clk_rd or negedge rst_rd_n) begin
        if (!rst_rd_n) begin
            expected_data <= 8'h00;
            read_count    <= 32'd0;

            error_latched <= 1'b0;
            empty_seen    <= 1'b0;
        end else begin

            // Do not count initial reset-empty state.
            // We want to see EMPTY after actual traffic.
            if (fifo_empty && (read_count != 0))
                empty_seen <= 1'b1;

            if (fifo_rd_valid) begin

                if (fifo_data_out != expected_data)
                    error_latched <= 1'b1;

                expected_data <= expected_data + 1'b1;
                read_count    <= read_count + 1'b1;
            end
        end
    end

    // ============================================================
    // FIFO
    // ============================================================

    async_fifo #(
        .DATA_WIDTH (8),
        .ADDR_WIDTH (4)
    ) fifo_i (
        .clk_wr    (clk_wr),
        .clk_rd    (clk_rd),

        .rst_wr_n  (rst_wr_n),
        .rst_rd_n  (rst_rd_n),

        .wr_en     (wr_en),
        .rd_en     (rd_en),

        .data_in   (tx_data),

        .data_out  (fifo_data_out),
        .rd_valid  (fifo_rd_valid),

        .full      (fifo_full),
        .empty     (fifo_empty)
    );

    // ============================================================
    // LEDs
    // ============================================================

    // LED0: ERROR. Must stay OFF.
    assign led[0] = error_latched;

    // LED1: FIFO has reached FULL at least once.
    assign led[1] = full_seen;

    // LED2: FIFO has reached EMPTY after transferring data.
    assign led[2] = empty_seen;

    // LED3: write activity heartbeat.
    assign led[3] = write_count[23];

    // LED4: read activity heartbeat.
    assign led[4] = read_count[23];

    // LED5: current FULL state.
    assign led[5] = fifo_full;

    // LED6: current EMPTY state.
    assign led[6] = fifo_empty;

    // LED7: PASS indication.
    //
    // Only used for visual indication, so combining signals from
    // two clock domains here is harmless: it drives no internal logic.
    assign led[7] =
        full_seen &&
        empty_seen &&
        !error_latched;

endmodule
`default_nettype wire