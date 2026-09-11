`timescale 1ns/1ps
module gpu_lsu_tb;
    reg clk=0; always #20 clk=~clk;
    reg reset=1,cancel=0;
    reg req_valid=0,req_write=0,rsp_ready=0;
    wire req_ready,rsp_valid;
    reg [2:0] req_tag=0;
    reg [7:0] req_mask=0;
    reg [255:0] req_address=0,req_data=0;
    wire [2:0] rsp_tag;
    wire [255:0] rsp_data;
    wire [7:0] rsp_error,occupied;
    reg aux_valid=0,aux_rsp_ready=1;
    reg [31:0] aux_address=0,aux_write_data=0;
    reg [3:0] aux_strobe=0;
    wire aux_ready,aux_rsp_valid,aux_error;
    wire [31:0] aux_read_data;
    `include "sim/system_memory.vh"
    gpu_lsu dut(.*,.reset(reset || cancel));
    integer t,l,n,count;
    reg [7:0] seen;
    reg [255:0] held;
    reg [2:0] held_tag;
    task send(input [2:0] tag,input wr,input [7:0] mask,input [31:0] base);
        begin
            @(negedge clk); req_tag=tag; req_write=wr; req_mask=mask;
            for(integer j=0;j<8;j=j+1) begin
                req_address[j*32 +: 32]=base+j*4;
                req_data[j*32 +: 32]=32'ha5000000+tag*256+j;
            end
            req_valid=1;
            do @(posedge clk); while(!req_ready);
            @(negedge clk); req_valid=0;
        end
    endtask
    task auxiliary(input [31:0] addr,input [31:0] value,input [3:0] mask);
        begin
            @(negedge clk); aux_valid=1; aux_address=addr; aux_write_data=value; aux_strobe=mask;
            do @(posedge clk); while(!aux_ready);
            @(negedge clk); aux_valid=0;
            while(!aux_rsp_valid) @(negedge clk);
            if(aux_error) $fatal(1,"auxiliary failure %h",addr);
            @(negedge clk);
        end
    endtask
    task collect(input wr);
        begin
            seen=0;
            for(integer j=0;j<8;j=j+1) begin
                while(!rsp_valid) @(negedge clk);
                if(seen[rsp_tag] || rsp_error) $fatal(1,"duplicate tag or unexpected lane error");
                seen[rsp_tag]=1;
                if(!wr) for(integer lane=0;lane<8;lane=lane+1)
                    if(rsp_data[lane*32 +: 32]!==32'ha5000000+rsp_tag*256+lane)
                        $fatal(1,"lane data mismatch tag %d lane %d",rsp_tag,lane);
                rsp_ready=1; @(negedge clk); rsp_ready=0;
            end
            if(seen!==8'hff || occupied!==0) $fatal(1,"slots did not drain");
        end
    endtask
    initial begin
        repeat(4) @(negedge clk); reset=0;
        for(t=0;t<8;t=t+1) send(t,1,8'hff,32'h00100000+t*32);
        if(occupied!==8'hff) $fatal(1,"eight vector slots not available");
        while(!rsp_valid) @(negedge clk);
        held=rsp_data; held_tag=rsp_tag;
        // A stalled vector response must not prevent the fetch/host port progressing.
        auxiliary(32'h01fffffc,32'h12345678,4'hf);
        auxiliary(32'h01fffffc,32'h00ab0000,4'b0100);
        auxiliary(32'h01fffffc,0,0);
        if(aux_read_data!==32'h12ab5678) $fatal(1,"last word or byte mask failure");
        if(!rsp_valid || rsp_data!==held || rsp_tag!==held_tag) $fatal(1,"unstable stalled response");
        collect(1);
        for(t=0;t<8;t=t+1) send(t,0,8'hff,32'h00100000+t*32);
        collect(0);
        send(0,0,0,32'hffffffff);
        while(!rsp_valid) @(negedge clk);
        if(rsp_error) $fatal(1,"zero mask generated errors");
        rsp_ready=1; @(negedge clk); rsp_ready=0;
        // Lane zero is the final valid word; lanes 1..7 are out of range.
        send(1,0,8'hff,32'h01fffffc);
        while(!rsp_valid) @(negedge clk);
        if(rsp_error!==8'hfe || rsp_data[31:0]!==32'h12ab5678) $fatal(1,"range validation failure");
        rsp_ready=1; @(negedge clk); rsp_ready=0;
        send(2,0,8'h55,3);
        while(!rsp_valid) @(negedge clk);
        if(rsp_error!==8'h55) $fatal(1,"alignment/mask failure");
        rsp_ready=1; @(negedge clk); rsp_ready=0;
        // Cancel before/after acceptance of either half without resetting SDRAM.
        for(t=1;t<=4;t=t+1) begin
            send(3,0,1,32'h00100000);
            wait(dut.state==t); @(negedge clk); cancel=1;
            @(negedge clk); cancel=0;
            send(4,0,1,32'h01fffffc);
            while(!rsp_valid) @(negedge clk);
            if(rsp_tag!==4 || rsp_error || rsp_data[31:0]!==32'h12ab5678)
                $fatal(1,"stale completion following GPU reset in phase %0d",t);
            rsp_ready=1; @(negedge clk); rsp_ready=0;
        end
        repeat(250) @(negedge clk);
        if(rsp_valid || occupied || ram.refreshes<=8) $fatal(1,"reset drain or refresh failure");
        $display("PASS SDRAM LSU: 8 tags, 64 lanes, backpressure, fetch progress, masks, 32 MiB boundaries, reset and refresh");
        $finish;
    end
    initial begin #10000000; $fatal(1,"LSU watchdog"); end
endmodule
`include "sim/sdram_model.vh"
