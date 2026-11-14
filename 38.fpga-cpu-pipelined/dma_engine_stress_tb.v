`timescale 1ns/1ps
`default_nettype none

// DMA stress regression. Execute with -s dma_engine_stress_tb.
// Default: 2 channels. To test 4: -DDMA_CHANNELS=4.
`ifndef DMA_CHANNELS
`define DMA_CHANNELS 2
`endif
module dma_engine_stress_tb;
    localparam integer NCH = `DMA_CHANNELS;
    localparam integer RAM_SIZE = 131072;
    localparam integer QMAX = 4096;

    reg clk = 0;
    always #5 clk = ~clk;
    reg reset = 1;
    reg select = 0, write = 0;
    reg [3:0] write_mask = 0;
    reg [15:0] address = 0;
    reg [31:0] write_data = 0;
    wire [31:0] read_data;
    wire mmio_error, irq;
    wire req_valid, req_write;
    wire [31:0] req_addr;
    wire [127:0] req_wdata;
    wire [15:0] req_wmask;
    reg req_ready = 0;
    wire rsp_ready;
    reg rsp_valid = 0;
    reg [127:0] rsp_rdata = 0;
    reg rsp_error = 0;
    reg response_consumed = 0;

    dma_engine #(.NUM_CHANNELS(NCH), .TAG_DEPTH(8)) dut (
        .clk(clk), .reset(reset), .select(select), .write(write),
        .write_mask(write_mask), .address(address),
        .write_data(write_data), .read_data(read_data),
        .mmio_error(mmio_error), .irq(irq),
        .req_valid(req_valid), .req_ready(req_ready),
        .req_write(req_write), .req_addr(req_addr),
        .req_wdata(req_wdata), .req_wmask(req_wmask),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
        .rsp_rdata(rsp_rdata), .rsp_error(rsp_error)
    );

    reg [7:0] mem [0:RAM_SIZE-1];
    reg [127:0] q_data [0:QMAX-1];
    reg q_error [0:QMAX-1];
    reg q_write [0:QMAX-1];
    integer q_head = 0, q_tail = 0, q_count = 0;
    integer tick = 0, accepted = 0, completed = 0;
    integer peak_pending = 0, read_tx = 0, write_tx = 0;
    integer stalled_requests = 0;
    integer delayed_responses = 0;
    integer read_errs = 0, write_errs = 0;
    integer last_channel = -1, switches = 0;
    integer i, b;
    reg [127:0] temp;
    reg [31:0] status_value;
    reg [31:0] scratch;

    // Error injection is one-shot, selected by physical address and operation.
    reg inject_enabled = 0;
    reg inject_write = 0;
    reg [31:0] inject_address = 0;
    reg injected = 0;
    reg [31:0] error_addr_seen = 0;

    // Enqueue on acceptance, retire in order. Drive the response on negedge
    // to avoid a sampling race with the engine's posedge state changes.
    // Hold the offered response stable until it handshakes.
    always @(negedge clk) begin
        if (reset) begin
            req_ready = 0;
            rsp_valid = 0;
            rsp_rdata = 0;
            rsp_error = 0;
        end else begin
            tick = tick + 1;
            req_ready = (tick % 17 >= 5);
            if (!rsp_valid || response_consumed) begin
                rsp_valid = (q_count != 0) && (tick % 23 >= 9);
                rsp_rdata = (q_count != 0) ? q_data[q_head] : 128'd0;
                rsp_error = (q_count != 0) ? q_error[q_head] : 1'b0;
            end
            response_consumed = 0;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            q_head = 0;
            q_tail = 0;
            q_count = 0;
        end else begin
            if (req_valid && !req_ready) stalled_requests = stalled_requests + 1;
            if (q_count > 0 && !rsp_valid) delayed_responses = delayed_responses + 1;
            if (rsp_valid && rsp_ready) begin
                response_consumed = 1;
                if (q_count == 0) $fatal(1, "response with empty queue");
                q_head = (q_head + 1) % QMAX;
                q_count = q_count - 1;
                completed = completed + 1;
            end
            if (req_valid && req_ready) begin
                if (req_addr[3:0] !== 4'd0 || req_addr > RAM_SIZE-16)
                    $fatal(1, "unaligned or out-of-range request addr=%h", req_addr);
                if (q_count == QMAX) $fatal(1, "memory response queue full");
                temp = 128'd0;
                for (b=0; b<16; b=b+1) temp[8*b +: 8] = mem[req_addr+b];
                q_data[q_tail] = temp;
                q_write[q_tail] = req_write;
                q_error[q_tail] = inject_enabled && !injected &&
                    (req_write == inject_write) && (req_addr == inject_address);
                if (q_error[q_tail]) begin
                    injected = 1;
                    error_addr_seen = req_addr;
                    if (req_write) write_errs = write_errs + 1;
                    else read_errs = read_errs + 1;
                end
                if (req_write && !q_error[q_tail]) begin
                    for (b=0; b<16; b=b+1)
                        if (req_wmask[b]) mem[req_addr+b] = req_wdata[8*b +: 8];
                end
                q_tail = (q_tail + 1) % QMAX;
                q_count = q_count + 1;
                if (q_count > peak_pending) peak_pending = q_count;
                accepted = accepted + 1;
                if (req_write) write_tx = write_tx + 1;
                else read_tx = read_tx + 1;
                if ((req_addr >> 12) != last_channel) begin
                    if (last_channel != -1) switches = switches + 1;
                    last_channel = (req_addr >> 12);
                end
            end
        end
    end

    task mmio_wr(input [15:0] a, input [31:0] d);
    begin
        @(negedge clk);
        select=1; write=1; write_mask=4'hf; address=a; write_data=d;
        #1;
        if (mmio_error !== 1'b0) $fatal(1, "MMIO WRITE error at %h data=%h", a, d);
        @(posedge clk);
        @(negedge clk); select=0; write=0;
    end
    endtask

    task mmio_rd(input [15:0] a, output [31:0] result);
    begin
        @(negedge clk);
        select=1; write=0; write_mask=0; address=a; write_data=0;
        #1;
        if (mmio_error !== 1'b0) $fatal(1, "MMIO READ error at %h", a);
        result=read_data;
        @(negedge clk); select=0;
    end
    endtask

    task channel_config(
        input integer ch, input [31:0] src_a, input [31:0] dst_a,
        input [31:0] w, input [31:0] h, input [31:0] ss,
        input [31:0] ds, input [31:0] pat
    );
        reg [15:0] off;
    begin
        off=ch*64;
        mmio_wr(off+16'h00, src_a);
        mmio_wr(off+16'h04, dst_a);
        mmio_wr(off+16'h08, w);
        mmio_wr(off+16'h0c, h);
        mmio_wr(off+16'h10, ss);
        mmio_wr(off+16'h14, ds);
        mmio_wr(off+16'h18, pat);
    end
    endtask

    task wait_status(input integer ch, input reg want_error);
        integer tries;
        reg [31:0] s;
        reg [15:0] off;
    begin
        off=ch*64+16'h20;
        s=0;
        for (tries=0; tries<15000; tries=tries+1) begin
            mmio_rd(off,s);
            if (!s[0]) begin
                if (want_error) begin
                    if (!s[2] || s[1])
                        $fatal(1, "CH%0d expected ERROR, status=%h", ch,s);
                end else if (!s[1] || s[2])
                    $fatal(1, "CH%0d expected DONE, status=%h", ch,s);
                if (q_count != 0)
                    $fatal(1, "CH%0d finished while %0d responses pending", ch,q_count);
                disable wait_status;
            end
        end
        $fatal(1, "timeout waiting CH%0d: status=%h pending=%0d", ch,s,q_count);
    end
    endtask

    task check_fill2d(input integer base, input integer w, input integer h,
                      input integer stride, input [7:0] value);
        integer row, col;
    begin
        for (row=0; row<h; row=row+1)
            for (col=0; col<stride; col=col+1)
                if (mem[base+row*stride+col] !== ((col<w)?value:8'hcc))
                    $fatal(1, "FILL2D bad byte at %h got=%h",base+row*stride+col,
                           mem[base+row*stride+col]);
    end
    endtask

    initial begin
        if (NCH != 2 && NCH != 4)
            $fatal(1, "Use DMA_CHANNELS=2 or 4");
        for (i=0; i<RAM_SIZE; i=i+1) mem[i]=8'hcc;
        for (i=0; i<8192; i=i+1) mem[16'h8000+i]=(i*13+7) & 255;
        repeat (6) @(negedge clk);
        reset=0;
        mmio_rd(16'h204,scratch);
        if (scratch !== NCH) $fatal(1, "DMA_CAPS channels=%0d expected=%0d",scratch,NCH);

        // 1. Large 2D FILL: 32 lines of 256 B with a 64-B gap.
        $display("TEST large FILL2D");
        channel_config(0, 0, 32'h1000, 256, 32, 0, 320, 32'h3C3C3C3C);
        mmio_wr(16'h01c,3);
        wait_status(0,0);
        check_fill2d('h1000,256,32,320,8'h3c);
        if (accepted != completed) $fatal(1,"FILL finished with in-flight operations");

        // 2. Long COPY, source and destination nonoverlapping.
        $display("TEST large COPY");
        channel_config(0, 32'h8000,32'h4000,2048,4,2048,2304,0);
        mmio_wr(16'h01c,1);
        wait_status(0,0);
        for (i=0; i<4; i=i+1)
            for (b=0; b<2048; b=b+1)
                if (mem['h4000+i*2304+b] !== mem['h8000+i*2048+b])
                    $fatal(1,"COPY mismatch row=%0d byte=%0d",i,b);

        // 3. Two concurrent channels (COPY + FILL). Note that the
        // current RTL is expected to reveal any outstanding-response bugs.
        $display("TEST concurrent channels");
        channel_config(0,32'h8000,32'hB000,1024,2,1024,1152,0);
        channel_config(1,0,32'hC000,1024,2,0,1152,32'h9A9A9A9A);
        mmio_wr(16'h01c,1);
        mmio_wr(16'h05c,3);
        // Poll both until both have finished. Each has independent state.
        begin : concurrent_wait
            integer t;
            reg [31:0] s0,s1;
            for (t=0; t<15000; t=t+1) begin
                mmio_rd(16'h020,s0);
                mmio_rd(16'h060,s1);
                if (!s0[0] && !s1[0]) begin
                    if (!s0[1] || s0[2] || !s1[1] || s1[2])
                        $fatal(1,"Concurrent status CH0=%h CH1=%h",s0,s1);
                    if (q_count != 0) $fatal(1,"Concurrent pending responses=%0d",q_count);
                    disable concurrent_wait;
                end
            end
            $fatal(1,"Concurrent test timeout");
        end
        for (i=0; i<2048; i=i+1) begin
            if (mem['hB000+(i/1024)*1152+(i%1024)] !== mem['h8000+i])
                $fatal(1,"Concurrent COPY data mismatch at %0d",i);
        end
        check_fill2d('hC000,1024,2,1152,8'h9a);

        // 4. Optional additional load from CH2 and CH3 when NCH=4.
        if (NCH==4) begin
            $display("TEST 4-channel configuration");
            channel_config(2,0,32'hD000,256,4,0,320,32'h22222222);
            channel_config(3,0,32'hE000,256,4,0,320,32'h33333333);
            mmio_wr(16'h09c,3);
            mmio_wr(16'h0dc,3);
            begin : four_wait
                integer t;
                reg [31:0] s2,s3;
                for (t=0; t<15000; t=t+1) begin
                    mmio_rd(16'h0a0,s2);
                    mmio_rd(16'h0e0,s3);
                    if (!s2[0] && !s3[0]) begin
                        if (!s2[1] || s2[2] || !s3[1] || s3[2])
                            $fatal(1,"4ch status %h %h",s2,s3);
                        disable four_wait;
                    end
                end
                $fatal(1,"4ch timeout");
            end
            check_fill2d('hD000,256,4,320,8'h22);
            check_fill2d('hE000,256,4,320,8'h33);
        end

        // 5. Inject a READ failure and verify it terminates with ERROR,
        // does not report DONE, and leaves no queued requests.
        $display("TEST read error");
        channel_config(0,32'h8000,32'hF000,512,1,512,512,0);
        injected=0; inject_enabled=1; inject_write=0; inject_address=32'h8000;
        mmio_wr(16'h01c,1);
        wait_status(0,1);
        if (!injected || read_errs != 1)
            $fatal(1,"READ error was not injected exactly once");
        inject_enabled=0;
        mmio_wr(16'h020,32'h6);

        // 6. Inject a WRITE failure on a small FILL.
        $display("TEST write error");
        channel_config(0,0,32'hF800,256,1,0,256,32'h5E5E5E5E);
        injected=0; inject_enabled=1; inject_write=1; inject_address=32'hF800;
        mmio_wr(16'h01c,3);
        wait_status(0,1);
        if (!injected || write_errs != 1)
            $fatal(1,"WRITE error was not injected exactly once");
        inject_enabled=0;

        if (accepted !== completed || q_count != 0)
            $fatal(1,"pending responses at end: accepted=%0d complete=%0d pending=%0d",accepted,completed,q_count);

        if (peak_pending < 2 ||
            stalled_requests == 0 ||
            delayed_responses == 0 ||
            switches == 0)
            $fatal(1,
                "insufficient coverage: peak=%0d reqstall=%0d rspdelay=%0d switches=%0d",
                peak_pending,
                stalled_requests,
                delayed_responses,
                switches);

        $display("PASS dma_engine_stress_tb channels=%0d requests=%0d responses=%0d reads=%0d writes=%0d peak=%0d switches=%0d",
            NCH,accepted,completed,read_tx,write_tx,peak_pending,switches);
        $finish;
    end
    initial begin
        #4000000;
        $fatal(1,"GLOBAL WATCHDOG dma_engine_stress_tb");
    end
endmodule
`default_nettype wire
