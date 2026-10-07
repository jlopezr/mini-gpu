`timescale 1ns/1ps
`default_nettype none

module memory_fabric_fifo_6_tb;
    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg reset;
    reg [5:0] req_empty, req_rd_valid, rsp_full;
    reg [177:0] req_data [0:5];
    wire [5:0] req_rd_en, rsp_wr_en;
    wire [128:0] rsp_data [0:5];
    wire sdram_req_valid, sdram_req_write, busy;
    wire [23:0] sdram_req_addr;
    wire [127:0] sdram_req_wdata;
    wire [15:0] sdram_req_wmask;
    reg sdram_req_ready, sdram_done;
    reg [127:0] sdram_rdata;
    reg sdram_pending;
    integer i, responses, max_cmd_count;
    integer response_port [0:15];

    memory_fabric_fifo_6 dut (
        .clk(clk), .reset(reset),
        .p0_req_empty(req_empty[0]), .p0_req_rd_en(req_rd_en[0]), .p0_req_rd_valid(req_rd_valid[0]), .p0_req_data(req_data[0]), .p0_rsp_full(rsp_full[0]), .p0_rsp_wr_en(rsp_wr_en[0]), .p0_rsp_data(rsp_data[0]),
        .p1_req_empty(req_empty[1]), .p1_req_rd_en(req_rd_en[1]), .p1_req_rd_valid(req_rd_valid[1]), .p1_req_data(req_data[1]), .p1_rsp_full(rsp_full[1]), .p1_rsp_wr_en(rsp_wr_en[1]), .p1_rsp_data(rsp_data[1]),
        .p2_req_empty(req_empty[2]), .p2_req_rd_en(req_rd_en[2]), .p2_req_rd_valid(req_rd_valid[2]), .p2_req_data(req_data[2]), .p2_rsp_full(rsp_full[2]), .p2_rsp_wr_en(rsp_wr_en[2]), .p2_rsp_data(rsp_data[2]),
        .p3_req_empty(req_empty[3]), .p3_req_rd_en(req_rd_en[3]), .p3_req_rd_valid(req_rd_valid[3]), .p3_req_data(req_data[3]), .p3_rsp_full(rsp_full[3]), .p3_rsp_wr_en(rsp_wr_en[3]), .p3_rsp_data(rsp_data[3]),
        .p4_req_empty(req_empty[4]), .p4_req_rd_en(req_rd_en[4]), .p4_req_rd_valid(req_rd_valid[4]), .p4_req_data(req_data[4]), .p4_rsp_full(rsp_full[4]), .p4_rsp_wr_en(rsp_wr_en[4]), .p4_rsp_data(rsp_data[4]),
        .p5_req_empty(req_empty[5]), .p5_req_rd_en(req_rd_en[5]), .p5_req_rd_valid(req_rd_valid[5]), .p5_req_data(req_data[5]), .p5_rsp_full(rsp_full[5]), .p5_rsp_wr_en(rsp_wr_en[5]), .p5_rsp_data(rsp_data[5]),
        .sdram_req_valid(sdram_req_valid), .sdram_req_ready(sdram_req_ready),
        .sdram_req_write(sdram_req_write), .sdram_req_addr(sdram_req_addr),
        .sdram_req_wdata(sdram_req_wdata), .sdram_req_wmask(sdram_req_wmask),
        .sdram_done(sdram_done), .sdram_rdata(sdram_rdata), .busy(busy)
    );

    always @(posedge clk) begin
        if (dut.cmd_count > max_cmd_count)
            max_cmd_count <= dut.cmd_count;
        req_rd_valid <= 6'd0;
        for (i = 0; i < 6; i = i + 1)
            if (req_rd_en[i]) begin
                req_empty[i] <= 1'b1;
                req_rd_valid[i] <= 1'b1;
            end

        sdram_done <= 1'b0;
        if (sdram_pending) begin
            sdram_done <= 1'b1;
            sdram_pending <= 1'b0;
        end
        if (sdram_req_valid && sdram_req_ready) begin
            sdram_pending <= 1'b1;
            sdram_rdata <= {96'd0, 7'd0, sdram_req_addr, 1'b0};
        end

        for (i = 0; i < 6; i = i + 1)
            if (rsp_wr_en[i]) begin
                response_port[responses] <= i;
                responses <= responses + 1;
            end
    end

    task enqueue;
        input integer port;
        input urgent;
        input [31:0] address;
        begin
            req_data[port] = {urgent, 1'b0, address, 128'd0, 16'd0};
            req_empty[port] = 1'b0;
        end
    endtask

    task wait_responses;
        input integer wanted;
        integer timeout;
        begin
            timeout = 0;
            while (responses < wanted && timeout < 500) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (responses < wanted) begin
                $display("FAIL: timeout waiting for responses");
                $finish(1);
            end
        end
    endtask

    initial begin
        reset = 1'b1;
        req_empty = 6'b111111;
        req_rd_valid = 6'd0;
        rsp_full = 6'd0;
        sdram_req_ready = 1'b1;
        sdram_done = 1'b0;
        sdram_pending = 1'b0;
        sdram_rdata = 128'd0;
        responses = 0;
        max_cmd_count = 0;
        for (i = 0; i < 6; i = i + 1)
            req_data[i] = 178'd0;
        repeat (3) @(posedge clk);
        reset = 1'b0;
        @(posedge clk);

        // All six ports must receive their own response in RR order.
        for (i = 0; i < 6; i = i + 1)
            enqueue(i, 1'b0, 32'h0000_1000 + i * 16);
        wait_responses(6);
        if (max_cmd_count < 2) begin
            $display("FAIL: command queue never held multiple requests");
            $finish(1);
        end
        for (i = 0; i < 6; i = i + 1)
            if (response_port[i] != i) begin
                $display("FAIL: response %0d routed to p%0d", i, response_port[i]);
                $finish(1);
            end

        // A blocked destination remains staged while the global response queue
        // absorbs a later completion.
        rsp_full[5] = 1'b1;
        enqueue(5, 1'b1, 32'h0000_2000);
        enqueue(0, 1'b0, 32'h0000_2010);
        repeat (30) @(posedge clk);
        if (responses != 6) begin
            $display("FAIL: response ignored destination backpressure");
            $finish(1);
        end
        if (dut.rsp_count == 0) begin
            $display("FAIL: response queue did not absorb later completion");
            $finish(1);
        end
        rsp_full[5] = 1'b0;
        wait_responses(8);
        if (response_port[6] != 5 || response_port[7] != 0) begin
            $display("FAIL: queued responses routed in wrong order");
            $finish(1);
        end

        $display("PASS: memory_fabric_fifo_6 command/response queues and routing");
        $finish;
    end
endmodule

`default_nettype wire
