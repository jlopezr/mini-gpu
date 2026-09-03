`default_nettype none

/*
 * Minimal multicyle MiniCPU v0.1.
 *
 * Implemented instructions:
 *   NOP
 *   MOVI Rd, imm16
 *   ADD/SUB/AND/OR/XOR Rd, Ra, Rb
 *   SHL/SHR/SAR Rd, Ra, Rb
 *   ADDI/ANDI/ORI/XORI Rd, Ra, imm16
 *   MOVHI Rd, imm16
 *   LOAD Rd, Ra, imm16
 *   STORE Rs, Ra, imm16
 *   BEQ/BNE/BLT/BGE/BLTU/BGEU Ra, Rb, offset
 *   BRA offset
 *   GETTID Rd (returns zero in MiniCPU)
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

    output reg dmem_valid,
    output reg [31:0] dmem_address,
    output reg [31:0] dmem_write_data,
    output reg [3:0] dmem_write_enable,
    input [31:0] dmem_read_data,
    input dmem_ready,
    input dmem_error,

    input [4:0] debug_register_address,
    output [31:0] debug_register_data,
    output [31:0] debug_pc
);

  localparam [5:0] OPCODE_NOP = 6'h00;
  localparam [5:0] OPCODE_ADD = 6'h01;
  localparam [5:0] OPCODE_SUB = 6'h02;
  localparam [5:0] OPCODE_MULFX = 6'h03;
  localparam [5:0] OPCODE_AND = 6'h04;
  localparam [5:0] OPCODE_OR = 6'h05;
  localparam [5:0] OPCODE_XOR = 6'h06;
  localparam [5:0] OPCODE_SHL = 6'h07;
  localparam [5:0] OPCODE_SHR = 6'h08;
  localparam [5:0] OPCODE_SAR = 6'h09;
  localparam [5:0] OPCODE_MUL = 6'h0a;
  localparam [5:0] OPCODE_DIV = 6'h0c;
  localparam [5:0] OPCODE_MOVI = 6'h10;
  localparam [5:0] OPCODE_ADDI = 6'h11;
  localparam [5:0] OPCODE_ANDI = 6'h12;
  localparam [5:0] OPCODE_ORI = 6'h13;
  localparam [5:0] OPCODE_XORI = 6'h14;
  localparam [5:0] OPCODE_LOAD = 6'h15;
  localparam [5:0] OPCODE_STORE = 6'h16;
  localparam [5:0] OPCODE_MOVHI = 6'h17;
  localparam [5:0] OPCODE_BEQ = 6'h20;
  localparam [5:0] OPCODE_BNE = 6'h21;
  localparam [5:0] OPCODE_BLT = 6'h22;
  localparam [5:0] OPCODE_BGE = 6'h23;
  localparam [5:0] OPCODE_BLTU = 6'h24;
  localparam [5:0] OPCODE_BGEU = 6'h25;
  localparam [5:0] OPCODE_BRA = 6'h2f;
  localparam [5:0] OPCODE_GETTID = 6'h30;
  localparam [5:0] OPCODE_TRAP = 6'h3e;
  localparam [5:0] OPCODE_HALT = 6'h3f;

  // Errors are terminal in this teaching CPU: there is no exception vector or
  // resume operation. On error, PC is restored to the offending instruction
  // so GET_STATUS provides a useful diagnostic without a separate error-PC
  // register or a wider monitor protocol.
  localparam [7:0] ERROR_NONE = 8'h00;
  localparam [7:0] ERROR_INVALID_OPCODE = 8'h01;
  localparam [7:0] ERROR_MEMORY_ACCESS = 8'h02;
  localparam [7:0] ERROR_EXPLICIT_TRAP = 8'h03;
  localparam [7:0] ERROR_DIVISION_BY_ZERO = 8'h04;
  localparam [7:0] ERROR_INVALID_ENCODING = 8'h05;

  localparam [3:0] STATE_HALTED = 4'd0;
  localparam [3:0] STATE_FETCH_REQUEST = 4'd1;
  localparam [3:0] STATE_FETCH_WAIT = 4'd2;
  localparam [3:0] STATE_EXECUTE = 4'd3;
  localparam [3:0] STATE_RETIRE = 4'd4;
  localparam [3:0] STATE_MEMORY_WAIT = 4'd5;
  localparam [3:0] STATE_DECODE = 4'd6;
  localparam [3:0] STATE_SHIFT_STEP = 4'd7;
  localparam [3:0] STATE_SHIFT_WRITE = 4'd8;
  localparam [3:0] STATE_BRANCH_COMMIT = 4'd9;
  localparam [3:0] STATE_BRANCH_COMPARE = 4'd10;

  reg [3:0] state;
  reg [31:0] pc;
  reg [31:0] instruction;
  reg step_active;
  reg halt_pending;
  reg halt_after_retire;
  reg load_pending;
  reg [4:0] load_destination;
  reg [31:0] operand_a;
  reg [31:0] operand_b;
  reg [31:0] shift_result;
  reg [4:0] shift_destination;
  reg [4:0] shift_remaining;
  reg [1:0] shift_kind;
  reg branch_taken;
  reg [31:0] branch_target;
  reg [32:0] branch_difference;
  reg branch_a_sign;
  reg branch_b_sign;
  reg [2:0] branch_kind;

  wire [5:0] opcode = instruction[31:26];
  wire [4:0] rd = instruction[25:21];
  wire [4:0] ra = instruction[20:16];
  wire [4:0] rb = instruction[15:11];
  wire [31:0] immediate_signed = {{16{instruction[15]}}, instruction[15:0]};
  wire [31:0] immediate_unsigned = {16'h0000, instruction[15:0]};

  // Validate the reserved fields combinationally, then register the result in
  // STATE_DECODE. The register keeps validation logic out of the execute-state
  // control path and was necessary to retain timing closure at 120 MHz.
  reg instruction_encoding_valid;
  reg instruction_encoding_valid_registered;
  always @* begin
    instruction_encoding_valid = 1'b1;
    case (opcode)
      OPCODE_NOP, OPCODE_TRAP, OPCODE_HALT:
        instruction_encoding_valid = instruction[25:0] == 0;
      OPCODE_ADD, OPCODE_SUB, OPCODE_MULFX, OPCODE_AND, OPCODE_OR, OPCODE_XOR,
      OPCODE_SHL, OPCODE_SHR, OPCODE_SAR, OPCODE_MUL, OPCODE_DIV:
        instruction_encoding_valid = instruction[10:0] == 0;
      OPCODE_MOVI, OPCODE_MOVHI:
        instruction_encoding_valid = instruction[20:16] == 0;
      OPCODE_GETTID:
        instruction_encoding_valid = instruction[20:0] == 0;
      default: instruction_encoding_valid = 1'b1;
    endcase
  end

  wire [31:0] register_a;
  wire [31:0] register_b;

  /*
   * STORE takes its source from the Rd field, whereas register-register ALU
   * instructions take their second operand from Rb. Registering this selection
   * during fetch keeps opcode decoding out of the register-file read path.
   * See timing.md, "Selección del segundo operando".
   */
  reg [4:0] register_a_address;
  reg [4:0] register_b_address;
  reg register_write_enable;
  reg [4:0] register_write_address;
  reg [31:0] register_write_data;

  assign debug_pc = pc;

  register_file register_file_i (
      .clk(clk),
      .reset(reset),
      .read_address_a(register_a_address),
      .read_data_a(register_a),
      .read_address_b(register_b_address),
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
      dmem_valid <= 1'b0;
      dmem_address <= 32'h0000_0000;
      dmem_write_data <= 32'h0000_0000;
      dmem_write_enable <= 4'b0000;
      load_pending <= 1'b0;
      load_destination <= 5'd0;
      operand_a <= 32'h0000_0000;
      operand_b <= 32'h0000_0000;
      shift_result <= 32'h0000_0000;
      shift_destination <= 5'd0;
      shift_remaining <= 5'd0;
      shift_kind <= 2'd0;
      branch_taken <= 1'b0;
      branch_target <= 32'h0000_0000;
      branch_difference <= 33'h0;
      branch_a_sign <= 1'b0;
      branch_b_sign <= 1'b0;
      branch_kind <= 3'd0;
      register_a_address <= 5'd0;
      register_b_address <= 5'd0;
      register_write_enable <= 1'b0;
      register_write_address <= 5'd0;
      register_write_data <= 32'h0000_0000;
      instruction_encoding_valid_registered <= 1'b1;
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
            // Conditional branches encode their operands in X/Y rather than
            // the Ra/Rb fields used by R-type instructions.
            if (imem_read_data[31:26] >= OPCODE_BEQ &&
                imem_read_data[31:26] <= OPCODE_BGEU) begin
              register_a_address <= imem_read_data[25:21];
              register_b_address <= imem_read_data[20:16];
            end else begin
              register_a_address <= imem_read_data[20:16];
              register_b_address <=
                  imem_read_data[31:26] == OPCODE_STORE ?
                      imem_read_data[25:21] : imem_read_data[15:11];
            end
            imem_valid <= 1'b0;
            pc <= pc + 3'd4;
            state <= STATE_DECODE;
          end
        end

        /*
         * Register the operands before the ALU. This is an extra cycle in the
         * multicyle CPU, not instruction pipelining. It breaks the long path
         * from the asynchronous register-file mux through the 32-bit adder.
         */
        STATE_DECODE: begin
          operand_a <= register_a;
          operand_b <= register_b;
          instruction_encoding_valid_registered <= instruction_encoding_valid;
          state <= STATE_EXECUTE;
        end

        STATE_EXECUTE: begin
          halt_after_retire <= 1'b0;

          if (!instruction_encoding_valid_registered) begin
            halted <= 1'b1;
            error <= 1'b1;
            error_code <= ERROR_INVALID_ENCODING;
            // Fetch has already advanced PC, so restore the faulting address.
            pc <= pc - 3'd4;
            state <= STATE_HALTED;
          end else case (opcode)
            OPCODE_NOP: begin
              state <= STATE_RETIRE;
            end

            OPCODE_MOVI: begin
              register_write_address <= rd;
              register_write_data <= immediate_signed;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_ADD: begin
              register_write_address <= rd;
              register_write_data <= operand_a + operand_b;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_SUB: begin
              register_write_address <= rd;
              register_write_data <= operand_a - operand_b;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_AND: begin
              register_write_address <= rd;
              register_write_data <= operand_a & operand_b;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_OR: begin
              register_write_address <= rd;
              register_write_data <= operand_a | operand_b;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_XOR: begin
              register_write_address <= rd;
              register_write_data <= operand_a ^ operand_b;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_SHL: begin
              shift_destination <= rd;
              shift_result <= operand_a;
              shift_remaining <= operand_b[4:0];
              shift_kind <= 2'd0;
              state <= operand_b[4:0] == 0 ? STATE_SHIFT_WRITE : STATE_SHIFT_STEP;
            end

            OPCODE_SHR: begin
              shift_destination <= rd;
              shift_result <= operand_a;
              shift_remaining <= operand_b[4:0];
              shift_kind <= 2'd1;
              state <= operand_b[4:0] == 0 ? STATE_SHIFT_WRITE : STATE_SHIFT_STEP;
            end

            OPCODE_SAR: begin
              shift_destination <= rd;
              shift_result <= operand_a;
              shift_remaining <= operand_b[4:0];
              shift_kind <= 2'd2;
              state <= operand_b[4:0] == 0 ? STATE_SHIFT_WRITE : STATE_SHIFT_STEP;
            end

            OPCODE_ADDI: begin
              register_write_address <= rd;
              register_write_data <= operand_a + immediate_signed;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_ANDI: begin
              register_write_address <= rd;
              register_write_data <= operand_a & immediate_unsigned;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_ORI: begin
              register_write_address <= rd;
              register_write_data <= operand_a | immediate_unsigned;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_XORI: begin
              register_write_address <= rd;
              register_write_data <= operand_a ^ immediate_unsigned;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_MOVHI: begin
              register_write_address <= rd;
              register_write_data <= {instruction[15:0], 16'h0000};
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_GETTID: begin
              register_write_address <= rd;
              register_write_data <= 32'h0000_0000;
              register_write_enable <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_BEQ: begin
              branch_difference <= {1'b0, operand_a} - {1'b0, operand_b};
              branch_a_sign <= operand_a[31];
              branch_b_sign <= operand_b[31];
              branch_kind <= 3'd0;
              branch_target <= pc + {{14{instruction[15]}}, instruction[15:0], 2'b00};
              state <= STATE_BRANCH_COMPARE;
            end

            OPCODE_BNE: begin
              branch_difference <= {1'b0, operand_a} - {1'b0, operand_b};
              branch_a_sign <= operand_a[31];
              branch_b_sign <= operand_b[31];
              branch_kind <= 3'd1;
              branch_target <= pc + {{14{instruction[15]}}, instruction[15:0], 2'b00};
              state <= STATE_BRANCH_COMPARE;
            end

            OPCODE_BLT: begin
              branch_difference <= {1'b0, operand_a} - {1'b0, operand_b};
              branch_a_sign <= operand_a[31];
              branch_b_sign <= operand_b[31];
              branch_kind <= 3'd2;
              branch_target <= pc + {{14{instruction[15]}}, instruction[15:0], 2'b00};
              state <= STATE_BRANCH_COMPARE;
            end

            OPCODE_BGE: begin
              branch_difference <= {1'b0, operand_a} - {1'b0, operand_b};
              branch_a_sign <= operand_a[31];
              branch_b_sign <= operand_b[31];
              branch_kind <= 3'd3;
              branch_target <= pc + {{14{instruction[15]}}, instruction[15:0], 2'b00};
              state <= STATE_BRANCH_COMPARE;
            end

            OPCODE_BLTU: begin
              branch_difference <= {1'b0, operand_a} - {1'b0, operand_b};
              branch_a_sign <= operand_a[31];
              branch_b_sign <= operand_b[31];
              branch_kind <= 3'd4;
              branch_target <= pc + {{14{instruction[15]}}, instruction[15:0], 2'b00};
              state <= STATE_BRANCH_COMPARE;
            end

            OPCODE_BGEU: begin
              branch_difference <= {1'b0, operand_a} - {1'b0, operand_b};
              branch_a_sign <= operand_a[31];
              branch_b_sign <= operand_b[31];
              branch_kind <= 3'd5;
              branch_target <= pc + {{14{instruction[15]}}, instruction[15:0], 2'b00};
              state <= STATE_BRANCH_COMPARE;
            end

            OPCODE_BRA: begin
              branch_taken <= 1'b1;
              branch_target <= pc + {{4{instruction[25]}}, instruction[25:0], 2'b00};
              state <= STATE_BRANCH_COMMIT;
            end

            OPCODE_LOAD: begin
              dmem_address <= operand_a + immediate_signed;
              dmem_write_enable <= 4'b0000;
              dmem_valid <= 1'b1;
              load_pending <= 1'b1;
              load_destination <= rd;
              state <= STATE_MEMORY_WAIT;
            end

            OPCODE_STORE: begin
              dmem_address <= operand_a + immediate_signed;
              dmem_write_data <= operand_b;
              dmem_write_enable <= 4'b1111;
              dmem_valid <= 1'b1;
              load_pending <= 1'b0;
              state <= STATE_MEMORY_WAIT;
            end

            OPCODE_HALT: begin
              halt_after_retire <= 1'b1;
              state <= STATE_RETIRE;
            end

            OPCODE_TRAP: begin
              halted <= 1'b1;
              error <= 1'b1;
              error_code <= ERROR_EXPLICIT_TRAP;
              // TRAP is a terminal diagnostic stop, not a retired HALT.
              pc <= pc - 3'd4;
              state <= STATE_HALTED;
            end

            default: begin
              halted <= 1'b1;
              error <= 1'b1;
              error_code <= ERROR_INVALID_OPCODE;
              pc <= pc - 3'd4;
              state <= STATE_HALTED;
            end
          endcase
        end

        STATE_MEMORY_WAIT: begin
          if (dmem_valid && dmem_ready) begin
            dmem_valid <= 1'b0;
            dmem_write_enable <= 4'b0000;

            if (dmem_error) begin
              halted <= 1'b1;
              error <= 1'b1;
              error_code <= ERROR_MEMORY_ACCESS;
              pc <= pc - 3'd4;
              state <= STATE_HALTED;
            end else begin
              if (load_pending) begin
                register_write_address <= load_destination;
                register_write_data <= dmem_read_data;
                register_write_enable <= 1'b1;
              end

              load_pending <= 1'b0;
              state <= STATE_RETIRE;
            end
          end
        end

        // Iterative one-bit shifter: it uses little logic and avoids a large
        // barrel shifter on the 120 MHz datapath. Shifts take 1..31 extra cycles.
        STATE_SHIFT_STEP: begin
          case (shift_kind)
            2'd0: shift_result <= shift_result << 1;
            2'd1: shift_result <= shift_result >> 1;
            default: shift_result <= $signed(shift_result) >>> 1;
          endcase
          shift_remaining <= shift_remaining - 1'b1;
          if (shift_remaining == 1)
            state <= STATE_SHIFT_WRITE;
        end

        STATE_SHIFT_WRITE: begin
          register_write_address <= shift_destination;
          register_write_data <= shift_result;
          register_write_enable <= 1'b1;
          state <= STATE_RETIRE;
        end

        // All comparisons reuse one registered subtraction. For signed values,
        // differing operand signs decide directly; otherwise diff[31] does.
        STATE_BRANCH_COMPARE: begin
          case (branch_kind)
            3'd0: branch_taken <= branch_difference[31:0] == 0;
            3'd1: branch_taken <= branch_difference[31:0] != 0;
            3'd2: branch_taken <=
                branch_a_sign != branch_b_sign ? branch_a_sign : branch_difference[31];
            3'd3: branch_taken <=
                !(branch_a_sign != branch_b_sign ? branch_a_sign : branch_difference[31]);
            3'd4: branch_taken <= branch_difference[32];
            default: branch_taken <= !branch_difference[32];
          endcase
          state <= STATE_BRANCH_COMMIT;
        end

        // Comparison and target calculation are registered before modifying PC.
        STATE_BRANCH_COMMIT: begin
          if (branch_taken)
            pc <= branch_target;
          state <= STATE_RETIRE;
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
