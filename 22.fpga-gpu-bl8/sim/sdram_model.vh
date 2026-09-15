`ifndef GPU_SDRAM_MODEL_VH
`define GPU_SDRAM_MODEL_VH
// Functional BL1 SDRAM bus model: command/address decoding and byte masks.
// Not a replacement for a vendor timing model or a physical board test.
module sdram_model(input clk, cke, csn, rasn, casn, wen,
    input [12:0] a, input [1:0] ba,dqm, inout [15:0] d);
    reg [15:0] words[0:16777215];
    reg [12:0] rows[0:3];
    reg [15:0] read_data;
    reg [2:0] read_cycles=0;
    integer refreshes=0;
    wire [23:0] address={rows[ba],ba,a[8:0]};
    assign d=read_cycles!=0 ? read_data : 16'hzzzz;
    always @(posedge clk) begin
        if(read_cycles!=0) read_cycles<=read_cycles-1'b1;
        if(cke && !csn) case({rasn,casn,wen})
            3'b011: rows[ba]<=a;
            3'b101: begin read_data<=words[address]; read_cycles<=3; end
            3'b100: begin
                if(!dqm[0]) words[address][7:0]<=d[7:0];
                if(!dqm[1]) words[address][15:8]<=d[15:8];
            end
            3'b001: refreshes<=refreshes+1;
            default: begin end
        endcase
    end
endmodule

`endif
