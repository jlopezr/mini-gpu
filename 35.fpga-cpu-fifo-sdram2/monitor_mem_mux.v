`default_nettype none

// ============================================================================
// monitor_mem_mux
//
// Separa los accesos del monitor entre:
//
//   RAM:
//       0x0000_0000 .. 0x01FF_FFFF
//
//   MEMTEST:
//       0x8120_0000 .. 0x8120_FFFF
//
// La RAM sale como la interfaz AUX de 32 bits que espera
// gpu_aux_adapter_128.
//
// MEMTEST se resuelve localmente.
// ============================================================================

module monitor_mem_mux #(
    parameter [31:0] RAM_SIZE     = 32'h0200_0000,
    parameter [31:0] MEMTEST_BASE = 32'h8120_0000
)(
    input wire clk,
    input wire reset,

    // ------------------------------------------------------------
    // Monitor
    // ------------------------------------------------------------

    input wire [31:0] mon_address,

    input wire [7:0]  mon_write_data,
    input wire        mon_write_enable,

    input wire [31:0] mon_write_word,
    input wire        mon_write_word_enable,

    input wire        mon_read_enable,

    output reg [7:0]  mon_read_data,
    output reg [31:0] mon_read_word,
    output reg        mon_ready,
    output reg        mon_error,

    // ------------------------------------------------------------
    // RAM / AUX adapter
    // ------------------------------------------------------------

    output reg [31:0] ram_address,

    output reg [7:0]  ram_write_data,
    output reg        ram_write_enable,

    output reg [31:0] ram_write_word,
    output reg        ram_write_word_enable,

    output reg        ram_read_enable,

    input wire [7:0]  ram_read_data,
    input wire [31:0] ram_read_word,
    input wire        ram_ready,
    input wire        ram_error,

    // ------------------------------------------------------------
    // MEMTEST
    // ------------------------------------------------------------

    output reg         memtest_select,
    output reg         memtest_write,
    output reg [3:0]   memtest_write_mask,
    output reg [15:0]  memtest_offset,
    output reg [31:0]  memtest_write_data,

    input wire [31:0]  memtest_read_data,
    input wire         memtest_error
);

    localparam ST_IDLE     = 2'd0;
    localparam ST_RAM_WAIT = 2'd1;
    localparam ST_MMIO_ACK = 2'd2;

    reg [1:0] state;

    wire request =
        mon_write_enable ||
        mon_write_word_enable ||
        mon_read_enable;

    wire address_is_ram =
        mon_address < RAM_SIZE;

    wire address_is_memtest =
        mon_address[31:16] == MEMTEST_BASE[31:16];

    always @(posedge clk) begin

        mon_ready <= 1'b0;

        ram_write_enable      <= 1'b0;
        ram_write_word_enable <= 1'b0;
        ram_read_enable       <= 1'b0;

        memtest_select <= 1'b0;

        if (reset) begin

            state <= ST_IDLE;

            mon_read_data <= 8'd0;
            mon_read_word <= 32'd0;
            mon_error <= 1'b0;

            ram_address <= 32'd0;
            ram_write_data <= 8'd0;
            ram_write_word <= 32'd0;

            memtest_write <= 1'b0;
            memtest_write_mask <= 4'd0;
            memtest_offset <= 16'd0;
            memtest_write_data <= 32'd0;

        end else begin

            case (state)

                // ====================================================
                // Accept monitor request
                // ====================================================

                ST_IDLE: begin

                    if (request) begin

                        mon_error <= 1'b0;

                        // --------------------------------------------
                        // RAM
                        // --------------------------------------------

                        if (address_is_ram) begin

                            ram_address <= mon_address;

                            if (mon_write_word_enable) begin

                                ram_write_word <= mon_write_word;
                                ram_write_word_enable <= 1'b1;

                            end else if (mon_write_enable) begin

                                ram_write_data <= mon_write_data;
                                ram_write_enable <= 1'b1;

                            end else begin

                                ram_read_enable <= 1'b1;
                            end

                            state <= ST_RAM_WAIT;

                        // --------------------------------------------
                        // MEMTEST
                        // --------------------------------------------

                        end else if (address_is_memtest) begin

                            memtest_offset <=
                                mon_address[15:0];

                            memtest_select <= 1'b1;

                            if (mon_write_word_enable) begin

                                memtest_write <= 1'b1;
                                memtest_write_mask <= 4'b1111;
                                memtest_write_data <= mon_write_word;

                            end else if (mon_write_enable) begin

                                // MEMTEST sólo acepta palabras.
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

                            state <= ST_MMIO_ACK;

                        // --------------------------------------------
                        // Invalid address
                        // --------------------------------------------

                        end else begin

                            mon_error <= 1'b1;
                            mon_ready <= 1'b1;
                        end
                    end
                end

                // ====================================================
                // Wait for AUX/RAM
                // ====================================================

                ST_RAM_WAIT: begin

                    if (ram_ready) begin

                        mon_read_data <= ram_read_data;
                        mon_read_word <= ram_read_word;

                        mon_error <= ram_error;
                        mon_ready <= 1'b1;

                        state <= ST_IDLE;
                    end
                end

                // ====================================================
                // MEMTEST has had one complete cycle with select high.
                // Capture result and ACK monitor.
                // ====================================================

                ST_MMIO_ACK: begin

                    mon_read_word <= memtest_read_data;

                    case (memtest_offset[1:0])
                        2'd0: mon_read_data <= memtest_read_data[7:0];
                        2'd1: mon_read_data <= memtest_read_data[15:8];
                        2'd2: mon_read_data <= memtest_read_data[23:16];
                        2'd3: mon_read_data <= memtest_read_data[31:24];
                    endcase

                    mon_error <= memtest_error;
                    mon_ready <= 1'b1;

                    state <= ST_IDLE;
                end

                default:
                    state <= ST_IDLE;

            endcase
        end
    end

endmodule

`default_nettype wire