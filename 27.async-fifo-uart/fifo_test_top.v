`default_nettype none

module fifo_test_top (
    input  wire       clk_25mhz,
    input  wire [6:0] btn,
    input  wire       ftdi_txd,
    output wire       ftdi_rxd,
    output wire [7:0] led
);
    // ------------------------------------------------------------
    // Independent clocks
    // ------------------------------------------------------------
    wire clk_wr = clk_25mhz;
    wire clk_rd;

    OSCG osc_internal (.OSC(clk_rd));
    defparam osc_internal.DIV = "16";

    // ------------------------------------------------------------
    // FIRE1 reset: btn[1] is active high externally.
    // ------------------------------------------------------------
    wire arst_n = ~btn[1];
    wire rst_wr_n;
    wire rst_rd_n;

    reset_sync reset_wr_i (
        .clk(clk_wr), .arst_n(arst_n), .srst_n(rst_wr_n)
    );

    reset_sync reset_rd_i (
        .clk(clk_rd), .arst_n(arst_n), .srst_n(rst_rd_n)
    );

    // ------------------------------------------------------------
    // FIFO
    // ------------------------------------------------------------
    wire [7:0] fifo_data_out;
    wire       fifo_rd_valid;
    wire       fifo_full;
    wire       fifo_empty;

    reg  [7:0] tx_data;
    wire       wr_en;
    wire       rd_en = 1'b1;

    // 256 write-clock cycles enabled, then 256 disabled.
    reg [8:0] wr_phase;
    assign wr_en = ~wr_phase[8];

    always @(posedge clk_wr or negedge rst_wr_n) begin
        if (!rst_wr_n)
            wr_phase <= 9'd0;
        else
            wr_phase <= wr_phase + 1'b1;
    end

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

    reg [7:0]  expected_data;
    reg [31:0] read_count;
    reg        error_latched;
    reg        empty_seen;

    always @(posedge clk_rd or negedge rst_rd_n) begin
        if (!rst_rd_n) begin
            expected_data <= 8'h00;
            read_count    <= 32'd0;
            error_latched <= 1'b0;
            empty_seen    <= 1'b0;
        end else begin
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

    async_fifo #(
        .DATA_WIDTH(8),
        .ADDR_WIDTH(4)
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

    // ------------------------------------------------------------
    // Synchronize read-domain status into the 25 MHz monitor domain.
    // Only single-bit status crosses here.
    // ------------------------------------------------------------
    (* async_reg = "true" *) reg error_sync1, error_sync2;
    (* async_reg = "true" *) reg empty_seen_sync1, empty_seen_sync2;
    (* async_reg = "true" *) reg empty_sync1, empty_sync2;
    (* async_reg = "true" *) reg read_hb_sync1, read_hb_sync2;

    always @(posedge clk_wr or negedge rst_wr_n) begin
        if (!rst_wr_n) begin
            error_sync1      <= 1'b0;
            error_sync2      <= 1'b0;
            empty_seen_sync1 <= 1'b0;
            empty_seen_sync2 <= 1'b0;
            empty_sync1      <= 1'b1;
            empty_sync2      <= 1'b1;
            read_hb_sync1    <= 1'b0;
            read_hb_sync2    <= 1'b0;
        end else begin
            error_sync1      <= error_latched;
            error_sync2      <= error_sync1;
            empty_seen_sync1 <= empty_seen;
            empty_seen_sync2 <= empty_seen_sync1;
            empty_sync1      <= fifo_empty;
            empty_sync2      <= empty_sync1;
            read_hb_sync1    <= read_count[23];
            read_hb_sync2    <= read_hb_sync1;
        end
    end

    wire pass = full_seen && empty_seen_sync2 && !error_sync2;

    // ------------------------------------------------------------
    // LEDs
    // ------------------------------------------------------------
    assign led[0] = error_sync2;
    assign led[1] = full_seen;
    assign led[2] = empty_seen_sync2;
    assign led[3] = write_count[23];
    assign led[4] = read_hb_sync2;
    assign led[5] = fifo_full;
    assign led[6] = empty_sync2;
    assign led[7] = pass;

    // ------------------------------------------------------------
    // UART at ~115200 baud from 25 MHz.
    // DIVISOR 216 is divisible by four for the existing RX design:
    // 25e6 / 216 = 115740.7 baud (+0.47%).
    // ------------------------------------------------------------
    wire [7:0] uart_rxd;
    wire       uart_rxd_strobe;
    reg  [7:0] uart_txd;
    reg        uart_txd_strobe;
    wire       uart_txd_ready;

    uart #(.DIVISOR(216)) uart_i (
        .clk        (clk_wr),
        .reset      (~rst_wr_n),
        .serial_rxd (ftdi_txd),
        .serial_txd (ftdi_rxd),
        .rxd        (uart_rxd),
        .rxd_strobe (uart_rxd_strobe),
        .txd        (uart_txd),
        .txd_strobe (uart_txd_strobe),
        .txd_ready  (uart_txd_ready)
    );

    // Snapshot only values already safe in clk_wr domain.
    reg [31:0] mon_wr_count;
    reg        mon_full;
    reg        mon_empty;
    reg        mon_full_seen;
    reg        mon_empty_seen;
    reg        mon_error;
    reg        mon_pass;

    function [7:0] hexchar;
        input [3:0] nibble;
        begin
            if (nibble < 10)
                hexchar = "0" + nibble;
            else
                hexchar = "A" + (nibble - 10);
        end
    endfunction

    // Message:
    // WR=XXXXXXXX FULL=x EMPTY=x FSEEN=x ESEEN=x ERR=x PASS=x\r\n
    // positions 0..56 (57 bytes)
    function [7:0] monitor_char;
        input [5:0] pos;
        begin
            case (pos)
                0: monitor_char="W";  1: monitor_char="R";  2: monitor_char="=";
                3: monitor_char=hexchar(mon_wr_count[31:28]);
                4: monitor_char=hexchar(mon_wr_count[27:24]);
                5: monitor_char=hexchar(mon_wr_count[23:20]);
                6: monitor_char=hexchar(mon_wr_count[19:16]);
                7: monitor_char=hexchar(mon_wr_count[15:12]);
                8: monitor_char=hexchar(mon_wr_count[11:8]);
                9: monitor_char=hexchar(mon_wr_count[7:4]);
                10: monitor_char=hexchar(mon_wr_count[3:0]);
                11: monitor_char=" ";
                12: monitor_char="F"; 13: monitor_char="U"; 14: monitor_char="L"; 15: monitor_char="L"; 16: monitor_char="=";
                17: monitor_char=mon_full ? "1" : "0";
                18: monitor_char=" ";
                19: monitor_char="E"; 20: monitor_char="M"; 21: monitor_char="P"; 22: monitor_char="T"; 23: monitor_char="Y"; 24: monitor_char="=";
                25: monitor_char=mon_empty ? "1" : "0";
                26: monitor_char=" ";
                27: monitor_char="F"; 28: monitor_char="S"; 29: monitor_char="E"; 30: monitor_char="E"; 31: monitor_char="N"; 32: monitor_char="=";
                33: monitor_char=mon_full_seen ? "1" : "0";
                34: monitor_char=" ";
                35: monitor_char="E"; 36: monitor_char="S"; 37: monitor_char="E"; 38: monitor_char="E"; 39: monitor_char="N"; 40: monitor_char="=";
                41: monitor_char=mon_empty_seen ? "1" : "0";
                42: monitor_char=" ";
                43: monitor_char="E"; 44: monitor_char="R"; 45: monitor_char="R"; 46: monitor_char="=";
                47: monitor_char=mon_error ? "1" : "0";
                48: monitor_char=" ";
                49: monitor_char="P"; 50: monitor_char="A"; 51: monitor_char="S"; 52: monitor_char="S"; 53: monitor_char="=";
                54: monitor_char=mon_pass ? "1" : "0";
                55: monitor_char=8'h0D;
                56: monitor_char=8'h0A;
                default: monitor_char="?";
            endcase
        end
    endfunction

    localparam [1:0] MON_WAIT       = 2'd0;
    localparam [1:0] MON_SEND       = 2'd1;
    localparam [1:0] MON_WAIT_BUSY  = 2'd2;
    localparam [1:0] MON_WAIT_READY = 2'd3;

    reg [1:0]  mon_state;
    reg [24:0] mon_timer;
    reg [5:0]  mon_pos;

    always @(posedge clk_wr or negedge rst_wr_n) begin
        if (!rst_wr_n) begin
            uart_txd        <= 8'h00;
            uart_txd_strobe <= 1'b0;
            mon_state       <= MON_WAIT;
            mon_timer       <= 25'd0;
            mon_pos         <= 6'd0;
            mon_wr_count    <= 32'd0;
            mon_full        <= 1'b0;
            mon_empty       <= 1'b1;
            mon_full_seen   <= 1'b0;
            mon_empty_seen  <= 1'b0;
            mon_error       <= 1'b0;
            mon_pass        <= 1'b0;
        end else begin
            uart_txd_strobe <= 1'b0;

            case (mon_state)
                MON_WAIT: begin
                    // 's' from the terminal requests an immediate status line.
                    if ((uart_rxd_strobe && (uart_rxd == "s" || uart_rxd == "S")) ||
                        (mon_timer == 25_000_000 - 1)) begin
                        mon_timer      <= 25'd0;
                        mon_pos        <= 6'd0;
                        mon_wr_count   <= write_count;
                        mon_full       <= fifo_full;
                        mon_empty      <= empty_sync2;
                        mon_full_seen  <= full_seen;
                        mon_empty_seen <= empty_seen_sync2;
                        mon_error      <= error_sync2;
                        mon_pass       <= pass;
                        mon_state      <= MON_SEND;
                    end else begin
                        mon_timer <= mon_timer + 1'b1;
                    end
                end

                MON_SEND: begin
                    if (uart_txd_ready) begin
                        uart_txd        <= monitor_char(mon_pos);
                        uart_txd_strobe <= 1'b1;
                        mon_state       <= MON_WAIT_BUSY;
                    end
                end

                MON_WAIT_BUSY: begin
                    if (!uart_txd_ready)
                        mon_state <= MON_WAIT_READY;
                end

                MON_WAIT_READY: begin
                    if (uart_txd_ready) begin
                        if (mon_pos == 6'd56) begin
                            mon_state <= MON_WAIT;
                            mon_pos   <= 6'd0;
                        end else begin
                            mon_pos   <= mon_pos + 1'b1;
                            mon_state <= MON_SEND;
                        end
                    end
                end

                default: mon_state <= MON_WAIT;
            endcase
        end
    end

endmodule

`default_nettype wire
