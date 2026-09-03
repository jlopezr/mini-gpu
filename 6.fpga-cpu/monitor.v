`default_nettype none

/*
 * Minimal UART monitor protocol.
 *
 * Requests and responses:
 *   01             (PING)        -> 81
 *   02             (GET_VERSION) -> 82 01 00
 *   10 A3 A2 A1 A0 DD          (WRITE_BYTE)  -> 90 (or ff)
 *   11 A3 A2 A1 A0             (READ_BYTE)   -> 91 DD (or ff)
 *   20 A3 A2 A1 A0 LL LL DD... (WRITE_BLOCK) -> a0 (or ff)
 *   21 A3 A2 A1 A0 LL LL       (READ_BLOCK)  -> a1 DD... (or ff)
 *   30             (RUN)         -> b0 (or ff)
 *   31             (HALT)        -> b1
 *   32             (STEP)        -> b2 (or ff)
 *   33             (GET_STATUS)  -> b3 FLAGS ERROR PC3 PC2 PC1 PC0
 *   34 RR          (READ_REG)    -> b4 D3 D2 D1 D0 (or ff)
 *   any other command            -> ff
 *
 * Addresses and lengths are transferred most-significant byte first. Block
 * lengths must be between 1 and 256 bytes. The memory reports invalid ranges.
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
    output reg [31:0] mem_address,
    output reg [7:0] mem_write_data,
    output reg mem_write_enable,
    output reg mem_read_enable,
    input [7:0] mem_read_data,
    input mem_ready,
    input mem_error,

    output reg cpu_run_request,
    output reg cpu_halt_request,
    output reg cpu_step_request,
    input cpu_halted,
    input cpu_error,
    input [7:0] cpu_error_code,
    input [31:0] cpu_pc,
    output reg [4:0] cpu_debug_register_address,
    input [31:0] cpu_debug_register_data,

    output reg [7:0] last_command,
    output busy
);

  localparam [7:0] CMD_PING = 8'h01;
  localparam [7:0] CMD_GET_VERSION = 8'h02;
  localparam [7:0] CMD_WRITE_BYTE = 8'h10;
  localparam [7:0] CMD_READ_BYTE = 8'h11;
  localparam [7:0] CMD_WRITE_BLOCK = 8'h20;
  localparam [7:0] CMD_READ_BLOCK = 8'h21;
  localparam [7:0] CMD_RUN = 8'h30;
  localparam [7:0] CMD_HALT = 8'h31;
  localparam [7:0] CMD_STEP = 8'h32;
  localparam [7:0] CMD_GET_STATUS = 8'h33;
  localparam [7:0] CMD_READ_REGISTER = 8'h34;
  localparam [7:0] RSP_PONG = 8'h81;
  localparam [7:0] RSP_VERSION = 8'h82;
  localparam [7:0] RSP_WRITE_BYTE = 8'h90;
  localparam [7:0] RSP_READ_BYTE = 8'h91;
  localparam [7:0] RSP_WRITE_BLOCK = 8'ha0;
  localparam [7:0] RSP_READ_BLOCK = 8'ha1;
  localparam [7:0] RSP_RUN = 8'hb0;
  localparam [7:0] RSP_HALT = 8'hb1;
  localparam [7:0] RSP_STEP = 8'hb2;
  localparam [7:0] RSP_STATUS = 8'hb3;
  localparam [7:0] RSP_READ_REGISTER = 8'hb4;
  localparam [7:0] RSP_ERROR = 8'hff;
  localparam [7:0] VERSION_MAJOR = 8'h01;
  localparam [7:0] VERSION_MINOR = 8'h01;

  localparam [4:0] STATE_IDLE = 5'd0;
  localparam [4:0] STATE_WRITE_ADDRESS_HIGH = 5'd1;
  localparam [4:0] STATE_WRITE_ADDRESS_LOW = 5'd2;
  localparam [4:0] STATE_WRITE_DATA = 5'd3;
  localparam [4:0] STATE_WAIT_WRITE = 5'd4;
  localparam [4:0] STATE_READ_ADDRESS_HIGH = 5'd5;
  localparam [4:0] STATE_READ_ADDRESS_LOW = 5'd6;
  localparam [4:0] STATE_WAIT_READ = 5'd7;
  localparam [4:0] STATE_RESPOND = 5'd8;
  localparam [4:0] STATE_WAIT_TX_ACCEPT = 5'd9;
  localparam [4:0] STATE_BLOCK_ADDRESS_HIGH = 5'd10;
  localparam [4:0] STATE_BLOCK_ADDRESS_LOW = 5'd11;
  localparam [4:0] STATE_BLOCK_LENGTH_HIGH = 5'd12;
  localparam [4:0] STATE_BLOCK_LENGTH_LOW = 5'd13;
  localparam [4:0] STATE_BLOCK_WRITE_DATA = 5'd14;
  localparam [4:0] STATE_BLOCK_WAIT_WRITE = 5'd15;
  localparam [4:0] STATE_BLOCK_READ_REQUEST = 5'd16;
  localparam [4:0] STATE_BLOCK_WAIT_READ = 5'd17;
  localparam [4:0] STATE_PREPARE_READ = 5'd18;
  localparam [4:0] STATE_BLOCK_PREPARE_READ = 5'd19;
  localparam [4:0] STATE_WRITE_ADDRESS_2 = 5'd20;
  localparam [4:0] STATE_WRITE_ADDRESS_1 = 5'd21;
  localparam [4:0] STATE_READ_ADDRESS_2 = 5'd22;
  localparam [4:0] STATE_READ_ADDRESS_1 = 5'd23;
  localparam [4:0] STATE_BLOCK_ADDRESS_2 = 5'd24;
  localparam [4:0] STATE_BLOCK_ADDRESS_1 = 5'd25;
  localparam [4:0] STATE_READ_REGISTER_ADDRESS = 5'd26;
  localparam [4:0] STATE_PREPARE_REGISTER = 5'd27;
  localparam [4:0] STATE_WAIT_REGISTER_1 = 5'd28;
  localparam [4:0] STATE_WAIT_REGISTER_2 = 5'd29;

  reg [4:0] state;
  reg [4:0] state_after_tx;
  reg [4:0] response_done_state;
  reg block_is_write;
  reg [15:0] block_length;
  reg [15:0] block_remaining;
  reg [7:0] mem_read_data_latched;
  reg mem_error_latched;
  reg [2:0] response_index;
  reg [2:0] response_length;
  reg [7:0] response_byte_0;
  reg [7:0] response_byte_1;
  reg [7:0] response_byte_2;
  reg [7:0] response_byte_3;
  reg [7:0] response_byte_4;
  reg [7:0] response_byte_5;
  reg [7:0] response_byte_6;

  assign busy = (state != STATE_IDLE);

  always @(posedge clk) begin
    tx_strobe <= 1'b0;
    mem_write_enable <= 1'b0;
    mem_read_enable <= 1'b0;
    cpu_run_request <= 1'b0;
    cpu_halt_request <= 1'b0;
    cpu_step_request <= 1'b0;

    if (reset) begin
      tx_data <= 8'h00;
      tx_strobe <= 1'b0;
      mem_address <= 32'h0000_0000;
      mem_write_data <= 8'h00;
      mem_write_enable <= 1'b0;
      mem_read_enable <= 1'b0;
      cpu_run_request <= 1'b0;
      cpu_halt_request <= 1'b0;
      cpu_step_request <= 1'b0;
      cpu_debug_register_address <= 5'd0;
      last_command <= 8'h00;
      state <= STATE_IDLE;
      state_after_tx <= STATE_IDLE;
      response_done_state <= STATE_IDLE;
      block_is_write <= 1'b0;
      block_length <= 16'd0;
      block_remaining <= 16'd0;
      mem_read_data_latched <= 8'h00;
      mem_error_latched <= 1'b0;
      response_index <= 2'd0;
      response_length <= 2'd0;
      response_byte_0 <= 8'h00;
      response_byte_1 <= 8'h00;
      response_byte_2 <= 8'h00;
      response_byte_3 <= 8'h00;
      response_byte_4 <= 8'h00;
      response_byte_5 <= 8'h00;
      response_byte_6 <= 8'h00;
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
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              CMD_GET_VERSION: begin
                response_byte_0 <= RSP_VERSION;
                response_byte_1 <= VERSION_MAJOR;
                response_byte_2 <= VERSION_MINOR;
                response_length <= 2'd3;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              CMD_WRITE_BYTE: state <= STATE_WRITE_ADDRESS_HIGH;
              CMD_READ_BYTE: state <= STATE_READ_ADDRESS_HIGH;
              CMD_WRITE_BLOCK: begin
                block_is_write <= 1'b1;
                state <= STATE_BLOCK_ADDRESS_HIGH;
              end
              CMD_READ_BLOCK: begin
                block_is_write <= 1'b0;
                state <= STATE_BLOCK_ADDRESS_HIGH;
              end
              CMD_RUN: begin
                response_byte_0 <= cpu_halted ? RSP_RUN : RSP_ERROR;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                if (cpu_halted) cpu_run_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              CMD_HALT: begin
                response_byte_0 <= RSP_HALT;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                cpu_halt_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              CMD_STEP: begin
                response_byte_0 <= cpu_halted ? RSP_STEP : RSP_ERROR;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                if (cpu_halted) cpu_step_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              CMD_GET_STATUS: begin
                response_byte_0 <= RSP_STATUS;
                response_byte_1 <= {6'b000000, cpu_error, cpu_halted};
                response_byte_2 <= cpu_error_code;
                response_byte_3 <= cpu_pc[31:24];
                response_byte_4 <= cpu_pc[23:16];
                response_byte_5 <= cpu_pc[15:8];
                response_byte_6 <= cpu_pc[7:0];
                response_length <= 3'd7;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              CMD_READ_REGISTER: state <= STATE_READ_REGISTER_ADDRESS;
              default: begin
                response_byte_0 <= RSP_ERROR;
                response_length <= 2'd1;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
            endcase
          end
        end

        STATE_READ_REGISTER_ADDRESS: begin
          if (rx_strobe) begin
            if (rx_data[7:5] != 3'b000 || !cpu_halted) begin
              response_byte_0 <= RSP_ERROR;
              response_length <= 3'd1;
              response_index <= 3'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else begin
              cpu_debug_register_address <= rx_data[4:0];
              state <= STATE_WAIT_REGISTER_1;
            end
          end
        end

        STATE_WAIT_REGISTER_1: state <= STATE_WAIT_REGISTER_2;
        STATE_WAIT_REGISTER_2: state <= STATE_PREPARE_REGISTER;

        STATE_PREPARE_REGISTER: begin
          response_byte_0 <= RSP_READ_REGISTER;
          response_byte_1 <= cpu_debug_register_data[31:24];
          response_byte_2 <= cpu_debug_register_data[23:16];
          response_byte_3 <= cpu_debug_register_data[15:8];
          response_byte_4 <= cpu_debug_register_data[7:0];
          response_length <= 3'd5;
          response_index <= 3'd0;
          response_done_state <= STATE_IDLE;
          state <= STATE_RESPOND;
        end

        STATE_WRITE_ADDRESS_HIGH: begin
          if (rx_strobe) begin
            mem_address[31:24] <= rx_data;
            state <= STATE_WRITE_ADDRESS_2;
          end
        end
        STATE_WRITE_ADDRESS_2: begin
          if (rx_strobe) begin
            mem_address[23:16] <= rx_data;
            state <= STATE_WRITE_ADDRESS_1;
          end
        end
        STATE_WRITE_ADDRESS_1: begin
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
            mem_write_data <= rx_data;
            mem_write_enable <= 1'b1;
            state <= STATE_WAIT_WRITE;
          end
        end
        STATE_WAIT_WRITE: begin
          if (mem_ready) begin
            response_byte_0 <= mem_error ? RSP_ERROR : RSP_WRITE_BYTE;
            response_length <= 2'd1;
            response_index <= 2'd0;
            response_done_state <= STATE_IDLE;
            state <= STATE_RESPOND;
          end
        end

        STATE_READ_ADDRESS_HIGH: begin
          if (rx_strobe) begin
            mem_address[31:24] <= rx_data;
            state <= STATE_READ_ADDRESS_2;
          end
        end
        STATE_READ_ADDRESS_2: begin
          if (rx_strobe) begin
            mem_address[23:16] <= rx_data;
            state <= STATE_READ_ADDRESS_1;
          end
        end
        STATE_READ_ADDRESS_1: begin
          if (rx_strobe) begin
            mem_address[15:8] <= rx_data;
            state <= STATE_READ_ADDRESS_LOW;
          end
        end
        STATE_READ_ADDRESS_LOW: begin
          if (rx_strobe) begin
            mem_address[7:0] <= rx_data;
            mem_read_enable <= 1'b1;
            state <= STATE_WAIT_READ;
          end
        end
        STATE_WAIT_READ: begin
          if (mem_ready) begin
            // Deliberate pipeline stage: register the RAM output before using it
            // to build the UART response. Without this extra cycle, the path from
            // block RAM through the response-selection logic failed timing at
            // 120 MHz. Review STATE_PREPARE_READ to understand this boundary.
            mem_read_data_latched <= mem_read_data;
            mem_error_latched <= mem_error;
            state <= STATE_PREPARE_READ;
          end
        end
        STATE_PREPARE_READ: begin
          response_byte_0 <= mem_error_latched ? RSP_ERROR : RSP_READ_BYTE;
          response_byte_1 <= mem_read_data_latched;
          response_length <= mem_error_latched ? 2'd1 : 2'd2;
          response_index <= 2'd0;
          response_done_state <= STATE_IDLE;
          state <= STATE_RESPOND;
        end

        STATE_BLOCK_ADDRESS_HIGH: begin
          if (rx_strobe) begin
            mem_address[31:24] <= rx_data;
            state <= STATE_BLOCK_ADDRESS_2;
          end
        end
        STATE_BLOCK_ADDRESS_2: begin
          if (rx_strobe) begin
            mem_address[23:16] <= rx_data;
            state <= STATE_BLOCK_ADDRESS_1;
          end
        end
        STATE_BLOCK_ADDRESS_1: begin
          if (rx_strobe) begin
            mem_address[15:8] <= rx_data;
            state <= STATE_BLOCK_ADDRESS_LOW;
          end
        end
        STATE_BLOCK_ADDRESS_LOW: begin
          if (rx_strobe) begin
            mem_address[7:0] <= rx_data;
            state <= STATE_BLOCK_LENGTH_HIGH;
          end
        end
        STATE_BLOCK_LENGTH_HIGH: begin
          if (rx_strobe) begin
            block_length[15:8] <= rx_data;
            state <= STATE_BLOCK_LENGTH_LOW;
          end
        end
        STATE_BLOCK_LENGTH_LOW: begin
          if (rx_strobe) begin
            block_length[7:0] <= rx_data;
            block_remaining <= {block_length[15:8], rx_data};

            if ({block_length[15:8], rx_data} == 0 ||
                {block_length[15:8], rx_data} > 16'd256 ||
                (mem_address[31:14] != 18'h00000 &&
                    mem_address[31:14] != 18'h00040) ||
                ({1'b0, mem_address[13:0]} +
                    {6'd0, block_length[8], rx_data}) > 15'h4000) begin
              response_byte_0 <= RSP_ERROR;
              response_length <= 2'd1;
              response_index <= 2'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else if (block_is_write) begin
              state <= STATE_BLOCK_WRITE_DATA;
            end else begin
              response_byte_0 <= RSP_READ_BLOCK;
              response_length <= 2'd1;
              response_index <= 2'd0;
              response_done_state <= STATE_BLOCK_READ_REQUEST;
              state <= STATE_RESPOND;
            end
          end
        end
        STATE_BLOCK_WRITE_DATA: begin
          if (rx_strobe) begin
            mem_write_data <= rx_data;
            mem_write_enable <= 1'b1;
            state <= STATE_BLOCK_WAIT_WRITE;
          end
        end
        STATE_BLOCK_WAIT_WRITE: begin
          if (mem_ready) begin
            if (mem_error) begin
              response_byte_0 <= RSP_ERROR;
              response_length <= 2'd1;
              response_index <= 2'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else if (block_remaining == 1) begin
              response_byte_0 <= RSP_WRITE_BLOCK;
              response_length <= 2'd1;
              response_index <= 2'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else begin
              mem_address <= mem_address + 1'b1;
              block_remaining <= block_remaining - 1'b1;
              state <= STATE_BLOCK_WRITE_DATA;
            end
          end
        end
        STATE_BLOCK_READ_REQUEST: begin
          mem_read_enable <= 1'b1;
          state <= STATE_BLOCK_WAIT_READ;
        end
        STATE_BLOCK_WAIT_READ: begin
          if (mem_ready) begin
            // The block-read path uses the same intentional RAM-output register.
            // Review STATE_BLOCK_PREPARE_READ when studying the read pipeline.
            mem_read_data_latched <= mem_read_data;
            mem_error_latched <= mem_error;
            state <= STATE_BLOCK_PREPARE_READ;
          end
        end
        STATE_BLOCK_PREPARE_READ: begin
          response_byte_0 <= mem_error_latched ? RSP_ERROR : mem_read_data_latched;
          response_length <= 2'd1;
          response_index <= 2'd0;

          if (mem_error_latched || block_remaining == 1) begin
            response_done_state <= STATE_IDLE;
          end else begin
            mem_address <= mem_address + 1'b1;
            block_remaining <= block_remaining - 1'b1;
            response_done_state <= STATE_BLOCK_READ_REQUEST;
          end
          state <= STATE_RESPOND;
        end

        STATE_RESPOND: begin
          if (tx_ready) begin
            case (response_index)
              2'd0: tx_data <= response_byte_0;
              2'd1: tx_data <= response_byte_1;
              2'd2: tx_data <= response_byte_2;
              3'd3: tx_data <= response_byte_3;
              3'd4: tx_data <= response_byte_4;
              3'd5: tx_data <= response_byte_5;
              default: tx_data <= response_byte_6;
            endcase

            tx_strobe <= 1'b1;
            if (response_index + 1 >= response_length) begin
              state_after_tx <= response_done_state;
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
