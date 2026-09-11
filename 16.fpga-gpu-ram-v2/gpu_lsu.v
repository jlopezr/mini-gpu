`default_nettype none
// Eight vector slots; round robin after each lane. Fetch/host and LSU take
// alternating turns when both request service. Each 32-bit word uses two BL1s.
module gpu_lsu (
    input clk, reset,
    input req_valid, output req_ready,
    input [2:0] req_tag, input [7:0] req_mask, input req_write,
    input [255:0] req_address, req_data,
    output reg rsp_valid, input rsp_ready,
    output reg [2:0] rsp_tag, output reg [255:0] rsp_data,
    output reg [7:0] rsp_error, output [7:0] occupied,
    input aux_valid, output aux_ready, input [31:0] aux_address, aux_write_data,
    input [3:0] aux_strobe, output reg aux_rsp_valid, input aux_rsp_ready,
    output reg [31:0] aux_read_data, output reg aux_error,
    input init_done, output mem_req_valid, input mem_req_ready,
    output mem_req_write, output [23:0] mem_req_addr,
    output [15:0] mem_req_wdata, output [1:0] mem_req_wmask,
    input mem_done, input [15:0] mem_rdata
);
    // SEND_LOW..WAIT_HIGH conservan sus códigos: gpu_lsu_tb recorre dut.state==1..4.
    localparam IDLE=0, SEND_LOW=1, WAIT_LOW=2, SEND_HIGH=3,
        WAIT_HIGH=4, AUX_RESPONSE=5, VECTOR_RESPONSE=6, SELECT=7;
    reg [2:0] state, cursor, selected, selected_lane;
    // has_pending[i] refleja |pending[i]. Mantenerlo como registro evita meter
    // los 64 bits de pending, multiplexados por candidate, en la prioridad.
    reg [7:0] busy, has_pending, pending[0:7], errors[0:7];
    reg [255:0] addresses[0:7], values[0:7];
    reg stores[0:7];
    reg owner_aux, prefer_aux;
    reg [31:0] word_address, word_data;
    reg [3:0] word_strobe;
    reg [15:0] low_data;
    reg found, lane_found;
    reg [2:0] pick, candidate, lane_pick;
    integer k,l,i;
    always @* begin
        found=0; pick=cursor; candidate=0;
        for(k=0;k<8;k=k+1) begin
            candidate=cursor+k[2:0];
            if(!found && busy[candidate] && (has_pending[candidate] || !rsp_valid)) begin found=1; pick=candidate; end
        end
        lane_found=0; lane_pick=0;
        for(l=0;l<8;l=l+1)
            if(!lane_found && pending[pick][l]) begin lane_found=1; lane_pick=l[2:0]; end
    end
    // Los multiplexores de 2048 bits se indexan con selected/selected_lane, ya
    // registrados en SELECT, para no encadenarlos tras la prioridad de IDLE.
    wire [31:0] selected_address=addresses[selected][selected_lane*32 +: 32];
    wire [31:0] selected_value=values[selected][selected_lane*32 +: 32];
    // Estado de pending tras retirar la lane en curso, para actualizar has_pending
    // en los dos puntos que la cierran. Depende de selected, ya registrado.
    wire [7:0] pending_after_lane=pending[selected] & ~(8'b1<<selected_lane);
    wire take_aux=aux_valid && (prefer_aux || !found);
    assign occupied=busy;
    assign req_ready=!reset && !busy[req_tag];
    assign aux_ready=!reset && init_done && state==IDLE && (prefer_aux || !found);
    assign mem_req_valid=!reset && (state==SEND_LOW || state==SEND_HIGH);
    assign mem_req_write=|word_strobe;
    assign mem_req_addr=word_address[24:1] + (state==SEND_HIGH ? 24'd1 : 24'd0);
    assign mem_req_wdata=state==SEND_HIGH ? word_data[31:16] : word_data[15:0];
    assign mem_req_wmask=state==SEND_HIGH ? word_strobe[3:2] : word_strobe[1:0];
    wire [255:0] completed_data;
    genvar lane;
    generate for(lane=0;lane<8;lane=lane+1) begin: response_lanes
        reg [31:0] words[0:7];
        always @(posedge clk)
            if(!reset && state==WAIT_HIGH && mem_done && !owner_aux && selected_lane==lane)
                words[selected]<={mem_rdata,low_data};
        assign completed_data[lane*32 +: 32]=words[selected];
    end endgenerate
    always @(posedge clk) begin
        if(reset) begin
            state<=IDLE; cursor<=0; selected<=0; selected_lane<=0; busy<=0; has_pending<=0;
            rsp_valid<=0; rsp_tag<=0; rsp_data<=0; rsp_error<=0;
            aux_rsp_valid<=0; aux_read_data<=0; aux_error<=0;
            owner_aux<=0; prefer_aux<=1; word_address<=0; word_data<=0; word_strobe<=0; low_data<=0;
            for(i=0;i<8;i=i+1) begin pending[i]<=0; errors[i]<=0; end
        end else begin
            if(rsp_valid && rsp_ready) begin rsp_valid<=0; busy[rsp_tag]<=0; end
            if(req_valid && req_ready) begin
                busy[req_tag]<=1; pending[req_tag]<=req_mask; has_pending[req_tag]<=|req_mask;
                errors[req_tag]<=0;
                addresses[req_tag]<=req_address; values[req_tag]<=req_data; stores[req_tag]<=req_write;
            end
            case(state)
                IDLE: if(init_done) begin
                    if(take_aux) begin
                        owner_aux<=1; prefer_aux<=0;
                        word_address<=aux_address; word_data<=aux_write_data; word_strobe<=aux_strobe;
                        aux_error<=0;
                        if(|aux_address[31:25] || |aux_address[1:0]) begin
                            aux_error<=1; aux_read_data<=0; aux_rsp_valid<=1; state<=AUX_RESPONSE;
                        end else state<=SEND_LOW;
                    end else if(found) begin
                        selected<=pick; selected_lane<=lane_pick; prefer_aux<=1;
                        // selected is registered first; the lane address and its
                        // buffers are read with that index on the next cycle.
                        state<=lane_found ? SELECT : VECTOR_RESPONSE;
                    end
                end
                SELECT: if(|selected_address[31:25] || |selected_address[1:0]) begin
                    pending[selected][selected_lane]<=0; has_pending[selected]<=|pending_after_lane;
                    errors[selected][selected_lane]<=1;
                    cursor<=selected+1'b1; state<=IDLE;
                end else begin
                    owner_aux<=0; word_address<=selected_address; word_data<=selected_value;
                    word_strobe<=stores[selected] ? 4'hf : 4'h0; state<=SEND_LOW;
                end
                SEND_LOW: if(mem_req_ready) state<=WAIT_LOW;
                WAIT_LOW: if(mem_done) begin low_data<=mem_rdata; state<=SEND_HIGH; end
                SEND_HIGH: if(mem_req_ready) state<=WAIT_HIGH;
                WAIT_HIGH: if(mem_done) begin
                    if(owner_aux) begin
                        aux_read_data<={mem_rdata,low_data}; aux_rsp_valid<=1; state<=AUX_RESPONSE;
                    end else begin
                        pending[selected][selected_lane]<=0; has_pending[selected]<=|pending_after_lane;
                        cursor<=selected+1'b1; state<=IDLE;
                    end
                end
                AUX_RESPONSE: if(aux_rsp_valid && aux_rsp_ready) begin aux_rsp_valid<=0; state<=IDLE; end
                VECTOR_RESPONSE: begin
                    rsp_tag<=selected; rsp_data<=completed_data; rsp_error<=errors[selected]; rsp_valid<=1;
                    cursor<=selected+1'b1; state<=IDLE;
                end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
