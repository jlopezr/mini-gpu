`timescale 1ns/1ps
`default_nettype none

module memory_fabric_fifo_4_tb;

    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg reset;

    reg         req_empty [0:3];
    wire        req_rd_en [0:3];
    reg         req_rd_valid [0:3];
    reg [177:0] req_data [0:3];

    reg         rsp_full [0:3];
    wire        rsp_wr_en [0:3];
    wire [128:0] rsp_data [0:3];

    wire         sdram_req_valid;
    reg          sdram_req_ready;
    wire         sdram_req_write;
    wire [23:0]  sdram_req_addr;
    wire [127:0] sdram_req_wdata;
    wire [15:0]  sdram_req_wmask;
    reg          sdram_done;
    reg [127:0]  sdram_rdata;
    wire         busy;

    integer request_count;
    integer response_count;
    reg [31:0] accepted_addr [0:31];
    reg         accepted_write [0:31];
    reg [127:0] accepted_wdata [0:31];
    reg [15:0] accepted_wmask [0:31];
    integer response_port [0:31];
    reg response_error [0:31];

    reg sdram_pending;
    integer index;

    memory_fabric_fifo_4 dut (
        .clk(clk),
        .reset(reset),

        .p0_req_empty(req_empty[0]),
        .p0_req_rd_en(req_rd_en[0]),
        .p0_req_rd_valid(req_rd_valid[0]),
        .p0_req_data(req_data[0]),
        .p0_rsp_full(rsp_full[0]),
        .p0_rsp_wr_en(rsp_wr_en[0]),
        .p0_rsp_data(rsp_data[0]),

        .p1_req_empty(req_empty[1]),
        .p1_req_rd_en(req_rd_en[1]),
        .p1_req_rd_valid(req_rd_valid[1]),
        .p1_req_data(req_data[1]),
        .p1_rsp_full(rsp_full[1]),
        .p1_rsp_wr_en(rsp_wr_en[1]),
        .p1_rsp_data(rsp_data[1]),

        .p2_req_empty(req_empty[2]),
        .p2_req_rd_en(req_rd_en[2]),
        .p2_req_rd_valid(req_rd_valid[2]),
        .p2_req_data(req_data[2]),
        .p2_rsp_full(rsp_full[2]),
        .p2_rsp_wr_en(rsp_wr_en[2]),
        .p2_rsp_data(rsp_data[2]),

        .p3_req_empty(req_empty[3]),
        .p3_req_rd_en(req_rd_en[3]),
        .p3_req_rd_valid(req_rd_valid[3]),
        .p3_req_data(req_data[3]),
        .p3_rsp_full(rsp_full[3]),
        .p3_rsp_wr_en(rsp_wr_en[3]),
        .p3_rsp_data(rsp_data[3]),

        .sdram_req_valid(sdram_req_valid),
        .sdram_req_ready(sdram_req_ready),
        .sdram_req_write(sdram_req_write),
        .sdram_req_addr(sdram_req_addr),
        .sdram_req_wdata(sdram_req_wdata),
        .sdram_req_wmask(sdram_req_wmask),
        .sdram_done(sdram_done),
        .sdram_rdata(sdram_rdata),
        .busy(busy)
    );

    // FIFO source model: rd_valid arrives one cycle after rd_en.
    always @(posedge clk) begin
        for (index = 0; index < 4; index = index + 1) begin
            req_rd_valid[index] <= 1'b0;
            if (req_rd_en[index]) begin
                req_empty[index] <= 1'b1;
                req_rd_valid[index] <= 1'b1;
            end
        end
    end

    // One-cycle SDRAM completion model and request log.
    always @(posedge clk) begin
        sdram_done <= 1'b0;
        if (sdram_pending) begin
            sdram_done <= 1'b1;
            sdram_pending <= 1'b0;
        end

        if (sdram_req_valid && sdram_req_ready) begin
            accepted_addr[request_count] <= {7'd0, sdram_req_addr, 1'b0};
            accepted_write[request_count] <= sdram_req_write;
            accepted_wdata[request_count] <= sdram_req_wdata;
            accepted_wmask[request_count] <= sdram_req_wmask;
            request_count <= request_count + 1;
            sdram_pending <= 1'b1;
            sdram_rdata <= {104'd0, sdram_req_addr};
        end

        for (index = 0; index < 4; index = index + 1) begin
            if (rsp_wr_en[index]) begin
                response_port[response_count] <= index;
                response_error[response_count] <= rsp_data[index][128];
                response_count <= response_count + 1;
            end
        end
    end

    task fail;
        input [8*96-1:0] message;
        begin
            $display("FAIL: %0s", message);
            $finish(1);
        end
    endtask

    task check;
        input condition;
        input [8*96-1:0] message;
        begin
            if (!condition)
                fail(message);
        end
    endtask

    task reset_dut;
        integer port;
        begin
            reset = 1'b1;
            sdram_req_ready = 1'b1;
            sdram_done = 1'b0;
            sdram_rdata = 128'd0;
            sdram_pending = 1'b0;
            request_count = 0;
            response_count = 0;
            for (port = 0; port < 4; port = port + 1) begin
                req_empty[port] = 1'b1;
                req_rd_valid[port] = 1'b0;
                req_data[port] = 178'd0;
                rsp_full[port] = 1'b0;
            end
            repeat (3) @(posedge clk);
            reset = 1'b0;
            @(posedge clk);
        end
    endtask

    task enqueue;
        input integer port;
        input urgent;
        input write_request;
        input [31:0] address;
        input [127:0] write_data;
        input [15:0] write_mask;
        begin
            if (!req_empty[port])
                fail("test FIFO already contains a request");
            req_data[port] = {
                urgent,
                write_request,
                address,
                write_data,
                write_mask
            };
            req_empty[port] = 1'b0;
        end
    endtask

    task wait_requests;
        input integer wanted;
        integer timeout;
        begin
            timeout = 0;
            while (request_count < wanted && timeout < 200) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (request_count < wanted)
                fail("timeout waiting for SDRAM requests");
        end
    endtask

    task wait_responses;
        input integer wanted;
        integer timeout;
        begin
            timeout = 0;
            while (response_count < wanted && timeout < 300) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (response_count < wanted)
                fail("timeout waiting for fabric responses");
        end
    endtask

    initial begin
        // An urgent request wins even when normal requests precede it in RR.
        reset_dut;
        enqueue(0, 1'b0, 1'b0, 32'h0000_1000, 128'd0, 16'h0000);
        enqueue(1, 1'b0, 1'b0, 32'h0000_1010, 128'd0, 16'h0000);
        enqueue(2, 1'b1, 1'b1, 32'h0000_1020,
                128'h00112233445566778899aabbccddeeff, 16'h5aa5);
        enqueue(3, 1'b0, 1'b0, 32'h0000_1030, 128'd0, 16'h0000);
        wait_requests(1);
        #1;
        check(accepted_addr[0] == 32'h0000_1020,
               "urgent port 2 did not win over normal requests");
        check(accepted_write[0] == 1'b1, "ST_CHECK lost write flag");
        check(accepted_wdata[0] == 128'h00112233445566778899aabbccddeeff,
               "ST_CHECK lost write data");
        check(accepted_wmask[0] == 16'h5aa5, "ST_CHECK lost write mask");
        wait_responses(1);
        #1;
        check(response_port[0] == 2, "response returned to wrong port");
        check(response_error[0] == 1'b0, "valid request returned an error");

        // With no urgent requests, arbitration follows RR from port 0.
        reset_dut;
        enqueue(1, 1'b0, 1'b0, 32'h0000_2010, 128'd0, 16'd0);
        enqueue(2, 1'b0, 1'b0, 32'h0000_2020, 128'd0, 16'd0);
        enqueue(3, 1'b0, 1'b0, 32'h0000_2030, 128'd0, 16'd0);
        wait_requests(3);
        #1;
        check(accepted_addr[0] == 32'h0000_2010, "normal RR first choice is wrong");
        check(accepted_addr[1] == 32'h0000_2020, "normal RR second choice is wrong");
        check(accepted_addr[2] == 32'h0000_2030, "normal RR third choice is wrong");

        // RR also orders urgent requests. First move rr_next to port 2.
        reset_dut;
        enqueue(1, 1'b0, 1'b0, 32'h0000_3010, 128'd0, 16'd0);
        wait_responses(1);
        enqueue(1, 1'b1, 1'b0, 32'h0000_3110, 128'd0, 16'd0);
        enqueue(3, 1'b1, 1'b0, 32'h0000_3130, 128'd0, 16'd0);
        wait_requests(3);
        #1;
        check(accepted_addr[1] == 32'h0000_3130,
               "urgent RR did not start from rr_next");
        check(accepted_addr[2] == 32'h0000_3110,
               "urgent RR did not wrap to the remaining request");

        // Misaligned and out-of-range requests fail locally, without SDRAM.
        reset_dut;
        enqueue(0, 1'b0, 1'b0, 32'h0000_1004, 128'd0, 16'd0);
        wait_responses(1);
        #1;
        check(request_count == 0, "misaligned request reached SDRAM");
        check(response_port[0] == 0, "misaligned response used wrong port");
        check(response_error[0] == 1'b1, "misaligned request was not rejected");

        enqueue(1, 1'b0, 1'b0, 32'h0200_0000, 128'd0, 16'd0);
        wait_responses(2);
        #1;
        check(request_count == 0, "out-of-range request reached SDRAM");
        check(response_port[1] == 1, "range-error response used wrong port");
        check(response_error[1] == 1'b1, "out-of-range request was not rejected");

        $display("PASS: memory_fabric_fifo_4 urgent/RR/check/response tests");
        $finish(0);
    end

endmodule

`default_nettype wire
