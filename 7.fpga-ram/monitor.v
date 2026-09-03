`default_nettype none

// UART memory monitor. Multi-byte fields are transferred most-significant
// byte first. Addresses are byte addresses in the 32 MiB SDRAM region.
module monitor (
    input wire clk, input wire reset,
    input wire [7:0] rx_data, input wire rx_strobe,
    output reg [7:0] tx_data, output reg tx_strobe, input wire tx_ready,
    output reg [31:0] mem_address, output reg [7:0] mem_write_data,
    output reg mem_write_enable, output reg mem_read_enable,
    input wire [7:0] mem_read_data, input wire mem_ready, input wire mem_error,
    output reg [7:0] last_command, output wire busy
);
  localparam [7:0] CMD_PING=8'h01, CMD_VERSION=8'h02,
    CMD_WRITE_BYTE=8'h10, CMD_READ_BYTE=8'h11,
    CMD_WRITE_BLOCK=8'h20, CMD_READ_BLOCK=8'h21;
  localparam [7:0] RSP_PONG=8'h81, RSP_VERSION=8'h82,
    RSP_WRITE_BYTE=8'h90, RSP_READ_BYTE=8'h91,
    RSP_WRITE_BLOCK=8'ha0, RSP_READ_BLOCK=8'ha1, RSP_ERROR=8'hff;

  localparam [4:0] S_IDLE=0, S_ADDRESS=1, S_WRITE_DATA=2,
    S_READ_REQUEST=3, S_WAIT_SINGLE=4, S_LENGTH_HIGH=5, S_LENGTH_LOW=6,
    S_BLOCK_WRITE_DATA=7, S_BLOCK_WAIT_WRITE=8,
    S_BLOCK_READ_REQUEST=9, S_BLOCK_WAIT_READ=10,
    S_SEND=11, S_WAIT_TX=12;

  reg [4:0] state, send_return_state, wait_return_state;
  reg [7:0] command;
  reg [1:0] address_bytes;
  reg [15:0] block_length, block_remaining;
  reg [1:0] response_index, response_length;
  reg [7:0] response_0, response_1, response_2;

  wire [31:0] address_with_byte = {mem_address[23:0], rx_data};
  wire [16:0] length_with_byte = {1'b0, block_length[15:8], rx_data};
  wire [32:0] block_end = {1'b0, mem_address} + length_with_byte;
  assign busy = state != S_IDLE;

  always @(posedge clk) begin
    tx_strobe <= 1'b0;
    mem_write_enable <= 1'b0;
    mem_read_enable <= 1'b0;
    if (reset) begin
      state<=S_IDLE; send_return_state<=S_IDLE; wait_return_state<=S_IDLE;
      command<=0; address_bytes<=0; block_length<=0; block_remaining<=0;
      response_index<=0; response_length<=0; response_0<=0; response_1<=0; response_2<=0;
      tx_data<=0; tx_strobe<=0; mem_address<=0; mem_write_data<=0;
      mem_write_enable<=0; mem_read_enable<=0; last_command<=0;
    end else begin
      case (state)
        S_IDLE: if (rx_strobe) begin
          last_command<=rx_data; command<=rx_data; response_index<=0;
          case (rx_data)
            CMD_PING: begin response_0<=RSP_PONG; response_length<=1; send_return_state<=S_IDLE; state<=S_SEND; end
            CMD_VERSION: begin response_0<=RSP_VERSION; response_1<=8'h02; response_2<=8'h00;
                               response_length<=3; send_return_state<=S_IDLE; state<=S_SEND; end
            CMD_WRITE_BYTE, CMD_READ_BYTE, CMD_WRITE_BLOCK, CMD_READ_BLOCK: begin
              mem_address<=0; address_bytes<=0; state<=S_ADDRESS;
            end
            default: begin response_0<=RSP_ERROR; response_length<=1; send_return_state<=S_IDLE; state<=S_SEND; end
          endcase
        end

        S_ADDRESS: if (rx_strobe) begin
          mem_address<=address_with_byte;
          if (address_bytes==3) begin
            if (address_with_byte[31:25] != 0) begin
              response_0<=RSP_ERROR; response_length<=1; response_index<=0;
              send_return_state<=S_IDLE; state<=S_SEND;
            end else if (command==CMD_WRITE_BYTE) state<=S_WRITE_DATA;
            else if (command==CMD_READ_BYTE) state<=S_READ_REQUEST;
            else state<=S_LENGTH_HIGH;
          end else address_bytes<=address_bytes+1'b1;
        end

        S_WRITE_DATA: if (rx_strobe) begin
          mem_write_data<=rx_data; mem_write_enable<=1; wait_return_state<=S_IDLE; state<=S_WAIT_SINGLE;
        end
        S_READ_REQUEST: begin mem_read_enable<=1; wait_return_state<=S_IDLE; state<=S_WAIT_SINGLE; end
        S_WAIT_SINGLE: if (mem_ready) begin
          response_index<=0; send_return_state<=wait_return_state;
          if (mem_error) begin response_0<=RSP_ERROR; response_length<=1; end
          else if (command==CMD_READ_BYTE) begin
            response_0<=RSP_READ_BYTE; response_1<=mem_read_data; response_length<=2;
          end else begin response_0<=RSP_WRITE_BYTE; response_length<=1; end
          state<=S_SEND;
        end

        S_LENGTH_HIGH: if (rx_strobe) begin block_length[15:8]<=rx_data; state<=S_LENGTH_LOW; end
        S_LENGTH_LOW: if (rx_strobe) begin
          block_length[7:0]<=rx_data; block_remaining<={block_length[15:8],rx_data};
          if (length_with_byte==0 || length_with_byte>256 || block_end>33'h02000000) begin
            response_0<=RSP_ERROR; response_length<=1; response_index<=0;
            send_return_state<=S_IDLE; state<=S_SEND;
          end else if (command==CMD_WRITE_BLOCK) state<=S_BLOCK_WRITE_DATA;
          else begin
            response_0<=RSP_READ_BLOCK; response_length<=1; response_index<=0;
            send_return_state<=S_BLOCK_READ_REQUEST; state<=S_SEND;
          end
        end

        S_BLOCK_WRITE_DATA: if (rx_strobe) begin
          mem_write_data<=rx_data; mem_write_enable<=1; state<=S_BLOCK_WAIT_WRITE;
        end
        S_BLOCK_WAIT_WRITE: if (mem_ready) begin
          if (mem_error) begin
            response_0<=RSP_ERROR; response_length<=1; response_index<=0;
            send_return_state<=S_IDLE; state<=S_SEND;
          end else if (block_remaining==1) begin
            response_0<=RSP_WRITE_BLOCK; response_length<=1; response_index<=0;
            send_return_state<=S_IDLE; state<=S_SEND;
          end else begin
            mem_address<=mem_address+1'b1; block_remaining<=block_remaining-1'b1;
            state<=S_BLOCK_WRITE_DATA;
          end
        end

        S_BLOCK_READ_REQUEST: begin mem_read_enable<=1; state<=S_BLOCK_WAIT_READ; end
        S_BLOCK_WAIT_READ: if (mem_ready) begin
          response_index<=0; response_length<=1;
          if (mem_error) begin response_0<=RSP_ERROR; send_return_state<=S_IDLE; end
          else begin
            response_0<=mem_read_data;
            if (block_remaining==1) send_return_state<=S_IDLE;
            else begin
              mem_address<=mem_address+1'b1; block_remaining<=block_remaining-1'b1;
              send_return_state<=S_BLOCK_READ_REQUEST;
            end
          end
          state<=S_SEND;
        end

        S_SEND: if (tx_ready) begin
          case (response_index)
            0: tx_data<=response_0;
            1: tx_data<=response_1;
            default: tx_data<=response_2;
          endcase
          tx_strobe<=1;
          if (response_index+1 >= response_length) wait_return_state<=send_return_state;
          else begin response_index<=response_index+1'b1; wait_return_state<=S_SEND; end
          state<=S_WAIT_TX;
        end
        S_WAIT_TX: if (!tx_ready) state<=wait_return_state;
        default: state<=S_IDLE;
      endcase
    end
  end
endmodule

`default_nettype wire
