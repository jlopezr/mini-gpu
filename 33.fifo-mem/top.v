`default_nettype none

module top (
    input         clk_25mhz,
    output [7:0]  led,
    output        wifi_gpio0,

    input         ftdi_txd,
    output        ftdi_rxd,

    output        sdram_clk,
    output        sdram_cke,
    output        sdram_csn,
    output        sdram_rasn,
    output        sdram_casn,
    output        sdram_wen,
    output [12:0] sdram_a,
    output [1:0]  sdram_ba,
    output [1:0]  sdram_dqm,
    inout  [15:0] sdram_d,

    output [3:0]  gpdi_dp
);

    // ========================================================================
    // Clocks / reset
    // ========================================================================

    wire clk_mem;
    wire pll_locked;

    pll_mem pll_mem_i (
        .clkin   (clk_25mhz),
        .clkout0 (clk_mem),
        .locked  (pll_locked)
    );

    // No tenemos pin de reset en este top.
    // Mantener reset hasta que el PLL lleve un rato estable.
    reg [7:0] reset_count = 8'd0;

    always @(posedge clk_25mhz) begin
        if (!pll_locked)
            reset_count <= 8'd0;
        else if (!(&reset_count))
            reset_count <= reset_count + 8'd1;
    end

    wire reset_25 = !(&reset_count);

    // Sincronizar la liberación del reset al dominio de memoria.
    reg [1:0] reset_mem_sync = 2'b11;

    always @(posedge clk_mem) begin
        if (!pll_locked)
            reset_mem_sync <= 2'b11;
        else
            reset_mem_sync <= {reset_mem_sync[0], reset_25};
    end

    wire reset_mem = reset_mem_sync[1];

    // ========================================================================
    // UART
    //
    // 25 MHz / 100 = 250 kbaud
    // ========================================================================

    wire [7:0] uart_rx_data;
    wire       uart_rx_strobe;

    wire [7:0] uart_tx_data;
    wire       uart_tx_strobe;
    wire       uart_tx_ready;

    uart #(
        .DIVISOR(100)
    ) uart_i (
        .clk        (clk_25mhz),
        .reset      (reset_25),

        .serial_rxd (ftdi_txd),
        .serial_txd (ftdi_rxd),

        .rxd        (uart_rx_data),
        .rxd_strobe (uart_rx_strobe),

        .txd        (uart_tx_data),
        .txd_strobe (uart_tx_strobe),
        .txd_ready  (uart_tx_ready)
    );

    // ========================================================================
    // Monitor bus
    // ========================================================================

    wire [31:0] mon_address;

    wire [7:0]  mon_write_data;
    wire        mon_write_enable;

    wire [31:0] mon_write_word;
    wire        mon_write_word_enable;

    wire        mon_read_enable;

    reg  [7:0]  mon_read_data;
    reg  [31:0] mon_read_word;

    reg         mon_ready;
    reg         mon_error;

    wire [7:0] monitor_last_command;
    wire       monitor_busy;

    monitor #(
        .VERSION_MAJOR (8'd1),
        .VERSION_MINOR (8'd0),

        .HAS_SERIAL (0),
        .HAS_INPUT  (0),

        .RAM_END (
            33'h0_0200_0000
        ),

        .WINDOW0_BASE (
            33'h0_8120_0000
        ),

        .WINDOW0_END (
            33'h0_8121_0000
        )
    ) monitor_i (
        .clk       (clk_25mhz),
        .reset     (reset_25),

        .rx_data   (uart_rx_data),
        .rx_strobe (uart_rx_strobe),

        .tx_data   (uart_tx_data),
        .tx_strobe (uart_tx_strobe),
        .tx_ready  (uart_tx_ready),

        .mem_address           (mon_address),
        .mem_write_data        (mon_write_data),
        .mem_write_enable      (mon_write_enable),
        .mem_write_word        (mon_write_word),
        .mem_write_word_enable (mon_write_word_enable),
        .mem_read_enable       (mon_read_enable),

        .mem_read_data (mon_read_data),
        .mem_read_word (mon_read_word),
        .mem_ready     (mon_ready),
        .mem_error     (mon_error),

        // No CPU en este bitstream.
        .cpu_run_request   (),
        .cpu_halt_request  (),
        .cpu_step_request  (),
        .cpu_reset_request (),

        .cpu_halted     (1'b1),
        .cpu_error      (1'b0),
        .cpu_error_code (8'd0),
        .cpu_pc         (32'd0),

        .cpu_debug_register_address (),
        .cpu_debug_register_data    (32'd0),

        // No CPU serial.
        .serial_push      (),
        .serial_push_data (),
        .serial_rx_free   (8'd0),
        .serial_pop       (),
        .serial_tx_data   (8'd0),
        .serial_tx_count  (8'd0),

        // No INPUT.
        .input_event_valid       (),
        .input_event_word        (),
        .input_presence_write    (),
        .input_presence_keyboard (),
        .input_presence_mouse    (),
        .input_free_slots        (5'd0),

        .last_command (monitor_last_command),
        .busy         (monitor_busy)
    );

    // ========================================================================
    // MEMTEST registers
    // ========================================================================

    wire [2:0] gen_enable;
    wire [2:0] gen_urgent;
    wire       clear_stats;

    reg         memtest_select;
    reg         memtest_write;
    reg  [3:0]  memtest_write_mask;
    reg  [15:0] memtest_offset;
    reg  [31:0] memtest_write_data;

    wire [31:0] memtest_read_data;
    wire        memtest_error;

    // Generator statistics.
    wire [31:0] gen0_requests;
    wire [31:0] gen0_errors;
    wire [31:0] gen0_mismatches;
    wire [31:0] gen0_address;
    wire [31:0] gen0_loops;

    wire [31:0] gen1_requests;
    wire [31:0] gen1_errors;
    wire [31:0] gen1_mismatches;
    wire [31:0] gen1_address;
    wire [31:0] gen1_loops;

    wire [31:0] gen2_requests;
    wire [31:0] gen2_errors;
    wire [31:0] gen2_mismatches;
    wire [31:0] gen2_address;
    wire [31:0] gen2_loops;

    memtest_regs memtest_regs_i (
        .clk   (clk_25mhz),
        .reset (reset_25),

        .select      (memtest_select),
        .write       (memtest_write),
        .write_mask  (memtest_write_mask),
        .offset      (memtest_offset),
        .write_data  (memtest_write_data),

        .read_data (memtest_read_data),
        .error     (memtest_error),

        .gen_enable  (gen_enable),
        .gen_urgent  (gen_urgent),
        .clear_stats (clear_stats),

        .gen0_requests   (gen0_requests),
        .gen0_errors     (gen0_errors),
        .gen0_mismatches (gen0_mismatches),
        .gen0_address    (gen0_address),
        .gen0_loops      (gen0_loops),

        .gen1_requests   (gen1_requests),
        .gen1_errors     (gen1_errors),
        .gen1_mismatches (gen1_mismatches),
        .gen1_address    (gen1_address),
        .gen1_loops      (gen1_loops),

        .gen2_requests   (gen2_requests),
        .gen2_errors     (gen2_errors),
        .gen2_mismatches (gen2_mismatches),
        .gen2_address    (gen2_address),
        .gen2_loops      (gen2_loops),

        .gen4_address       (32'd0), .gen4_error_seen    (1'b0),
        .gen4_mismatch_seen (1'b0),
        .gen5_address       (32'd0), .gen5_error_seen    (1'b0),
        .gen5_mismatch_seen (1'b0)
    );

    // ========================================================================
    // Monitor -> AUX adapter
    //
    // Convierte byte/word del monitor a la interfaz AUX de 32 bits.
    // ========================================================================

    reg         aux_valid;
    wire        aux_ready;

    reg  [31:0] aux_address;
    reg  [31:0] aux_write_data;
    reg  [3:0]  aux_strobe;

    wire        aux_rsp_valid;
    reg         aux_rsp_ready;

    wire [31:0] aux_read_data;
    wire        aux_error;

    localparam MON_IDLE      = 3'd0;
    localparam MON_AUX_REQ   = 3'd1;
    localparam MON_AUX_RSP   = 3'd2;
    localparam MON_MMIO_WAIT = 3'd3;

    reg [2:0] mon_state;

    reg [1:0] mon_byte_lane;
    reg       mon_byte_read;

    wire mon_request =
        mon_write_enable ||
        mon_write_word_enable ||
        mon_read_enable;

    wire mon_is_memtest =
        (mon_address[31:16] == 16'h8120);

    always @(posedge clk_25mhz) begin
        if (reset_25) begin
            mon_state <= MON_IDLE;

            mon_ready <= 1'b0;
            mon_error <= 1'b0;

            mon_read_data <= 8'd0;
            mon_read_word <= 32'd0;

            aux_valid <= 1'b0;
            aux_address <= 32'd0;
            aux_write_data <= 32'd0;
            aux_strobe <= 4'd0;
            aux_rsp_ready <= 1'b0;

            memtest_select <= 1'b0;
            memtest_write <= 1'b0;
            memtest_write_mask <= 4'd0;
            memtest_offset <= 16'd0;
            memtest_write_data <= 32'd0;

            mon_byte_lane <= 2'd0;
            mon_byte_read <= 1'b0;

        end else begin
            mon_ready <= 1'b0;
            aux_rsp_ready <= 1'b0;
            memtest_select <= 1'b0;

            case (mon_state)

                MON_IDLE: begin
                    aux_valid <= 1'b0;
                    mon_error <= 1'b0;

                    if (mon_request) begin
                        mon_byte_lane <= mon_address[1:0];

                        // ------------------------------------------------
                        // MEMTEST
                        // ------------------------------------------------

                        if (mon_is_memtest) begin
                            memtest_select <= 1'b1;
                            memtest_offset <= mon_address[15:0];

                            if (mon_write_word_enable) begin
                                memtest_write <= 1'b1;
                                memtest_write_mask <= 4'b1111;
                                memtest_write_data <= mon_write_word;

                            end else if (mon_write_enable) begin
                                // MEMTEST rechaza writes parciales.
                                memtest_write <= 1'b1;

                                case (mon_address[1:0])
                                    2'd0: begin
                                        memtest_write_mask <= 4'b0001;
                                        memtest_write_data <=
                                            {24'd0, mon_write_data};
                                    end
                                    2'd1: begin
                                        memtest_write_mask <= 4'b0010;
                                        memtest_write_data <=
                                            {16'd0, mon_write_data, 8'd0};
                                    end
                                    2'd2: begin
                                        memtest_write_mask <= 4'b0100;
                                        memtest_write_data <=
                                            {8'd0, mon_write_data, 16'd0};
                                    end
                                    default: begin
                                        memtest_write_mask <= 4'b1000;
                                        memtest_write_data <=
                                            {mon_write_data, 24'd0};
                                    end
                                endcase

                            end else begin
                                memtest_write <= 1'b0;
                                memtest_write_mask <= 4'd0;
                                memtest_write_data <= 32'd0;
                            end

                            mon_state <= MON_MMIO_WAIT;

                        // ------------------------------------------------
                        // RAM
                        // ------------------------------------------------

                        end else begin
                            // AUX siempre ve dirección de palabra alineada.
                            aux_address <= {
                                mon_address[31:2],
                                2'b00
                            };

                            if (mon_write_word_enable) begin
                                aux_write_data <= mon_write_word;
                                aux_strobe <= 4'b1111;
                                mon_byte_read <= 1'b0;

                            end else if (mon_write_enable) begin
                                case (mon_address[1:0])
                                    2'd0: begin
                                        aux_write_data <=
                                            {24'd0, mon_write_data};
                                        aux_strobe <= 4'b0001;
                                    end

                                    2'd1: begin
                                        aux_write_data <=
                                            {16'd0, mon_write_data, 8'd0};
                                        aux_strobe <= 4'b0010;
                                    end

                                    2'd2: begin
                                        aux_write_data <=
                                            {8'd0, mon_write_data, 16'd0};
                                        aux_strobe <= 4'b0100;
                                    end

                                    default: begin
                                        aux_write_data <=
                                            {mon_write_data, 24'd0};
                                        aux_strobe <= 4'b1000;
                                    end
                                endcase

                                mon_byte_read <= 1'b0;

                            end else begin
                                // strobe=0 -> lectura.
                                aux_write_data <= 32'd0;
                                aux_strobe <= 4'b0000;
                                mon_byte_read <=
                                    (mon_address[1:0] != 2'b00);
                            end

                            aux_valid <= 1'b1;
                            mon_state <= MON_AUX_REQ;
                        end
                    end
                end

                MON_AUX_REQ: begin
                    if (aux_ready) begin
                        aux_valid <= 1'b0;
                        mon_state <= MON_AUX_RSP;
                    end
                end

                MON_AUX_RSP: begin
                    aux_rsp_ready <= 1'b1;

                    if (aux_rsp_valid) begin
                        mon_read_word <= aux_read_data;

                        case (mon_byte_lane)
                            2'd0: mon_read_data <= aux_read_data[7:0];
                            2'd1: mon_read_data <= aux_read_data[15:8];
                            2'd2: mon_read_data <= aux_read_data[23:16];
                            2'd3: mon_read_data <= aux_read_data[31:24];
                        endcase

                        mon_error <= aux_error;
                        mon_ready <= 1'b1;

                        mon_state <= MON_IDLE;
                    end
                end

                MON_MMIO_WAIT: begin
                    mon_read_word <= memtest_read_data;

                    case (mon_byte_lane)
                        2'd0: mon_read_data <= memtest_read_data[7:0];
                        2'd1: mon_read_data <= memtest_read_data[15:8];
                        2'd2: mon_read_data <= memtest_read_data[23:16];
                        2'd3: mon_read_data <= memtest_read_data[31:24];
                    endcase

                    mon_error <= memtest_error;
                    mon_ready <= 1'b1;

                    mon_state <= MON_IDLE;
                end

                default:
                    mon_state <= MON_IDLE;

            endcase
        end
    end

    // ========================================================================
    // SDRAM init_done -> 25 MHz
    // ========================================================================

    wire sdram_init_done;

    (* async_reg = "true" *) reg init_sync1;
    (* async_reg = "true" *) reg init_sync2;

    always @(posedge clk_25mhz) begin
        if (reset_25) begin
            init_sync1 <= 1'b0;
            init_sync2 <= 1'b0;
        end else begin
            init_sync1 <= sdram_init_done;
            init_sync2 <= init_sync1;
        end
    end

    // ========================================================================
    // Master request/response buses
    // ========================================================================

    wire [3:0]         m_req_valid;
    wire [3:0]         m_req_ready;
    wire [3:0]         m_req_urgent;
    wire [3:0]         m_req_write;

    wire [31:0]        m_req_addr  [0:3];
    wire [127:0]       m_req_wdata [0:3];
    wire [15:0]        m_req_wmask [0:3];

    wire [3:0]         m_rsp_valid;
    wire [3:0]         m_rsp_ready;
    wire [127:0]       m_rsp_rdata [0:3];
    wire [3:0]         m_rsp_error;

    // ========================================================================
    // Traffic generators
    // ========================================================================

    memory_traffic_gen #(
        .BASE_ADDR   (32'h0010_0000),
        .REGION_SIZE (32'h0010_0000),
        .SEED        (32'h1111_1111)
    ) gen0 (
        .clk           (clk_25mhz),
        .reset         (reset_25),
        .enable        (gen_enable[0]),
        .urgent_enable (gen_urgent[0]),
        .clear_stats   (clear_stats),

        .req_valid  (m_req_valid[0]),
        .req_ready  (m_req_ready[0]),
        .req_urgent (m_req_urgent[0]),
        .req_write  (m_req_write[0]),
        .req_addr   (m_req_addr[0]),
        .req_wdata  (m_req_wdata[0]),
        .req_wmask  (m_req_wmask[0]),

        .rsp_valid (m_rsp_valid[0]),
        .rsp_ready (m_rsp_ready[0]),
        .rsp_rdata (m_rsp_rdata[0]),
        .rsp_error (m_rsp_error[0]),

        .active               (),
        .request_count        (gen0_requests),
        .write_count          (),
        .read_count           (),
        .response_error_count (gen0_errors),
        .mismatch_count       (gen0_mismatches),
        .current_addr         (gen0_address),
        .loop_count           (gen0_loops),
        .last_error_addr      (),
        .last_expected        (),
        .last_received        ()
    );

    memory_traffic_gen #(
        .BASE_ADDR   (32'h0020_0000),
        .REGION_SIZE (32'h0010_0000),
        .SEED        (32'h2222_2222)
    ) gen1 (
        .clk           (clk_25mhz),
        .reset         (reset_25),
        .enable        (gen_enable[1]),
        .urgent_enable (gen_urgent[1]),
        .clear_stats   (clear_stats),

        .req_valid  (m_req_valid[1]),
        .req_ready  (m_req_ready[1]),
        .req_urgent (m_req_urgent[1]),
        .req_write  (m_req_write[1]),
        .req_addr   (m_req_addr[1]),
        .req_wdata  (m_req_wdata[1]),
        .req_wmask  (m_req_wmask[1]),

        .rsp_valid (m_rsp_valid[1]),
        .rsp_ready (m_rsp_ready[1]),
        .rsp_rdata (m_rsp_rdata[1]),
        .rsp_error (m_rsp_error[1]),

        .active               (),
        .request_count        (gen1_requests),
        .write_count          (),
        .read_count           (),
        .response_error_count (gen1_errors),
        .mismatch_count       (gen1_mismatches),
        .current_addr         (gen1_address),
        .loop_count           (gen1_loops),
        .last_error_addr      (),
        .last_expected        (),
        .last_received        ()
    );

    memory_traffic_gen #(
        .BASE_ADDR   (32'h0030_0000),
        .REGION_SIZE (32'h0010_0000),
        .SEED        (32'h3333_3333)
    ) gen2 (
        .clk           (clk_25mhz),
        .reset         (reset_25),
        .enable        (gen_enable[2]),
        .urgent_enable (gen_urgent[2]),
        .clear_stats   (clear_stats),

        .req_valid  (m_req_valid[2]),
        .req_ready  (m_req_ready[2]),
        .req_urgent (m_req_urgent[2]),
        .req_write  (m_req_write[2]),
        .req_addr   (m_req_addr[2]),
        .req_wdata  (m_req_wdata[2]),
        .req_wmask  (m_req_wmask[2]),

        .rsp_valid (m_rsp_valid[2]),
        .rsp_ready (m_rsp_ready[2]),
        .rsp_rdata (m_rsp_rdata[2]),
        .rsp_error (m_rsp_error[2]),

        .active               (),
        .request_count        (gen2_requests),
        .write_count          (),
        .read_count           (),
        .response_error_count (gen2_errors),
        .mismatch_count       (gen2_mismatches),
        .current_addr         (gen2_address),
        .loop_count           (gen2_loops),
        .last_error_addr      (),
        .last_expected        (),
        .last_received        ()
    );

    // ========================================================================
    // AUX adapter = master 3
    // ========================================================================

    gpu_aux_adapter_128 aux_adapter_i (
        .clk       (clk_25mhz),
        .reset     (reset_25),
        .init_done (init_sync2),

        .aux_valid      (aux_valid),
        .aux_ready      (aux_ready),
        .aux_address    (aux_address),
        .aux_write_data (aux_write_data),
        .aux_strobe     (aux_strobe),

        .aux_rsp_valid (aux_rsp_valid),
        .aux_rsp_ready (aux_rsp_ready),
        .aux_read_data (aux_read_data),
        .aux_error     (aux_error),

        .req_valid (m_req_valid[3]),
        .req_ready (m_req_ready[3]),
        .req_write (m_req_write[3]),
        .req_addr  (m_req_addr[3]),
        .req_wdata (m_req_wdata[3]),
        .req_wmask (m_req_wmask[3]),

        .rsp_valid (m_rsp_valid[3]),
        .rsp_ready (m_rsp_ready[3]),
        .rsp_rdata (m_rsp_rdata[3]),
        .rsp_error (m_rsp_error[3])
    );

    assign m_req_urgent[3] = 1'b0;

    // ========================================================================
    // Four CDC bridges
    // ========================================================================

    wire [3:0] req_empty;
    wire [3:0] req_rd_en;
    wire [3:0] req_rd_valid;

    wire [177:0] req_data [0:3];

    wire [3:0] rsp_full;
    wire [3:0] rsp_wr_en;

    wire [128:0] rsp_data [0:3];

    genvar i;

    generate
        for (i = 0; i < 4; i = i + 1) begin : g_bridge

            fabric_fifo_bridge #(
                .FIFO_ADDR_WIDTH(2)
            ) bridge (
                .master_clk   (clk_25mhz),
                .master_reset (reset_25),

                .req_valid  (m_req_valid[i]),
                .req_ready  (m_req_ready[i]),
                .req_urgent (m_req_urgent[i]),
                .req_write  (m_req_write[i]),
                .req_addr   (m_req_addr[i]),
                .req_wdata  (m_req_wdata[i]),
                .req_wmask  (m_req_wmask[i]),

                .rsp_valid (m_rsp_valid[i]),
                .rsp_ready (m_rsp_ready[i]),
                .rsp_rdata (m_rsp_rdata[i]),
                .rsp_error (m_rsp_error[i]),

                .mem_clk   (clk_mem),
                .mem_reset (reset_mem),

                .mem_req_empty    (req_empty[i]),
                .mem_req_rd_en    (req_rd_en[i]),
                .mem_req_rd_valid (req_rd_valid[i]),
                .mem_req_data     (req_data[i]),

                .mem_rsp_full  (rsp_full[i]),
                .mem_rsp_wr_en (rsp_wr_en[i]),
                .mem_rsp_data  (rsp_data[i])
            );

        end
    endgenerate

    // ========================================================================
    // Memory fabric @100 MHz
    // ========================================================================

    wire         dram_req_valid;
    wire         dram_req_ready;
    wire         dram_req_write;
    wire [23:0]  dram_req_addr;
    wire [127:0] dram_req_wdata;
    wire [15:0]  dram_req_wmask;

    wire         dram_done;
    wire [127:0] dram_rdata;

    wire fabric_busy;

    memory_fabric_fifo_4 fabric_i (
        .clk   (clk_mem),
        .reset (reset_mem),

        .p0_req_empty    (req_empty[0]),
        .p0_req_rd_en    (req_rd_en[0]),
        .p0_req_rd_valid (req_rd_valid[0]),
        .p0_req_data     (req_data[0]),
        .p0_rsp_full     (rsp_full[0]),
        .p0_rsp_wr_en    (rsp_wr_en[0]),
        .p0_rsp_data     (rsp_data[0]),

        .p1_req_empty    (req_empty[1]),
        .p1_req_rd_en    (req_rd_en[1]),
        .p1_req_rd_valid (req_rd_valid[1]),
        .p1_req_data     (req_data[1]),
        .p1_rsp_full     (rsp_full[1]),
        .p1_rsp_wr_en    (rsp_wr_en[1]),
        .p1_rsp_data     (rsp_data[1]),

        .p2_req_empty    (req_empty[2]),
        .p2_req_rd_en    (req_rd_en[2]),
        .p2_req_rd_valid (req_rd_valid[2]),
        .p2_req_data     (req_data[2]),
        .p2_rsp_full     (rsp_full[2]),
        .p2_rsp_wr_en    (rsp_wr_en[2]),
        .p2_rsp_data     (rsp_data[2]),

        .p3_req_empty    (req_empty[3]),
        .p3_req_rd_en    (req_rd_en[3]),
        .p3_req_rd_valid (req_rd_valid[3]),
        .p3_req_data     (req_data[3]),
        .p3_rsp_full     (rsp_full[3]),
        .p3_rsp_wr_en    (rsp_wr_en[3]),
        .p3_rsp_data     (rsp_data[3]),

        .sdram_req_valid (dram_req_valid),
        .sdram_req_ready (dram_req_ready),
        .sdram_req_write (dram_req_write),
        .sdram_req_addr  (dram_req_addr),
        .sdram_req_wdata (dram_req_wdata),
        .sdram_req_wmask (dram_req_wmask),

        .sdram_done  (dram_done),
        .sdram_rdata (dram_rdata),

        .busy (fabric_busy)
    );

    // ========================================================================
    // SDRAM @100 MHz
    // ========================================================================

    wire sdram_busy;

    sdram_controller_128 #(
        .CLK_FREQ_HZ(100_000_000)
    ) sdram_i (
        .clk   (clk_mem),
        .reset (reset_mem),

        .req_valid (dram_req_valid),
        .req_write (dram_req_write),
        .req_addr  (dram_req_addr),
        .req_wdata (dram_req_wdata),
        .req_wmask (dram_req_wmask),

        .req_ready (dram_req_ready),

        .done  (dram_done),
        .rdata (dram_rdata),

        .init_done (sdram_init_done),
        .busy      (sdram_busy),

        .sdram_clk  (sdram_clk),
        .sdram_cke  (sdram_cke),
        .sdram_csn  (sdram_csn),
        .sdram_rasn (sdram_rasn),
        .sdram_casn (sdram_casn),
        .sdram_wen  (sdram_wen),

        .sdram_a   (sdram_a),
        .sdram_ba  (sdram_ba),
        .sdram_dqm (sdram_dqm),
        .sdram_d   (sdram_d)
    );

    // ========================================================================
    // Board outputs / debug
    // ========================================================================

    assign wifi_gpio0 = 1'b1;

    // No HDMI en este bitstream.
    assign gpdi_dp = 4'b0000;

    // LEDs:
    //
    // 0 PLL locked
    // 1 SDRAM init done
    // 2 gen0 enabled
    // 3 gen1 enabled
    // 4 gen2 enabled
    // 5 any response error
    // 6 any mismatch
    // 7 monitor busy

    assign led[0] = pll_locked;
    assign led[1] = init_sync2;

    assign led[2] = gen_enable[0];
    assign led[3] = gen_enable[1];
    assign led[4] = gen_enable[2];

    assign led[5] =
        (gen0_errors != 0) ||
        (gen1_errors != 0) ||
        (gen2_errors != 0);

    assign led[6] =
        (gen0_mismatches != 0) ||
        (gen1_mismatches != 0) ||
        (gen2_mismatches != 0);

    assign led[7] = monitor_busy;

endmodule

`default_nettype wire
