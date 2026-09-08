`timescale 1ns/1ps
module gpu_lsu_tb;
    reg clk=0; always #5 clk=~clk;
    reg reset=1,req_valid=0,req_write=0,rsp_ready=0;
    wire req_ready,rsp_valid;
    reg [2:0] req_tag=0;
    reg [7:0] req_mask=0;
    reg [255:0] req_address=0,req_data=0;
    wire [2:0] rsp_tag;
    wire [255:0] rsp_data;
    wire [7:0] rsp_error,occupied;
    wire [7:0] bank_valid,bank_write,bank_rsp_ready;
    wire [95:0] bank_row;
    wire [255:0] bank_data;
    reg [7:0] bank_ready=0,bank_rsp_valid=0,bank_rsp_error=0;
    reg [255:0] bank_rsp_data=0;
    gpu_lsu dut(.*);
    // Backend deliberately stalls acceptance and returns banks at different
    // times. This is not the fixed-latency BRAM implementation.
    reg [31:0] words[0:32767];
    integer delay[0:7];
    reg [7:0] servicing=0;
    integer cycle=0,b,count,max_parallel=0;
    reg accept_all=0;
    reg [7:0] previous_stall=0;
    reg [95:0] previous_row;
    reg [255:0] previous_data;
    reg [7:0] previous_write;
    always @(negedge clk) begin
        cycle=cycle+1;
        for(b=0;b<8;b=b+1) bank_ready[b]=!servicing[b] && !bank_rsp_valid[b] && (accept_all || (cycle+b)%5!=0);
    end
    always @(posedge clk) begin
        if(!reset) begin
            count=0;
            for(b=0;b<8;b=b+1) begin
                if(previous_stall[b] && (!bank_valid[b] || bank_row[b*12 +: 12]!==previous_row[b*12 +: 12] ||
                    bank_data[b*32 +: 32]!==previous_data[b*32 +: 32] || bank_write[b]!==previous_write[b]))
                    $fatal(1,"backend request changed before acceptance");
                if(bank_rsp_valid[b] && bank_rsp_ready[b]) bank_rsp_valid[b]<=0;
                if(servicing[b]) begin
                    delay[b]=delay[b]-1;
                    if(delay[b]==0) begin servicing[b]<=0; bank_rsp_valid[b]<=1; end
                end
                if(bank_valid[b] && bank_ready[b]) begin
                    count=count+1;
                    bank_rsp_data[b*32 +: 32]<=words[bank_row[b*12 +: 12]*8+b];
                    if(bank_write[b]) words[bank_row[b*12 +: 12]*8+b]<=bank_data[b*32 +: 32];
                    servicing[b]<=1; delay[b]=80+((cycle*7+b*13)%41);
                end
            end
            if(count>max_parallel) max_parallel=count;
            previous_stall<=bank_valid & ~bank_ready;
            previous_row<=bank_row; previous_data<=bank_data; previous_write<=bank_write;
        end
    end
    task enqueue;
        input [2:0] tag;
        input wr,conflicts;
        integer l;
        begin
            @(negedge clk); req_tag=tag; req_write=wr; req_mask=8'hff;
            for(l=0;l<8;l=l+1) begin
                req_address[l*32 +: 32]=tag*256+l*(conflicts ? 32 : 4);
                req_data[l*32 +: 32]=32'habc00000+tag*8+l;
            end
            req_valid=1;
            do @(posedge clk); while(!req_ready);
            @(negedge clk); req_valid=0;
        end
    endtask
    task drain;
        input reads;
        integer n,l;
        reg [7:0] seen;
        reg [255:0] saved;
        reg [2:0] saved_tag;
        begin
            seen=0;
            for(n=0;n<8;n=n+1) begin
                wait(rsp_valid); @(negedge clk);
                saved=rsp_data; saved_tag=rsp_tag;
                repeat(11) begin
                    @(negedge clk);
                    if(!rsp_valid || rsp_data!==saved || rsp_tag!==saved_tag) $fatal(1,"response changed under backpressure");
                end
                if(rsp_error!==0 || seen[rsp_tag]) $fatal(1,"bad or duplicate response");
                if(reads) for(l=0;l<8;l=l+1)
                    if(rsp_data[l*32 +: 32] !== 32'habc00000+rsp_tag*8+l) $fatal(1,"load data tag %d lane %d",rsp_tag,l);
                seen[rsp_tag]=1; rsp_ready=1;
                @(negedge clk); rsp_ready=0;
            end
            if(seen!==8'hff) $fatal(1,"missing response");
        end
    endtask
    integer t,phase;
    initial begin
        repeat(4) @(negedge clk); reset=0;
        for(phase=0;phase<4;phase=phase+1) begin
            accept_all=phase==2;
            for(t=0;t<8;t=t+1) enqueue(t,phase%2==0,phase<2);
            if(occupied!==8'hff) $fatal(1,"must accept eight warp slots");
            #1;
            if(req_ready) $fatal(1,"must reject duplicate occupied tag");
            drain(phase%2==1);
            $display("PASS LSU phase %d: eight outstanding, variable latency, backpressure",phase);
        end
        // Invalid addresses and inactive lanes: only active invalid lanes fail.
        @(negedge clk); req_tag=0; req_mask=8'h03; req_write=0;
        req_address=0; req_address[31:0]=32'h20000; req_address[63:32]=3;
        req_valid=1; @(negedge clk); req_valid=0;
        wait(rsp_valid); @(negedge clk);
        if(rsp_error!==8'h03) $fatal(1,"invalid address error mask %h",rsp_error);
        rsp_ready=1; @(negedge clk); rsp_ready=0;
        if(max_parallel!=8) $fatal(1,"all eight banks must operate concurrently");
        $display("PASS LSU invalid addresses; maximum simultaneous bank accepts=%d",max_parallel);
        $finish;
    end
    initial begin #1000000; $fatal(1,"LSU watchdog"); end
endmodule
