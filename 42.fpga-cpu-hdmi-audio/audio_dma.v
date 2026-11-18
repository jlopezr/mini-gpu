`default_nettype none

/* Continuous PCM reader: SDRAM ring -> four 32-bit stereo frames -> FIFO. */
module audio_dma(
    input wire clk, input wire reset, input wire enabled, input wire wb_dirty,
    input wire [31:0] ring_base, input wire [4:0] ring_log2_frames,
    input wire [31:0] write_cursor, output reg [31:0] read_cursor,
    output wire req_valid, input wire req_ready, output wire req_write,
    output wire [31:0] req_addr, output wire [127:0] req_wdata,
    output wire [15:0] req_wmask, input wire rsp_valid, output wire rsp_ready,
    input wire [127:0] rsp_rdata, input wire rsp_error,
    output wire fifo_wr_en, output wire [31:0] fifo_wdata, input wire fifo_full,
    output reg [31:0] errors
);
    reg request_pending, have_word;
    reg [127:0] word;
    reg [1:0] frame_index;
    wire [31:0] available = write_cursor - read_cursor;
    wire [31:0] ring_frames = (32'h1 << ring_log2_frames);
    wire [31:0] ring_mask = (32'h1 << ring_log2_frames) - 1'b1;
    wire can_read = enabled && !wb_dirty && !request_pending && !have_word &&
                    !fifo_full && (available >= 32'd4) && (available <= ring_frames);
    /* These are a conventional valid/ready interface: data and valid are
     * combinational from the held SDRAM word, and the state below advances on
     * that same accepted edge.  Registering valid one cycle late can count a
     * frame as consumed while the async FIFO rejects it at full. */
    assign fifo_wr_en = have_word && !fifo_full;
    assign fifo_wdata = word[frame_index*32 +: 32];
    assign req_valid = can_read;
    assign req_write = 1'b0;
    assign req_addr = ring_base + ((read_cursor & ring_mask) << 2);
    assign req_wdata = 128'd0;
    assign req_wmask = 16'd0;
    assign rsp_ready = request_pending;
    always @(posedge clk) begin
      if (reset) begin
        request_pending <= 0; have_word <= 0; frame_index <= 0;
        read_cursor <= 0; errors <= 0;
      end else begin
        if (!enabled) begin
          request_pending <= 0; have_word <= 0; frame_index <= 0; read_cursor <= 0;
        end else begin
          /* Cursors are absolute.  If either side laps the other, unsigned
           * subtraction looks like a huge amount of valid PCM.  Drop that
           * stale epoch and resume from the producer instead of replaying it. */
          if (!request_pending && !have_word && available > ring_frames) begin
            read_cursor <= write_cursor;
            errors <= errors + 1'b1;
          end else begin
            if (req_valid && req_ready) request_pending <= 1'b1;
            if (rsp_valid && rsp_ready) begin
              request_pending <= 1'b0;
              if (rsp_error) errors <= errors + 1'b1;
              else begin word <= rsp_rdata; have_word <= 1'b1; frame_index <= 0; end
            end
            if (fifo_wr_en) begin
              if (frame_index == 2'd3) begin
                have_word <= 1'b0; read_cursor <= read_cursor + 32'd4;
              end else frame_index <= frame_index + 1'b1;
            end
          end
        end
      end
    end
endmodule
`default_nettype wire
