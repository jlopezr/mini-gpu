`default_nettype none

// ============================================================================
// memtest_regs
//
// Registros MMIO para controlar tres grupos y observar hasta cinco
// memory_traffic_gen. GEN4/GEN5 comparten el control de GEN2 en top_fabric6.
//
// Mapa:
//
//   +0x00 CONTROL
//          bit 0  GEN0_ENABLE
//          bit 1  GEN1_ENABLE
//          bit 2  GEN2_ENABLE
//          bit 3  GEN0_URGENT
//          bit 4  GEN1_URGENT
//          bit 5  GEN2_URGENT
//          bit 8  CLEAR_STATS   (pulso)
//
//   +0x04 GEN0_REQUESTS
//   +0x08 GEN0_ERRORS
//   +0x0C GEN0_MISMATCHES
//   +0x10 GEN0_ADDRESS
//   +0x14 GEN0_LOOPS
//
//   +0x20 GEN1_REQUESTS
//   +0x24 GEN1_ERRORS
//   +0x28 GEN1_MISMATCHES
//   +0x2C GEN1_ADDRESS
//   +0x30 GEN1_LOOPS
//
//   +0x40 GEN2_REQUESTS
//   +0x44 GEN2_ERRORS
//   +0x48 GEN2_MISMATCHES
//   +0x4C GEN2_ADDRESS
//   +0x50 GEN2_LOOPS
//
//   +0x60 GEN4_ADDRESS
//   +0x64 GEN4_STATUS: bit 0 response error, bit 1 mismatch
//   +0x80 GEN5_ADDRESS
//   +0x84 GEN5_STATUS: bit 0 response error, bit 1 mismatch
//
// Sólo admite accesos de palabra de 32 bits.
// ============================================================================

module memtest_regs (
    input  wire        clk,
    input  wire        reset,

    input  wire        select,
    input  wire        write,
    input  wire [3:0]  write_mask,
    input  wire [15:0] offset,
    input  wire [31:0] write_data,

    output reg  [31:0] read_data,
    output reg         error,

    output reg  [2:0]  gen_enable,
    output reg  [2:0]  gen_urgent,
    output reg         clear_stats,

    input wire [31:0] gen0_requests,
    input wire [31:0] gen0_errors,
    input wire [31:0] gen0_mismatches,
    input wire [31:0] gen0_address,
    input wire [31:0] gen0_loops,

    input wire [31:0] gen1_requests,
    input wire [31:0] gen1_errors,
    input wire [31:0] gen1_mismatches,
    input wire [31:0] gen1_address,
    input wire [31:0] gen1_loops,

    input wire [31:0] gen2_requests,
    input wire [31:0] gen2_errors,
    input wire [31:0] gen2_mismatches,
    input wire [31:0] gen2_address,
    input wire [31:0] gen2_loops,

    input wire [31:0] gen4_address,
    input wire        gen4_error_seen,
    input wire        gen4_mismatch_seen,

    input wire [31:0] gen5_address,
    input wire        gen5_error_seen,
    input wire        gen5_mismatch_seen
);

    wire aligned = (offset[1:0] == 2'b00);

    always @(posedge clk) begin
        clear_stats <= 1'b0;

        if (reset) begin
            gen_enable <= 3'b000;
            gen_urgent <= 3'b000;
            clear_stats <= 1'b0;
        end else if (select && write &&
                     offset == 16'h0000 &&
                     aligned &&
                     write_mask == 4'b1111) begin

            gen_enable <= write_data[2:0];
            gen_urgent <= write_data[5:3];

            if (write_data[8])
                clear_stats <= 1'b1;
        end
    end

    always @* begin
        read_data = 32'd0;
        error = 1'b0;

        if (select) begin
            if (!aligned) begin
                error = 1'b1;
            end else if (write) begin
                // CONTROL es el único registro escribible.
                if (offset != 16'h0000 ||
                    write_mask != 4'b1111)
                    error = 1'b1;
            end else begin
                case (offset)

                    16'h0000:
                        read_data = {
                            23'd0,
                            1'b0,       // CLEAR_STATS siempre lee 0
                            2'd0,
                            gen_urgent,
                            gen_enable
                        };

                    16'h0004: read_data = gen0_requests;
                    16'h0008: read_data = gen0_errors;
                    16'h000C: read_data = gen0_mismatches;
                    16'h0010: read_data = gen0_address;
                    16'h0014: read_data = gen0_loops;

                    16'h0020: read_data = gen1_requests;
                    16'h0024: read_data = gen1_errors;
                    16'h0028: read_data = gen1_mismatches;
                    16'h002C: read_data = gen1_address;
                    16'h0030: read_data = gen1_loops;

                    16'h0040: read_data = gen2_requests;
                    16'h0044: read_data = gen2_errors;
                    16'h0048: read_data = gen2_mismatches;
                    16'h004C: read_data = gen2_address;
                    16'h0050: read_data = gen2_loops;

                    16'h0060: read_data = gen4_address;
                    16'h0064: read_data = {30'd0, gen4_mismatch_seen,
                                            gen4_error_seen};
                    16'h0080: read_data = gen5_address;
                    16'h0084: read_data = {30'd0, gen5_mismatch_seen,
                                            gen5_error_seen};

                    default: begin
                        read_data = 32'd0;
                        error = 1'b1;
                    end
                endcase
            end
        end
    end

endmodule

`default_nettype wire
