`timescale 1ns/1ps
module gpu_regions_tb;
    reg clk=0;
    always #20 clk=~clk;
    reg reset=1,gpu_reset=0,run_request=0,halt_request=0,step_request=0;
    wire halted,error,retired;
    wire [7:0] error_code;
    reg [31:0] host_address=0;
    reg [7:0] host_write_data=0;
    reg host_write_enable=0,host_read_enable=0;
    wire [7:0] host_read_data;
    wire host_ready,host_error;
    reg [4:0] debug_register=0;
    wire [31:0] debug_data,debug_pc;
    `include "sim/system_memory.vh"
    gpu_system #(.SIMT_REGION_DEPTH(1), .SIMT_PATH_DEPTH(2)) dut(.*,.instruction_retired(retired));
    reg [7:0] byte_result;
    reg [31:0] word_result;
    integer i,w,cycles;
    task access;
        input wr;
        input [31:0] addr;
        input [7:0] data;
        begin
            @(negedge clk); host_address=addr; host_write_data=data;
            host_write_enable=wr; host_read_enable=!wr;
            @(negedge clk); host_write_enable=0; host_read_enable=0;
            cycles=0;
            while(!host_ready && cycles<100) begin @(negedge clk); cycles=cycles+1; end
            if(!host_ready || host_error) $fatal(1,"host access failed %h",addr);
            byte_result=host_read_data;
        end
    endtask
    task write_word;
        input [31:0] addr,data;
        integer j;
        begin for(j=0;j<4;j=j+1) access(1,addr+j,data[j*8 +: 8]); end
    endtask
    task read_word;
        input [31:0] addr;
        integer j;
        begin for(j=0;j<4;j=j+1) begin access(0,addr+j,0); word_result[j*8 +: 8]=byte_result; end end
    endtask
    task fresh;
        begin
            @(negedge clk); gpu_reset=1;
            @(negedge clk); gpu_reset=0;
            wait(halted); @(negedge clk);
            for(w=1;w<8;w=w+1) write_word(32'h80000004+w*16,0);
        end
    endtask
    task launch;
        begin
            @(negedge clk); run_request=1;
            @(negedge clk); run_request=0;
        end
    endtask
    task stopped;
        input [7:0] code;
        input [31:0] pc_expected;
        begin
            cycles=0;
            while(!halted && cycles<20000) begin @(negedge clk); cycles=cycles+1; end
            if(!halted || error_code!==code || error!==(code!=0) || debug_pc!==pc_expected)
                $fatal(1,"stop got halt=%b error=%h pc=%h expected error=%h pc=%h state=%d",halted,error_code,debug_pc,code,pc_expected,dut.sm.state);
            if(code!=0) begin
                launch;
                repeat(10) @(negedge clk);
                if(!halted || error_code!==code || debug_pc!==pc_expected) $fatal(1,"fault resumed without reset");
            end
        end
    endtask
    task single_step;
        input [31:0] expected_pc;
        begin
            @(negedge clk); step_request=1;
            @(negedge clk); step_request=0;
            stopped(0,expected_pc);
        end
    endtask
    initial begin
        repeat(4) @(negedge clk); reset=0;
        // A single region survives many iterations, including reduced masks.
        fresh;
        write_word(0,32'hc0200000); // GETTID R1
        write_word(4,32'h44210014); // ADDI R1, R1, 20
        write_word(8,32'hc4000003); // SSY +3
        write_word(12,32'h8c410002); // BGE R2, R1, 2
        write_word(16,32'h44420001); // ADDI R2, R2, 1
        write_word(20,32'hbffffffc); // BRA -4
        write_word(24,32'h44620000); // ADDI R3, R2, 0
        write_word(28,32'hcc000000); // EXIT
        launch; stopped(0,32);
        if(dut.sm.sp[0]!==0 || dut.sm.pp[0]!==0) $fatal(1,"finished stacks not cleared");
        for(i=0;i<8;i=i+1) begin
            access(1,32'h80000100,i);
            @(negedge clk); debug_register=3;
            repeat(3) @(negedge clk);
            if(debug_data!==20+i) $fatal(1,"parked lane %0d result %h",i,debug_data);
        end
        access(1,32'h80000100,0);
        // Third pending path overflows independently of the one-region limit.
        fresh;
        write_word(0,32'hc0200000); // GETTID R1
        write_word(4,32'hc4000004); // SSY +4
        write_word(8,32'h80200002); // BEQ R1, R0, 2
        write_word(12,32'h4421ffff); // ADDI R1, R1, -1
        write_word(16,32'hbffffffc); // BRA -4
        write_word(20,32'hbc000000); // BRA +0
        write_word(24,32'hcc000000); // EXIT
        launch; stopped(6,8);
        if(dut.sm.sp[0]!==1 || dut.sm.pp[0]!==2 || dut.sm.active[0]!==8'hfc)
            $fatal(1,"path overflow changed SIMT state");
        read_word(32'h8000000c);
        if(word_result!==32'h201) $fatal(1,"independent stack status %h",word_result);
        write_word(32'h80000008,0);
        if(dut.sm.sp[0]!==0 || dut.sm.pp[0]!==0) $fatal(1,"configuration did not clear stacks");
        // Direct join remains legal with both path slots occupied.
        fresh;
        write_word(0,32'hc0200000); // GETTID R1
        write_word(4,32'hc400000a); // SSY +10
        write_word(8,32'h80200006); // BEQ R1, R0, 6
        write_word(12,32'h40400001); // MOVI R2, 1
        write_word(16,32'h80220006); // BEQ R1, R2, 6
        write_word(20,32'h40400004); // MOVI R2, 4
        write_word(24,32'h88220005); // BLT R1, R2, 5
        write_word(28,32'h40600014); // MOVI R3, 20
        write_word(32,32'hbc000003); // BRA +3
        write_word(36,32'h4060000a); // MOVI R3, 10
        write_word(40,32'hbc000001); // BRA +1
        write_word(44,32'h4060001e); // MOVI R3, 30
        write_word(48,32'h44630001); // ADDI R3, R3, 1
        write_word(52,32'hcc000000); // EXIT
        launch; stopped(0,56);
        for(i=0;i<8;i=i+1) begin
            access(1,32'h80000100,i);
            @(negedge clk); debug_register=3;
            repeat(3) @(negedge clk);
            if(debug_data!==(i==0 ? 11 : i==1 ? 31 : i<4 ? 1 : 21))
                $fatal(1,"full path direct join lane %0d result %h",i,debug_data);
        end
        access(1,32'h80000100,0);
        // Distinct sites sharing a join still require two regions.
        fresh;
        write_word(0,32'hc4000001); // SSY +1
        write_word(4,32'hc4000000); // SSY +0
        write_word(8,32'hcc000000); // EXIT
        launch; stopped(6,4);
        // Target validation wins over region overflow.
        fresh;
        write_word(0,32'hc4000001); // SSY +1
        write_word(4,32'hc4007ffe); // SSY +32766
        write_word(8,32'hcc000000); // EXIT
        launch; stopped(2,4);
        // Reusing an opening after its code changes must preserve the region.
        fresh;
        write_word(0,32'hc4000001); // SSY +1
        write_word(4,32'hbffffffe); // BRA -2
        write_word(8,32'hcc000000); // EXIT
        write_word(12,32'hcc000000); // EXIT
        single_step(4); single_step(0);
        write_word(0,32'hc4000002); // same SSY site, changed join from 8 to 12
        launch; stopped(6,0);
        if(dut.sm.join_pc[0]!==8 || dut.sm.sp[0]!==1) $fatal(1,"changed join replaced region");
        // STEP must finish all zero-instruction reconvergence transitions.
        fresh;
        write_word(0,32'hc4000000); // SSY +0
        write_word(4,32'hcc000000); // EXIT
        single_step(4);
        if(dut.sm.sp[0]!==0 || dut.sm.retired_count!==1) $fatal(1,"SSY step not normalized");
        fresh;
        write_word(0,32'hc0200000); // GETTID R1
        write_word(4,32'hc4000002); // SSY +2
        write_word(8,32'h80200001); // BEQ R1, R0, 1
        write_word(12,32'hbc000000); // BRA +0
        write_word(16,32'hcc000000); // EXIT
        single_step(4); single_step(8); single_step(12);
        if(dut.sm.active[0]!==8'hfe || dut.sm.pp[0]!==0) $fatal(1,"direct join did not park");
        single_step(16);
        if(dut.sm.active[0]!==8'hff || dut.sm.sp[0]!==0 || dut.sm.retired_count!==4)
            $fatal(1,"branch step not normalized");
        fresh;
        if(dut.sm.sp[0]!==0 || dut.sm.pp[0]!==0) $fatal(1,"reset did not clear stacks");
        $display("PASS reusable regions: independent limits, parking, faults, STEP and reset");
        $finish;
    end
    initial begin #20000000; $fatal(1,"watchdog"); end
endmodule

`include "sim/sdram_model.vh"
