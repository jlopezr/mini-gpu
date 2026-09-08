`timescale 1ns/1ps
module gpu_scheduler_tb;
    reg clk=0; always #5 clk=~clk;
    reg reset=1,run_request=0,halt_request=0,step_request=0;
    wire halted,error,instruction_retired,error_lane_valid;
    wire [7:0] error_code;
    wire [2:0] error_warp,error_lane;
    wire [31:0] error_pc,retired_count,debug_data,debug_pc,cfg_read_data;
    reg [2:0] debug_warp=0,debug_lane=0;
    reg [4:0] debug_register=3,cfg_word=0;
    reg cfg_write=0;
    reg [31:0] cfg_data=0;
    reg [3:0] cfg_strobe=15;
    wire imem_valid,imem_rsp_ready;
    wire [31:0] imem_address;
    reg imem_rsp_valid=0,imem_error=0;
    wire imem_ready=!imem_rsp_valid;
    reg [31:0] imem_data=0;
    wire lsu_valid,lsu_write,lsu_rsp_ready;
    wire [2:0] lsu_tag;
    wire [7:0] lsu_mask;
    wire [255:0] lsu_address,lsu_data;
    reg [7:0] lsu_occupied=0;
    wire lsu_ready=!lsu_occupied[lsu_tag];
    reg lsu_rsp_valid=0;
    reg [2:0] lsu_rsp_tag=0;
    reg [255:0] lsu_rsp_data={8{32'd40}};
    reg [7:0] lsu_rsp_error=0;
    gpu_sm dut(.*);
    integer l;
    always @(posedge clk) begin
        if(reset) begin imem_rsp_valid<=0; lsu_occupied<=0; end
        else begin
            if(imem_rsp_valid && imem_rsp_ready) imem_rsp_valid<=0;
            if(imem_valid && imem_ready) begin
                imem_rsp_valid<=1;
                case(imem_address)
                    0: imem_data<=32'hc0200000; // GETTID R1
                    4: imem_data<=32'h54401000; // LOAD R2,R0,4096
                    8: imem_data<=32'h44620001; // ADDI R3,R2,1
                    12: imem_data<=32'hfc000000;
                    16: imem_data<=32'h40600063; // MOVI R3,99
                    20: imem_data<=32'hfc000000;
                    default: imem_data<=32'hf8000000;
                endcase
            end
            if(lsu_valid && lsu_ready) begin
                if(lsu_mask!==255 || lsu_write) $fatal(1,"bad vector request");
                for(l=0;l<8;l=l+1) if(lsu_address[l*32 +: 32]!==4096) $fatal(1,"bad lane address");
                lsu_occupied[lsu_tag]<=1;
            end
            if(lsu_rsp_valid && lsu_rsp_ready) lsu_occupied[lsu_rsp_tag]<=0;
        end
    end
    integer phase,w,lane,cycles;
    initial begin
        for(phase=0;phase<2;phase=phase+1) begin
            reset=1; repeat(4) @(negedge clk); reset=0;
            wait(halted); @(negedge clk);
            if(phase==1) begin
                cfg_word=28; cfg_data=16; cfg_write=1;
                @(negedge clk); cfg_write=0;
            end
            run_request=1; @(negedge clk); run_request=0;
            cycles=0;
            while(lsu_occupied!==(phase==0 ? 8'hff : 8'h7f) && cycles<3000) begin
                @(negedge clk); cycles=cycles+1;
            end
            if(cycles==3000) $fatal(1,"scheduler blocked before other warps could submit memory");
            repeat(200) @(negedge clk);
            if(phase==1 && dut.live[7]!==0) $fatal(1,"ready ALU warp did not finish while seven warps waited");
            for(w=0;w<(phase==0 ? 8 : 7);w=w+1) begin
                lsu_rsp_tag=w; lsu_rsp_valid=1;
                do @(posedge clk); while(!lsu_rsp_ready);
                @(negedge clk); lsu_rsp_valid=0;
            end
            cycles=0;
            while(!halted && cycles<3000) begin @(negedge clk); cycles=cycles+1; end
            if(!halted || error) $fatal(1,"scheduler did not complete");
            for(w=0;w<8;w=w+1) for(lane=0;lane<8;lane=lane+1) begin
                debug_warp=w; debug_lane=lane; repeat(3) @(negedge clk);
                if(debug_data !== (phase==1 && w==7 ? 32'd99 : 32'd41)) $fatal(1,"wrong context writeback");
            end
            $display("PASS scheduler phase %d: outstanding memory and independent warp progress",phase);
        end
        $finish;
    end
    initial begin #1000000; $fatal(1,"scheduler watchdog"); end
endmodule
