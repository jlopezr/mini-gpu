`default_nettype none

// Simple, closed-page controller for W9825G6KH at exactly 25 MHz.
// req_addr is a 16-bit-word address: {row[12:0], bank[1:0], column[8:0]}.
module sdram_controller (
    input  wire        clk,
    input  wire        reset,
    input  wire        req_valid,
    input  wire        req_write,
    input  wire [23:0] req_addr,
    input  wire [15:0] req_wdata,
    output wire        req_ready,
    output reg         done,
    output reg  [15:0] rdata,
    output reg         init_done,
    output wire        sdram_clk,
    output reg         sdram_cke,
    output reg         sdram_csn,
    output reg         sdram_rasn,
    output reg         sdram_casn,
    output reg         sdram_wen,
    output reg  [12:0] sdram_a,
    output reg  [1:0]  sdram_ba,
    output reg  [1:0]  sdram_dqm,
    inout  wire [15:0] sdram_d
);
    localparam [3:0] CMD_MRS       = 4'b0000;
    localparam [3:0] CMD_REFRESH   = 4'b0001;
    localparam [3:0] CMD_PRECHARGE = 4'b0010;
    localparam [3:0] CMD_ACTIVE    = 4'b0011;
    localparam [3:0] CMD_WRITE     = 4'b0100;
    localparam [3:0] CMD_READ      = 4'b0101;
    localparam [3:0] CMD_NOP       = 4'b0111;

    localparam [4:0] ST_INIT_WAIT=0, ST_INIT_PRE=1, ST_INIT_PRE_WAIT=2,
                     ST_INIT_REF=3, ST_INIT_REF_WAIT0=4, ST_INIT_REF_WAIT1=5,
                     ST_INIT_MRS=6, ST_INIT_MRS_WAIT0=7, ST_INIT_MRS_WAIT1=8,
                     ST_IDLE=9, ST_ACTIVE=10, ST_TRCD=11, ST_READ=12,
                     ST_READ_WAIT0=13, ST_READ_WAIT1=14, ST_READ_CAPTURE=15,
                     ST_WRITE=16, ST_WRITE_WAIT0=17, ST_WRITE_WAIT1=18,
                     ST_REFRESH=19, ST_REFRESH_WAIT0=20, ST_REFRESH_WAIT1=21;

    reg [4:0] state;
    reg [12:0] init_count;
    reg [3:0] init_refreshes;
    reg [7:0] refresh_count;
    reg [23:0] saved_addr;
    reg [15:0] saved_wdata;
    reg saved_write;

    wire [12:0] saved_row = saved_addr[23:11];
    wire [1:0]  saved_bank = saved_addr[10:9];
    wire [8:0]  saved_col = saved_addr[8:0];

    assign sdram_clk = clk;
    assign req_ready = (state == ST_IDLE) && (refresh_count < 8'd190);
    assign sdram_d = (state == ST_WRITE) ? saved_wdata : 16'hzzzz;

    always @* begin
        {sdram_csn, sdram_rasn, sdram_casn, sdram_wen} = CMD_NOP;
        sdram_a = 13'd0;
        sdram_ba = 2'd0;
        sdram_dqm = 2'b00;
        case (state)
            ST_INIT_WAIT: begin sdram_dqm = 2'b11; end
            ST_INIT_PRE: begin
                {sdram_csn, sdram_rasn, sdram_casn, sdram_wen} = CMD_PRECHARGE;
                sdram_a[10] = 1'b1;
            end
            ST_INIT_REF: begin
                {sdram_csn, sdram_rasn, sdram_casn, sdram_wen} = CMD_REFRESH;
            end
            ST_INIT_MRS: begin
                // BL=1, sequential, CAS latency=2, programmed write burst.
                {sdram_csn, sdram_rasn, sdram_casn, sdram_wen} = CMD_MRS;
                sdram_a = 13'h020;
            end
            ST_ACTIVE: begin
                {sdram_csn, sdram_rasn, sdram_casn, sdram_wen} = CMD_ACTIVE;
                sdram_a = saved_row;
                sdram_ba = saved_bank;
            end
            ST_READ: begin
                {sdram_csn, sdram_rasn, sdram_casn, sdram_wen} = CMD_READ;
                sdram_a = {2'b00, 1'b1, 1'b0, saved_col}; // A10=auto-precharge
                sdram_ba = saved_bank;
            end
            ST_WRITE: begin
                {sdram_csn, sdram_rasn, sdram_casn, sdram_wen} = CMD_WRITE;
                sdram_a = {2'b00, 1'b1, 1'b0, saved_col};
                sdram_ba = saved_bank;
            end
            ST_REFRESH: begin
                {sdram_csn, sdram_rasn, sdram_casn, sdram_wen} = CMD_REFRESH;
            end
            default: begin end
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= ST_INIT_WAIT;
            init_count <= 0;
            init_refreshes <= 0;
            refresh_count <= 0;
            saved_addr <= 0;
            saved_wdata <= 0;
            saved_write <= 0;
            done <= 0;
            rdata <= 0;
            init_done <= 0;
            sdram_cke <= 1;
        end else begin
            done <= 0;
            if (init_done && refresh_count < 8'hff)
                refresh_count <= refresh_count + 1'b1;
            case (state)
                ST_INIT_WAIT: begin
                    // 5000 clocks = 200 us at 25 MHz; use 5001 conservatively.
                    if (init_count == 13'd5000) begin init_count <= 0; state <= ST_INIT_PRE; end
                    else init_count <= init_count + 1'b1;
                end
                ST_INIT_PRE: state <= ST_INIT_PRE_WAIT;
                ST_INIT_PRE_WAIT: state <= ST_INIT_REF;
                ST_INIT_REF: state <= ST_INIT_REF_WAIT0;
                ST_INIT_REF_WAIT0: state <= ST_INIT_REF_WAIT1;
                ST_INIT_REF_WAIT1: begin
                    if (init_refreshes == 4'd7) begin init_refreshes <= 0; state <= ST_INIT_MRS; end
                    else begin init_refreshes <= init_refreshes + 1'b1; state <= ST_INIT_REF; end
                end
                ST_INIT_MRS: state <= ST_INIT_MRS_WAIT0;
                ST_INIT_MRS_WAIT0: state <= ST_INIT_MRS_WAIT1;
                ST_INIT_MRS_WAIT1: begin
                    init_done <= 1;
                    refresh_count <= 0;
                    state <= ST_IDLE;
                end
                ST_IDLE: begin
                    if (refresh_count >= 8'd190) begin
                        refresh_count <= 0;
                        state <= ST_REFRESH;
                    end else if (req_valid) begin
                        saved_addr <= req_addr;
                        saved_wdata <= req_wdata;
                        saved_write <= req_write;
                        state <= ST_ACTIVE;
                    end
                end
                ST_ACTIVE: state <= ST_TRCD;
                ST_TRCD: state <= saved_write ? ST_WRITE : ST_READ;
                ST_READ: state <= ST_READ_WAIT0;
                ST_READ_WAIT0: state <= ST_READ_WAIT1;
                ST_READ_WAIT1: state <= ST_READ_CAPTURE;
                ST_READ_CAPTURE: begin rdata <= sdram_d; done <= 1; state <= ST_IDLE; end
                ST_WRITE: state <= ST_WRITE_WAIT0;
                ST_WRITE_WAIT0: state <= ST_WRITE_WAIT1;
                ST_WRITE_WAIT1: begin done <= 1; state <= ST_IDLE; end
                ST_REFRESH: state <= ST_REFRESH_WAIT0;
                ST_REFRESH_WAIT0: state <= ST_REFRESH_WAIT1;
                ST_REFRESH_WAIT1: state <= ST_IDLE;
                default: state <= ST_INIT_WAIT;
            endcase
        end
    end
endmodule

`default_nettype wire
