`default_nettype none

// Adapts the monitor's byte-addressed interface to the SDRAM controller's
// 16-bit word interface. The 32 MiB SDRAM occupies 0x00000000..0x01ffffff.
module sdram_byte_adapter (
    input  wire        clk,
    input  wire        reset,
    input  wire        init_done,
    input  wire [31:0] address,
    input  wire [7:0]  write_data,
    input  wire        write_enable,
    input  wire        read_enable,
    output reg  [7:0]  read_data,
    output reg         ready,
    output reg         error,
    output reg         req_valid,
    output reg         req_write,
    output reg  [23:0] req_addr,
    output reg  [15:0] req_wdata,
    output reg  [1:0]  req_wmask,
    input  wire        req_ready,
    input  wire        done,
    input  wire [15:0] rdata
);
  localparam STATE_IDLE = 1'b0;
  localparam STATE_WAIT = 1'b1;

  reg state;
  reg saved_byte_select;
  reg saved_read;

  always @(posedge clk) begin
    ready <= 1'b0;
    error <= 1'b0;

    if (reset) begin
      state <= STATE_IDLE;
      saved_byte_select <= 1'b0;
      saved_read <= 1'b0;
      read_data <= 8'h00;
      req_valid <= 1'b0;
      req_write <= 1'b0;
      req_addr <= 24'h000000;
      req_wdata <= 16'h0000;
      req_wmask <= 2'b00;
    end else begin
      case (state)
        STATE_IDLE: begin
          req_valid <= 1'b0;
          if (write_enable || read_enable) begin
            if (!init_done || address[31:25] != 0 || (write_enable && read_enable)) begin
              error <= 1'b1;
              ready <= 1'b1;
            end else begin
              saved_byte_select <= address[0];
              saved_read <= read_enable;
              req_addr <= address[24:1];
              req_write <= write_enable;
              req_wdata <= address[0] ? {write_data, 8'h00} : {8'h00, write_data};
              req_wmask <= address[0] ? 2'b10 : 2'b01;
              req_valid <= 1'b1;
              state <= STATE_WAIT;
            end
          end
        end
        STATE_WAIT: begin
          if (req_valid && req_ready)
            req_valid <= 1'b0;
          if (done) begin
            if (saved_read)
              read_data <= saved_byte_select ? rdata[15:8] : rdata[7:0];
            ready <= 1'b1;
            state <= STATE_IDLE;
          end
        end
      endcase
    end
  end
endmodule

`default_nettype wire

