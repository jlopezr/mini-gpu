`default_nettype none

/*
 * Experimental pipelined MiniCPU.
 *
 * This prototype keeps the monitor-facing contract of the multicycle CPU:
 * reset starts halted, RUN starts free-running execution, STEP retires exactly
 * one instruction, and errors leave the architectural PC on the faulting
 * instruction.
 *
 * IF -> ID -> EX -> WB. ID decodes, reads the register file (with a bypass
 * from WB) and computes load/store addresses; EX has the ALU, the branch
 * decision and the memory access.
 *
 * Forwarding map (grep the tags):
 *   FWD-WB-EX  WB -> EX operand mux (ex_a, ex_b): the result of the
 *              instruction right before, for the ALU, branch compare,
 *              JALR/JR target, store data and MUL/DIV operands. Selected by
 *              ex_forward_a/b, decided in ID and registered.
 *   FWD-WB-ID  register-file bypass (id_op_a, id_op_b): the value WB writes
 *              this cycle, which the asynchronous read does not see yet.
 *   FWD-HOLD   an instruction held in EX (memory, MUL/DIV) latches its
 *              forwarded operands, since WB retires after one cycle.
 *   A load's consumer needs no path of its own: it waits in ID during the
 *   access and enters EX as the load moves to WB with its data (FWD-WB-EX).
 * Not forwarded, on purpose:
 *   AGI        a load/store whose base register is written by the
 *              instruction in EX waits one cycle (raw_hazard): the address
 *              is computed in ID, and EX -> ID forwarding would put the ALU
 *              in front of the address adder in the same cycle.
 *   Branches are decided in EX, not in ID with forwarded operands, for the
 *   same reason; prediction is what will recover their bubbles.
 *
 * Two resets. reset is the system one: the memories are reset with it, so
 * nothing is in flight afterwards. soft_reset is the monitor's RESET, which
 * restarts only the CPU while the I-cache and the D-cache may still owe it
 * responses (a program was running): it resets everything but the in-flight
 * bookkeeping (if_req_*, if_inflight, if_discard, ex_mem_drop), and what is
 * in flight becomes dropped, as when the CPU stops.
 *
 * MUL/MULHI/MULFX and DIV/DIVU/REM/REMU run in EX, which holds them for
 * several cycles like a memory access (section 04b).
 */
module cpu #(
    // REM/REMU right after their DIV/DIVU reuse its remainder instead of
    // dividing again. Invisible to the architecture: zero only changes cycles.
    parameter ALU_FAST_PATH = 1'b1,
    // Static branch prediction at the head of the IF queue, with a return
    // address stack (section 02b). Zero: every taken branch redirects from EX.
    parameter BRANCH_PREDICT = 1'b1,
    // Branch target buffer looked up with each fetch request (section 02c).
    // Needs BRANCH_PREDICT.
    parameter BTB = 1'b1,
    // 2^BTB_BITS entries, direct-mapped by pc[BTB_BITS+1:2], with a partial
    // tag of BTB_TAG_BITS bits above the index. Small values only make sense
    // in a testbench, to force aliasing.
    parameter integer BTB_BITS = 6,
    parameter integer BTB_TAG_BITS = 10
) (
    input clk,
    input reset,
    input soft_reset,

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

    // dmem, como imem: peticion (valid/ready, aceptada cuando los dos estan
    // altos) y respuesta (rvalid + read_data + error, una por peticion y en
    // orden). La peticion sale de los registros de EX en su primer ciclo.
    output dmem_valid,
    output [31:0] dmem_address,
    output [31:0] dmem_write_data,
    output [3:0] dmem_write_enable,
    input dmem_ready,
    input [31:0] dmem_read_data,
    input dmem_rvalid,
    input dmem_error,
    // Hay un acceso a datos en EX sin terminar: para STALL_MEM/STALL_MMIO.
    output dmem_waiting,

    input [4:0] debug_register_address,
    output [31:0] debug_register_data,
    output [31:0] debug_pc,

    // Why the ID -> EX transfer did not happen this cycle, one-hot and
    // registered (cpu_perf_counters, PIPELINE = 1): [0] EX busy with a memory
    // access, [1] RAW hazard, [2] taken branch (the wrong-path instruction
    // that becomes a bubble, and ID empty until the target), [3] ID empty
    // for any other reason, [4] EX busy with a MUL/DIV (MULDIV = 1). All
    // zero: an instruction moved on, or the CPU is halted or stopping (STEP,
    // HALT, error).
    (* pipeline_stage = "_PERF" *) output reg [4:0] perf_stall,
    // One pulse per retired MUL/MULHI/MULFX/DIV/DIVU/REM/REMU, registered and
    // in the same cycle as instruction_retired.
    (* pipeline_stage = "WB" *) output reg perf_muldiv_retired
);

  // Everything but the in-flight bookkeeping (header): reset or soft_reset.
  wire core_reset = reset || soft_reset;

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
  // Stays in EX until the multiplier or divider is done, then becomes
  // OPCLASS_NORMAL with its result in ex_result.
  localparam [2:0] OPCLASS_MULDIV = 3'd5;

  // EX's ALU operation (ex_alu_op). b is the immediate when ex_alu_imm.
  localparam [3:0] ALU_ADD = 4'd0;
  localparam [3:0] ALU_SUB = 4'd1;
  localparam [3:0] ALU_AND = 4'd2;
  localparam [3:0] ALU_OR = 4'd3;
  localparam [3:0] ALU_XOR = 4'd4;
  localparam [3:0] ALU_SHL = 4'd5;
  localparam [3:0] ALU_SHR = 4'd6;
  localparam [3:0] ALU_SAR = 4'd7;
  localparam [3:0] ALU_SLT = 4'd8;
  localparam [3:0] ALU_SLTU = 4'd9;

  // Branch condition in EX (ex_branch_cond), comparing a with b.
  localparam [2:0] BRANCH_EQ = 3'd0;
  localparam [2:0] BRANCH_NE = 3'd1;
  localparam [2:0] BRANCH_LT = 3'd2;
  localparam [2:0] BRANCH_GE = 3'd3;
  localparam [2:0] BRANCH_LTU = 3'd4;
  localparam [2:0] BRANCH_GEU = 3'd5;
  localparam [2:0] BRANCH_ALWAYS = 3'd6;

  // Return address stack: entries, and bits to index them.
  localparam integer RAS_DEPTH = 8;
  localparam integer RAS_BITS = 3;

  localparam integer BTB_ENTRIES = 1 << BTB_BITS;

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
  wire ctl_start;
  wire ctl_abort;
  wire ctl_fault;
  wire ctl_retire;
  wire ctl_retire_stop;
  wire ctl_flush;
  wire ctl_advance;
  wire ctl_memory;
  wire ctl_muldiv;
  (* pipeline_stage = "_PERF" *) reg perf_after_redirect;
  (* pipeline_stage = "_PERF" *) reg perf_after_predict;

  // Register file
  wire [31:0] register_a;
  wire [31:0] register_b;
  wire register_file_busy;
  wire register_write_enable;
  wire [4:0] register_write_address;
  wire [31:0] register_write_data;

  // IF: fetch queue. Entry 0 (if_valid/if_pc/if_instruction) is the head
  // that ID takes; entries 1 to 3 are behind it.
  reg if_valid, if_valid1, if_valid2, if_valid3;
  reg [31:0] if_pc, if_pc1, if_pc2, if_pc3;
  reg [31:0] if_instruction, if_instruction1, if_instruction2, if_instruction3;
  // Requests in flight, in order (section 02c): the PC of each, and whether
  // the BTB sent the next request to a target. A response takes its entry.
  reg [31:0] if_req_pc [0:3];
  reg if_req_btb [0:3];
  reg [31:0] if_req_target [0:3];
  // Fetched after a BTB hit, before the redirect: the fall-through slot.
  reg if_req_drop [0:3];
  reg [1:0] if_req_write;
  reg [1:0] if_req_read;
  wire [31:0] if_response_pc;
  wire if_response_btb;
  wire [31:0] if_response_target;
  wire if_response_drop;
  // Up to four: entries + in flight never pass four (imem_valid), but after
  // a redirect the queue is empty and all four can be in flight.
  reg [2:0] if_inflight;
  reg [2:0] if_discard;
  wire [2:0] if_used;
  wire if_accept;
  wire if_keep;
  wire if_pop;
  wire [2:0] if_inflight_next;
  reg if_valid_n, if_valid1_n, if_valid2_n, if_valid3_n;
  reg [31:0] if_pc_n, if_pc1_n, if_pc2_n, if_pc3_n;
  reg [31:0] if_instruction_n, if_instruction1_n, if_instruction2_n, if_instruction3_n;
  // Per entry: the BTB predicted it taken when it was fetched, and where.
  reg if_btb, if_btb1, if_btb2, if_btb3;
  reg [31:0] if_btb_target, if_btb_target1, if_btb_target2, if_btb_target3;
  reg if_btb_n, if_btb1_n, if_btb2_n, if_btb3_n;
  reg [31:0] if_btb_target_n, if_btb_target1_n, if_btb_target2_n, if_btb_target3_n;
  // A taken branch, registered: IF redirects the cycle after EX decides.
  reg if_redirect;
  reg [31:0] if_redirect_pc;
  // Predecode of the queue head, for ID's source registers (section 02).
  wire [5:0] if_opcode;
  wire if_compare_branch;
  wire if_store;
  wire if_memory;
  wire [4:0] if_src_a;
  wire [4:0] if_src_b;
  // Static prediction of the queue head (section 02b).
  wire if_call;
  wire if_return;
  wire if_static_taken;
  wire [31:0] if_static_target;
  wire if_predict_taken;
  wire [31:0] if_predict_target;
  wire if_take;
  wire if_predict_pop;
  reg [31:0] if_ras [0:RAS_DEPTH-1];
  reg [RAS_BITS-1:0] if_ras_top;
  reg [RAS_BITS:0] if_ras_count;
  // Branch target buffer (section 02c).
  reg [BTB_ENTRIES-1:0] if_btb_valid;
  reg [BTB_TAG_BITS-1:0] if_btb_tag [0:BTB_ENTRIES-1];
  reg [29:0] if_btb_dest [0:BTB_ENTRIES-1];
  reg [1:0] if_btb_counter [0:BTB_ENTRIES-1];
  reg if_btb_return [0:BTB_ENTRIES-1];
  wire [BTB_BITS-1:0] if_lookup_index;
  wire if_lookup_hit;
  wire if_lookup_taken;
  wire [31:0] if_lookup_target;
  // The lookup of the request accepted last cycle predicted taken: fetch
  // goes to its target now (registered, section 02c).
  reg if_btb_lookup_taken;
  reg [31:0] if_btb_redirect_pc;
  // The queue was emptied in the cycle of that lookup: its request is stale.
  reg if_btb_stale;
  wire if_btb_redirect;

  // ID
  reg id_valid;
  // ID holds an instruction that will run: not the wrong-path one that came
  // in behind a taken branch (it sits in ID during the if_redirect cycle).
  wire id_live;
  reg [31:0] id_pc;
  reg [31:0] id_instruction;
  wire [5:0] id_opcode;
  wire [4:0] id_rd;
  wire [4:0] id_ra;
  wire [4:0] id_rb;
  // Register-file sources and whether it is a load/store, from IF's
  // predecode (section 02), loaded with id_instruction (section 03).
  reg [4:0] id_src_a;
  reg [4:0] id_src_b;
  reg id_memory;
  // IF predicted it taken, and where it sent the fetch (section 02b).
  reg id_predicted;
  reg [31:0] id_predict_target;
  // JR R31, mini-cc's return: the BTB marks its entries as returns.
  wire id_return;
  // A predicted PC-relative target that is not this branch's (a BTB entry
  // that belongs to another branch, or to an old program).
  wire id_target_wrong;
  wire [31:0] id_imm_signed;
  wire [31:0] id_imm_unsigned;
  wire [31:0] id_jump_offset;
  wire [31:0] id_bra_offset;
  wire id_shift_immediate;
  // Operands: the register file, or WB's result if WB is about to write it.
  wire id_bypass_a;
  wire id_bypass_b;
  wire [31:0] id_op_a;
  wire [31:0] id_op_b;
  // EX takes the operand from WB next cycle: the instruction in EX writes it.
  wire id_forward_a;
  wire id_forward_b;
  reg [1:0] id_access_size;
  reg id_access_signed;
  wire [31:0] id_effective_address;
  wire id_address_misaligned;
  reg [3:0] id_store_mask;
  reg id_encoding_valid;
  wire raw_hazard;
  reg [31:0] id_result;
  reg id_use_alu;
  reg [3:0] id_alu_op;
  reg id_alu_imm;
  reg [31:0] id_imm;
  reg [2:0] id_branch_cond;
  reg id_branch_register;
  reg [31:0] id_branch_target;
  reg id_reg_write;
  reg id_halt_after_retire;
  reg [2:0] id_class;
  reg [7:0] id_error_code;

  // EX
  reg ex_valid;
  reg [31:0] ex_pc;
  reg [31:0] ex_next_pc;
  reg [4:0] ex_rd;
  // Computed in ID: the load/store address, a constant result (MOVI, JAL's
  // return address...), and the MUL/DIV result once it is done.
  reg [31:0] ex_result;
  // Operands as ID read them, and whether to take WB's result instead
  // (forwarding). While EX holds an instruction they keep the forwarded
  // value: WB retires after one cycle.
  reg [31:0] ex_op_a;
  reg [31:0] ex_op_b;
  reg ex_forward_a;
  reg ex_forward_b;
  wire [31:0] ex_a;
  wire [31:0] ex_b;
  // ALU and branch, decoded in ID.
  reg ex_use_alu;
  reg [3:0] ex_alu_op;
  reg ex_alu_imm;
  reg [31:0] ex_imm;
  reg [2:0] ex_branch_cond;
  reg ex_branch_register;
  reg [31:0] ex_branch_target;
  wire [31:0] ex_alu_b;
  wire [31:0] ex_sum;
  wire [32:0] ex_difference;
  wire ex_signed_less;
  reg [31:0] ex_alu_result;
  reg ex_taken;
  wire ex_redirects;
  wire [31:0] ex_target;
  reg ex_predicted;
  reg [31:0] ex_predict_target;
  reg ex_return;
  reg ex_target_wrong;
  wire ex_is_branch;
  wire ex_branch_taken;
  // BTB update when a branch leaves EX (section 02c).
  wire [BTB_BITS-1:0] ex_btb_index;
  wire [BTB_TAG_BITS-1:0] ex_btb_tag;
  wire ex_btb_hit;
  wire [1:0] ex_btb_counter;
  wire ex_btb_update;
  // The update, registered: written into the BTB one cycle later, so that
  // ctl_advance and ex_target do not reach the table.
  reg if_btb_write;
  reg if_btb_write_taken;
  reg if_btb_write_hit;
  reg [BTB_BITS-1:0] if_btb_write_index;
  reg [BTB_TAG_BITS-1:0] if_btb_write_tag;
  reg [29:0] if_btb_write_dest;
  reg if_btb_write_return;
  reg [1:0] if_btb_write_counter;
  reg if_btb_write_kill;
  wire ex_wrong_return;
  wire [31:0] ex_redirect_pc;
  reg [31:0] ex_store_data;
  reg [3:0] ex_store_mask;
  reg [1:0] ex_load_size;
  reg ex_load_signed;
  reg ex_reg_write;
  reg ex_halt_after_retire;
  reg [2:0] ex_class;
  reg [7:0] ex_error_code;
  reg ex_mem_request_sent;   // accepted, waiting for its response
  reg [1:0] ex_mem_drop;     // responses still to come that nobody waits for
  wire ex_mem_posted;
  wire ex_mem_done;
  reg [31:0] ex_load_extended;
  reg [7:0] ex_load_byte;
  reg [15:0] ex_load_half;
  wire ex_is_memory;

  // EX: multiplier and divider (section 04b), on ex_a and ex_b.
  wire ex_is_muldiv;
  wire ex_md_run;
  reg [5:0] ex_md_op;          // opcode
  reg [4:0] ex_md_ra;
  reg [4:0] ex_md_rb;
  reg ex_md_fast;              // REM/REMU that reuses the previous remainder
  reg ex_md_counted;           // a MUL/DIV, for perf_muldiv_retired (ex_class
                               // turns NORMAL when it is done)
  reg wb_md_counted;
  reg [5:0] ex_md_step;
  wire ex_md_is_div;
  wire ex_md_signed_div;
  // The md_* registers are EX's: its logic reads them while the MUL/DIV waits.
  (* pipeline_stage = "EX" *) reg [31:0] md_ll, md_lh, md_hl, md_hh;
  (* pipeline_stage = "EX" *) reg [31:0] md_correction;
  (* pipeline_stage = "EX" *) reg [63:0] md_product;
  wire [31:0] md_high_signed;
  reg [31:0] md_mul_result;
  (* pipeline_stage = "EX" *) reg [31:0] md_dividend;
  (* pipeline_stage = "EX" *) reg [31:0] md_divisor;
  (* pipeline_stage = "EX" *) reg [31:0] md_quotient;
  (* pipeline_stage = "EX" *) reg [31:0] md_remainder;
  (* pipeline_stage = "EX" *) reg md_quotient_negative;
  (* pipeline_stage = "EX" *) reg md_remainder_negative;
  wire [31:0] md_shifted;
  wire md_subtract;
  reg [31:0] md_div_result;
  // Last completed DIV/DIVU, for the REM/REMU fast path.
  (* pipeline_stage = "EX" *) reg md_tag_valid;
  (* pipeline_stage = "EX" *) reg md_tag_unsigned;
  (* pipeline_stage = "EX" *) reg [4:0] md_tag_ra;
  (* pipeline_stage = "EX" *) reg [4:0] md_tag_rb;
  wire id_md_fast;

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
  assign id_live = id_valid && !if_redirect;

  // Per-cycle decisions.
  assign ctl_start = halted &&
      (ctl_start_pending || run_request || step_request) && !register_file_busy;
  assign ctl_abort = !halted && halt_request;
  assign ctl_fault = !halted && !halt_request && wb_valid && wb_error;
  assign ctl_retire = !halted && !halt_request && wb_valid && !wb_error;
  assign ctl_retire_stop = ctl_retire &&
      (wb_halt_after_retire || ctl_step_active);
  assign ctl_flush = ctl_abort || ctl_fault || ctl_retire_stop;
  // A memory access lets the next instruction into EX in the cycle it ends
  // (ex_mem_done), not the one after: dmem_ready and dmem_rvalid come from
  // registers in dcache.v and cpu_dmem_adapter.v.
  assign ctl_advance = !halted && !halt_request && !wb_stops_machine &&
      !(ex_is_memory && !ex_mem_done) && !ex_is_muldiv;
  assign ctl_memory = !halted && !halt_request &&
      !wb_stops_machine && ex_is_memory;
  assign ctl_muldiv = !halted && !halt_request &&
      !wb_stops_machine && ex_is_muldiv;

  // Performance accounting at the ID -> EX transfer: every running cycle is
  // either an instruction moving on or exactly one reason it did not, so the
  // reasons add up to CYCLES - RETIRED (minus STEP/HALT/error cycles). Taken
  // here and registered, so raw_hazard only feeds one LUT and one FF next to
  // ID instead of a wire across the chip. When EX redirects, what moves from
  // ID is on the wrong path and becomes a bubble: it counts as a branch.
  always @(posedge clk) begin
    if (core_reset || halted) begin
      perf_stall <= 5'b00000;
      perf_after_redirect <= 1'b0;
      perf_after_predict <= 1'b0;
    end else begin
      perf_stall <= 5'b00000;
      if (ctl_memory && !ex_mem_done)
        perf_stall[0] <= 1'b1;
      else if (ctl_muldiv)
        perf_stall[4] <= 1'b1;
      else if (ctl_advance && ex_redirects)
        perf_stall[2] <= 1'b1;
      else if (ctl_advance && id_live && raw_hazard)
        perf_stall[1] <= 1'b1;
      else if (ctl_advance && !id_live)
        perf_stall[(perf_after_redirect || perf_after_predict) ? 2 : 3] <= 1'b1;

      // Set by a taken branch; cleared once ID holds the first instruction of
      // the new path.
      if (ctl_advance && ex_redirects)
        perf_after_redirect <= 1'b1;
      else if (id_live)
        perf_after_redirect <= 1'b0;
      // A predicted-taken branch leaves ID empty until its target arrives;
      // those cycles are the branch's too. Cleared when the target is popped.
      if (if_predict_pop)
        perf_after_predict <= 1'b1;
      else if (if_take)
        perf_after_predict <= 1'b0;
    end
  end

  // Control FSM: only this process owns ctl_* and halted.
  always @(posedge clk) begin
    if (core_reset) begin
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
  // source fields; the value WB writes at the end of this cycle reaches ID
  // through id_bypass_a/b (section 03).

  // ctl_retire is exactly the cycle WB retires. A write during reset is
  // harmless: reset restarts the clearing sweep, which overwrites it.
  assign register_write_enable = ctl_retire && wb_reg_write;
  assign register_write_address = wb_rd;
  assign register_write_data = wb_result;

  register_file register_file_i (
      .clk(clk),
      .reset(core_reset),
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
   * whenever its response is sure to fit: the four queue entries count both
   * the instructions already there and the requests still in flight. The
   * count does not look at whether ID takes the head this cycle, so the
   * pipeline's decisions (raw_hazard, ex_redirects) stay out of imem_valid. A
   * hit answers two cycles after the request (the I-cache registers its
   * response), so four entries are exactly enough for one instruction per
   * cycle: two requests in flight, the response, and ID taking it.
   *
   * A redirect (taken branch) or a stop (abort, fault, STEP/HALT retire)
   * empties the queue, and the responses still in flight belong to the old
   * path: if_discard counts them and they are dropped as they arrive. They
   * arrive in order, so a count is enough.
   *
   * The redirect is registered (if_redirect, if_redirect_pc): in the cycle
   * EX decides a taken branch, IF and ID carry on as if it were not taken,
   * the branch moves to WB and the instruction behind it enters EX as a
   * bubble (ex_valid, one LUT after the compare); the next cycle IF empties
   * the queue and fetches the target, and ID drops the wrong-path
   * instruction it took (id_live). So the 33-bit compare ends in a few
   * registers instead of steering the queue, if_pop and ID's load in the
   * same cycle. A taken branch costs six bubbles, which branch prediction
   * can win back. cpu_redirect_tb checks the wrong-path slots.
   */
  assign if_used = {2'b00, if_valid} + {2'b00, if_valid1} + {2'b00, if_valid2} +
                   {2'b00, if_valid3} + if_inflight;
  assign imem_valid = !halted && (if_used < 3'd4);
  assign if_accept = imem_valid && imem_ready;
  assign if_keep = imem_rvalid && (if_discard == 3'd0) && !if_response_drop;
  assign if_inflight_next = if_inflight + {2'b00, if_accept} - {2'b00, imem_rvalid};
  assign if_pop = ctl_advance && !raw_hazard && if_valid;

  // Next queue contents without a flush: pop the head if ID takes it, then
  // put a kept response in the first free entry.
  always @* begin
    if_valid_n = if_valid;    if_pc_n = if_pc;    if_instruction_n = if_instruction;
    if_valid1_n = if_valid1;  if_pc1_n = if_pc1;  if_instruction1_n = if_instruction1;
    if_valid2_n = if_valid2;  if_pc2_n = if_pc2;  if_instruction2_n = if_instruction2;
    if_valid3_n = if_valid3;  if_pc3_n = if_pc3;  if_instruction3_n = if_instruction3;
    if_btb_n = if_btb;    if_btb_target_n = if_btb_target;
    if_btb1_n = if_btb1;  if_btb_target1_n = if_btb_target1;
    if_btb2_n = if_btb2;  if_btb_target2_n = if_btb_target2;
    if_btb3_n = if_btb3;  if_btb_target3_n = if_btb_target3;
    if (if_pop) begin
      if_valid_n = if_valid1;  if_pc_n = if_pc1;  if_instruction_n = if_instruction1;
      if_valid1_n = if_valid2; if_pc1_n = if_pc2; if_instruction1_n = if_instruction2;
      if_valid2_n = if_valid3; if_pc2_n = if_pc3; if_instruction2_n = if_instruction3;
      if_valid3_n = 1'b0;
      if_btb_n = if_btb1;   if_btb_target_n = if_btb_target1;
      if_btb1_n = if_btb2;  if_btb_target1_n = if_btb_target2;
      if_btb2_n = if_btb3;  if_btb_target2_n = if_btb_target3;
    end
    if (if_keep) begin
      if (!if_valid_n) begin
        if_valid_n = 1'b1;  if_pc_n = if_response_pc;  if_instruction_n = imem_read_data;
        if_btb_n = if_response_btb;  if_btb_target_n = if_response_target;
      end else if (!if_valid1_n) begin
        if_valid1_n = 1'b1; if_pc1_n = if_response_pc; if_instruction1_n = imem_read_data;
        if_btb1_n = if_response_btb; if_btb_target1_n = if_response_target;
      end else if (!if_valid2_n) begin
        if_valid2_n = 1'b1; if_pc2_n = if_response_pc; if_instruction2_n = imem_read_data;
        if_btb2_n = if_response_btb; if_btb_target2_n = if_response_target;
      end else begin
        if_valid3_n = 1'b1; if_pc3_n = if_response_pc; if_instruction3_n = imem_read_data;
        if_btb3_n = if_response_btb; if_btb_target3_n = if_response_target;
      end
    end
  end

  assign if_response_pc = if_req_pc[if_req_read];
  assign if_response_btb = if_req_btb[if_req_read];
  assign if_response_target = if_req_target[if_req_read];
  assign if_response_drop = if_req_drop[if_req_read];
  assign if_btb_redirect = if_btb_lookup_taken && !if_btb_stale;

  // Every accepted request gets one response, in order, kept or dropped.
  always @(posedge clk) begin
    if (reset) begin
      if_req_write <= 2'd0;
      if_req_read <= 2'd0;
    end else begin
      if (if_accept) begin
        if_req_pc[if_req_write] <= imem_address;
        if_req_btb[if_req_write] <= if_lookup_taken;
        if_req_target[if_req_write] <= if_lookup_target;
        if_req_drop[if_req_write] <= if_btb_redirect;
        if_req_write <= if_req_write + 2'd1;
      end
      if (imem_rvalid) if_req_read <= if_req_read + 2'd1;
    end
  end

  always @(posedge clk) begin
    if (core_reset) begin
      imem_address <= 32'd0;
      // soft_reset: the I-cache still answers what it accepted; drop it.
      if_inflight <= reset ? 3'd0 : if_inflight_next;
      if_discard <= reset ? 3'd0 : if_inflight_next;
      if_valid <= 1'b0;
      if_valid1 <= 1'b0;
      if_valid2 <= 1'b0;
      if_valid3 <= 1'b0;
      if_pc <= 32'd0;
      if_pc1 <= 32'd0;
      if_pc2 <= 32'd0;
      if_pc3 <= 32'd0;
      if_instruction <= 32'd0;
      if_instruction1 <= 32'd0;
      if_instruction2 <= 32'd0;
      if_instruction3 <= 32'd0;
      if_btb <= 1'b0;
      if_btb1 <= 1'b0;
      if_btb2 <= 1'b0;
      if_btb3 <= 1'b0;
      if_btb_target <= 32'd0;
      if_btb_target1 <= 32'd0;
      if_btb_target2 <= 32'd0;
      if_btb_target3 <= 32'd0;
      if_redirect <= 1'b0;
      if_redirect_pc <= 32'd0;
      if_btb_lookup_taken <= 1'b0;
      if_btb_redirect_pc <= 32'd0;
      if_btb_stale <= 1'b0;
    end else begin
      // Not from a request that is itself the dropped fall-through slot. One
      // accepted in a cycle that empties the queue is stale: that is kept in
      // its own register (if_btb_stale) so that ctl_advance -> if_pop does
      // not reach this one.
      if_btb_lookup_taken <= if_accept && if_lookup_taken && !if_btb_redirect;
      if_btb_redirect_pc <= if_lookup_target;
      if_btb_stale <= halted || ctl_abort || ctl_fault || ctl_retire_stop ||
                      if_redirect || if_predict_pop;
      // ctl_advance is low in any cycle that stops the machine, so a stop
      // never leaves a redirect behind.
      if_redirect <= ctl_advance && ex_redirects;
      if_redirect_pc <= ex_redirect_pc;
      if_inflight <= if_inflight_next;
      if (if_accept) imem_address <= imem_address + 32'd4;

      if (halted || ctl_abort || ctl_fault || ctl_retire_stop ||
          if_redirect) begin
        // Empty the queue; whatever is still in flight is stale.
        if_valid <= 1'b0;
        if_valid1 <= 1'b0;
        if_valid2 <= 1'b0;
        if_valid3 <= 1'b0;
        if_discard <= if_inflight_next;
        if (halted) begin
          if (ctl_start) imem_address <= architectural_pc;
        end else if (!(ctl_abort || ctl_fault || ctl_retire_stop)) begin
          imem_address <= if_redirect_pc;
        end
      end else if (if_predict_pop) begin
        // The head goes to ID and is predicted taken: what is behind it in
        // the queue, and in flight, is the fall-through path. ID keeps it.
        if_valid <= 1'b0;
        if_valid1 <= 1'b0;
        if_valid2 <= 1'b0;
        if_valid3 <= 1'b0;
        if_discard <= if_inflight_next;
        imem_address <= if_static_target;
      end else begin
        if_valid <= if_valid_n;    if_pc <= if_pc_n;    if_instruction <= if_instruction_n;
        if_valid1 <= if_valid1_n;  if_pc1 <= if_pc1_n;  if_instruction1 <= if_instruction1_n;
        if_valid2 <= if_valid2_n;  if_pc2 <= if_pc2_n;  if_instruction2 <= if_instruction2_n;
        if_valid3 <= if_valid3_n;  if_pc3 <= if_pc3_n;  if_instruction3 <= if_instruction3_n;
        if_btb <= if_btb_n;    if_btb_target <= if_btb_target_n;
        if_btb1 <= if_btb1_n;  if_btb_target1 <= if_btb_target1_n;
        if_btb2 <= if_btb2_n;  if_btb_target2 <= if_btb_target2_n;
        if_btb3 <= if_btb3_n;  if_btb_target3 <= if_btb_target3_n;
        if (imem_rvalid && if_discard != 3'd0) if_discard <= if_discard - 3'd1;
        if (if_btb_redirect) imem_address <= if_btb_redirect_pc;
      end
    end
  end

  /*
   * Predecode. Which fields name the register-file sources, and whether the
   * instruction is a load/store, depends only on the opcode, so it is worked
   * out here, from the head of the IF queue (if_instruction, a register with
   * time to spare), and stored next to id_instruction at the IF -> ID
   * boundary (section 03). At the head and not where the I-cache response
   * enters the queue, so as not to lengthen the EBR path.
   *
   * ID then reads the register file, and compares against ex_rd/wb_rd for
   * forwarding, straight from registers: the opcode decode (a range compare
   * that Yosys builds as a carry chain) is not at the head of ID's critical
   * path.
   *   - conditional branches compare rd with ra;
   *   - stores write the data in rd;
   *   - everything else reads ra and rb.
   * An instruction that does not read a source may still get it forwarded:
   * it never looks at it.
   */
  assign if_opcode = if_instruction[31:26];
  assign if_compare_branch = if_opcode >= OPCODE_BEQ && if_opcode <= OPCODE_BGEU;
  assign if_store = if_opcode == OPCODE_STORE || if_opcode == OPCODE_STOREB ||
                    if_opcode == OPCODE_STOREH;
  assign if_memory = if_store || if_opcode == OPCODE_LOAD ||
                     if_opcode == OPCODE_LOADB || if_opcode == OPCODE_LOADUB ||
                     if_opcode == OPCODE_LOADH || if_opcode == OPCODE_LOADUH;
  assign if_src_a = if_compare_branch ? if_instruction[25:21] : if_instruction[20:16];
  assign if_src_b = if_compare_branch ? if_instruction[20:16] :
                    (if_store ? if_instruction[25:21] : if_instruction[15:11]);

  // ======================================================================
  // 02b. IF — STATIC BRANCH PREDICTION AND RETURN ADDRESS STACK
  // ======================================================================

  /*
   * When ID takes the queue head (if_pop), IF predicts it from its opcode:
   *   - BRA and JAL: always taken (they cannot fail);
   *   - conditional branches backwards (negative offset): taken, the end of
   *     a loop; forwards: not taken (backward-taken, forward-not-taken);
   *   - JR R31 (mini-cc's return): taken, to the top of the return address
   *     stack, if it is not empty. Calls (JAL/JALR with rd = R31) push pc+4.
   * Predicted taken: the rest of the queue and whatever is in flight are
   * the fall-through path, so they are dropped like after a redirect, and
   * fetch goes on at the target. ID keeps the branch, with id_predicted and
   * the target it predicted.
   *
   * EX checks (ex_redirects): it redirects only if the prediction was wrong
   * -- taken and not predicted, predicted and not taken (back to pc+4), or a
   * return to another address --, with the same cost as an unpredicted
   * branch today. A correct one costs the fetch of its target: about three
   * bubbles instead of six.
   *
   * The stack is updated here, so the wrong path after a misprediction can
   * leave it off; that only costs a later misprediction, since EX checks.
   * The target adders read the head registers, which have time to spare.
   */
  assign if_call = (if_opcode == OPCODE_JAL || if_opcode == OPCODE_JALR) &&
                   if_instruction[25:21] == 5'd31;
  assign if_return = if_opcode == OPCODE_JR && if_instruction[20:16] == 5'd31;
  // Only for what the BTB did not predict at fetch: if it did, the queue
  // behind the head is already the target path.
  assign if_static_taken = BRANCH_PREDICT && !if_btb && (
      if_opcode == OPCODE_BRA || if_opcode == OPCODE_JAL ||
      (if_compare_branch && if_instruction[15]) ||
      (if_return && if_ras_count != 0));
  assign if_static_target =
      if_return ? if_ras[if_ras_top] :
      (if_opcode == OPCODE_BRA) ? (if_pc + 32'd4) + {{4{if_instruction[25]}}, if_instruction[25:0], 2'b00} :
                                  (if_pc + 32'd4) + {{14{if_instruction[15]}}, if_instruction[15:0], 2'b00};
  // ID really takes the head: not in the cycle a redirect empties everything.
  assign if_take = if_pop && !if_redirect;
  assign if_predict_pop = if_take && if_static_taken;
  // What ID gets: the BTB's prediction, or the static one.
  assign if_predict_taken = if_btb || if_static_taken;
  assign if_predict_target = if_btb ? if_btb_target : if_static_target;

  always @(posedge clk) begin
    if (core_reset) begin
      if_ras_top <= {RAS_BITS{1'b0}};
      if_ras_count <= {(RAS_BITS+1){1'b0}};
    end else if (BRANCH_PREDICT && if_take) begin
      if (if_call) begin
        if_ras[if_ras_top + 1'b1] <= if_pc + 32'd4;
        if_ras_top <= if_ras_top + 1'b1;
        if (if_ras_count != RAS_DEPTH) if_ras_count <= if_ras_count + 1'b1;
      end else if (if_return && if_ras_count != 0) begin
        if_ras_top <= if_ras_top - 1'b1;
        if_ras_count <= if_ras_count - 1'b1;
      end
    end
  end

  // ======================================================================
  // 02c. IF — BRANCH TARGET BUFFER
  // ======================================================================

  /*
   * Looked up with every fetch request (imem_address), and the answer
   * registered (if_btb_redirect): a hit that predicts taken sends fetch to
   * the target in the next cycle, and the request accepted in between, the
   * fall-through, is marked to be dropped (if_req_drop). A correctly
   * predicted branch costs one bubble. Sending the very next request to the
   * target would cost none, but puts the table, its tag compare and the
   * target mux inside the imem_address loop: the CPU fell from ~70 to an
   * estimated 45 MHz and nextpnr did not finish routing. Entries: partial tag,
   * target, a 2-bit counter (taken if >= 2) and a return bit; a return
   * takes the top of the return address stack (02b) instead of the target.
   * Requests are no longer sequential, so each request in flight keeps its
   * PC and prediction (if_req_*), and each queue entry carries them on to ID
   * (if_btb*). The static prediction of 02b only acts on what the BTB did not
   * predict.
   *
   * Written when a branch leaves EX (ex_btb_update): taken branches allocate
   * (counter 2, weakly taken) or count up; not taken ones count down if they
   * are there. Only branches whose target is fixed (PC-relative) and returns
   * go in; other register jumps (JALR, JR to a table) do not. Emptied (valid
   * bits) on reset and while halted: the monitor may load another program.
   * A stale or aliased entry only costs a misprediction: EX checks the
   * direction, ID the PC-relative target and EX the return address, and an
   * instruction predicted taken that is not a branch redirects to pc+4.
   */
  assign if_lookup_index = imem_address[BTB_BITS+1:2];
  assign if_lookup_hit = BTB && BRANCH_PREDICT && if_btb_valid[if_lookup_index] &&
      if_btb_tag[if_lookup_index] == imem_address[BTB_BITS+BTB_TAG_BITS+1:BTB_BITS+2];
  assign if_lookup_taken = if_lookup_hit &&
      (if_btb_return[if_lookup_index] ? (if_ras_count != 0) : if_btb_counter[if_lookup_index][1]);
  assign if_lookup_target = if_btb_return[if_lookup_index] ? if_ras[if_ras_top] :
                            {if_btb_dest[if_lookup_index], 2'b00};

  assign ex_btb_index = ex_pc[BTB_BITS+1:2];
  assign ex_btb_tag = ex_pc[BTB_BITS+BTB_TAG_BITS+1:BTB_BITS+2];
  assign ex_btb_hit = if_btb_valid[ex_btb_index] && if_btb_tag[ex_btb_index] == ex_btb_tag;
  assign ex_btb_counter = if_btb_counter[ex_btb_index];
  assign ex_btb_update = BTB && BRANCH_PREDICT && ctl_advance && ex_is_branch &&
                         (!ex_branch_register || ex_return);

  always @(posedge clk) begin
    if_btb_write <= !core_reset && !halted && ex_btb_update;
    // Predicted taken but not a branch: the entry is someone else's.
    if_btb_write_kill <= !core_reset && !halted && BTB && ctl_advance && ex_valid &&
                      !ex_is_branch && ex_predicted && ex_btb_hit;
    if_btb_write_taken <= ex_taken;
    if_btb_write_hit <= ex_btb_hit;
    if_btb_write_index <= ex_btb_index;
    if_btb_write_tag <= ex_btb_tag;
    if_btb_write_dest <= ex_target[31:2];
    if_btb_write_return <= ex_return;
    if_btb_write_counter <= ex_btb_counter;
  end

  always @(posedge clk) begin
    if (core_reset || halted) begin
      if_btb_valid <= {BTB_ENTRIES{1'b0}};
    end else if (if_btb_write) begin
      if (if_btb_write_taken) begin
        if_btb_valid[if_btb_write_index] <= 1'b1;
        if_btb_tag[if_btb_write_index] <= if_btb_write_tag;
        if_btb_dest[if_btb_write_index] <= if_btb_write_dest;
        if_btb_return[if_btb_write_index] <= if_btb_write_return;
        if_btb_counter[if_btb_write_index] <= !if_btb_write_hit ? 2'd2 :
            (if_btb_write_counter == 2'd3) ? 2'd3 : if_btb_write_counter + 2'd1;
      end else if (if_btb_write_hit) begin
        if_btb_counter[if_btb_write_index] <= (if_btb_write_counter == 2'd0) ? 2'd0 :
                                           if_btb_write_counter - 2'd1;
      end
    end else if (if_btb_write_kill) begin
      if_btb_valid[if_btb_write_index] <= 1'b0;
    end
  end

  // ======================================================================
  // 03. ID — DECODE, OPERANDS AND ADDRESSES
  // ======================================================================

  /*
   * ID decodes for EX and reads the operands; the ALU and the branch decision
   * are in EX (section 04). What ID still computes from register values is
   * the load/store address (base + offset), so that the data request leaves
   * from EX registers (dmem_address = ex_result) and the D-cache path does
   * not grow by a forwarding mux and an adder.
   *
   * Operands. The register file holds everything retired. The instruction in
   * WB writes at the end of this cycle, so ID takes WB's result directly
   * (id_bypass_*). The instruction in EX goes to WB at the same time this one
   * goes to EX, so EX will take it from WB then (id_forward_* ->
   * ex_forward_*, a register: EX's forwarding mux selects from a FF).
   *
   * The one hazard left: a load/store whose base is written by the
   * instruction in EX. Its address is needed here, so it waits one cycle and
   * then takes the value through the bypass. A load's consumer does not wait:
   * it stays in ID while the access runs, and enters EX when the load moves
   * to WB with its data.
   */

  assign id_opcode = id_instruction[31:26];
  assign id_rd = id_instruction[25:21];
  assign id_ra = id_instruction[20:16];
  assign id_rb = id_instruction[15:11];

  assign id_imm_signed = {{16{id_instruction[15]}}, id_instruction[15:0]};
  assign id_imm_unsigned = {16'h0000, id_instruction[15:0]};
  assign id_jump_offset = {{14{id_instruction[15]}}, id_instruction[15:0], 2'b00};
  assign id_bra_offset = {{4{id_instruction[25]}}, id_instruction[25:0], 2'b00};
  assign id_shift_immediate = id_instruction[10];

  // FWD-WB-ID: register-file bypass.
  assign id_bypass_a = wb_valid && wb_reg_write && wb_rd != 5'd0 && wb_rd == id_src_a;
  assign id_bypass_b = wb_valid && wb_reg_write && wb_rd != 5'd0 && wb_rd == id_src_b;
  assign id_op_a = id_bypass_a ? wb_result : register_a;
  assign id_op_b = id_bypass_b ? wb_result : register_b;
  // FWD-WB-EX, decided here: the instruction in EX goes to WB as this one goes
  // to EX, so EX will take the operand from WB (ex_forward_a/b).
  assign id_forward_a = ex_valid && ex_reg_write && ex_rd != 5'd0 && ex_rd == id_src_a;
  assign id_forward_b = ex_valid && ex_reg_write && ex_rd != 5'd0 && ex_rd == id_src_b;
  // AGI: the address needs the base now, and the instruction in EX has not
  // produced it yet. The only RAW stall.
  assign raw_hazard = id_live && id_memory && id_forward_a;

  assign id_return = id_opcode == OPCODE_JR && id_ra == 5'd31;
  assign id_target_wrong = id_predicted && !id_branch_register &&
                           id_predict_target[31:2] != id_branch_target[31:2];

  assign id_effective_address = id_op_a + id_imm_signed;
  assign id_address_misaligned = (id_access_size == 2'd2) ? (id_effective_address[1:0] != 2'b00) :
      (id_access_size == 2'd1) ? (id_effective_address[0] != 1'b0) : 1'b0;

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
      2'd0: id_store_mask = 4'b0001 << id_effective_address[1:0];
      2'd1: id_store_mask = id_effective_address[1] ? 4'b1100 : 4'b0011;
      default: id_store_mask = 4'b1111;
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

  // What EX does with the instruction. id_result is a value known here (it
  // goes to WB unless id_use_alu); EX's ALU computes a OP b, b being
  // id_imm when id_alu_imm. A branch is taken when id_branch_cond holds for
  // a and b; its target is id_branch_target, or a + id_imm (word-aligned)
  // when id_branch_register (JALR, JR: the ALU's adder).
  always @* begin
    id_result = 32'h0000_0000;
    id_use_alu = 1'b0;
    id_alu_op = ALU_ADD;
    id_alu_imm = 1'b0;
    id_imm = id_imm_signed;
    id_branch_cond = BRANCH_ALWAYS;
    id_branch_register = 1'b0;
    id_branch_target = (id_pc + 32'd4) + id_jump_offset;
    id_reg_write = 1'b0;
    id_halt_after_retire = 1'b0;
    id_class = OPCLASS_NORMAL;
    id_error_code = ERROR_NONE;

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

        OPCODE_ADD:  begin id_use_alu = 1'b1; id_alu_op = ALU_ADD; id_reg_write = 1'b1; end
        OPCODE_SUB:  begin id_use_alu = 1'b1; id_alu_op = ALU_SUB; id_reg_write = 1'b1; end
        OPCODE_AND:  begin id_use_alu = 1'b1; id_alu_op = ALU_AND; id_reg_write = 1'b1; end
        OPCODE_OR:   begin id_use_alu = 1'b1; id_alu_op = ALU_OR;  id_reg_write = 1'b1; end
        OPCODE_XOR:  begin id_use_alu = 1'b1; id_alu_op = ALU_XOR; id_reg_write = 1'b1; end
        OPCODE_SLT:  begin id_use_alu = 1'b1; id_alu_op = ALU_SLT; id_reg_write = 1'b1; end
        OPCODE_SLTU: begin id_use_alu = 1'b1; id_alu_op = ALU_SLTU; id_reg_write = 1'b1; end
        OPCODE_ADDI: begin
          id_use_alu = 1'b1; id_alu_op = ALU_ADD; id_alu_imm = 1'b1;
          id_reg_write = 1'b1;
        end
        OPCODE_ANDI: begin
          id_use_alu = 1'b1; id_alu_op = ALU_AND; id_alu_imm = 1'b1;
          id_imm = id_imm_unsigned; id_reg_write = 1'b1;
        end
        OPCODE_ORI: begin
          id_use_alu = 1'b1; id_alu_op = ALU_OR; id_alu_imm = 1'b1;
          id_imm = id_imm_unsigned; id_reg_write = 1'b1;
        end
        OPCODE_XORI: begin
          id_use_alu = 1'b1; id_alu_op = ALU_XOR; id_alu_imm = 1'b1;
          id_imm = id_imm_unsigned; id_reg_write = 1'b1;
        end

        // The shift amount is rb's field (immediate) or rb's value [4:0].
        OPCODE_SHL, OPCODE_SHR, OPCODE_SAR: begin
          id_use_alu = 1'b1;
          id_alu_op = (id_opcode == OPCODE_SHL) ? ALU_SHL :
                      (id_opcode == OPCODE_SHR) ? ALU_SHR : ALU_SAR;
          id_alu_imm = id_shift_immediate;
          id_imm = {27'd0, id_rb};
          id_reg_write = 1'b1;
        end

        OPCODE_MUL, OPCODE_MULHI, OPCODE_MULFX,
        OPCODE_DIV, OPCODE_DIVU, OPCODE_REM, OPCODE_REMU: begin
          id_class = OPCLASS_MULDIV;
          id_reg_write = 1'b1;
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

        OPCODE_BEQ:  begin id_branch_cond = BRANCH_EQ;  id_class = OPCLASS_BRANCH; end
        OPCODE_BNE:  begin id_branch_cond = BRANCH_NE;  id_class = OPCLASS_BRANCH; end
        OPCODE_BLT:  begin id_branch_cond = BRANCH_LT;  id_class = OPCLASS_BRANCH; end
        OPCODE_BGE:  begin id_branch_cond = BRANCH_GE;  id_class = OPCLASS_BRANCH; end
        OPCODE_BLTU: begin id_branch_cond = BRANCH_LTU; id_class = OPCLASS_BRANCH; end
        OPCODE_BGEU: begin id_branch_cond = BRANCH_GEU; id_class = OPCLASS_BRANCH; end
        OPCODE_BRA: begin
          id_branch_target = (id_pc + 32'd4) + id_bra_offset;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_JAL: begin
          id_result = id_pc + 32'd4;
          id_reg_write = 1'b1;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_JALR: begin
          id_branch_register = 1'b1;
          id_alu_imm = 1'b1;
          id_imm = id_jump_offset;
          id_result = id_pc + 32'd4;
          id_reg_write = 1'b1;
          id_class = OPCLASS_BRANCH;
        end
        OPCODE_JR: begin
          id_branch_register = 1'b1;
          id_alu_imm = 1'b1;
          id_imm = 32'd0;
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
    if (core_reset) begin
      id_valid <= 1'b0;
      id_pc <= 32'd0;
      id_instruction <= 32'd0;
      id_src_a <= 5'd0;
      id_src_b <= 5'd0;
      id_memory <= 1'b0;
      id_predicted <= 1'b0;
      id_predict_target <= 32'd0;
    end else if (halted || ctl_flush) begin
      id_valid <= 1'b0;
    end else if (if_redirect) begin
      // The instruction that came in behind the taken branch is dropped, and
      // so is the queue head: IF is emptying the queue this same cycle.
      id_valid <= 1'b0;
    end else if (ctl_advance && !raw_hazard) begin
      id_valid <= if_valid;
      id_pc <= if_pc;
      id_instruction <= if_instruction;
      id_src_a <= if_src_a;
      id_src_b <= if_src_b;
      id_memory <= if_memory;
      id_predicted <= if_predict_taken;
      id_predict_target <= if_predict_target;
    end
  end

  // ======================================================================
  // 04. EX — ALU, BRANCHES AND MEMORY
  // ======================================================================

  /*
   * FWD-WB-EX. ex_forward_* was decided in ID (the instruction ahead of
   * this one writes the operand), so the mux selects from a register: FF ->
   * mux -> ALU, no compare in front. The only source is WB: with the ALU
   * in EX, WB holds the result of the instruction right before, and anything
   * older is already in the register file or came through ID's bypass.
   */
  assign ex_a = ex_forward_a ? wb_result : ex_op_a;
  assign ex_b = ex_forward_b ? wb_result : ex_op_b;

  assign ex_alu_b = ex_alu_imm ? ex_imm : ex_b;
  assign ex_sum = ex_a + ex_alu_b;
  assign ex_difference = {1'b0, ex_a} - {1'b0, ex_alu_b};
  assign ex_signed_less = (ex_a[31] != ex_alu_b[31]) ? ex_a[31] : ex_difference[31];

  always @* begin
    case (ex_alu_op)
      ALU_ADD:  ex_alu_result = ex_sum;
      ALU_SUB:  ex_alu_result = ex_difference[31:0];
      ALU_AND:  ex_alu_result = ex_a & ex_alu_b;
      ALU_OR:   ex_alu_result = ex_a | ex_alu_b;
      ALU_XOR:  ex_alu_result = ex_a ^ ex_alu_b;
      ALU_SHL:  ex_alu_result = ex_a << ex_alu_b[4:0];
      ALU_SHR:  ex_alu_result = ex_a >> ex_alu_b[4:0];
      ALU_SAR:  ex_alu_result = $signed(ex_a) >>> ex_alu_b[4:0];
      ALU_SLT:  ex_alu_result = {31'd0, ex_signed_less};
      default:  ex_alu_result = {31'd0, ex_difference[32]};  // SLTU
    endcase
    case (ex_branch_cond)
      BRANCH_EQ:  ex_taken = ex_difference[31:0] == 32'd0;
      BRANCH_NE:  ex_taken = ex_difference[31:0] != 32'd0;
      BRANCH_LT:  ex_taken = ex_signed_less;
      BRANCH_GE:  ex_taken = !ex_signed_less;
      BRANCH_LTU: ex_taken = ex_difference[32];
      BRANCH_GEU: ex_taken = !ex_difference[32];
      default:    ex_taken = 1'b1;
    endcase
  end

  // A branch is never held in EX (it is not memory or MUL/DIV), so it
  // redirects in the cycle it leaves, if it leaves (ctl_advance).
  assign ex_target = ex_branch_register ? (ex_sum & ~32'd3) : ex_branch_target;
  // Section 02b: only a misprediction redirects. A predicted PC-relative
  // target is the same sum as ex_branch_target; a predicted register jump
  // (JR R31, offset 0) is checked against the register itself.
  assign ex_wrong_return = ex_predicted && ex_branch_register &&
                           ex_a[31:2] != ex_predict_target[31:2];
  assign ex_is_branch = ex_valid && (ex_class == OPCLASS_BRANCH);
  assign ex_branch_taken = ex_is_branch && ex_taken;
  // Section 02c adds two ways to be wrong: a PC-relative target that is not
  // this branch's (checked in ID, ex_target_wrong), and a prediction on an
  // instruction that is not a branch (back to pc+4).
  assign ex_redirects = ex_is_branch ?
      ((ex_taken != ex_predicted) || (ex_taken && ex_target_wrong) || ex_wrong_return) :
      (ex_valid && ex_predicted);
  assign ex_redirect_pc = ex_branch_taken ? ex_target : ex_next_pc;

  // Store data: the low byte or half replicated, as the mask expects.
  always @* begin
    case (ex_load_size)
      2'd0: ex_store_data = {4{ex_b[7:0]}};
      2'd1: ex_store_data = {2{ex_b[15:0]}};
      default: ex_store_data = ex_b;
    endcase
  end

  assign ex_is_memory = ex_valid &&
      (ex_class == OPCLASS_LOAD || ex_class == OPCLASS_STORE);

  // The request comes straight from the EX registers in the first cycle of
  // the access, and stays until accepted. The access ends with its response,
  // except a STORE to SDRAM, which ends as soon as it is accepted ("posted"):
  // cpu_dmem_adapter puts it in its write-combining buffer and can no longer
  // fail it, so nobody needs the answer. Its response still comes, in order,
  // and ex_mem_drop skips it. MMIO stores and every LOAD wait: an MMIO store
  // can fail, and the error has to carry the PC of that STORE.
  // SDRAM is the low 32 MiB (cpu_dmem_adapter SDRAM_SIZE_BYTES), the same
  // seven NORs the adapter uses.
  assign dmem_valid = ctl_memory && !ex_mem_request_sent;
  assign dmem_address = ex_result;
  assign dmem_write_data = ex_store_data;
  assign dmem_write_enable = (ex_class == OPCLASS_STORE) ? ex_store_mask : 4'b0000;
  assign ex_mem_posted = dmem_valid && dmem_ready &&
                         (ex_class == OPCLASS_STORE) && (ex_result[31:25] == 7'd0);
  assign ex_mem_done = ex_mem_posted ||
      (ctl_memory && ex_mem_request_sent && dmem_rvalid && ex_mem_drop == 2'd0);
  assign dmem_waiting = ctl_memory && !ex_mem_done;

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

  // ======================================================================
  // 04b. EX — MULTIPLIER AND DIVIDER
  // ======================================================================

  /*
   * A MUL/DIV class instruction stays in EX (ctl_advance low) while
   * ex_md_step counts. When it is done, the EX block writes the result into
   * ex_result and turns ex_class into OPCLASS_NORMAL (or OPCLASS_ERROR for a
   * division by zero), and from then on it leaves EX like an instruction
   * with a result known in ID (ex_use_alu low). Its consumer waits in ID
   * meanwhile and takes the result from WB, forwarded, like any other.
   * The operands are ex_a and ex_b, which EX keeps once forwarded.
   *
   * Multiplier, 3 cycles in EX plus the one to leave it. MUL, MULHI and
   * MULFX are all slices of the same signed 64-bit product, built from the
   * unsigned one (1.isa/isa.md):
   *
   *     signed[63:32] = unsigned[63:32] - (a[31] ? b : 0) - (b[31] ? a : 0)
   *
   * MUL is signed[31:0], MULHI signed[63:32], and MULFX (Q16.16, arithmetic
   * shift by 16) signed[47:16]. These registers have no reset and no enable:
   * they recompute every cycle from ex_a/ex_b, which stay put while the
   * instruction waits in EX.
   *   step 0: four 16x16 products (one ECP5 DSP each) and the correction.
   *   step 1: md_product, the unsigned 64-bit product.
   *   step 2: md_mul_result -> ex_result.
   *
   * Divider: restoring, one bit per cycle over the magnitudes; the sign goes
   * on at the end (quotient truncated towards zero, remainder with the sign
   * of the dividend). -2^31 / -1 wraps to 0x80000000 with remainder 0 by
   * itself.
   *   step 0: division by zero -> error; fast REM/REMU -> sign; else setup.
   *   steps 1-32: one quotient bit each (fast REM/REMU: step 1 writes).
   *   step 33: md_div_result -> ex_result.
   *
   * Fast path, as in the 35: a REM/REMU whose immediately preceding
   * instruction was a DIV/DIVU with the same source registers takes the
   * remainder that DIV left in md_remainder. Comparing register numbers is
   * enough because nothing ran in between, provided the DIV did not
   * overwrite one of its own sources (rd == ra or rd == rb arms no tag).
   * The tag is armed when a DIV/DIVU completes and cleared when any other
   * valid instruction enters EX, and on halt; the match (id_md_fast) is
   * taken from ID's instruction fields, off the register-file path.
   */
  assign ex_is_muldiv = ex_valid && (ex_class == OPCLASS_MULDIV);
  // The cycles in which the instruction in EX works: the same condition that
  // the EX block below uses to keep it (not halted, not flushed).
  assign ex_md_run = !halted && !ctl_flush && ex_is_muldiv;
  assign ex_md_is_div = ex_md_op[3:2] == 2'b11;  // 0x0c-0x0f
  assign ex_md_signed_div = (ex_md_op == OPCODE_DIV) || (ex_md_op == OPCODE_REM);
  assign id_md_fast = ALU_FAST_PATH && md_tag_valid &&
      md_tag_ra == id_ra && md_tag_rb == id_rb &&
      ((id_opcode == OPCODE_REM && !md_tag_unsigned) ||
       (id_opcode == OPCODE_REMU && md_tag_unsigned));

  always @(posedge clk) begin
    md_ll <= ex_a[15:0] * ex_b[15:0];
    md_lh <= ex_a[15:0] * ex_b[31:16];
    md_hl <= ex_a[31:16] * ex_b[15:0];
    md_hh <= ex_a[31:16] * ex_b[31:16];
    md_correction <= (ex_a[31] ? ex_b : 32'd0) + (ex_b[31] ? ex_a : 32'd0);
    md_product <= {md_hh, md_ll} + ({31'd0, {1'b0, md_lh} + {1'b0, md_hl}} << 16);
  end

  assign md_high_signed = md_product[63:32] - md_correction;

  always @* begin
    case (ex_md_op)
      OPCODE_MUL: md_mul_result = md_product[31:0];
      OPCODE_MULHI: md_mul_result = md_high_signed;
      default: md_mul_result = {md_high_signed[15:0], md_product[31:16]};  // MULFX
    endcase
    case (ex_md_op)
      OPCODE_DIV: md_div_result = md_quotient_negative ? -md_quotient : md_quotient;
      OPCODE_DIVU: md_div_result = md_quotient;
      OPCODE_REM: md_div_result = md_remainder_negative ? -md_remainder : md_remainder;
      default: md_div_result = md_remainder;  // REMU
    endcase
  end

  assign md_shifted = {md_remainder[30:0], md_dividend[31]};
  assign md_subtract = md_shifted >= md_divisor;

  always @(posedge clk) begin
    if (ex_md_run && ex_md_is_div) begin
      if (ex_md_step == 6'd0) begin
        if (ex_md_fast) begin
          // md_remainder is the DIV's; only the sign is this instruction's.
          md_remainder_negative <= ex_md_signed_div && ex_a[31];
        end else begin
          md_dividend <= (ex_md_signed_div && ex_a[31]) ? -ex_a : ex_a;
          md_divisor <= (ex_md_signed_div && ex_b[31]) ? -ex_b : ex_b;
          md_quotient_negative <= ex_md_signed_div && (ex_a[31] ^ ex_b[31]);
          md_remainder_negative <= ex_md_signed_div && ex_a[31];
          md_quotient <= 32'd0;
          md_remainder <= 32'd0;
        end
      end else if (!ex_md_fast && ex_md_step <= 6'd32) begin
        md_dividend <= {md_dividend[30:0], 1'b0};
        md_remainder <= md_subtract ? md_shifted - md_divisor : md_shifted;
        md_quotient <= {md_quotient[30:0], md_subtract};
      end
    end
  end

  // ID -> EX boundary and data-memory transaction state.
  always @(posedge clk) begin
    if (core_reset) begin
      ex_valid <= 1'b0;
      ex_pc <= 32'd0;
      ex_next_pc <= 32'd0;
      ex_rd <= 5'd0;
      ex_result <= 32'd0;
      ex_op_a <= 32'd0;
      ex_op_b <= 32'd0;
      ex_forward_a <= 1'b0;
      ex_forward_b <= 1'b0;
      ex_use_alu <= 1'b0;
      ex_alu_op <= ALU_ADD;
      ex_alu_imm <= 1'b0;
      ex_imm <= 32'd0;
      ex_branch_cond <= BRANCH_ALWAYS;
      ex_branch_register <= 1'b0;
      ex_branch_target <= 32'd0;
      ex_predicted <= 1'b0;
      ex_predict_target <= 32'd0;
      ex_return <= 1'b0;
      ex_target_wrong <= 1'b0;
      ex_store_mask <= 4'b0000;
      ex_load_size <= 2'd2;
      ex_load_signed <= 1'b0;
      ex_reg_write <= 1'b0;
      ex_halt_after_retire <= 1'b0;
      ex_class <= OPCLASS_NORMAL;
      ex_error_code <= ERROR_NONE;
      ex_mem_request_sent <= 1'b0;
      // soft_reset: the access in flight, or accepted this cycle, still gets
      // its response from the D-cache; drop it.
      ex_mem_drop <= reset ? 2'd0 : ex_mem_drop
                     + {1'b0, (ex_mem_request_sent && !(dmem_rvalid && ex_mem_drop == 2'd0)) ||
                              (dmem_valid && dmem_ready)}
                     - {1'b0, dmem_rvalid && ex_mem_drop != 2'd0};
      ex_md_op <= OPCODE_NOP;
      ex_md_ra <= 5'd0;
      ex_md_rb <= 5'd0;
      ex_md_fast <= 1'b0;
      ex_md_counted <= 1'b0;
      ex_md_step <= 6'd0;
      md_tag_valid <= 1'b0;
      md_tag_unsigned <= 1'b0;
      md_tag_ra <= 5'd0;
      md_tag_rb <= 5'd0;
    end else if (halted || ctl_flush) begin
      ex_valid <= 1'b0;
      ex_mem_request_sent <= 1'b0;
      // After a stop the monitor may run anything before RUN: no fast path.
      md_tag_valid <= 1'b0;
      // An access already accepted still gets its response: drop it too.
      ex_mem_drop <= ex_mem_drop
                     + {1'b0, ex_mem_request_sent && !(dmem_rvalid && ex_mem_drop == 2'd0)}
                     - {1'b0, dmem_rvalid && ex_mem_drop != 2'd0};
    end else begin
      ex_mem_drop <= ex_mem_drop + {1'b0, ex_mem_posted}
                     - {1'b0, dmem_rvalid && ex_mem_drop != 2'd0};
      // FWD-HOLD: an instruction that stays in EX keeps its operands as
      // forwarded: the producer leaves WB at the end of this cycle.
      ex_op_a <= ex_a;
      ex_op_b <= ex_b;
      ex_forward_a <= 1'b0;
      ex_forward_b <= 1'b0;
      if (ctl_advance) begin
        if (!raw_hazard) begin
          // Behind a taken branch, a bubble (the wrong path).
          ex_valid <= id_live && !ex_redirects;
          ex_pc <= id_pc;
          ex_next_pc <= id_pc + 32'd4;
          ex_rd <= id_rd;
          ex_result <= id_result;
          ex_op_a <= id_op_a;
          ex_op_b <= id_op_b;
          ex_forward_a <= id_forward_a;
          ex_forward_b <= id_forward_b;
          ex_use_alu <= id_use_alu;
          ex_alu_op <= id_alu_op;
          ex_alu_imm <= id_alu_imm;
          ex_imm <= id_imm;
          ex_branch_cond <= id_branch_cond;
          ex_branch_register <= id_branch_register;
          ex_branch_target <= id_branch_target;
          ex_predicted <= id_predicted;
          ex_predict_target <= id_predict_target;
          ex_return <= id_return;
          ex_target_wrong <= id_target_wrong;
          ex_store_mask <= id_store_mask;
          ex_load_size <= id_access_size;
          ex_load_signed <= id_access_signed;
          ex_reg_write <= id_reg_write;
          ex_halt_after_retire <= id_halt_after_retire;
          ex_class <= id_class;
          ex_error_code <= id_error_code;
          ex_mem_request_sent <= 1'b0;
          ex_md_op <= id_opcode;
          ex_md_ra <= id_ra;
          ex_md_rb <= id_rb;
          ex_md_fast <= id_md_fast;
          ex_md_counted <= id_class == OPCLASS_MULDIV;
          ex_md_step <= 6'd0;
          // Any other instruction between a DIV and its REM ends the tag.
          if (id_live) md_tag_valid <= 1'b0;
        end else begin
          ex_valid <= 1'b0;
        end
      end
      if (ex_md_run) begin
        ex_md_step <= ex_md_step + 6'd1;
        if (!ex_md_is_div) begin
          if (ex_md_step == 6'd2) begin
            ex_result <= md_mul_result;
            ex_class <= OPCLASS_NORMAL;
          end
        end else if (ex_md_step == 6'd0 && ex_b == 32'd0) begin
          ex_class <= OPCLASS_ERROR;
          ex_error_code <= ERROR_DIVISION_BY_ZERO;
        end else if ((ex_md_fast && ex_md_step == 6'd1) || ex_md_step == 6'd33) begin
          // The fast path ends at step 1: step 0 put the sign in place.
          ex_result <= md_div_result;
          ex_class <= OPCLASS_NORMAL;
          if (ex_md_op == OPCODE_DIV || ex_md_op == OPCODE_DIVU) begin
            md_tag_valid <= ALU_FAST_PATH && ex_rd != ex_md_ra && ex_rd != ex_md_rb;
            md_tag_unsigned <= ex_md_op == OPCODE_DIVU;
            md_tag_ra <= ex_md_ra;
            md_tag_rb <= ex_md_rb;
          end
        end
      end
      // When the access ends, ctl_advance is high in that same cycle and the
      // block above has already brought in the next instruction (or a bubble).
      if (ctl_memory && !ex_mem_done && dmem_valid && dmem_ready)
        ex_mem_request_sent <= 1'b1;
    end
  end

  // ======================================================================
  // 05. WB — RETIRE STATE
  // ======================================================================

  assign debug_pc = architectural_pc;

  // EX -> WB boundary, architectural retirement and error reporting.
  always @(posedge clk) begin
    instruction_retired <= 1'b0;
    perf_muldiv_retired <= 1'b0;
    if (core_reset) begin
      wb_md_counted <= 1'b0;
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
        perf_muldiv_retired <= wb_md_counted;
        architectural_pc <= wb_next_pc;
        wb_valid <= 1'b0;
      end
      // A memory access ending also has ctl_advance high: it goes first.
      if (ex_mem_done) begin
        wb_valid <= 1'b1;
        wb_pc <= ex_pc;
        wb_next_pc <= ex_next_pc;
        wb_rd <= ex_rd;
        wb_result <= ex_load_extended;
        wb_reg_write <= ex_class == OPCLASS_LOAD;
        wb_md_counted <= 1'b0;
        wb_halt_after_retire <= ex_halt_after_retire;
        wb_error <= !ex_mem_posted && dmem_error;
        wb_error_code <= ERROR_MEMORY_ACCESS;
      end else if (ctl_advance && ex_valid) begin
        wb_valid <= 1'b1;
        wb_pc <= ex_pc;
        wb_next_pc <= (ex_class == OPCLASS_BRANCH && ex_taken) ? ex_target : ex_next_pc;
        wb_rd <= ex_rd;
        wb_result <= ex_use_alu ? ex_alu_result : ex_result;
        wb_reg_write <= ex_reg_write;
        wb_halt_after_retire <= ex_halt_after_retire;
        wb_md_counted <= ex_md_counted;
        wb_error <= ex_class == OPCLASS_ERROR;
        wb_error_code <= ex_error_code;
      end
    end
  end

endmodule

`default_nettype wire
