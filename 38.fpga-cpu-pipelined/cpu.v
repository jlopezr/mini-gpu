`default_nettype none

/*
 * Experimental pipelined MiniCPU.
 *
 * This prototype keeps the monitor-facing contract of the multicycle CPU:
 * reset starts halted, RUN starts free-running execution, STEP retires exactly
 * one instruction, and errors leave the architectural PC on the faulting
 * instruction. The pipeline is deliberately conservative: RAW hazards, memory waits and control events insert bubbles.
 * The current fetch handshake also limits instruction throughput.
 */
module cpu (
    input clk,
    input reset,

    input run_request,
    input halt_request,
    input step_request,

    (* pipeline_stage = "_CTL" *) output reg halted,
    (* pipeline_stage = "WB" *) output reg error,
    (* pipeline_stage = "WB" *) output reg [7:0] error_code,
    (* pipeline_stage = "WB" *) output reg instruction_retired,

    // imem: peticion (valid/ready, aceptada cuando los dos estan altos) y
    // respuesta (rvalid + read_data, una por peticion y en orden).
    output imem_valid,
    (* pipeline_stage = "IF" *) output reg [31:0] imem_address,
    input imem_ready,
    input [31:0] imem_read_data,
    input imem_rvalid,

    (* pipeline_stage = "EX" *) output reg dmem_valid,
    (* pipeline_stage = "EX" *) output reg [31:0] dmem_address,
    (* pipeline_stage = "EX" *) output reg [31:0] dmem_write_data,
    (* pipeline_stage = "EX" *) output reg [3:0] dmem_write_enable,
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

  localparam [2:0] OPCLASS_NORMAL = 3'd0;
  localparam [2:0] OPCLASS_LOAD = 3'd1;
  localparam [2:0] OPCLASS_STORE = 3'd2;
  localparam [2:0] OPCLASS_BRANCH = 3'd3;
  localparam [2:0] OPCLASS_ERROR = 3'd4;

  // ======================================================================
  // DECLARATIONS (all before use, for Icarus elaboration)
  // ======================================================================

  /*
   * Pipeline stage of each register, for `tools/timing-wall --stages`.
   *
   * A register belongs to the stage whose logic reads it, i.e. where the
   * instruction is while it uses that register; the logic of stage X is then
   * the cone from the X registers to the X+1 registers. Registers named
   * `if_*`, `id_*`, `ex_*` and `wb_*` get their stage from the prefix and need
   * no attribute, and `ctl_*` goes to `_CTL`, the global run/halt/step
   * control; only the rest are tagged. Values starting with `_` are groups
   * that are not pipeline stages. Yosys keeps these attributes in hardware.json; it drops them on
   * memories, so the register file array is not tagged.
   */

  // Control
  reg ctl_step_active;
  reg ctl_start_pending;
  reg ctl_start_step_pending;
  wire wb_stops_machine;
  wire id_redirects_fetch;
  wire ctl_start;
  wire ctl_abort;
  wire ctl_fault;
  wire ctl_retire;
  wire ctl_retire_stop;
  wire ctl_flush;
  wire ctl_advance;
  wire ctl_memory;
  wire ctl_fetch;

  // Register file
  wire [31:0] register_a;
  wire [31:0] register_b;
  wire register_file_busy;
  wire register_write_enable;
  wire [4:0] register_write_address;
  wire [31:0] register_write_data;

  // IF: fetch queue. Entry 0 (if_valid/if_pc/if_instruction) is the head
  // that ID takes; entries 1 and 2 are behind it.
  reg if_valid, if_valid1, if_valid2;
  reg [31:0] if_pc, if_pc1, if_pc2;
  reg [31:0] if_instruction, if_instruction1, if_instruction2;
  reg [31:0] if_response_pc;
  reg [1:0] if_inflight;
  reg [1:0] if_discard;
  wire [2:0] if_used;
  wire if_accept;
  wire if_keep;
  wire if_pop;
  wire [1:0] if_inflight_next;
  reg if_valid_n, if_valid1_n, if_valid2_n;
  reg [31:0] if_pc_n, if_pc1_n, if_pc2_n;
  reg [31:0] if_instruction_n, if_instruction1_n, if_instruction2_n;

  // ID
  reg id_valid;
  reg [31:0] id_pc;
  reg [31:0] id_instruction;
  wire [5:0] id_opcode;
  wire [4:0] id_rd;
  wire [4:0] id_ra;
  wire [4:0] id_rb;
  wire [4:0] id_src_a;
  wire [4:0] id_src_b;
  wire [31:0] id_imm_signed;
  wire [31:0] id_imm_unsigned;
  wire [31:0] id_jump_offset;
  wire [31:0] id_bra_offset;
  wire id_shift_immediate;
  wire [4:0] id_shift_amount;
  reg [1:0] id_access_size;
  reg id_access_signed;
  wire [31:0] id_effective_address;
  wire id_address_misaligned;
  reg [31:0] id_store_data;
  reg [3:0] id_store_mask;
  reg id_encoding_valid;
  wire id_uses_a;
  wire id_uses_b;
  wire hazard_ex;
  wire hazard_wb;
  wire raw_hazard;
  reg [31:0] id_result;
  reg [31:0] id_next_pc;
  reg id_reg_write;
  reg id_halt_after_retire;
  reg id_branch_taken;
  reg [2:0] id_class;
  reg [7:0] id_error_code;
  reg [32:0] id_compare_difference;
  reg id_compare_signed_less;

  // EX
  reg ex_valid;
  reg [31:0] ex_pc;
  reg [31:0] ex_next_pc;
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
  reg ex_mem_request_sent;
  reg [31:0] ex_load_extended;
  reg [7:0] ex_load_byte;
  reg [15:0] ex_load_half;
  wire ex_is_memory;

  // WB
  reg wb_valid;
  reg [31:0] wb_pc;
  reg [31:0] wb_next_pc;
  reg [4:0] wb_rd;
  reg [31:0] wb_result;
  reg wb_reg_write;
  reg wb_halt_after_retire;
  reg wb_error;
  reg [7:0] wb_error_code;
  (* pipeline_stage = "WB" *) reg [31:0] architectural_pc;

  // ======================================================================
  // 00. CONTROL — RUN/HALT/STEP AND PIPELINE FLOW
  // ======================================================================

  // Shared combinational control. Every register has a single sequential
  // owner: the control FSM below, or the always block of its stage.

  // Events seen by the stages (raw_hazard itself is computed in ID).
  assign wb_stops_machine = wb_valid &&
      (wb_error || wb_halt_after_retire || ctl_step_active);
  assign id_redirects_fetch = id_valid && !raw_hazard &&
      (id_class == OPCLASS_BRANCH) && id_branch_taken;

  // Per-cycle decisions.
  assign ctl_start = halted &&
      (ctl_start_pending || run_request || step_request) && !register_file_busy;
  assign ctl_abort = !halted && halt_request;
  assign ctl_fault = !halted && !halt_request && wb_valid && wb_error;
  assign ctl_retire = !halted && !halt_request && wb_valid && !wb_error;
  assign ctl_retire_stop = ctl_retire &&
      (wb_halt_after_retire || ctl_step_active);
  assign ctl_flush = ctl_abort || ctl_fault || ctl_retire_stop;
  assign ctl_advance = !halted && !halt_request &&
      !wb_stops_machine && !ex_is_memory;
  assign ctl_memory = !halted && !halt_request &&
      !wb_stops_machine && ex_is_memory;
  assign ctl_fetch = !halted && !halt_request &&
      !wb_stops_machine && !id_redirects_fetch;

  // Control FSM: only this process owns ctl_* and halted.
  always @(posedge clk) begin
    if (reset) begin
      ctl_step_active <= 1'b0;
      ctl_start_pending <= 1'b0;
      ctl_start_step_pending <= 1'b0;
      halted <= 1'b1;
    end else if (halted) begin
      if (run_request || step_request) begin
        ctl_start_pending <= 1'b1;
        ctl_start_step_pending <= step_request;
      end
      if (ctl_start) begin
        halted <= 1'b0;
        ctl_step_active <= ctl_start_pending ? ctl_start_step_pending : step_request;
        ctl_start_pending <= 1'b0;
        ctl_start_step_pending <= 1'b0;
      end
    end else if (ctl_abort) begin
      halted <= 1'b1;
      ctl_step_active <= 1'b0;
      ctl_start_pending <= 1'b0;
      ctl_start_step_pending <= 1'b0;
    end else if (ctl_fault) begin
      halted <= 1'b1;
    end else if (ctl_retire_stop) begin
      halted <= 1'b1;
      ctl_step_active <= 1'b0;
    end
  end

  // ======================================================================
  // 01. REGISTER FILE (WB WRITE PORT, ID READ PORT)
  // ======================================================================

  // WB drives the synchronous register-file write port directly (there is
  // no _WR write buffer any more). ID reads asynchronously with its own
  // source fields. There is no WB -> ID bypass: hazard_wb stalls ID while
  // the producer is in WB, and the next cycle the bank already holds it.

  // ctl_retire is exactly the cycle WB retires. A write during reset is
  // harmless: reset restarts the clearing sweep, which overwrites it.
  assign register_write_enable = ctl_retire && wb_reg_write;
  assign register_write_address = wb_rd;
  assign register_write_data = wb_result;

  register_file register_file_i (
      .clk(clk),
      .reset(reset),
      .read_address_a(id_src_a),
      .read_data_a(register_a),
      .read_address_b(id_src_b),
      .read_data_b(register_b),
      .write_enable(register_write_enable),
      .write_address(register_write_address),
      .write_data(register_write_data),
      .debug_address(debug_register_address),
      .debug_data(debug_register_data),
      .busy(register_file_busy)
  );

  // ======================================================================
  // 02. IF — FETCH STATE
  // ======================================================================

  /*
   * Fetch with request and response split (see instruction_buffer.v).
   *
   * imem_address is the address of the next request. A request goes out
   * whenever its response is sure to fit: the three queue entries count both
   * the instructions already there and the requests still in flight. The
   * count does not look at whether ID takes the head this cycle, so ID's
   * decision (raw_hazard, id_redirects_fetch) stays out of imem_valid. With a
   * one-cycle hit, three entries are exactly enough for one instruction per
   * cycle: request, response, and ID taking it.
   *
   * A redirect (taken branch) or a stop (abort, fault, STEP/HALT retire)
   * empties the queue, and the responses still in flight belong to the old
   * path: if_discard counts them and they are dropped as they arrive. They
   * arrive in order, so a count is enough.
   */
  assign if_used = {1'b0, if_valid} + {1'b0, if_valid1} + {1'b0, if_valid2} +
                   {1'b0, if_inflight};
  assign imem_valid = !halted && (if_used < 3'd3);
  assign if_accept = imem_valid && imem_ready;
  assign if_keep = imem_rvalid && (if_discard == 2'd0);
  assign if_inflight_next = if_inflight + {1'b0, if_accept} - {1'b0, imem_rvalid};
  assign if_pop = ctl_advance && !raw_hazard && !id_redirects_fetch && if_valid;

  // Next queue contents without a flush: pop the head if ID takes it, then
  // put a kept response in the first free entry.
  always @* begin
    if_valid_n = if_valid;    if_pc_n = if_pc;    if_instruction_n = if_instruction;
    if_valid1_n = if_valid1;  if_pc1_n = if_pc1;  if_instruction1_n = if_instruction1;
    if_valid2_n = if_valid2;  if_pc2_n = if_pc2;  if_instruction2_n = if_instruction2;
    if (if_pop) begin
      if_valid_n = if_valid1;  if_pc_n = if_pc1;  if_instruction_n = if_instruction1;
      if_valid1_n = if_valid2; if_pc1_n = if_pc2; if_instruction1_n = if_instruction2;
      if_valid2_n = 1'b0;
    end
    if (if_keep) begin
      if (!if_valid_n) begin
        if_valid_n = 1'b1;  if_pc_n = if_response_pc;  if_instruction_n = imem_read_data;
      end else if (!if_valid1_n) begin
        if_valid1_n = 1'b1; if_pc1_n = if_response_pc; if_instruction1_n = imem_read_data;
      end else begin
        if_valid2_n = 1'b1; if_pc2_n = if_response_pc; if_instruction2_n = imem_read_data;
      end
    end
  end

  always @(posedge clk) begin
    if (reset) begin
      imem_address <= 32'd0;
      if_response_pc <= 32'd0;
      if_inflight <= 2'd0;
      if_discard <= 2'd0;
      if_valid <= 1'b0;
      if_valid1 <= 1'b0;
      if_valid2 <= 1'b0;
      if_pc <= 32'd0;
      if_pc1 <= 32'd0;
      if_pc2 <= 32'd0;
      if_instruction <= 32'd0;
      if_instruction1 <= 32'd0;
      if_instruction2 <= 32'd0;
    end else begin
      if_inflight <= if_inflight_next;
      if (if_accept) imem_address <= imem_address + 32'd4;

      if (halted || ctl_abort || ctl_fault || ctl_retire_stop ||
          (ctl_advance && !raw_hazard && id_redirects_fetch)) begin
        // Empty the queue; whatever is still in flight is stale.
        if_valid <= 1'b0;
        if_valid1 <= 1'b0;
        if_valid2 <= 1'b0;
        if_discard <= if_inflight_next;
        if (halted) begin
          if (ctl_start) begin
            imem_address <= architectural_pc;
            if_response_pc <= architectural_pc;
          end
        end else if (!(ctl_abort || ctl_fault || ctl_retire_stop)) begin
          imem_address <= id_next_pc;
          if_response_pc <= id_next_pc;
        end
      end else begin
        if_valid <= if_valid_n;    if_pc <= if_pc_n;    if_instruction <= if_instruction_n;
        if_valid1 <= if_valid1_n;  if_pc1 <= if_pc1_n;  if_instruction1 <= if_instruction1_n;
        if_valid2 <= if_valid2_n;  if_pc2 <= if_pc2_n;  if_instruction2 <= if_instruction2_n;
        if (if_keep) if_response_pc <= if_response_pc + 32'd4;
        if (imem_rvalid && !if_keep) if_discard <= if_discard - 2'd1;
      end
    end
  end

  // ======================================================================
  // 03. ID — DECODE, OPERANDS, HAZARDS AND ALU
  // ======================================================================

  assign id_opcode = id_instruction[31:26];
  assign id_rd = id_instruction[25:21];
  assign id_ra = id_instruction[20:16];
  assign id_rb = id_instruction[15:11];
  assign id_src_a = (id_opcode >= OPCODE_BEQ && id_opcode <= OPCODE_BGEU) ?
                        id_rd : id_ra;
  assign id_src_b = (id_opcode >= OPCODE_BEQ && id_opcode <= OPCODE_BGEU) ?
                        id_ra : ((id_opcode == OPCODE_STORE ||
                                  id_opcode == OPCODE_STOREB ||
                                  id_opcode == OPCODE_STOREH) ? id_rd : id_rb);
  assign id_imm_signed = {{16{id_instruction[15]}}, id_instruction[15:0]};
  assign id_imm_unsigned = {16'h0000, id_instruction[15:0]};
  assign id_jump_offset = {{14{id_instruction[15]}}, id_instruction[15:0], 2'b00};
  assign id_bra_offset = {{4{id_instruction[25]}}, id_instruction[25:0], 2'b00};
  assign id_shift_immediate = id_instruction[10];
  assign id_shift_amount = id_shift_immediate ? id_rb : register_b[4:0];
  assign id_effective_address = register_a + id_imm_signed;
  assign id_address_misaligned = (id_access_size == 2'd2) ? (id_effective_address[1:0] != 2'b00) :
      (id_access_size == 2'd1) ? (id_effective_address[0] != 1'b0) : 1'b0;
  assign id_uses_a = id_valid &&
      !(id_opcode == OPCODE_NOP || id_opcode == OPCODE_MOVI ||
        id_opcode == OPCODE_MOVHI || id_opcode == OPCODE_JAL ||
        id_opcode == OPCODE_HALT || id_opcode == OPCODE_TRAP ||
        id_opcode == OPCODE_SSY || id_opcode == OPCODE_BAR);
  assign id_uses_b = id_valid &&
      ((id_opcode >= OPCODE_ADD && id_opcode <= OPCODE_SAR) ||
       (id_opcode >= OPCODE_BEQ && id_opcode <= OPCODE_BGEU) ||
       id_opcode == OPCODE_SLT || id_opcode == OPCODE_SLTU ||
       id_opcode == OPCODE_STORE || id_opcode == OPCODE_STOREB ||
       id_opcode == OPCODE_STOREH);
  assign hazard_ex = ex_valid && ex_reg_write && ex_rd != 5'd0 &&
                   ((id_uses_a && id_src_a == ex_rd) ||
                    (id_uses_b && id_src_b == ex_rd));
  assign hazard_wb = wb_valid && wb_reg_write && wb_rd != 5'd0 &&
                   ((id_uses_a && id_src_a == wb_rd) ||
                    (id_uses_b && id_src_b == wb_rd));
  assign raw_hazard = hazard_ex || hazard_wb;

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

  always @* begin
    case (id_access_size)
      2'd0: begin
        id_store_data = {4{register_b[7:0]}};
        id_store_mask = 4'b0001 << id_effective_address[1:0];
      end
      2'd1: begin
        id_store_data = {2{register_b[15:0]}};
        id_store_mask = id_effective_address[1] ? 4'b1100 : 4'b0011;
      end
      default: begin
        id_store_data = register_b;
        id_store_mask = 4'b1111;
      end
    endcase
  end

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

  always @* begin
    id_result = 32'h0000_0000;
    id_next_pc = id_pc + 32'd4;
    id_reg_write = 1'b0;
    id_halt_after_retire = 1'b0;
    id_branch_taken = 1'b0;
    id_class = OPCLASS_NORMAL;
    id_error_code = ERROR_NONE;
    id_compare_difference = {1'b0, register_a} - {1'b0, register_b};
    id_compare_signed_less =
        register_a[31] != register_b[31] ? register_a[31] :
                                                id_compare_difference[31];

    if (!id_encoding_valid) begin
      id_class = OPCLASS_ERROR;
      id_error_code = ERROR_INVALID_ENCODING;
    end else begin
      case (id_opcode)
        OPCODE_NOP, OPCODE_SSY, OPCODE_BAR: begin
        end

        OPCODE_MOVI: begin
          id_result = id_imm_signed;
          id_reg_write = 1'b1;
        end

        OPCODE_MOVHI: begin
          id_result = {id_instruction[15:0], 16'h0000};
          id_reg_write = 1'b1;
        end

        OPCODE_GETTID: begin
          id_result = 32'h0000_0000;
          id_reg_write = 1'b1;
        end

        OPCODE_ADD:  begin id_result = register_a + register_b; id_reg_write = 1'b1; end
        OPCODE_SUB:  begin id_result = register_a - register_b; id_reg_write = 1'b1; end
        OPCODE_AND:  begin id_result = register_a & register_b; id_reg_write = 1'b1; end
        OPCODE_OR:   begin id_result = register_a | register_b; id_reg_write = 1'b1; end
        OPCODE_XOR:  begin id_result = register_a ^ register_b; id_reg_write = 1'b1; end
        OPCODE_ADDI: begin id_result = register_a + id_imm_signed; id_reg_write = 1'b1; end
        OPCODE_ANDI: begin id_result = register_a & id_imm_unsigned; id_reg_write = 1'b1; end
        OPCODE_ORI:  begin id_result = register_a | id_imm_unsigned; id_reg_write = 1'b1; end
        OPCODE_XORI: begin id_result = register_a ^ id_imm_unsigned; id_reg_write = 1'b1; end

        OPCODE_SHL: begin id_result = register_a << id_shift_amount; id_reg_write = 1'b1; end
        OPCODE_SHR: begin id_result = register_a >> id_shift_amount; id_reg_write = 1'b1; end
        OPCODE_SAR: begin id_result = $signed(register_a) >>> id_shift_amount; id_reg_write = 1'b1; end

        OPCODE_SLT: begin id_result = {31'd0, id_compare_signed_less}; id_reg_write = 1'b1; end
        OPCODE_SLTU: begin id_result = {31'd0, id_compare_difference[32]}; id_reg_write = 1'b1; end

        OPCODE_MUL, OPCODE_MULHI, OPCODE_MULFX,
        OPCODE_DIV, OPCODE_DIVU, OPCODE_REM, OPCODE_REMU: begin
          id_class = OPCLASS_ERROR;
          id_error_code = ERROR_INVALID_OPCODE;
        end

        OPCODE_LOAD, OPCODE_LOADB, OPCODE_LOADUB, OPCODE_LOADH, OPCODE_LOADUH: begin
          if (id_address_misaligned) begin
            id_class = OPCLASS_ERROR;
            id_error_code = ERROR_MEMORY_ACCESS;
          end else begin
            id_result = id_effective_address;
            id_class = OPCLASS_LOAD;
            id_reg_write = 1'b1;
          end
        end

        OPCODE_STORE, OPCODE_STOREB, OPCODE_STOREH: begin
          if (id_address_misaligned) begin
            id_class = OPCLASS_ERROR;
            id_error_code = ERROR_MEMORY_ACCESS;
          end else begin
            id_result = id_effective_address;
            id_class = OPCLASS_STORE;
          end
        end

        OPCODE_BEQ: begin
          id_branch_taken = id_compare_difference[31:0] == 0;
          id_next_pc = (id_pc + 32'd4) + id_jump_offset;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_BNE: begin
          id_branch_taken = id_compare_difference[31:0] != 0;
          id_next_pc = (id_pc + 32'd4) + id_jump_offset;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_BLT: begin
          id_branch_taken = id_compare_signed_less;
          id_next_pc = (id_pc + 32'd4) + id_jump_offset;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_BGE: begin
          id_branch_taken = !id_compare_signed_less;
          id_next_pc = (id_pc + 32'd4) + id_jump_offset;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_BLTU: begin
          id_branch_taken = id_compare_difference[32];
          id_next_pc = (id_pc + 32'd4) + id_jump_offset;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_BGEU: begin
          id_branch_taken = !id_compare_difference[32];
          id_next_pc = (id_pc + 32'd4) + id_jump_offset;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_BRA: begin
          id_branch_taken = 1'b1;
          id_next_pc = (id_pc + 32'd4) + id_bra_offset;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_JAL: begin
          id_branch_taken = 1'b1;
          id_next_pc = (id_pc + 32'd4) + id_jump_offset;
          id_result = id_pc + 32'd4;
          id_reg_write = 1'b1;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_JALR: begin
          id_branch_taken = 1'b1;
          id_next_pc = (register_a + id_jump_offset) & ~32'd3;
          id_result = id_pc + 32'd4;
          id_reg_write = 1'b1;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_JR: begin
          id_branch_taken = 1'b1;
          id_next_pc = register_a & ~32'd3;
          id_class = OPCLASS_BRANCH;
        end

        OPCODE_HALT: begin
          id_halt_after_retire = 1'b1;
        end
        OPCODE_TRAP: begin
          id_class = OPCLASS_ERROR;
          id_error_code = ERROR_EXPLICIT_TRAP;
        end

        default: begin
          id_class = OPCLASS_ERROR;
          id_error_code = ERROR_INVALID_OPCODE;
        end
      endcase
    end
  end

  // IF -> ID boundary registers.
  always @(posedge clk) begin
    if (reset) begin
      id_valid <= 1'b0;
      id_pc <= 32'd0;
      id_instruction <= 32'd0;
    end else if (halted || ctl_flush) begin
      id_valid <= 1'b0;
    end else if (ctl_advance && !raw_hazard) begin
      if (id_redirects_fetch) begin
        id_valid <= 1'b0;
      end else begin
        id_valid <= if_valid;
        id_pc <= if_pc;
        id_instruction <= if_instruction;
      end
    end
  end

  // ======================================================================
  // 04. EX — MEMORY STAGE
  // ======================================================================

  // Despite the prefix, this stage only does the memory access: the ALU and
  // the branch decision run in ID, so ex_result already holds the result
  // (or the load/store address) when the instruction gets here.

  assign ex_is_memory = ex_valid &&
      (ex_class == OPCLASS_LOAD || ex_class == OPCLASS_STORE);

  always @* begin
    case (dmem_address[1:0])
      2'd0: ex_load_byte = dmem_read_data[7:0];
      2'd1: ex_load_byte = dmem_read_data[15:8];
      2'd2: ex_load_byte = dmem_read_data[23:16];
      default: ex_load_byte = dmem_read_data[31:24];
    endcase
    ex_load_half = dmem_address[1] ? dmem_read_data[31:16] : dmem_read_data[15:0];
    case (ex_load_size)
      2'd0:
        ex_load_extended =
            ex_load_signed ? {{24{ex_load_byte[7]}}, ex_load_byte} : {24'd0, ex_load_byte};
      2'd1:
        ex_load_extended =
            ex_load_signed ? {{16{ex_load_half[15]}}, ex_load_half} : {16'd0, ex_load_half};
      default: ex_load_extended = dmem_read_data;
    endcase
  end

  // ID -> EX boundary and data-memory transaction state.
  always @(posedge clk) begin
    if (reset) begin
      ex_valid <= 1'b0;
      ex_pc <= 32'd0;
      ex_next_pc <= 32'd0;
      ex_rd <= 5'd0;
      ex_result <= 32'd0;
      ex_store_data <= 32'd0;
      ex_store_mask <= 4'b0000;
      ex_load_size <= 2'd2;
      ex_load_signed <= 1'b0;
      ex_reg_write <= 1'b0;
      ex_halt_after_retire <= 1'b0;
      ex_class <= OPCLASS_NORMAL;
      ex_error_code <= ERROR_NONE;
      ex_mem_request_sent <= 1'b0;
      dmem_valid <= 1'b0;
      dmem_address <= 32'd0;
      dmem_write_data <= 32'd0;
      dmem_write_enable <= 4'b0000;
    end else if (halted || ctl_flush) begin
      ex_valid <= 1'b0;
      ex_mem_request_sent <= 1'b0;
      dmem_valid <= 1'b0;
      dmem_write_enable <= 4'b0000;
    end else begin
      if (ctl_advance) begin
        if (!raw_hazard) begin
          ex_valid <= id_valid;
          ex_pc <= id_pc;
          ex_next_pc <= id_branch_taken ? id_next_pc : (id_pc + 32'd4);
          ex_rd <= id_rd;
          ex_result <= id_result;
          ex_store_data <= id_store_data;
          ex_store_mask <= id_store_mask;
          ex_load_size <= id_access_size;
          ex_load_signed <= id_access_signed;
          ex_reg_write <= id_reg_write;
          ex_halt_after_retire <= id_halt_after_retire;
          ex_class <= id_class;
          ex_error_code <= id_error_code;
          ex_mem_request_sent <= 1'b0;
        end else begin
          ex_valid <= 1'b0;
        end
      end
      if (ctl_memory) begin
        if (!ex_mem_request_sent) begin
          dmem_address <= ex_result;
          dmem_write_data <= ex_store_data;
          dmem_write_enable <= (ex_class == OPCLASS_STORE) ? ex_store_mask : 4'b0000;
          dmem_valid <= 1'b1;
          ex_mem_request_sent <= 1'b1;
        end else if (dmem_ready) begin
          dmem_valid <= 1'b0;
          dmem_write_enable <= 4'b0000;
          ex_valid <= 1'b0;
          ex_mem_request_sent <= 1'b0;
        end
      end
    end
  end

  // ======================================================================
  // 05. WB — RETIRE STATE
  // ======================================================================

  assign debug_pc = architectural_pc;

  // EX -> WB boundary, architectural retirement and error reporting.
  always @(posedge clk) begin
    instruction_retired <= 1'b0;
    if (reset) begin
      wb_valid <= 1'b0;
      wb_pc <= 32'd0;
      wb_next_pc <= 32'd0;
      wb_rd <= 5'd0;
      wb_result <= 32'd0;
      wb_reg_write <= 1'b0;
      wb_halt_after_retire <= 1'b0;
      wb_error <= 1'b0;
      wb_error_code <= ERROR_NONE;
      error <= 1'b0;
      error_code <= ERROR_NONE;
      architectural_pc <= 32'd0;
    end else if (halted || ctl_abort) begin
      wb_valid <= 1'b0;
    end else if (ctl_fault) begin
      error <= 1'b1;
      error_code <= wb_error_code;
      architectural_pc <= wb_pc;
      wb_valid <= 1'b0;
    end else begin
      if (ctl_retire) begin
        instruction_retired <= 1'b1;
        architectural_pc <= wb_next_pc;
        wb_valid <= 1'b0;
      end
      if (ctl_advance && ex_valid) begin
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
      if (ctl_memory && ex_mem_request_sent && dmem_ready) begin
        wb_valid <= 1'b1;
        wb_pc <= ex_pc;
        wb_next_pc <= ex_next_pc;
        wb_rd <= ex_rd;
        wb_result <= ex_load_extended;
        wb_reg_write <= ex_class == OPCLASS_LOAD;
        wb_halt_after_retire <= ex_halt_after_retire;
        wb_error <= dmem_error;
        wb_error_code <= ERROR_MEMORY_ACCESS;
      end
    end
  end

endmodule

`default_nettype wire
