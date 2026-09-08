`timescale 1ns/1ps
module gpu_system_tb;
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
    `include "fixtures/count.vh"
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
    initial begin
        repeat(4) @(negedge clk); reset=0;
        for(test_id=0;test_id<CASES;test_id=test_id+1) begin
            @(negedge clk); gpu_reset=1;
            @(negedge clk); gpu_reset=0;
            wait(halted); @(negedge clk);
            $sformat(path,"fixtures/%02d.program.hex",test_id); $readmemh(path,program_words);
            $sformat(path,"fixtures/%02d.regs.hex",test_id); $readmemh(path,expected);
            $sformat(path,"fixtures/%02d.memory.hex",test_id); $readmemh(path,expected_memory);
            $sformat(path,"fixtures/%02d.config.hex",test_id); $readmemh(path,config_words);
            $sformat(path,"fixtures/%02d.state.hex",test_id); $readmemh(path,expected_state);
            for(i=0;i<256;i=i+1) write_word(i*4,program_words[i]);
            for(i=0;i<512;i=i+1) write_word(4096+i*4,0);
            for(w=0;w<8;w=w+1) begin
                write_word(32'h80000000+w*16,config_words[w*3]);
                write_word(32'h80000004+w*16,config_words[w*3+1]);
                write_word(32'h80000008+w*16,config_words[w*3+2]);
            end
            @(negedge clk); run_request=1;
            @(negedge clk); run_request=0;
            cycles=0;
            while(!halted && cycles<200000) begin @(negedge clk); cycles=cycles+1; end
            if(!halted || error) $fatal(1,"case %0d stopped: halted=%b code=%h pc=%h warp=%d state=%d",test_id,halted,error_code,debug_pc,dut.sm.error_warp,dut.sm.state);
            for(w=0;w<8;w=w+1) begin
                for(l=0;l<8;l=l+1) begin
                    access(1,32'h80000100,w*8+l);
                    for(r=0;r<32;r=r+1) begin
                        @(negedge clk); debug_register=r;
                        repeat(3) @(negedge clk);
                        if(debug_data !== expected[w*256+l*32+r])
                            $fatal(1,"case %0d w%0d lane%0d R%0d got %h expected %h",test_id,w,l,r,debug_data,expected[w*256+l*32+r]);
                    end
                end
                read_word(32'h80000000+w*16);
                if(word_result!==expected_state[w*3]) $fatal(1,"case %d warp %d PC got %h expected %h",test_id,w,word_result,expected_state[w*3]);
            end
            for(i=0;i<512;i=i+1) begin
                read_word(4096+i*4);
                if(word_result !== expected_memory[i]) $fatal(1,"case %0d mem %h got %h expected %h",test_id,4096+i*4,word_result,expected_memory[i]);
            end
            $display("PASS differential case %0d",test_id);
        end
        $display("PASS all differential GPU cases"); $finish;
    end
    initial begin #200000000; $fatal(1,"watchdog"); end
endmodule
