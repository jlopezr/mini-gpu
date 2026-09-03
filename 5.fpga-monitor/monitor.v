`default_nettype none

/*
 * Minimal UART monitor protocol.
 *
 * Requests and responses:
 *   01             (PING)        -> 81
 *   02             (GET_VERSION) -> 82 01 00
 *   10 AA AA DD    (WRITE_BYTE)  -> 90 (or ff if address > 3fff)
 *   11 AA AA       (READ_BYTE)   -> 91 DD (or ff if address > 3fff)
 *   any other command            -> ff
 *
 * Addresses are transferred most-significant byte first. The host must wait
 * for the complete response before sending another command.
 */
module monitor (
    input clk,
    input reset,
    input [7:0] rx_data,
    input rx_strobe,
    output reg [7:0] tx_data,
    output reg tx_strobe,
    input tx_ready,
    output reg [15:0] mem_address,
    output reg [7:0] mem_write_data,
    output reg mem_write_enable,
    output reg mem_read_enable,
    input [7:0] mem_read_data,
    input mem_ready,
    output reg [7:0] last_command,
    output busy
);

  localparam [7:0] CMD_PING = 8'h01;
  localparam [7:0] CMD_GET_VERSION = 8'h02;
  localparam [7:0] CMD_WRITE_BYTE = 8'h10;
  localparam [7:0] CMD_READ_BYTE = 8'h11;
  localparam [7:0] RSP_PONG = 8'h81;
  localparam [7:0] RSP_VERSION = 8'h82;
  localparam [7:0] RSP_WRITE_BYTE = 8'h90;
  localparam [7:0] RSP_READ_BYTE = 8'h91;
  localparam [7:0] RSP_ERROR = 8'hff;
  localparam [7:0] VERSION_MAJOR = 8'h01;
  localparam [7:0] VERSION_MINOR = 8'h00;

  localparam [3:0] STATE_IDLE = 4'd0;
  localparam [3:0] STATE_WRITE_ADDRESS_HIGH = 4'd1;
  localparam [3:0] STATE_WRITE_ADDRESS_LOW = 4'd2;
  localparam [3:0] STATE_WRITE_DATA = 4'd3;
  localparam [3:0] STATE_WAIT_WRITE = 4'd4;
  localparam [3:0] STATE_READ_ADDRESS_HIGH = 4'd5;
  localparam [3:0] STATE_READ_ADDRESS_LOW = 4'd6;
  localparam [3:0] STATE_WAIT_READ = 4'd7;
  localparam [3:0] STATE_RESPOND = 4'd8;
  localparam [3:0] STATE_WAIT_TX_ACCEPT = 4'd9;

  reg [3:0] state;
  reg [3:0] state_after_tx;
  reg [1:0] response_index;
  reg [1:0] response_length;
  reg [7:0] response_byte_0;
  reg [7:0] response_byte_1;
  reg [7:0] response_byte_2;

  assign busy = (state != STATE_IDLE);

  always @(posedge clk) begin
    tx_strobe <= 1'b0;
    mem_write_enable <= 1'b0;
    mem_read_enable <= 1'b0;

    if (reset) begin
      tx_data <= 8'h00;
      tx_strobe <= 1'b0;
      mem_address <= 16'h0000;
      mem_write_data <= 8'h00;
      mem_write_enable <= 1'b0;
      mem_read_enable <= 1'b0;
      last_command <= 8'h00;
      state <= STATE_IDLE;
      state_after_tx <= STATE_IDLE;
      response_index <= 2'd0;
      response_length <= 2'd0;
      response_byte_0 <= 8'h00;
      response_byte_1 <= 8'h00;
      response_byte_2 <= 8'h00;
    end else begin
      case (state)
        STATE_IDLE: begin
          if (rx_strobe) begin
            last_command <= rx_data;
            response_index <= 2'd0;

            case (rx_data)
              CMD_PING: begin
                response_byte_0 <= RSP_PONG;
                response_length <= 2'd1;
                state <= STATE_RESPOND;
              end
              CMD_GET_VERSION: begin
                response_byte_0 <= RSP_VERSION;
                response_byte_1 <= VERSION_MAJOR;
                response_byte_2 <= VERSION_MINOR;
                response_length <= 2'd3;
                state <= STATE_RESPOND;
              end
              CMD_WRITE_BYTE: state <= STATE_WRITE_ADDRESS_HIGH;
              CMD_READ_BYTE: state <= STATE_READ_ADDRESS_HIGH;
              default: begin
                response_byte_0 <= RSP_ERROR;
                response_length <= 2'd1;
                state <= STATE_RESPOND;
              end
            endcase
          end
        end

        STATE_WRITE_ADDRESS_HIGH: begin
          if (rx_strobe) begin
            mem_address[15:8] <= rx_data;
            state <= STATE_WRITE_ADDRESS_LOW;
          end
        end
        STATE_WRITE_ADDRESS_LOW: begin
          if (rx_strobe) begin
            mem_address[7:0] <= rx_data;
            state <= STATE_WRITE_DATA;
          end
        end
        STATE_WRITE_DATA: begin
          if (rx_strobe) begin
            if (mem_address[15:14] != 0) begin
              response_byte_0 <= RSP_ERROR;
              response_length <= 2'd1;
              response_index <= 2'd0;
              state <= STATE_RESPOND;
            end else begin
              mem_write_data <= rx_data;
              mem_write_enable <= 1'b1;
              state <= STATE_WAIT_WRITE;
            end
          end
        end
        STATE_WAIT_WRITE: begin
          if (mem_ready) begin
            response_byte_0 <= RSP_WRITE_BYTE;
            response_length <= 2'd1;
            response_index <= 2'd0;
            state <= STATE_RESPOND;
          end
        end

        STATE_READ_ADDRESS_HIGH: begin
          if (rx_strobe) begin
            mem_address[15:8] <= rx_data;
            state <= STATE_READ_ADDRESS_LOW;
          end
        end
        STATE_READ_ADDRESS_LOW: begin
          if (rx_strobe) begin
            mem_address[7:0] <= rx_data;
            if (mem_address[15:14] != 0) begin
              response_byte_0 <= RSP_ERROR;
              response_length <= 2'd1;
              response_index <= 2'd0;
              state <= STATE_RESPOND;
            end else begin
              mem_read_enable <= 1'b1;
              state <= STATE_WAIT_READ;
            end
          end
        end
        STATE_WAIT_READ: begin
          if (mem_ready) begin
            response_byte_0 <= RSP_READ_BYTE;
            response_byte_1 <= mem_read_data;
            response_length <= 2'd2;
            response_index <= 2'd0;
            state <= STATE_RESPOND;
          end
        end

        STATE_RESPOND: begin
          if (tx_ready) begin
            case (response_index)
              2'd0: tx_data <= response_byte_0;
              2'd1: tx_data <= response_byte_1;
              default: tx_data <= response_byte_2;
            endcase

            tx_strobe <= 1'b1;
            if (response_index + 1 >= response_length) begin
              state_after_tx <= STATE_IDLE;
            end else begin
              response_index <= response_index + 1'b1;
              state_after_tx <= STATE_RESPOND;
            end
            state <= STATE_WAIT_TX_ACCEPT;
          end
        end
        STATE_WAIT_TX_ACCEPT: begin
          if (!tx_ready) begin
            state <= state_after_tx;
          end
        end
        default: state <= STATE_IDLE;
      endcase
    end
  end
endmodule

`default_nettype wire
