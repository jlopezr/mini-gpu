`default_nettype none

/* PCM HDMI control plane. The SDRAM reader is deliberately separate: this
 * block owns the software-visible ring contract and reports the consumer state.
 */
module audio_mmio(
    input wire clk, input wire reset,
    input wire select, input wire write, input wire [3:0] write_mask,
    input wire [15:0] address, input wire [31:0] write_data,
    output reg [31:0] read_data, output reg mmio_error,
    output reg enabled, output reg [31:0] ring_base,
    output reg [4:0] ring_log2_frames, output reg [31:0] write_cursor,
    input wire [31:0] read_cursor, input wire [15:0] fifo_level,
    input wire fifo_empty, input wire [31:0] underruns, input wire [31:0] sample_ticks,
    output reg clear_underruns
);
    always @* begin
        read_data = 32'd0;
        mmio_error = 1'b0;
        if (select) begin
            if (address[1:0] != 0 || (write && write_mask != 4'hf))
                mmio_error = 1'b1;
            else begin
                case (address[7:2])
                    6'd0: begin read_data = 32'h4155_4431; if (write) mmio_error = 1'b1; end
                    6'd1: begin read_data = 32'h0001_0001; if (write) mmio_error = 1'b1; end
                    6'd2: begin read_data = {31'd0, enabled}; if (write && (write_data & ~32'h3)) mmio_error = 1'b1; end
                    6'd3: read_data = ring_base;
                    6'd4: begin read_data = {27'd0, ring_log2_frames}; if (write && (write_data < 32'd4 || write_data > 32'd20)) mmio_error = 1'b1; end
                    6'd5: read_data = write_cursor;
                    6'd6: begin read_data = read_cursor; if (write) mmio_error = 1'b1; end
                    6'd7: begin read_data = {15'd0, fifo_empty, fifo_level}; if (write) mmio_error = 1'b1; end
                    6'd8: begin read_data = underruns; if (write && write_data != 32'h1) mmio_error = 1'b1; end
                    6'd9: begin read_data = sample_ticks; if (write) mmio_error = 1'b1; end
                    default: mmio_error = 1'b1;
                endcase
            end
        end
    end
    always @(posedge clk) begin
        clear_underruns <= 1'b0;
        if (reset) begin
            enabled <= 1'b0; ring_base <= 0; ring_log2_frames <= 5'd12;
            write_cursor <= 0;
        end else if (select && write && !mmio_error) begin
            case (address[7:2])
                6'd2: begin enabled <= write_data[0]; if (write_data[1]) clear_underruns <= 1'b1; end
                6'd3: ring_base <= write_data;
                6'd4: ring_log2_frames <= write_data[4:0];
                6'd5: write_cursor <= write_data;
                6'd8: clear_underruns <= 1'b1;
                default: ;
            endcase
        end
    end
endmodule

`default_nettype wire
