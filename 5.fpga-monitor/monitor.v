`default_nettype none

/*
 * Minimal UART monitor protocol.
 *
 * Requests:
 *   0x01 (PING)        -> 0x81
 *   0x02 (GET_VERSION) -> 0x82 0x01 0x00
 *   any other byte     -> 0xff
 *
 * The host must wait for the complete response before sending another command.
 */
module monitor (
    input clk,
    input reset,

    input [7:0] rx_data,
    input rx_strobe,

    output reg [7:0] tx_data,
    output reg tx_strobe,
    input tx_ready,

    output reg [7:0] last_command,
    output busy
);

  localparam [7:0] CMD_PING = 8'h01;
  localparam [7:0] CMD_GET_VERSION = 8'h02;

  localparam [7:0] RSP_PONG = 8'h81;
  localparam [7:0] RSP_VERSION = 8'h82;
  localparam [7:0] RSP_ERROR = 8'hff;

  localparam [7:0] VERSION_MAJOR = 8'h01;
  localparam [7:0] VERSION_MINOR = 8'h00;

  localparam [1:0] STATE_IDLE = 2'd0;
  localparam [1:0] STATE_PING = 2'd1;
  localparam [1:0] STATE_VERSION = 2'd2;
  localparam [1:0] STATE_ERROR = 2'd3;

  reg [1:0] state;
  reg [1:0] response_index;
  reg waiting_for_accept;

  assign busy = (state != STATE_IDLE) || waiting_for_accept;

  always @(posedge clk) begin
    tx_strobe <= 1'b0;

    if (reset) begin
      tx_data <= 8'h00;
      tx_strobe <= 1'b0;
      last_command <= 8'h00;
      state <= STATE_IDLE;
      response_index <= 2'd0;
      waiting_for_accept <= 1'b0;
    end else if (waiting_for_accept) begin
      // tx_ready goes low after uart_tx has sampled tx_strobe.
      if (!tx_ready) begin
        waiting_for_accept <= 1'b0;
      end
    end else begin
      case (state)
        STATE_IDLE: begin
          response_index <= 2'd0;

          if (rx_strobe) begin
            last_command <= rx_data;

            case (rx_data)
              CMD_PING: state <= STATE_PING;
              CMD_GET_VERSION: state <= STATE_VERSION;
              default: state <= STATE_ERROR;
            endcase
          end
        end

        STATE_PING: begin
          if (tx_ready) begin
            tx_data <= RSP_PONG;
            tx_strobe <= 1'b1;
            waiting_for_accept <= 1'b1;
            state <= STATE_IDLE;
          end
        end

        STATE_VERSION: begin
          if (tx_ready) begin
            tx_strobe <= 1'b1;
            waiting_for_accept <= 1'b1;

            case (response_index)
              2'd0: begin
                tx_data <= RSP_VERSION;
                response_index <= 2'd1;
              end
              2'd1: begin
                tx_data <= VERSION_MAJOR;
                response_index <= 2'd2;
              end
              default: begin
                tx_data <= VERSION_MINOR;
                state <= STATE_IDLE;
              end
            endcase
          end
        end

        default: begin
          if (tx_ready) begin
            tx_data <= RSP_ERROR;
            tx_strobe <= 1'b1;
            waiting_for_accept <= 1'b1;
            state <= STATE_IDLE;
          end
        end
      endcase
    end
  end
endmodule

`default_nettype wire
