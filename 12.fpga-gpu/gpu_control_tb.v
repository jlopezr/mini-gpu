`timescale 1ns/1ps
module gpu_control_tb;
    reg clk=0;
    always #5 clk=~clk;
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
    gpu_system dut(.*,.instruction_retired(retired));
    reg [31:0] program_words[0:255],expected[0:2047],expected_memory[0:511],config_words[0:23],expected_state[0:23];
    reg [1023:0] path;
    reg [7:0] byte_result;
    reg [31:0] word_result;
    integer test_id,i,w,l,r,cycles;
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
    initial begin
        repeat(4) @(negedge clk); reset=0;
        fresh; write_word(0,32'hf8000000); launch; stopped(3,0); // TRAP
        fresh; write_word(0,32'hb8000000); launch; stopped(1,0); // illegal opcode
        fresh; write_word(0,32'hfc000001); launch; stopped(5,0); // reserved bits
        fresh; write_word(0,32'h30200000); launch; stopped(4,0); // DIV R1,R0,R0
        fresh; write_word(0,32'h54200001); launch; stopped(2,0); // LOAD R1,R0,1
        fresh; write_word(0,32'h58200003); launch; stopped(2,0); // STORE R1,R0,3
        fresh; write_word(32'h80000000,32'h20000); launch; stopped(2,32'h20000);
        fresh;
        for(i=0;i<9;i=i+1) write_word(i*4,32'hc4000010); // nine nested SSY frames
        launch; stopped(6,32);
        fresh;
        write_word(0,32'hc0200000); // GETTID R1
        write_word(4,32'h80200001); // BEQ R1,R0,+1 without SSY
        write_word(8,32'hfc000000); write_word(12,32'hfc000000);
        launch; stopped(6,4);
        fresh;
        write_word(0,32'hc0200000);
        write_word(4,32'hc4000002); // SSY PC16
        write_word(8,32'h80200001); // BEQ R1,R0,PC16
        write_word(12,32'hc8000000); // divergent BAR
        write_word(16,32'hfc000000);
        launch; stopped(7,12);
        fresh;
        write_word(0,32'hc8000000); write_word(4,32'hfc000000);
        write_word(8,32'hc8000000); write_word(12,32'hfc000000);
        write_word(32'h80000014,255); write_word(32'h80000010,8);
        launch; stopped(7,8);
        $display("PASS fault diagnostics: ISA, memory, division, stack and barriers");

        fresh; write_word(0,32'hc8000000); write_word(4,32'hfc000000);
        @(negedge clk); step_request=1;
        @(negedge clk); step_request=0;
        stopped(0,4);
        if(dut.sm.wait_bar!==0 || dut.sm.generation[0]!==1) $fatal(1,"BAR step did not release");

        // STEP counts one warp instruction and drains a pending load.
        fresh;
        write_word(4096,32'h12345678);
        write_word(0,32'h40201000); // MOVI R1,4096
        write_word(4,32'h54410000); // LOAD R2,R1,0
        write_word(8,32'hfc000000);
        @(negedge clk); step_request=1;
        @(negedge clk); step_request=0;
        stopped(0,4);
        if(dut.sm.retired_count!==1) $fatal(1,"STEP retired too much");
        @(negedge clk); step_request=1;
        @(negedge clk); step_request=0;
        stopped(0,8);
        debug_register=2; repeat(3) @(negedge clk);
        if(debug_data!==32'h12345678 || dut.occupied!==0) $fatal(1,"LOAD step did not drain");
        launch; stopped(0,12);
        fresh; read_word(4096);
        if(word_result!==32'h12345678) $fatal(1,"reset erased RAM");

        // Explicit halt at an instruction boundary, then resume the loop.
        write_word(0,32'h44210001); // ADDI R1,R1,1
        write_word(4,32'hbffffffe); // BRA 0
        launch; repeat(80) @(negedge clk);
        // The host cannot take memory ownership while GPU runs.
        host_address=0; host_read_enable=1;
        @(negedge clk); host_read_enable=0;
        if(!host_ready || !host_error) $fatal(1,"running host access was not rejected");
        halt_request=1; @(negedge clk); halt_request=0;
        cycles=0; while(!halted && cycles<1000) begin @(negedge clk); cycles=cycles+1; end
        if(!halted || error) $fatal(1,"halt failed");
        debug_register=1; repeat(3) @(negedge clk); word_result=debug_data;
        launch; repeat(80) @(negedge clk);
        halt_request=1; @(negedge clk); halt_request=0;
        wait(halted); repeat(3) @(negedge clk);
        if(debug_data<=word_result) $fatal(1,"resume failed");
        $display("PASS STEP, halt/resume, host arbitration and RAM preservation");
        $finish;
    end
    initial begin #20000000; $fatal(1,"control watchdog"); end
endmodule
