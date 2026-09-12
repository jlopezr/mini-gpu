`default_nettype none

// Closed-page W9825G6KH controller. Addresses select 16-bit words.
// Burst length is one and every READ/WRITE uses auto-precharge. Timing values
// are converted to whole clock cycles, always rounding up.
module sdram_controller #(
    parameter integer CLK_FREQ_HZ = 25_000_000,
    parameter integer POWERUP_DELAY_US = 200,
    parameter integer REFRESH_RATE_HZ = 128_000,
    parameter integer MAX_ACCESS_CYCLES = 15,
    parameter integer TRP_NS = 20,
    parameter integer TRCD_NS = 20,
    parameter integer TRFC_NS = 66,
    parameter integer TMRD_CYCLES = 2,
    parameter integer CAS_LATENCY_CYCLES = 2,
    parameter integer TWR_CYCLES = 2
) (
    input wire clk, input wire reset,
    input wire req_valid, input wire req_write,
    input wire [23:0] req_addr, input wire [15:0] req_wdata,
    input wire [1:0] req_wmask,
    output wire req_ready, output reg done, output reg [15:0] rdata,
    output reg init_done, output wire busy,
    output wire sdram_clk, output reg sdram_cke, output reg sdram_csn,
    output reg sdram_rasn, output reg sdram_casn, output reg sdram_wen,
    output reg [12:0] sdram_a, output reg [1:0] sdram_ba,
    output reg [1:0] sdram_dqm, inout wire [15:0] sdram_d
);
  localparam [3:0] CMD_MRS=4'b0000, CMD_REFRESH=4'b0001,
    CMD_PRECHARGE=4'b0010, CMD_ACTIVE=4'b0011, CMD_WRITE=4'b0100,
    CMD_READ=4'b0101, CMD_NOP=4'b0111;
  localparam [4:0] ST_INIT_WAIT=0, ST_INIT_PRE=1, ST_INIT_PRE_WAIT=2,
    ST_INIT_REF=3, ST_INIT_REF_WAIT0=4, ST_INIT_REF_WAIT1=5,
    ST_INIT_MRS=6, ST_INIT_MRS_WAIT0=7, ST_INIT_MRS_WAIT1=8,
    ST_IDLE=9, ST_ACTIVE=10, ST_TRCD=11, ST_READ=12,
    ST_READ_WAIT0=13, ST_READ_WAIT1=14, ST_READ_CAPTURE=15,
    ST_WRITE=16, ST_WRITE_WAIT0=17, ST_WRITE_WAIT1=18,
    ST_REFRESH=19, ST_REFRESH_WAIT0=20, ST_REFRESH_WAIT1=21;

  function integer ns_to_cycles;
    input integer delay_ns;
    integer result;
    begin
      // Dividing the frequency first avoids overflowing Verilog's 32-bit
      // integer arithmetic for the supported clock range.
      result = (((CLK_FREQ_HZ / 1000) * delay_ns) + 999_999) / 1_000_000;
      ns_to_cycles = (result < 1) ? 1 : result;
    end
  endfunction

  localparam integer POWERUP_DELAY_CYCLES =
      (((CLK_FREQ_HZ / 1000) * POWERUP_DELAY_US) + 999) / 1000;
  localparam integer REFRESH_PERIOD_CYCLES = CLK_FREQ_HZ / REFRESH_RATE_HZ;
  localparam integer REFRESH_TRIGGER_CYCLES =
      REFRESH_PERIOD_CYCLES - MAX_ACCESS_CYCLES;
  localparam integer TRP_CYCLES = ns_to_cycles(TRP_NS);
  localparam integer TRCD_CYCLES = ns_to_cycles(TRCD_NS);
  localparam integer TRFC_CYCLES = ns_to_cycles(TRFC_NS);

  reg [4:0] state;
  reg [31:0] init_count;
  reg [3:0] init_refreshes;
  reg [31:0] refresh_count;
  reg [15:0] timing_count;
  reg [23:0] saved_addr;
  reg [15:0] saved_wdata;
  reg [1:0] saved_wmask;
  reg saved_write;
  wire [12:0] saved_row = saved_addr[23:11];
  wire [1:0] saved_bank = saved_addr[10:9];
  wire [8:0] saved_col = saved_addr[8:0];

  // Start refresh early enough to finish an in-flight closed-page access
  // before the next average refresh deadline.
  assign req_ready = (state == ST_IDLE) &&
                     (refresh_count < REFRESH_TRIGGER_CYCLES);
  assign busy = state != ST_IDLE;
  assign sdram_clk = clk;
  assign sdram_d = (state == ST_WRITE) ? saved_wdata : 16'hzzzz;

  always @* begin
    {sdram_csn, sdram_rasn, sdram_casn, sdram_wen} = CMD_NOP;
    sdram_a = 13'd0;
    sdram_ba = 2'd0;
    sdram_dqm = 2'b00;
    case (state)
      ST_INIT_WAIT: sdram_dqm = 2'b11;
      ST_INIT_PRE: begin
        {sdram_csn,sdram_rasn,sdram_casn,sdram_wen}=CMD_PRECHARGE;
        sdram_a[10]=1'b1;
      end
      ST_INIT_REF: {sdram_csn,sdram_rasn,sdram_casn,sdram_wen}=CMD_REFRESH;
      ST_INIT_MRS: begin
        {sdram_csn,sdram_rasn,sdram_casn,sdram_wen}=CMD_MRS;
        sdram_a=13'h020; // BL1, sequential, CL2
      end
      ST_ACTIVE: begin
        {sdram_csn,sdram_rasn,sdram_casn,sdram_wen}=CMD_ACTIVE;
        sdram_a=saved_row; sdram_ba=saved_bank;
      end
      ST_READ: begin
        {sdram_csn,sdram_rasn,sdram_casn,sdram_wen}=CMD_READ;
        sdram_a={2'b00,1'b1,1'b0,saved_col}; sdram_ba=saved_bank;
      end
      ST_WRITE: begin
        {sdram_csn,sdram_rasn,sdram_casn,sdram_wen}=CMD_WRITE;
        sdram_a={2'b00,1'b1,1'b0,saved_col}; sdram_ba=saved_bank;
        sdram_dqm=~saved_wmask;
      end
      ST_REFRESH: {sdram_csn,sdram_rasn,sdram_casn,sdram_wen}=CMD_REFRESH;
      default: begin end
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state<=ST_INIT_WAIT; init_count<=0; init_refreshes<=0; refresh_count<=0;
      timing_count<=0;
      saved_addr<=0; saved_wdata<=0; saved_wmask<=0; saved_write<=0;
      done<=0; rdata<=0; init_done<=0; sdram_cke<=1;
    end else begin
      done<=0;
      if (init_done && refresh_count < REFRESH_PERIOD_CYCLES)
        refresh_count<=refresh_count+1'b1;
      case (state)
        ST_INIT_WAIT: if (init_count>=POWERUP_DELAY_CYCLES) begin init_count<=0; state<=ST_INIT_PRE; end
                      else init_count<=init_count+1'b1;
        ST_INIT_PRE: begin timing_count<=0; state<=ST_INIT_PRE_WAIT; end
        ST_INIT_PRE_WAIT:
          if (timing_count+1>=TRP_CYCLES) begin timing_count<=0; state<=ST_INIT_REF; end
          else timing_count<=timing_count+1'b1;
        ST_INIT_REF: begin timing_count<=0; state<=ST_INIT_REF_WAIT0; end
        ST_INIT_REF_WAIT0: begin timing_count<=1; state<=ST_INIT_REF_WAIT1; end
        ST_INIT_REF_WAIT1:
          if (timing_count>=TRFC_CYCLES-1) begin
            timing_count<=0;
            if (init_refreshes==4'd7) begin init_refreshes<=0; state<=ST_INIT_MRS; end
            else begin init_refreshes<=init_refreshes+1'b1; state<=ST_INIT_REF; end
          end else timing_count<=timing_count+1'b1;
        ST_INIT_MRS: begin timing_count<=0; state<=ST_INIT_MRS_WAIT0; end
        ST_INIT_MRS_WAIT0: begin timing_count<=1; state<=ST_INIT_MRS_WAIT1; end
        ST_INIT_MRS_WAIT1:
          if (timing_count>=TMRD_CYCLES-1) begin
            timing_count<=0; init_done<=1; refresh_count<=0; state<=ST_IDLE;
          end else timing_count<=timing_count+1'b1;
        ST_IDLE: if (refresh_count>=REFRESH_TRIGGER_CYCLES) begin refresh_count<=0; state<=ST_REFRESH; end
                 else if (req_valid) begin
                   saved_addr<=req_addr; saved_wdata<=req_wdata;
                   saved_wmask<=req_wmask; saved_write<=req_write; state<=ST_ACTIVE;
                 end
        ST_ACTIVE: begin timing_count<=0; state<=ST_TRCD; end
        ST_TRCD:
          if (timing_count+1>=TRCD_CYCLES) begin
            timing_count<=0; state<=saved_write ? ST_WRITE : ST_READ;
          end else timing_count<=timing_count+1'b1;
        ST_READ: begin timing_count<=0; state<=ST_READ_WAIT0; end
        ST_READ_WAIT0: begin timing_count<=1; state<=ST_READ_WAIT1; end
        ST_READ_WAIT1:
          if (timing_count>=CAS_LATENCY_CYCLES-1) begin timing_count<=0; state<=ST_READ_CAPTURE; end
          else timing_count<=timing_count+1'b1;
        ST_READ_CAPTURE: begin rdata<=sdram_d; done<=1; state<=ST_IDLE; end
        ST_WRITE: begin timing_count<=0; state<=ST_WRITE_WAIT0; end
        ST_WRITE_WAIT0: begin timing_count<=1; state<=ST_WRITE_WAIT1; end
        ST_WRITE_WAIT1:
          if (timing_count>=TWR_CYCLES-1) begin timing_count<=0; done<=1; state<=ST_IDLE; end
          else timing_count<=timing_count+1'b1;
        ST_REFRESH: begin timing_count<=0; state<=ST_REFRESH_WAIT0; end
        ST_REFRESH_WAIT0: begin timing_count<=1; state<=ST_REFRESH_WAIT1; end
        ST_REFRESH_WAIT1:
          if (timing_count>=TRFC_CYCLES-1) begin timing_count<=0; state<=ST_IDLE; end
          else timing_count<=timing_count+1'b1;
        default: state<=ST_INIT_WAIT;
      endcase
    end
  end
endmodule

`default_nettype wire
