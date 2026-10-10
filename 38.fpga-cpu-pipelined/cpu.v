`default_nettype none

/*
 * Experimental pipelined MiniCPU.
 *
 * This prototype keeps the monitor-facing contract of the multicycle CPU:
 * reset starts halted, RUN starts free-running execution, STEP retires exactly
 * one instruction, and errors leave the architectural PC on the faulting
 * instruction. The pipeline is deliberately conservative: it can accept one
 * independent instruction per cycle, while RAW hazards, memory waits and long
 * control events insert bubbles.
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
  localparam [5:0] OPCODE_MULHI = 6'h0b;
  localparam [5:0] OPCODE_DIV = 6'h0c;
  localparam [5:0] OPCODE_DIVU = 6'h0d;
  localparam [5:0] OPCODE_REM = 6'h0e;
  localparam [5:0] OPCODE_REMU = 6'h0f;
  localparam [5:0] OPCODE_MOVI = 6'h10;
  localparam [5:0] OPCODE_ADDI = 6'h11;
  localparam [5:0] OPCODE_ANDI = 6'h12;
  localparam [5:0] OPCODE_ORI = 6'h13;
  localparam [5:0] OPCODE_XORI = 6'h14;
  localparam [5:0] OPCODE_LOAD = 6'h15;
  localparam [5:0] OPCODE_STORE = 6'h16;
  localparam [5:0] OPCODE_MOVHI = 6'h17;
  localparam [5:0] OPCODE_LOADB = 6'h18;
  localparam [5:0] OPCODE_LOADUB = 6'h19;
  localparam [5:0] OPCODE_STOREB = 6'h1a;
  localparam [5:0] OPCODE_LOADH = 6'h1b;
  localparam [5:0] OPCODE_LOADUH = 6'h1c;
  localparam [5:0] OPCODE_STOREH = 6'h1d;
  localparam [5:0] OPCODE_BEQ = 6'h20;
  localparam [5:0] OPCODE_BNE = 6'h21;
  localparam [5:0] OPCODE_BLT = 6'h22;
  localparam [5:0] OPCODE_BGE = 6'h23;
  localparam [5:0] OPCODE_BLTU = 6'h24;
  localparam [5:0] OPCODE_BGEU = 6'h25;
  localparam [5:0] OPCODE_SLT = 6'h26;
  localparam [5:0] OPCODE_SLTU = 6'h27;
  localparam [5:0] OPCODE_JAL = 6'h2c;
  localparam [5:0] OPCODE_JALR = 6'h2d;
  localparam [5:0] OPCODE_JR = 6'h2e;
  localparam [5:0] OPCODE_BRA = 6'h2f;
  localparam [5:0] OPCODE_GETTID = 6'h30;
  localparam [5:0] OPCODE_SSY = 6'h31;
  localparam [5:0] OPCODE_BAR = 6'h32;
  localparam [5:0] OPCODE_TRAP = 6'h3e;
  localparam [5:0] OPCODE_HALT = 6'h3f;

  localparam [7:0] ERROR_NONE = 8'h00;
  localparam [7:0] ERROR_INVALID_OPCODE = 8'h01;
  localparam [7:0] ERROR_MEMORY_ACCESS = 8'h02;
  localparam [7:0] ERROR_EXPLICIT_TRAP = 8'h03;
  localparam [7:0] ERROR_DIVISION_BY_ZERO = 8'h04;
  localparam [7:0] ERROR_INVALID_ENCODING = 8'h05;

  parameter ALU_FAST_PATH = 1'b1;
  wire unused_alu_fast_path = ALU_FAST_PATH;

  localparam [2:0] OPCLASS_NORMAL = 3'd0;
  localparam [2:0] OPCLASS_LOAD = 3'd1;
  localparam [2:0] OPCLASS_STORE = 3'd2;
  localparam [2:0] OPCLASS_BRANCH = 3'd3;
  localparam [2:0] OPCLASS_ERROR = 3'd4;

  reg running;
  reg step_active;
  reg halt_pending;
  reg [31:0] architectural_pc;
  reg [31:0] fetch_request_pc;

  assign debug_pc = architectural_pc;

  wire [31:0] register_a;
  wire [31:0] register_b;
  reg [4:0] register_a_address;
  reg [4:0] register_b_address;
  reg register_write_enable;
  reg [4:0] register_write_address;
  reg [31:0] register_write_data;

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

  reg if_valid;
  reg [31:0] if_pc;
  reg [31:0] if_instruction;

  reg id_valid;
  reg [31:0] id_pc;
  reg [31:0] id_instruction;

  reg ex_valid;
  reg [31:0] ex_pc;
  reg [31:0] ex_next_pc;
  reg [31:0] ex_instruction;
  reg [4:0] ex_rd;
  reg [31:0] ex_result;
  reg [31:0] ex_store_data;
  reg [3:0] ex_store_mask;
  reg [1:0] ex_load_size;
  reg ex_load_signed;
  reg ex_reg_write;
  reg ex_halt_after_retire;
  reg [2:0] ex_class;
  reg [7:0] ex_error_code;

  reg wb_valid;
  reg [31:0] wb_pc;
  reg [31:0] wb_next_pc;
  reg [4:0] wb_rd;
  reg [31:0] wb_result;
  reg wb_reg_write;
  reg wb_halt_after_retire;
  reg wb_error;
  reg [7:0] wb_error_code;

  reg mem_request_sent;

  wire [5:0] id_opcode = id_instruction[31:26];
  wire [4:0] id_rd = id_instruction[25:21];
  wire [4:0] id_ra = id_instruction[20:16];
  wire [4:0] id_rb = id_instruction[15:11];
  wire [4:0] id_src_a = (id_opcode >= OPCODE_BEQ && id_opcode <= OPCODE_BGEU) ?
                        id_rd : id_ra;
  wire [4:0] id_src_b = (id_opcode >= OPCODE_BEQ && id_opcode <= OPCODE_BGEU) ?
                        id_ra : ((id_opcode == OPCODE_STORE ||
                                  id_opcode == OPCODE_STOREB ||
                                  id_opcode == OPCODE_STOREH) ? id_rd : id_rb);
  wire pending_register_write = register_write_enable &&
                                register_write_address != 5'd0;
  wire [31:0] id_live_operand_a =
      (pending_register_write && id_src_a == register_write_address) ?
      register_write_data : register_a;
  wire [31:0] id_live_operand_b =
      (pending_register_write && id_src_b == register_write_address) ?
      register_write_data : register_b;
  wire [31:0] id_imm_signed = {{16{id_instruction[15]}}, id_instruction[15:0]};
  wire [31:0] id_imm_unsigned = {16'h0000, id_instruction[15:0]};
  wire [31:0] id_jump_offset = {{14{id_instruction[15]}}, id_instruction[15:0], 2'b00};
  wire [31:0] id_bra_offset = {{4{id_instruction[25]}}, id_instruction[25:0], 2'b00};
  wire id_shift_immediate = id_instruction[10];
  wire [4:0] id_shift_amount =
      id_shift_immediate ? id_rb : id_live_operand_b[4:0];

  reg [1:0] id_access_size;
  reg id_access_signed;
  always @* begin
    case (id_opcode)
      OPCODE_LOADB:  begin id_access_size = 2'd0; id_access_signed = 1'b1; end
      OPCODE_LOADUB: begin id_access_size = 2'd0; id_access_signed = 1'b0; end
      OPCODE_STOREB: begin id_access_size = 2'd0; id_access_signed = 1'b0; end
      OPCODE_LOADH:  begin id_access_size = 2'd1; id_access_signed = 1'b1; end
      OPCODE_LOADUH: begin id_access_size = 2'd1; id_access_signed = 1'b0; end
      OPCODE_STOREH: begin id_access_size = 2'd1; id_access_signed = 1'b0; end
      default:       begin id_access_size = 2'd2; id_access_signed = 1'b0; end
    endcase
  end

  wire [31:0] id_effective_address = id_live_operand_a + id_imm_signed;
  wire id_address_misaligned =
      (id_access_size == 2'd2) ? (id_effective_address[1:0] != 2'b00) :
      (id_access_size == 2'd1) ? (id_effective_address[0] != 1'b0) : 1'b0;

  reg [31:0] id_store_data;
  reg [3:0] id_store_mask;
  always @* begin
    case (id_access_size)
      2'd0: begin
        id_store_data = {4{id_live_operand_b[7:0]}};
        id_store_mask = 4'b0001 << id_effective_address[1:0];
      end
      2'd1: begin
        id_store_data = {2{id_live_operand_b[15:0]}};
        id_store_mask = id_effective_address[1] ? 4'b1100 : 4'b0011;
      end
      default: begin
        id_store_data = id_live_operand_b;
        id_store_mask = 4'b1111;
      end
    endcase
  end

  reg id_encoding_valid;
  always @* begin
    id_encoding_valid = 1'b1;
    case (id_opcode)
      OPCODE_NOP, OPCODE_TRAP, OPCODE_HALT, OPCODE_BAR:
        id_encoding_valid = id_instruction[25:0] == 0;
      OPCODE_ADD, OPCODE_SUB, OPCODE_MULFX, OPCODE_AND, OPCODE_OR, OPCODE_XOR,
      OPCODE_MUL, OPCODE_MULHI, OPCODE_DIV, OPCODE_DIVU, OPCODE_REM,
      OPCODE_REMU, OPCODE_SLT, OPCODE_SLTU:
        id_encoding_valid = id_instruction[10:0] == 0;
      OPCODE_SHL, OPCODE_SHR, OPCODE_SAR:
        id_encoding_valid = id_instruction[9:0] == 0;
      OPCODE_MOVI, OPCODE_MOVHI:
        id_encoding_valid = id_instruction[20:16] == 0;
      OPCODE_GETTID:
        id_encoding_valid = id_instruction[20:0] == 0;
      OPCODE_JAL:
        id_encoding_valid = id_instruction[20:16] == 0;
      OPCODE_JR:
        id_encoding_valid = id_instruction[25:21] == 0 &&
                            id_instruction[15:0] == 0;
      default: id_encoding_valid = 1'b1;
    endcase
  end

  wire id_uses_a = id_valid &&
      !(id_opcode == OPCODE_NOP || id_opcode == OPCODE_MOVI ||
        id_opcode == OPCODE_MOVHI || id_opcode == OPCODE_JAL ||
        id_opcode == OPCODE_HALT || id_opcode == OPCODE_TRAP ||
        id_opcode == OPCODE_SSY || id_opcode == OPCODE_BAR);
  wire id_uses_b = id_valid &&
      ((id_opcode >= OPCODE_ADD && id_opcode <= OPCODE_SAR) ||
       (id_opcode >= OPCODE_BEQ && id_opcode <= OPCODE_BGEU) ||
       id_opcode == OPCODE_SLT || id_opcode == OPCODE_SLTU ||
       id_opcode == OPCODE_STORE || id_opcode == OPCODE_STOREB ||
       id_opcode == OPCODE_STOREH);
  wire [5:0] if_opcode = if_instruction[31:26];
  wire [4:0] if_rd = if_instruction[25:21];
  wire [4:0] if_ra_field = if_instruction[20:16];
  wire [4:0] if_rb_field = if_instruction[15:11];
  wire if_is_branch = if_opcode >= OPCODE_BEQ && if_opcode <= OPCODE_BGEU;
  wire if_is_store = (if_opcode == OPCODE_STORE) ||
                     (if_opcode == OPCODE_STOREB) ||
                     (if_opcode == OPCODE_STOREH);
  wire [4:0] if_src_a = if_is_branch ? if_rd : if_ra_field;
  wire [4:0] if_src_b = if_is_branch ? if_ra_field :
                        (if_is_store ? if_rd : if_rb_field);

  always @* begin
    register_a_address = id_valid ? id_src_a : if_src_a;
    register_b_address = id_valid ? id_src_b : if_src_b;
  end

  wire hazard_ex = ex_valid && ex_reg_write && ex_rd != 5'd0 &&
                   ((id_uses_a && id_src_a == ex_rd) ||
                    (id_uses_b && id_src_b == ex_rd));
  wire hazard_wb = wb_valid && wb_reg_write && wb_rd != 5'd0 &&
                   ((id_uses_a && id_src_a == wb_rd) ||
                    (id_uses_b && id_src_b == wb_rd));
  wire raw_hazard = hazard_ex || hazard_wb;

  reg [31:0] load_extended;
  reg [7:0] load_byte;
  reg [15:0] load_half;
  always @* begin
    case (dmem_address[1:0])
      2'd0: load_byte = dmem_read_data[7:0];
      2'd1: load_byte = dmem_read_data[15:8];
      2'd2: load_byte = dmem_read_data[23:16];
      default: load_byte = dmem_read_data[31:24];
    endcase
    load_half = dmem_address[1] ? dmem_read_data[31:16] : dmem_read_data[15:0];
    case (ex_load_size)
      2'd0:
        load_extended =
            ex_load_signed ? {{24{load_byte[7]}}, load_byte} : {24'd0, load_byte};
      2'd1:
        load_extended =
            ex_load_signed ? {{16{load_half[15]}}, load_half} : {16'd0, load_half};
      default: load_extended = dmem_read_data;
    endcase
  end

  reg [31:0] exec_result;
  reg [31:0] exec_next_pc;
  reg exec_reg_write;
  reg exec_halt_after_retire;
  reg exec_branch_taken;
  reg [2:0] exec_class;
  reg [7:0] exec_error_code;
  reg [63:0] exec_product;
  reg signed [31:0] signed_a;
  reg signed [31:0] signed_b;
  reg [31:0] abs_a;
  reg [31:0] abs_b;
  reg signed [63:0] signed_product;
  reg signed [31:0] signed_quotient;
  reg signed [31:0] signed_remainder;
  reg [32:0] compare_difference;
  reg compare_signed_less;

  always @* begin
    exec_result = 32'h0000_0000;
    exec_next_pc = id_pc + 32'd4;
    exec_reg_write = 1'b0;
    exec_halt_after_retire = 1'b0;
    exec_branch_taken = 1'b0;
    exec_class = OPCLASS_NORMAL;
    exec_error_code = ERROR_NONE;
    exec_product = 64'h0000_0000_0000_0000;
    signed_a = id_live_operand_a;
    signed_b = id_live_operand_b;
    abs_a = id_live_operand_a[31] ? (~id_live_operand_a + 1'b1) : id_live_operand_a;
    abs_b = id_live_operand_b[31] ? (~id_live_operand_b + 1'b1) : id_live_operand_b;
    signed_product = signed_a * signed_b;
    signed_quotient = 32'sd0;
    signed_remainder = 32'sd0;
    compare_difference = {1'b0, id_live_operand_a} - {1'b0, id_live_operand_b};
    compare_signed_less =
        id_live_operand_a[31] != id_live_operand_b[31] ? id_live_operand_a[31] :
                                                compare_difference[31];

    if (!id_encoding_valid) begin
      exec_class = OPCLASS_ERROR;
      exec_error_code = ERROR_INVALID_ENCODING;
    end else begin
      case (id_opcode)
        OPCODE_NOP, OPCODE_SSY, OPCODE_BAR: begin
        end

        OPCODE_MOVI: begin
          exec_result = id_imm_signed;
          exec_reg_write = 1'b1;
        end

        OPCODE_MOVHI: begin
          exec_result = {id_instruction[15:0], 16'h0000};
          exec_reg_write = 1'b1;
        end

        OPCODE_GETTID: begin
          exec_result = 32'h0000_0000;
          exec_reg_write = 1'b1;
        end

        OPCODE_ADD:  begin exec_result = id_live_operand_a + id_live_operand_b; exec_reg_write = 1'b1; end
        OPCODE_SUB:  begin exec_result = id_live_operand_a - id_live_operand_b; exec_reg_write = 1'b1; end
        OPCODE_AND:  begin exec_result = id_live_operand_a & id_live_operand_b; exec_reg_write = 1'b1; end
        OPCODE_OR:   begin exec_result = id_live_operand_a | id_live_operand_b; exec_reg_write = 1'b1; end
        OPCODE_XOR:  begin exec_result = id_live_operand_a ^ id_live_operand_b; exec_reg_write = 1'b1; end
        OPCODE_ADDI: begin exec_result = id_live_operand_a + id_imm_signed; exec_reg_write = 1'b1; end
        OPCODE_ANDI: begin exec_result = id_live_operand_a & id_imm_unsigned; exec_reg_write = 1'b1; end
        OPCODE_ORI:  begin exec_result = id_live_operand_a | id_imm_unsigned; exec_reg_write = 1'b1; end
        OPCODE_XORI: begin exec_result = id_live_operand_a ^ id_imm_unsigned; exec_reg_write = 1'b1; end

        OPCODE_SHL: begin exec_result = id_live_operand_a << id_shift_amount; exec_reg_write = 1'b1; end
        OPCODE_SHR: begin exec_result = id_live_operand_a >> id_shift_amount; exec_reg_write = 1'b1; end
        OPCODE_SAR: begin exec_result = $signed(id_live_operand_a) >>> id_shift_amount; exec_reg_write = 1'b1; end

        OPCODE_SLT: begin exec_result = {31'd0, compare_signed_less}; exec_reg_write = 1'b1; end
        OPCODE_SLTU: begin exec_result = {31'd0, compare_difference[32]}; exec_reg_write = 1'b1; end

        OPCODE_MUL: begin
          exec_product = id_live_operand_a * id_live_operand_b;
          exec_result = exec_product[31:0];
          exec_reg_write = 1'b1;
        end
        OPCODE_MULHI: begin
          exec_result = signed_product[63:32];
          exec_reg_write = 1'b1;
        end
        OPCODE_MULFX: begin
          exec_product = abs_a * abs_b;
          exec_result = (id_live_operand_a[31] ^ id_live_operand_b[31]) ?
              (~exec_product[47:16] + (exec_product[15:0] == 16'h0000)) :
              exec_product[47:16];
          exec_reg_write = 1'b1;
        end

        OPCODE_DIV, OPCODE_DIVU, OPCODE_REM, OPCODE_REMU: begin
          if (id_live_operand_b == 0) begin
            exec_class = OPCLASS_ERROR;
            exec_error_code = ERROR_DIVISION_BY_ZERO;
          end else begin
            signed_quotient = signed_a / signed_b;
            signed_remainder = signed_a % signed_b;
            case (id_opcode)
              OPCODE_DIV:  exec_result = signed_quotient;
              OPCODE_DIVU: exec_result = id_live_operand_a / id_live_operand_b;
              OPCODE_REM:  exec_result = signed_remainder;
              default:     exec_result = id_live_operand_a % id_live_operand_b;
            endcase
            exec_reg_write = 1'b1;
          end
        end

        OPCODE_LOAD, OPCODE_LOADB, OPCODE_LOADUB, OPCODE_LOADH, OPCODE_LOADUH: begin
          if (id_address_misaligned) begin
            exec_class = OPCLASS_ERROR;
            exec_error_code = ERROR_MEMORY_ACCESS;
          end else begin
            exec_result = id_effective_address;
            exec_class = OPCLASS_LOAD;
            exec_reg_write = 1'b1;
          end
        end

        OPCODE_STORE, OPCODE_STOREB, OPCODE_STOREH: begin
          if (id_address_misaligned) begin
            exec_class = OPCLASS_ERROR;
            exec_error_code = ERROR_MEMORY_ACCESS;
          end else begin
            exec_result = id_effective_address;
            exec_class = OPCLASS_STORE;
          end
        end

        OPCODE_BEQ: begin
          exec_branch_taken = compare_difference[31:0] == 0;
          exec_next_pc = (id_pc + 32'd4) + id_jump_offset;
          exec_class = OPCLASS_BRANCH;
        end
        OPCODE_BNE: begin
          exec_branch_taken = compare_difference[31:0] != 0;
          exec_next_pc = (id_pc + 32'd4) + id_jump_offset;
          exec_class = OPCLASS_BRANCH;
        end
        OPCODE_BLT: begin
          exec_branch_taken = compare_signed_less;
          exec_next_pc = (id_pc + 32'd4) + id_jump_offset;
          exec_class = OPCLASS_BRANCH;
        end
        OPCODE_BGE: begin
          exec_branch_taken = !compare_signed_less;
          exec_next_pc = (id_pc + 32'd4) + id_jump_offset;
          exec_class = OPCLASS_BRANCH;
        end
        OPCODE_BLTU: begin
          exec_branch_taken = compare_difference[32];
          exec_next_pc = (id_pc + 32'd4) + id_jump_offset;
          exec_class = OPCLASS_BRANCH;
        end
        OPCODE_BGEU: begin
          exec_branch_taken = !compare_difference[32];
          exec_next_pc = (id_pc + 32'd4) + id_jump_offset;
          exec_class = OPCLASS_BRANCH;
        end
        OPCODE_BRA: begin
          exec_branch_taken = 1'b1;
          exec_next_pc = (id_pc + 32'd4) + id_bra_offset;
          exec_class = OPCLASS_BRANCH;
        end
        OPCODE_JAL: begin
          exec_branch_taken = 1'b1;
          exec_next_pc = (id_pc + 32'd4) + id_jump_offset;
          exec_result = id_pc + 32'd4;
          exec_reg_write = 1'b1;
          exec_class = OPCLASS_BRANCH;
        end
        OPCODE_JALR: begin
          exec_branch_taken = 1'b1;
          exec_next_pc = (id_live_operand_a + id_jump_offset) & ~32'd3;
          exec_result = id_pc + 32'd4;
          exec_reg_write = 1'b1;
          exec_class = OPCLASS_BRANCH;
        end
        OPCODE_JR: begin
          exec_branch_taken = 1'b1;
          exec_next_pc = id_live_operand_a & ~32'd3;
          exec_class = OPCLASS_BRANCH;
        end

        OPCODE_HALT: begin
          exec_halt_after_retire = 1'b1;
        end
        OPCODE_TRAP: begin
          exec_class = OPCLASS_ERROR;
          exec_error_code = ERROR_EXPLICIT_TRAP;
        end

        default: begin
          exec_class = OPCLASS_ERROR;
          exec_error_code = ERROR_INVALID_OPCODE;
        end
      endcase
    end
  end

  wire ex_is_memory = ex_valid &&
      (ex_class == OPCLASS_LOAD || ex_class == OPCLASS_STORE);
  wire issue_stall = raw_hazard || ex_is_memory;
  wire wb_stops_machine = wb_valid &&
      (wb_error || wb_halt_after_retire || step_active || halt_pending);
  wire id_redirects_fetch = id_valid && !raw_hazard &&
      (exec_class == OPCLASS_BRANCH) && exec_branch_taken;

  always @(posedge clk) begin
    register_write_enable <= 1'b0;
    instruction_retired <= 1'b0;

    if (reset) begin
      running <= 1'b0;
      step_active <= 1'b0;
      halt_pending <= 1'b0;
      halted <= 1'b1;
      error <= 1'b0;
      error_code <= ERROR_NONE;
      architectural_pc <= 32'h0000_0000;
      fetch_request_pc <= 32'h0000_0000;
      imem_valid <= 1'b0;
      imem_address <= 32'h0000_0000;
      dmem_valid <= 1'b0;
      dmem_address <= 32'h0000_0000;
      dmem_write_data <= 32'h0000_0000;
      dmem_write_enable <= 4'b0000;
      if_valid <= 1'b0;
      if_pc <= 32'h0000_0000;
      if_instruction <= 32'h0000_0000;
      id_valid <= 1'b0;
      id_pc <= 32'h0000_0000;
      id_instruction <= 32'h0000_0000;
      ex_valid <= 1'b0;
      ex_pc <= 32'h0000_0000;
      ex_next_pc <= 32'h0000_0000;
      ex_instruction <= 32'h0000_0000;
      ex_rd <= 5'd0;
      ex_result <= 32'h0000_0000;
      ex_store_data <= 32'h0000_0000;
      ex_store_mask <= 4'b0000;
      ex_load_size <= 2'd2;
      ex_load_signed <= 1'b0;
      ex_reg_write <= 1'b0;
      ex_halt_after_retire <= 1'b0;
      ex_class <= OPCLASS_NORMAL;
      ex_error_code <= ERROR_NONE;
      wb_valid <= 1'b0;
      wb_pc <= 32'h0000_0000;
      wb_next_pc <= 32'h0000_0000;
      wb_rd <= 5'd0;
      wb_result <= 32'h0000_0000;
      wb_reg_write <= 1'b0;
      wb_halt_after_retire <= 1'b0;
      wb_error <= 1'b0;
      wb_error_code <= ERROR_NONE;
      mem_request_sent <= 1'b0;
    end else begin
      if (halt_request && running)
        halt_pending <= 1'b1;

      if (halted) begin
        imem_valid <= 1'b0;
        dmem_valid <= 1'b0;
        dmem_write_enable <= 4'b0000;
        if_valid <= 1'b0;
        id_valid <= 1'b0;
        ex_valid <= 1'b0;
        wb_valid <= 1'b0;
        mem_request_sent <= 1'b0;
        halt_pending <= 1'b0;

        if (run_request || step_request) begin
          halted <= 1'b0;
          running <= 1'b1;
          step_active <= step_request;
          imem_address <= architectural_pc;
          fetch_request_pc <= architectural_pc;
          imem_valid <= 1'b1;
        end
      end else begin
        if (halt_request) begin
          halted <= 1'b1;
          running <= 1'b0;
          step_active <= 1'b0;
          halt_pending <= 1'b0;
          fetch_request_pc <= architectural_pc;
          if_valid <= 1'b0;
          id_valid <= 1'b0;
          ex_valid <= 1'b0;
          wb_valid <= 1'b0;
          imem_valid <= 1'b0;
          dmem_valid <= 1'b0;
          dmem_write_enable <= 4'b0000;
          mem_request_sent <= 1'b0;
        end else begin
        if (wb_valid) begin
          if (wb_error) begin
            error <= 1'b1;
            error_code <= wb_error_code;
            architectural_pc <= wb_pc;
            fetch_request_pc <= wb_pc;
            halted <= 1'b1;
            running <= 1'b0;
            if_valid <= 1'b0;
            id_valid <= 1'b0;
            ex_valid <= 1'b0;
            wb_valid <= 1'b0;
            imem_valid <= 1'b0;
            dmem_valid <= 1'b0;
            dmem_write_enable <= 4'b0000;
            mem_request_sent <= 1'b0;
          end else begin
            instruction_retired <= 1'b1;
            architectural_pc <= wb_next_pc;
            if (wb_reg_write) begin
              register_write_address <= wb_rd;
              register_write_data <= wb_result;
              register_write_enable <= 1'b1;
            end

            if (wb_halt_after_retire || step_active || halt_pending) begin
              halted <= 1'b1;
              running <= 1'b0;
              fetch_request_pc <= wb_next_pc;
              step_active <= 1'b0;
              halt_pending <= 1'b0;
              if_valid <= 1'b0;
              id_valid <= 1'b0;
              ex_valid <= 1'b0;
              wb_valid <= 1'b0;
              imem_valid <= 1'b0;
              dmem_valid <= 1'b0;
              dmem_write_enable <= 4'b0000;
              mem_request_sent <= 1'b0;
            end else begin
              wb_valid <= 1'b0;
            end
          end
        end

        if (!halted && running && !wb_stops_machine && !ex_is_memory) begin
          if (ex_valid) begin
            wb_valid <= 1'b1;
            wb_pc <= ex_pc;
            wb_next_pc <= ex_next_pc;
            wb_rd <= ex_rd;
            wb_result <= ex_result;
            wb_reg_write <= ex_reg_write;
            wb_halt_after_retire <= ex_halt_after_retire;
            wb_error <= ex_class == OPCLASS_ERROR;
            wb_error_code <= ex_error_code;
          end

          if (!raw_hazard) begin
            ex_valid <= id_valid;
            ex_pc <= id_pc;
            ex_next_pc <= exec_branch_taken ? exec_next_pc : (id_pc + 32'd4);
            ex_instruction <= id_instruction;
            ex_rd <= id_rd;
            ex_result <= exec_result;
            ex_store_data <= id_store_data;
            ex_store_mask <= id_store_mask;
            ex_load_size <= id_access_size;
            ex_load_signed <= id_access_signed;
            ex_reg_write <= exec_reg_write;
            ex_halt_after_retire <= exec_halt_after_retire;
            ex_class <= exec_class;
            ex_error_code <= exec_error_code;
            mem_request_sent <= 1'b0;

            if (id_redirects_fetch) begin
              imem_address <= exec_next_pc;
              fetch_request_pc <= exec_next_pc;
              imem_valid <= 1'b0;
              if_valid <= 1'b0;
              id_valid <= 1'b0;
            end else begin
              id_valid <= if_valid;
              id_pc <= if_pc;
              id_instruction <= if_instruction;
              if_valid <= 1'b0;
            end
          end else begin
            ex_valid <= 1'b0;
          end
        end

        if (!wb_stops_machine && ex_is_memory) begin
          if (!mem_request_sent) begin
            dmem_address <= ex_result;
            dmem_write_data <= ex_store_data;
            dmem_write_enable <= (ex_class == OPCLASS_STORE) ? ex_store_mask : 4'b0000;
            dmem_valid <= 1'b1;
            mem_request_sent <= 1'b1;
          end else if (dmem_ready) begin
            dmem_valid <= 1'b0;
            dmem_write_enable <= 4'b0000;
            wb_valid <= 1'b1;
            wb_pc <= ex_pc;
            wb_next_pc <= ex_next_pc;
            wb_rd <= ex_rd;
            wb_result <= load_extended;
            wb_reg_write <= ex_class == OPCLASS_LOAD;
            wb_halt_after_retire <= ex_halt_after_retire;
            wb_error <= dmem_error;
            wb_error_code <= ERROR_MEMORY_ACCESS;
            ex_valid <= 1'b0;
            mem_request_sent <= 1'b0;
          end
        end

        if (!halted && running && !wb_stops_machine && !id_redirects_fetch) begin
          if (imem_valid && imem_ready && !if_valid) begin
            if_pc <= fetch_request_pc;
            if_instruction <= imem_read_data;
            if_valid <= 1'b1;
            imem_address <= imem_address + 32'd4;
            fetch_request_pc <= imem_address + 32'd4;
            imem_valid <= 1'b0;
          end else if (!imem_valid && !if_valid && !issue_stall) begin
            fetch_request_pc <= imem_address;
            imem_valid <= 1'b1;
          end
        end
        end
      end
    end
  end
endmodule

`default_nettype wire
