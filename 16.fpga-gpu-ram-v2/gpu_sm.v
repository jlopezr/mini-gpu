`default_nettype none
module gpu_sm #(parameter SIMT_DEPTH=8, SIMT_REGION_DEPTH=SIMT_DEPTH, SIMT_PATH_DEPTH=8) (
    input clk, reset,
    input run_request, halt_request, step_request,
    output halted,
    output reg error,
    output reg [7:0] error_code,
    output reg [2:0] error_warp, error_lane,
    output reg error_lane_valid,
    output reg [31:0] error_pc,
    output reg instruction_retired,
    output reg [31:0] retired_count,
    output [31:0] debug_warp_retired_count,
    input [2:0] debug_warp, debug_lane,
    input [4:0] debug_register,
    output [31:0] debug_data, debug_pc,
    input cfg_write,
    input [4:0] cfg_word,
    input [31:0] cfg_data,
    input [3:0] cfg_strobe,
    output reg [31:0] cfg_read_data,
    output imem_valid,
    input imem_ready,
    output [31:0] imem_address,
    input imem_rsp_valid,
    output imem_rsp_ready,
    input [31:0] imem_data,
    input imem_error,
    output lsu_valid,
    input lsu_ready,
    output [2:0] lsu_tag,
    output [7:0] lsu_mask,
    output lsu_write,
    output [255:0] lsu_address, lsu_data,
    input lsu_rsp_valid,
    output lsu_rsp_ready,
    input [2:0] lsu_rsp_tag,
    input [255:0] lsu_rsp_data,
    input [7:0] lsu_rsp_error,
    input [7:0] lsu_occupied
);
    localparam INIT=0, PICK=1, RECON=2, FETCH=3, FETCH_WAIT=4,
        RF_WAIT=5, DECODE=6, START=7, EXEC=8, FINISH=9, MEMORY=10, NORMALIZE=11;
    localparam [7:0] ERROR_NONE = 8'h00;
    localparam [7:0] ERROR_INVALID_OPCODE = 8'h01;
    localparam [7:0] ERROR_MEMORY_ACCESS = 8'h02;
    localparam [7:0] ERROR_EXPLICIT_TRAP = 8'h03;
    localparam [7:0] ERROR_DIVISION_BY_ZERO = 8'h04;
    localparam [7:0] ERROR_INVALID_ENCODING = 8'h05;
    localparam [7:0] ERROR_SIMT = 8'h06;
    localparam [7:0] ERROR_BARRIER = 8'h07;
    reg [3:0] state;
    reg [7:0] init_address;
    reg running, pause_pending, stepping;
    reg [2:0] current, cursor;
    reg [31:0] pc[0:7], groups[0:7], generation[0:7];
    reg [7:0] active[0:7], live[0:7];
    reg [7:0] wait_mem, wait_bar;
    reg [4:0] load_rd[0:7];
    reg [7:0] load_mask[0:7];
    reg [7:0] load_is_write;
    reg [31:0] instruction;
    reg [31:0] warp_retired_count[0:7];
    assign debug_warp_retired_count=warp_retired_count[debug_warp];
    localparam SP_BITS=$clog2(SIMT_REGION_DEPTH+1);
    localparam PP_BITS=$clog2(SIMT_PATH_DEPTH+1);
    reg [SP_BITS-1:0] sp[0:7];
    reg [PP_BITS-1:0] pp[0:7];
    reg [31:0] ssy_pc[0:8*SIMT_REGION_DEPTH-1], join_pc[0:8*SIMT_REGION_DEPTH-1];
    reg [7:0] entry_mask[0:8*SIMT_REGION_DEPTH-1];
    reg [PP_BITS-1:0] path_base[0:8*SIMT_REGION_DEPTH-1];
    reg [31:0] pending_pc[0:8*SIMT_PATH_DEPTH-1];
    reg [7:0] pending_mask[0:8*SIMT_PATH_DEPTH-1];
    wire [5:0] opcode=instruction[31:26];
    wire branch=opcode>=6'h20 && opcode<=6'h25;
    wire [4:0] ra=branch ? instruction[25:21] : instruction[20:16];
    wire [4:0] rb=branch ? instruction[20:16] :
        (opcode==6'h16 ? instruction[25:21] : instruction[15:11]);
    wire [31:0] immediate={{16{instruction[15]}},instruction[15:0]};
    wire [31:0] target=pc[current]+4+{{4{instruction[25]}},instruction[25:0],2'b00};
    wire [31:0] branch_target=pc[current]+4+{{14{instruction[15]}},instruction[15:0],2'b00};
    wire [31:0] stack_count={{(32-SP_BITS){1'b0}},sp[current]};
    wire [31:0] top_index={29'b0,current}*SIMT_REGION_DEPTH+(stack_count==0 ? 0 : stack_count-1);
    wire [31:0] push_index={29'b0,current}*SIMT_REGION_DEPTH+stack_count;
    wire [31:0] path_count={{(32-PP_BITS){1'b0}},pp[current]};
    wire [31:0] path_top={29'b0,current}*SIMT_PATH_DEPTH+(path_count==0 ? 0 : path_count-1);
    wire [31:0] path_push={29'b0,current}*SIMT_PATH_DEPTH+path_count;
    assign halted=!running && state==PICK && wait_mem==0 && lsu_occupied==0;
    assign debug_pc=error ? error_pc : pc[debug_warp];
    assign imem_valid=state==FETCH;
    assign imem_address=pc[current];
    assign imem_rsp_ready=state==FETCH_WAIT;
    assign lsu_valid=state==MEMORY;
    assign lsu_tag=current;
    assign lsu_mask=active[current];
    assign lsu_write=opcode==6'h16;
    assign lsu_rsp_ready=state==PICK;

    wire [255:0] rf_a, rf_b, lane_pc, lane_write_data;
    wire [39:0] lane_write_address;
    wire [7:0] lane_we, lane_retired, lane_halted, lane_error;
    wire [63:0] lane_error_code;
    reg [7:0] done;
    wire response_commit=lsu_rsp_valid && lsu_rsp_ready;
    genvar l;
    generate for(l=0;l<8;l=l+1) begin: lanes
        wire rf_write=state==INIT ||
            (response_commit && load_mask[lsu_rsp_tag][l] && !load_is_write[lsu_rsp_tag] && !lsu_rsp_error[l]) ||
            (state==EXEC && active[current][l] && lane_we[l]);
        wire [7:0] wa=state==INIT ? init_address :
            (response_commit ? {lsu_rsp_tag,load_rd[lsu_rsp_tag]} : {current,lane_write_address[l*5 +: 5]});
        wire [31:0] wd=state==INIT ? 32'b0 :
            (response_commit ? lsu_rsp_data[l*32 +: 32] : lane_write_data[l*32 +: 32]);
        gpu_register_file rf (
            .clk(clk), .read_address_a(halted ? {debug_warp,debug_register} : {current,ra}),
            .read_address_b({current,rb}), .read_data_a(rf_a[l*32 +: 32]),
            .read_data_b(rf_b[l*32 +: 32]), .write_enable(rf_write),
            .write_address(wa), .write_data(wd)
        );
        assign lsu_address[l*32 +: 32]=rf_a[l*32 +: 32]+immediate;
        assign lsu_data[l*32 +: 32]=rf_b[l*32 +: 32];
        wire fetch_valid;
        gpu_lane alu (
            .clk(clk), .reset(reset), .launch_pc(pc[current]),
            .thread_id({26'b0,current,l[2:0]}),
            .register_a(rf_a[l*32 +: 32]), .register_b(rf_b[l*32 +: 32]),
            .register_write_enable(lane_we[l]),
            .register_write_address(lane_write_address[l*5 +: 5]),
            .register_write_data(lane_write_data[l*32 +: 32]),
            .run_request(1'b0), .halt_request(1'b0),
            .step_request(state==START && active[current][l]),
            .halted(lane_halted[l]), .error(lane_error[l]),
            .error_code(lane_error_code[l*8 +: 8]), .instruction_retired(lane_retired[l]),
            .imem_valid(fetch_valid), .imem_address(), .imem_read_data(instruction),
            .imem_ready(fetch_valid), .dmem_valid(), .dmem_address(),
            .dmem_write_data(), .dmem_write_enable(), .dmem_read_data(32'b0),
            .dmem_ready(1'b0), .dmem_error(1'b0), .debug_register_address(5'b0),
            .debug_register_data(), .debug_pc(lane_pc[l*32 +: 32])
        );
    end endgenerate
    assign debug_data=rf_a[debug_lane*32 +: 32];

    reg normalize_found;
    reg [2:0] normalize_warp;
    reg pick_found, any_live, all_bar, bar_mismatch;
    reg [2:0] pick_warp;
    reg [7:0] release_bar;
    // Warps con barrera ya satisfecha pendientes de liberar. Se libera uno por
    // ciclo: escribir los ocho a la vez obligaba a inferir ocho puertos de
    // escritura sobre pc, generation y wait_bar.
    reg [7:0] releasing;
    reg release_found;
    reg [2:0] release_warp;
    integer a,b,t;
    reg [2:0] candidate;
    always @* begin
        normalize_found=0; normalize_warp=0;
        pick_found=0; pick_warp=cursor; any_live=0; release_bar=0;
        all_bar=0; bar_mismatch=0; candidate=0;
        for(a=0;a<8;a=a+1) begin
            if (live[a]!=0) any_live=1;
            if (!normalize_found && live[a]!=0 && !wait_mem[a] && !wait_bar[a] &&
                (active[a]==0 || (sp[a]!=0 && pc[a]==join_pc[a*SIMT_REGION_DEPTH+{{(32-SP_BITS){1'b0}},sp[a]}-1]))) begin
                normalize_found=1; normalize_warp=a[2:0];
            end
            candidate=cursor+a[2:0];
            if (!pick_found && live[candidate]!=0 && !wait_mem[candidate] && !wait_bar[candidate]) begin
                pick_found=1; pick_warp=candidate;
            end
            all_bar=wait_bar[a];
            for(b=0;b<8;b=b+1) begin
                if (groups[a]==groups[b] && live[b]!=0 && !wait_bar[b]) all_bar=0;
                if (wait_bar[b] && groups[b]==groups[current] &&
                    (pc[b]!=pc[current] || generation[b]!=generation[current])) bar_mismatch=1;
            end
            release_bar[a]=all_bar;
        end
        release_found=0; release_warp=0;
        for(a=0;a<8;a=a+1)
            if(!release_found && releasing[a]) begin release_found=1; release_warp=a[2:0]; end
    end
    reg [7:0] taken;
    reg alu_fault;
    reg [2:0] fault_lane;
    reg [7:0] fault_code;
    always @* begin
            taken=0; alu_fault=0; fault_lane=0; fault_code=ERROR_NONE;
        for(t=0;t<8;t=t+1) begin
            taken[t]=active[current][t] && lane_pc[t*32 +: 32] != pc[current]+4;
            if (!alu_fault && active[current][t] && lane_error[t]) begin
                alu_fault=1; fault_lane=t[2:0]; fault_code=lane_error_code[t*8 +: 8];
            end
        end
    end
    always @* begin
        case(cfg_word[1:0])
            0: cfg_read_data=pc[cfg_word[4:2]];
            1: cfg_read_data={16'b0,live[cfg_word[4:2]],active[cfg_word[4:2]]};
            2: cfg_read_data=groups[cfg_word[4:2]];
            3: begin
                cfg_read_data=0;
                cfg_read_data[SP_BITS-1:0]=sp[cfg_word[4:2]];
                cfg_read_data[8 +: PP_BITS]=pp[cfg_word[4:2]];
                cfg_read_data[16]=wait_mem[cfg_word[4:2]];
                cfg_read_data[17]=wait_bar[cfg_word[4:2]];
            end
        endcase
    end
    task fault;
        input [7:0] code;
        input [2:0] warp_id, lane_id;
        input lane_valid;
        begin
            if (!error) begin
                error<=1; error_code<=code; error_warp<=warp_id;
                error_lane<=lane_id; error_lane_valid<=lane_valid; error_pc<=pc[warp_id];
            end
            running<=0; pause_pending<=0; state<=PICK;
            // Con el conjunto latcheado hay que descartarlo: antes un error
            // simplemente impedía que la liberación atómica llegara a ocurrir.
            releasing<=0;
        end
    endtask
    task retire;
        begin
            instruction_retired<=1; retired_count<=retired_count+1'b1;
            warp_retired_count[current]<=warp_retired_count[current]+1'b1;
            state<=PICK;
        end
    endtask
    integer w,c;
    always @(posedge clk) begin
        instruction_retired<=0;
        if (reset) begin
            state<=INIT; init_address<=0; running<=0; pause_pending<=0; stepping<=0;
            current<=0; cursor<=0; wait_mem<=0; wait_bar<=0; releasing<=0; load_is_write<=0;
            error<=0; error_code<=ERROR_NONE; error_pc<=0; error_warp<=0; error_lane<=0; error_lane_valid<=0;
            retired_count<=0; instruction<=0; done<=0;
            for(w=0;w<8;w=w+1) begin
                pc[w]<=0; active[w]<=8'hff; live[w]<=8'hff; groups[w]<=0;
                warp_retired_count[w]<=0; generation[w]<=0; sp[w]<=0; pp[w]<=0; load_rd[w]<=0; load_mask[w]<=0;
            end
        end else begin
            if (halt_request && running) pause_pending<=1;
            if (halted && cfg_write) begin
                for(c=0;c<4;c=c+1) if(cfg_strobe[c]) begin
                    if(cfg_word[1:0]==0) pc[cfg_word[4:2]][c*8 +: 8]<=cfg_data[c*8 +: 8];
                    if(cfg_word[1:0]==2) groups[cfg_word[4:2]][c*8 +: 8]<=cfg_data[c*8 +: 8];
                end
                if(cfg_word[1:0]==1 && cfg_strobe[0]) begin
                    active[cfg_word[4:2]]<=cfg_data[7:0]; live[cfg_word[4:2]]<=cfg_data[7:0];
                end
                warp_retired_count[cfg_word[4:2]]<=0; sp[cfg_word[4:2]]<=0; pp[cfg_word[4:2]]<=0;
                wait_bar[cfg_word[4:2]]<=0; releasing[cfg_word[4:2]]<=0; generation[cfg_word[4:2]]<=0;
            end
            case(state)
                INIT: begin
                    init_address<=init_address+1'b1;
                    if(init_address==255) state<=PICK;
                end
                PICK: begin
                    if(response_commit) begin
                        wait_mem[lsu_rsp_tag]<=0;
                        if(|lsu_rsp_error) begin
                            // Lowest failing lane within this response; first observed global fault.
                            for(w=7;w>=0;w=w-1) if(lsu_rsp_error[w]) fault(ERROR_MEMORY_ACCESS,lsu_rsp_tag,w[2:0],1'b1);
                        end else begin
                            pc[lsu_rsp_tag]<=pc[lsu_rsp_tag]+4;
                            instruction_retired<=1; retired_count<=retired_count+1'b1;
                            warp_retired_count[lsu_rsp_tag]<=warp_retired_count[lsu_rsp_tag]+1'b1;
                        end
                    end else if (release_found && !error) begin
                        // Barrier release is a control transition, not another
                        // instruction. Complete it even when STEP/HALT pauses.
                        // El conjunto queda latcheado en releasing, así que basta
                        // con un puerto: se drena un warp por ciclo.
                        wait_bar[release_warp]<=0; releasing[release_warp]<=0;
                        pc[release_warp]<=pc[release_warp]+4;
                        generation[release_warp]<=generation[release_warp]+1'b1;
                    end else if (|release_bar && !error) begin
                        // release_bar deja de valer en cuanto se libera el primer
                        // warp del grupo, por eso se captura entero de una vez.
                        releasing<=release_bar;
                    end else if (normalize_found && !error) begin
                        current<=normalize_warp; state<=NORMALIZE;
                    end else if (pause_pending || (running && !any_live)) begin
                        running<=0; pause_pending<=0;
                    end else if (halted && (run_request || step_request) && !error) begin
                        running<=1; stepping<=!run_request && step_request;
                    end else if (running && !error) begin
                        if (pick_found) begin
                            current<=pick_warp; cursor<=pick_warp+1'b1; state<=RECON;
                        end
                    end
                end
                RECON, NORMALIZE: begin
                    if (sp[current]!=0 && (active[current]==0 || pc[current]==join_pc[top_index])) begin
                        if (pp[current]>path_base[top_index]) begin
                            pc[current]<=pending_pc[path_top];
                            active[current]<=pending_mask[path_top] & live[current];
                            pp[current]<=pp[current]-1'b1;
                        end else begin
                            pc[current]<=join_pc[top_index];
                            active[current]<=entry_mask[top_index] & live[current]; sp[current]<=sp[current]-1'b1;
                        end
                    end else if (active[current]==0) begin
                        if(live[current]==0) state<=PICK;
                        else fault(ERROR_SIMT,current,0,0);
                    end else state<=state==NORMALIZE ? PICK : FETCH;
                end
                FETCH: if(imem_valid && imem_ready) state<=FETCH_WAIT;
                FETCH_WAIT: if(imem_rsp_valid) begin
                    if(imem_error) fault(ERROR_MEMORY_ACCESS,current,0,0);
                    else begin instruction<=imem_data; state<=RF_WAIT; end
                end
                RF_WAIT: state<=DECODE;
                DECODE: begin
                    if(stepping) begin pause_pending<=1; stepping<=0; end
                    if ((opcode==6'h32 || opcode==6'h33 || opcode==6'h3f) && instruction[25:0]!=0)
                        fault(ERROR_INVALID_ENCODING,current,0,0);
                    else case(opcode)
                        6'h15,6'h16: state<=MEMORY;
                        6'h31: begin
                            if(|target[31:17] || |target[1:0]) fault(ERROR_MEMORY_ACCESS,current,0,0);
                            else if(sp[current]!=0 && ssy_pc[top_index]==pc[current]) begin
                                if(join_pc[top_index]!=target) fault(ERROR_SIMT,current,0,0);
                                else begin pc[current]<=pc[current]+4; retire; end
                            end
                            else if(stack_count==SIMT_REGION_DEPTH) fault(ERROR_SIMT,current,0,0);
                            else begin
                                join_pc[push_index]<=target; entry_mask[push_index]<=active[current];
                                ssy_pc[push_index]<=pc[current]; path_base[push_index]<=pp[current];
                                sp[current]<=sp[current]+1'b1; pc[current]<=pc[current]+4; retire;
                            end
                        end
                        6'h32: begin
                            if(active[current]!=live[current] || bar_mismatch) fault(ERROR_BARRIER,current,0,0);
                            else begin wait_bar[current]<=1; retire; end
                        end
                        6'h33,6'h3f: begin
                            live[current]<=live[current] & ~active[current]; active[current]<=0;
                            pc[current]<=pc[current]+4;
                            if ((live[current] & ~active[current])==0) begin
                                sp[current]<=0; pp[current]<=0;
                            end
                            retire;
                        end
                        default: begin done<=~active[current]; state<=START; end
                    endcase
                end
                START: state<=EXEC;
                EXEC: begin
                    done<=done | lane_retired;
                    if(alu_fault) fault(fault_code,current,fault_lane,fault_code==ERROR_DIVISION_BY_ZERO);
                    else if (&done) state<=FINISH;
                end
                FINISH: begin
                    if(branch && taken!=0 && taken!=active[current]) begin
                        if(sp[current]==0) fault(ERROR_SIMT,current,0,0);
                        else if(branch_target==join_pc[top_index]) begin
                            active[current]<=active[current] & ~taken;
                            pc[current]<=pc[current]+4; retire;
                        end else if(pc[current]+4==join_pc[top_index]) begin
                            active[current]<=taken; pc[current]<=branch_target; retire;
                        end else if(path_count==SIMT_PATH_DEPTH) fault(ERROR_SIMT,current,0,0);
                        else begin
                            pending_pc[path_push]<=branch_target; pending_mask[path_push]<=taken;
                            pp[current]<=pp[current]+1'b1; active[current]<=active[current] & ~taken;
                            pc[current]<=pc[current]+4; retire;
                        end
                    end else begin
                        if (branch && taken!=0) pc[current]<=branch_target;
                        else if(opcode==6'h2f) pc[current]<=target;
                        else pc[current]<=pc[current]+4;
                        retire;
                    end
                end
                MEMORY: if(lsu_valid && lsu_ready) begin
                    wait_mem[current]<=1; load_rd[current]<=instruction[25:21];
                    load_mask[current]<=active[current]; load_is_write[current]<=lsu_write;
                    state<=PICK;
                end
                default: fault(ERROR_INVALID_OPCODE,current,0,0);
            endcase
        end
    end
endmodule
`default_nettype wire
