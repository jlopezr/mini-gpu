`timescale 1ns/1ps
`default_nettype none

// Directed, self-checking test for dma_engine.v (NUM_CHANNELS=2).
// The mock port returns one ordered response per accepted 128-bit request.
// No external SDRAM/fabric is needed.
module dma_engine_tb;
    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg reset = 1'b1;
    reg select = 1'b0, write = 1'b0;
    reg [3:0] write_mask = 4'h0;
    reg [15:0] address = 16'h0;
    reg [31:0] write_data = 32'h0;
    wire [31:0] read_data;
    wire mmio_error, irq;

    wire req_valid, req_write;
    wire [31:0] req_addr;
    wire [127:0] req_wdata;
    wire [15:0] req_wmask;
    reg req_ready = 1'b0;
    wire rsp_ready;
    reg rsp_valid = 1'b0;
    reg [127:0] rsp_rdata = 128'd0;
    reg rsp_error = 1'b0;

    dma_engine #(.NUM_CHANNELS(2), .TAG_DEPTH(8)) dut (
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

    // 64 KiB byte-addressed mock RAM, all accesses in test are within range.
    reg [7:0] mem [0:65535];
    reg [127:0] response_q [0:4095];
    reg error_q [0:4095];
    integer q_head = 0, q_tail = 0, q_count = 0;
    integer delay_counter = 0;
    integer accepted = 0, acknowledged = 0;
    integer seen_ch0 = 0, seen_ch1 = 0;
    integer i, b;
    reg [127:0] temp;
    reg [31:0] expected_status;
    integer timeout;
    reg inject_error = 0;

    // Drive responses on falling edge, *not* at the edge sampled by DUT.
    // req_ready is periodically suppressed to exercise request backpressure.
    integer tick = 0;
    always @(negedge clk) begin
        if (reset) begin
            req_ready = 1'b0;
            rsp_valid = 1'b0;
            rsp_rdata = 128'd0;
            rsp_error = 1'b0;
        end else begin
            tick = tick + 1;
            req_ready = (tick % 7 != 0) && (tick % 7 != 1);
            rsp_valid = (q_count != 0) && (tick % 11 >= 3);
            rsp_rdata = (q_count != 0) ? response_q[q_head] : 128'd0;
            rsp_error = (q_count != 0) ? error_q[q_head] : 1'b0;
        end
    end

    // Mock memory: captures data on READ acceptance, applies WRITE on
    // acceptance, but emits completions later and in the same order.
    always @(posedge clk) begin
        if (reset) begin
            q_head = 0;
            q_tail = 0;
            q_count = 0;
        end else begin
            if (rsp_valid && rsp_ready) begin
                if (q_count <= 0) $fatal(1, "response underflow");
                q_head = q_head + 1;
                q_count = q_count - 1;
                acknowledged = acknowledged + 1;
            end
            if (req_valid && req_ready) begin
                if (req_addr[3:0] !== 4'd0 || req_addr > 32'd65520)
                    $fatal(1, "unaligned/out-of-range request %h", req_addr);
                if (q_count >= 4095) $fatal(1, "mock queue overflow");
                temp = 128'd0;
                for (b=0; b<16; b=b+1)
                    temp[b*8 +: 8] = mem[req_addr+b];
                response_q[q_tail] = temp;
                error_q[q_tail] = inject_error;
                if (req_write && !inject_error) begin
                    for (b=0; b<16; b=b+1)
                        if (req_wmask[b])
                            mem[req_addr+b] = req_wdata[b*8 +: 8];
                end
                if (req_addr >= 32'h1000 && req_addr < 32'h2000)
                    seen_ch0 = seen_ch0 + 1;
                if (req_addr >= 32'h2000 && req_addr < 32'h3000)
                    seen_ch1 = seen_ch1 + 1;
                q_tail = q_tail + 1;
                q_count = q_count + 1;
                accepted = accepted + 1;
            end
        end
    end

    task mmio_wr(input [15:0] a, input [31:0] d);
    begin
        @(negedge clk);
        select = 1'b1; write = 1'b1; write_mask = 4'hf;
        address = a; write_data = d;
        #1;
        if (mmio_error !== 1'b0)
            $fatal(1, "unexpected MMIO WRITE error @%h = %h", a, d);
        @(posedge clk);
        @(negedge clk);
        select = 1'b0;
    end
    endtask

    task mmio_rd(input [15:0] a, output [31:0] d);
    begin
        @(negedge clk);
        select = 1'b1; write = 1'b0; write_mask = 4'h0;
        address = a; write_data = 32'h0;
        #1;
        if (mmio_error !== 1'b0)
            $fatal(1, "unexpected MMIO READ error @%h", a);
        d = read_data;
        @(negedge clk);
        select = 1'b0;
    end
    endtask

    task wait_done(input [15:0] status_addr);
        reg [31:0] s;
        integer tries;
    begin
        s = 0; tries = 0;
        while ((s & 3) != 2 && tries < 2000) begin
            mmio_rd(status_addr, s);
            tries = tries + 1;
        end
        if (tries >= 2000)
            $fatal(1, "timeout waiting for DONE at %h, last STATUS=%h", status_addr, s);
        if (s[2]) $fatal(1, "DMA error at %h", status_addr);
    end
    endtask

    task verify_fill(input integer base, input integer n, input [7:0] value);
        integer z;
    begin
        for (z=0; z<n; z=z+1)
            if (mem[base+z] !== value)
                $fatal(1, "FILL mismatch @%h: got %h expected %h", base+z, mem[base+z], value);
    end
    endtask

    reg [31:0] tmp;
    initial begin
        for (i=0; i<65536; i=i+1) mem[i] = 8'hcc;
        for (i=0; i<256; i=i+1) mem[16'h3000+i] = i[7:0];
        repeat (5) @(negedge clk);
        reset = 1'b0;

        // 1. Register read: reads use write_mask=0, unlike writes.
        mmio_rd(16'h0204, tmp);
        if (tmp !== 32'd2) $fatal(1, "CAPS wrong: %h", tmp);

        // 2. CH0: 64-byte FILL, four 128-bit writes.
        mmio_wr(16'h0004, 32'h00001000);
        mmio_wr(16'h0008, 32'd64);
        mmio_wr(16'h000c, 32'd1);
        mmio_wr(16'h0014, 32'd64);
        mmio_wr(16'h0018, 32'h5A5A5A5A);
        mmio_wr(16'h001c, 32'd3); // START | FILL
        wait_done(16'h0020);
        verify_fill(16'h1000, 64, 8'h5a);
        if (accepted !== acknowledged)
            $fatal(1, "DONE before all acknowledgements");

        // 3. CH0: 2D FILL, two rows with a hole between rows.
        mmio_wr(16'h0004, 32'h00001100);
        mmio_wr(16'h0008, 32'd32);
        mmio_wr(16'h000c, 32'd2);
        mmio_wr(16'h0014, 32'd64);
        mmio_wr(16'h0018, 32'h11111111);
        mmio_wr(16'h001c, 32'd3);
        wait_done(16'h0020);
        verify_fill(16'h1100, 32, 8'h11);
        verify_fill(16'h1140, 32, 8'h11);
        verify_fill(16'h1120, 32, 8'hcc);

        // 4. CH0 COPY 64 B, CH1 FILL 64 B. Both must complete.
        mmio_wr(16'h0000, 32'h00003000);
        mmio_wr(16'h0004, 32'h00001200);
        mmio_wr(16'h0008, 32'd64);
        mmio_wr(16'h000c, 32'd1);
        mmio_wr(16'h0010, 32'd64);
        mmio_wr(16'h0014, 32'd64);
        mmio_wr(16'h0044, 32'h00002000);
        mmio_wr(16'h0048, 32'd64);
        mmio_wr(16'h004c, 32'd1);
        mmio_wr(16'h0054, 32'd64);
        mmio_wr(16'h0058, 32'h77777777);
        mmio_wr(16'h001c, 32'd1); // CH0 COPY
        mmio_wr(16'h005c, 32'd3); // CH1 FILL
        wait_done(16'h0020);
        wait_done(16'h0060);
        for (i=0; i<64; i=i+1)
            if (mem[16'h1200+i] !== i[7:0])
                $fatal(1, "COPY mismatch at byte %0d", i);
        verify_fill(16'h2000, 64, 8'h77);
        if (seen_ch0 == 0 || seen_ch1 == 0)
            $fatal(1, "both channels must issue requests");

        // 5. W1C status, maskable sticky IRQ.
        mmio_wr(16'h020c, 32'h3);
        mmio_rd(16'h0208, tmp);
        if (tmp !== 32'h3 || irq !== 1'b1)
            $fatal(1, "IRQ must be pending for both completed channels: %h", tmp);
        mmio_wr(16'h0208, 32'h3);
        mmio_rd(16'h0208, tmp);
        if (tmp !== 0 || irq !== 1'b0)
            $fatal(1, "IRQ W1C failed: %h", tmp);
        mmio_wr(16'h0020, 32'h6);
        mmio_wr(16'h0060, 32'h6);
        mmio_rd(16'h0020, tmp);
        if (tmp[2:1] !== 2'b00) $fatal(1, "W1C status failed");

        $display("PASS dma_engine_tb: %0d requests, %0d responses", accepted, acknowledged);
        $finish;
    end

    initial begin
        #200000;
        $fatal(1, "global watchdog timeout");
    end
endmodule
`default_nettype wire
