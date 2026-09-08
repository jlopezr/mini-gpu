`default_nettype none
// One occupied slot per warp; vector request accepted atomically.
// Each wave grants at most one lane per bank. Round robin rotates after every
// wave, including bank conflicts. Backend latency is completely unconstrained.
module gpu_lsu (
    input clk, reset,
    input req_valid,
    output req_ready,
    input [2:0] req_tag,
    input [7:0] req_mask,
    input req_write,
    input [255:0] req_address, req_data,
    output reg rsp_valid,
    input rsp_ready,
    output reg [2:0] rsp_tag,
    output reg [255:0] rsp_data,
    output reg [7:0] rsp_error,
    output [7:0] occupied,
    output reg [7:0] bank_valid,
    input [7:0] bank_ready,
    output reg [95:0] bank_row,
    output reg [255:0] bank_data,
    output reg [7:0] bank_write,
    input [7:0] bank_rsp_valid,
    output [7:0] bank_rsp_ready,
    input [255:0] bank_rsp_data,
    input [7:0] bank_rsp_error
);
    reg [7:0] busy;
    reg [7:0] pending[0:7], errors[0:7];
    reg [255:0] addresses[0:7], values[0:7];
    reg stores[0:7];
    reg [2:0] cursor, selected;
    reg [2:0] lane_for_bank[0:7];
    reg [7:0] waiting, wave_mask;
    reg [1:0] state;
    localparam PICK=0, ROUTE=1, WAIT=2, COMPLETE=3;
    assign occupied = busy;
    assign req_ready = !busy[req_tag] && !reset;
    assign bank_rsp_ready = state == WAIT ? waiting : 8'b0;

    // Bank responses are transposed into eight independent lane buffers.
    // Each buffer has ONE write port; a variable slice write into a 256-bit
    // array would synthesize eight enormous priority/write-mask networks.
    wire [255:0] completed_data;
    genvar rl;
    generate for(rl=0;rl<8;rl=rl+1) begin: response_lanes
        reg [31:0] words[0:7];
        reg write_result;
        reg [31:0] value;
        integer rb;
        always @* begin
            write_result=0; value=0;
            for(rb=0;rb<8;rb=rb+1) begin
                if(state==WAIT && waiting[rb] && bank_rsp_valid[rb] && lane_for_bank[rb]==rl[2:0]) begin
                    write_result=1; value=bank_rsp_data[rb*32 +: 32];
                end
            end
        end
        always @(posedge clk) if(!reset && write_result) words[selected]<=value;
        assign completed_data[rl*32 +: 32]=words[selected];
    end endgenerate
    reg [7:0] returned_errors;
    integer eb;
    always @* begin
        returned_errors=0;
        for(eb=0;eb<8;eb=eb+1)
            if(waiting[eb] && bank_rsp_valid[eb] && bank_rsp_error[eb])
                returned_errors[lane_for_bank[eb]]=1;
    end

    reg found;
    reg [2:0] pick, candidate;
    integer i, n, k;
    always @* begin
        found=0; pick=cursor; candidate=0;
        for (k=0; k<8; k=k+1) begin
            candidate=cursor+k[2:0];
            if (!found && busy[candidate]) begin
                found=1; pick=candidate;
            end
        end
    end
    reg [7:0] route_valid, route_mask, route_error;
    reg [95:0] route_row;
    reg [255:0] route_data;
    reg [23:0] route_lanes;
    reg [31:0] addr;
    integer lane, bank;
    always @* begin
        route_valid=0; route_mask=0; route_error=0;
        route_row=0; route_data=0; route_lanes=0; addr=0; bank=0;
        for (lane=0; lane<8; lane=lane+1) begin
            addr=addresses[selected][lane*32 +: 32];
            bank={29'b0,addr[4:2]};
            if (pending[selected][lane]) begin
                if (|addr[31:17] || |addr[1:0]) begin
                    route_mask[lane]=1; route_error[lane]=1;
                end else if (!route_valid[bank]) begin
                    route_valid[bank]=1; route_mask[lane]=1;
                    route_row[bank*12 +: 12]=addr[16:5];
                    route_data[bank*32 +: 32]=values[selected][lane*32 +: 32];
                    route_lanes[bank*3 +: 3]=lane[2:0];
                end
            end
        end
    end
    always @(posedge clk) begin
        if (reset) begin
            busy<=0; state<=PICK; cursor<=0; selected<=0;
            rsp_valid<=0; rsp_tag<=0; rsp_data<=0; rsp_error<=0;
            bank_valid<=0; bank_row<=0; bank_data<=0; bank_write<=0;
            waiting<=0; wave_mask<=0;
            for (i=0;i<8;i=i+1) begin
                pending[i]<=0; errors[i]<=0; lane_for_bank[i]<=0;
            end
        end else begin
            if (req_valid && req_ready) begin
                busy[req_tag]<=1; pending[req_tag]<=req_mask;
                addresses[req_tag]<=req_address; values[req_tag]<=req_data;
                stores[req_tag]<=req_write; errors[req_tag]<=0;
            end
            case (state)
                PICK: if (found) begin selected<=pick; state<=ROUTE; end
                ROUTE: begin
                    if (pending[selected]==0) begin
                        rsp_tag<=selected; rsp_data<=completed_data;
                        rsp_error<=errors[selected]; rsp_valid<=1; state<=COMPLETE;
                    end else begin
                        bank_valid<=route_valid; waiting<=route_valid;
                        bank_row<=route_row; bank_data<=route_data;
                        bank_write<={8{stores[selected]}};
                        wave_mask<=route_mask;
                        errors[selected]<=errors[selected] | route_error;
                        for(n=0;n<8;n=n+1) lane_for_bank[n]<=route_lanes[n*3 +: 3];
                        state<=WAIT;
                    end
                end
                WAIT: begin
                    bank_valid<=bank_valid & ~bank_ready;
                    errors[selected]<=errors[selected] | returned_errors;
                    for(n=0;n<8;n=n+1) begin
                        if (bank_rsp_valid[n] && waiting[n]) begin
                            waiting[n]<=0;
                        end
                    end
                    if (waiting==0) begin
                        pending[selected]<=pending[selected] & ~wave_mask;
                        cursor<=selected+1'b1;
                        state<=PICK;
                    end
                end
                COMPLETE: if (rsp_valid && rsp_ready) begin
                    rsp_valid<=0; busy[selected]<=0;
                    cursor<=selected+1'b1; state<=PICK;
                end
            endcase
        end
    end
endmodule
`default_nettype wire
