`default_nettype none

/*
 * Minimal multicyle MiniCPU v0.1.
 *
 * Implemented instructions:
 *   MOVI Rd, imm16
 *   ADD  Rd, Ra, Rb
 *   HALT
 *
 * The CPU starts halted after reset. run_request starts continuous execution;
 * step_request retires one instruction and stops again. halt_request is latched
 * and honored only after the current instruction has retired.
 */
module cpu (
    input clk,
    input reset,

    input run_request,
    input halt_request,
    input step_request,

    output reg halted,
    output reg error,
    output reg [7:0] error_code,
    output reg instruction_retired,

    output reg imem_valid,
    output reg [31:0] imem_address,
    input [31:0] imem_read_data,
    input imem_ready,

    input [4:0] debug_register_address,
    output [31:0] debug_register_data,
    output [31:0] debug_pc
);

  localparam [5:0] OPCODE_ADD = 6'h01;
  localparam [5:0] OPCODE_MOVI = 6'h10;
  localparam [5:0] OPCODE_HALT = 6'h3f;

  localparam [7:0] ERROR_NONE = 8'h00;
  localparam [7:0] ERROR_INVALID_OPCODE = 8'h01;

  localparam [2:0] STATE_HALTED = 3'd0;
  localparam [2:0] STATE_FETCH_REQUEST = 3'd1;
  localparam [2:0] STATE_FETCH_WAIT = 3'd2;
  localparam [2:0] STATE_EXECUTE = 3'd3;
  localparam [2:0] STATE_RETIRE = 3'd4;

  reg [2:0] state;
  reg [31:0] pc;
  reg [31:0] instruction;
  reg step_active;
  reg halt_pending;
  reg halt_after_retire;

  wire [5:0] opcode = instruction[31:26];
  wire [4:0] rd = instruction[25:21];
  wire [4:0] ra = instruction[20:16];
  wire [4:0] rb = instruction[15:11];
  wire [31:0] immediate_signed = {{16{instruction[15]}}, instruction[15:0]};

  wire [31:0] register_a;
  wire [31:0] register_b;
  reg register_write_enable;
  reg [4:0] register_write_address;
  reg [31:0] register_write_data;

  assign debug_pc = pc;

  register_file register_file_i (
      .clk(clk),
      .reset(reset),
      .read_address_a(ra),
      .read_data_a(register_a),
      .read_address_b(rb),
      .read_data_b(register_b),
      .write_enable(register_write_enable),
      .write_address(register_write_address),
      .write_data(register_write_data),
      .debug_address(debug_register_address),
      .debug_data(debug_register_data)
  );

  always @(posedge clk) begin
    register_write_enable <= 1'b0;
    instruction_retired <= 1'b0;

    if (reset) begin
      state <= STATE_HALTED;
      pc <= 32'h0000_0000;
      instruction <= 32'h0000_0000;
      step_active <= 1'b0;
      halt_pending <= 1'b0;
      halt_after_retire <= 1'b0;
      halted <= 1'b1;
      error <= 1'b0;
      error_code <= ERROR_NONE;
      imem_valid <= 1'b0;
      imem_address <= 32'h0000_0000;
      register_write_enable <= 1'b0;
      register_write_address <= 5'd0;
      register_write_data <= 32'h0000_0000;
    end else begin
      if (halt_request && state != STATE_HALTED) begin
        halt_pending <= 1'b1;
      end

      case (state)
        STATE_HALTED: begin
          imem_valid <= 1'b0;
          halt_pending <= 1'b0;

          if (run_request) begin
            halted <= 1'b0;
            step_active <= 1'b0;
            state <= STATE_FETCH_REQUEST;
          end else if (step_request) begin
            halted <= 1'b0;
            step_active <= 1'b1;
            state <= STATE_FETCH_REQUEST;
          end
        end

        STATE_FETCH_REQUEST: begin
          imem_address <= pc;
          imem_valid <= 1'b1;
          state <= STATE_FETCH_WAIT;
        end

        STATE_FETCH_WAIT: begin
          if (imem_valid && imem_ready) begin
            instruction <= imem_read_data;
            imem_valid <= 1'b0;
            pc <= pc + 3'd4;
            state <= STATE_EXECUTE;
          end
        end

        STATE_EXECUTE: begin
          halt_after_retire <= 1'b0;

          case (opcode)
            OPCODE_MOVI: begin
              register_write_address <= rd;
              register_write_data <= immediate_signed;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_ADD: begin
              register_write_address <= rd;
              register_write_data <= register_a + register_b;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_HALT: begin
              halt_after_retire <= 1'b1;
              state <= STATE_RETIRE;
            end

            default: begin
              halted <= 1'b1;
              error <= 1'b1;
              error_code <= ERROR_INVALID_OPCODE;
              state <= STATE_HALTED;
            end
          endcase
        end

        STATE_RETIRE: begin
          instruction_retired <= 1'b1;

          if (halt_after_retire || step_active || halt_pending || halt_request) begin
            halted <= 1'b1;
            step_active <= 1'b0;
            halt_pending <= 1'b0;
            state <= STATE_HALTED;
          end else begin
            state <= STATE_FETCH_REQUEST;
          end
        end

        default: begin
          halted <= 1'b1;
          error <= 1'b1;
          error_code <= ERROR_INVALID_OPCODE;
          imem_valid <= 1'b0;
          state <= STATE_HALTED;
        end
      endcase
    end
  end
endmodule

`default_nettype wire
