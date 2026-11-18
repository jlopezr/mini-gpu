`timescale 1ns/1ps
`default_nettype none

// Banco del fabric de seis puertos contra un controlador SDRAM SIMULADO que
// acepta varias peticiones a la vez y responde en orden tras `lat` ciclos.
// Es el contrato del controlador de la 35: una respuesta por peticion
// aceptada, en el orden en que se aceptaron.
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
    integer i, k, responses, max_outstanding, max_rsp_count, lat, now;
    integer response_port [0:63];
    reg [31:0] response_addr [0:63];
    reg response_error [0:63];

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

    // Controlador simulado: cola de peticiones aceptadas con su instante de
    // respuesta. Acepta mientras haya hueco (`sdram_req_ready`) y responde en
    // orden, como mucho una por ciclo.
    reg [23:0] mq_addr [0:63];
    integer mq_time [0:63];
    integer mq_head, mq_tail, accepted;

    always @(posedge clk) begin
        now <= now + 1;

        if (dut.outstanding > max_outstanding)
            max_outstanding <= dut.outstanding;
        if (dut.rsp_count > max_rsp_count)
            max_rsp_count <= dut.rsp_count;

        req_rd_valid <= 6'd0;
        for (i = 0; i < 6; i = i + 1)
            if (req_rd_en[i]) begin
                req_empty[i] <= 1'b1;
                req_rd_valid[i] <= 1'b1;
            end

        sdram_done <= 1'b0;
        if (mq_head != mq_tail && mq_time[mq_head % 64] <= now) begin
            sdram_done <= 1'b1;
            sdram_rdata <= {96'd0, 7'd0, mq_addr[mq_head % 64], 1'b0};
            mq_head <= mq_head + 1;
        end
        if (sdram_req_valid && sdram_req_ready) begin
            mq_addr[mq_tail % 64] <= sdram_req_addr;
            mq_time[mq_tail % 64] <= now + lat;
            mq_tail <= mq_tail + 1;
            accepted <= accepted + 1;
        end

        for (i = 0; i < 6; i = i + 1)
            if (rsp_wr_en[i]) begin
                response_port[responses] <= i;
                response_addr[responses] <= rsp_data[i][31:0];
                response_error[responses] <= rsp_data[i][128];
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
            while (responses < wanted && timeout < 2000) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (responses < wanted) begin
                $display("FAIL: timeout waiting for responses (%0d of %0d)",
                         responses, wanted);
                $display("  outstanding=%0d meta=%0d rsp=%0d cmd=%0d issue_valid=%b err=%b mq=%0d/%0d route=%b",
                         dut.outstanding, dut.meta_count, dut.rsp_count, dut.cmd_count,
                         dut.issue_valid, dut.issue_error, mq_head, mq_tail, dut.route_valid);
                $finish(1);
            end
        end
    endtask

    task expect_response;
        input integer index;
        input integer port;
        input [31:0] address;
        input error;
        begin
            if (response_port[index] != port ||
                response_error[index] !== error ||
                (!error && response_addr[index] !== address)) begin
                $display("FAIL: response %0d came from p%0d addr %08x err %b, want p%0d addr %08x err %b",
                         index, response_port[index], response_addr[index],
                         response_error[index], port, address, error);
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
        sdram_rdata = 128'd0;
        responses = 0;
        max_outstanding = 0;
        max_rsp_count = 0;
        lat = 12;
        now = 0;
        mq_head = 0;
        mq_tail = 0;
        accepted = 0;
        for (i = 0; i < 6; i = i + 1)
            req_data[i] = 178'd0;
        repeat (3) @(posedge clk);
        reset = 1'b0;
        @(posedge clk);

        // All six ports must receive their own response in RR order, with the
        // controller holding several requests at once.
        for (i = 0; i < 6; i = i + 1)
            enqueue(i, 1'b0, 32'h0000_1000 + i * 16);
        wait_responses(6);
        if (max_outstanding < 3) begin
            $display("FAIL: only %0d requests were ever in flight", max_outstanding);
            $finish(1);
        end
        for (i = 0; i < 6; i = i + 1)
            expect_response(i, i, 32'h0000_1000 + i * 16, 1'b0);

        // A blocked destination remains staged while the global response queue
        // absorbs a later completion.
        rsp_full[5] = 1'b1;
        enqueue(5, 1'b1, 32'h0000_2000);
        enqueue(0, 1'b0, 32'h0000_2010);
        repeat (60) @(posedge clk);
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
        expect_response(6, 5, 32'h0000_2000, 1'b0);
        expect_response(7, 0, 32'h0000_2010, 1'b0);

        // An invalid address never reaches the controller, yet its error
        // response must keep its place in the order.
        accepted = 0;
        enqueue(0, 1'b0, 32'h0000_3000);
        enqueue(1, 1'b0, 32'h0000_3010);
        enqueue(2, 1'b0, 32'h0300_0000);     // fuera de SDRAM
        enqueue(3, 1'b0, 32'h0000_3030);
        enqueue(4, 1'b0, 32'h0000_3041);     // desalineada
        enqueue(5, 1'b0, 32'h0000_3050);
        wait_responses(14);
        // Todas a la vez: el round-robin sigue donde lo dejo la prueba anterior
        // (p0 fue el ultimo servido), asi que arranca en p1.
        expect_response(8, 1, 32'h0000_3010, 1'b0);
        expect_response(9, 2, 32'h0, 1'b1);
        expect_response(10, 3, 32'h0000_3030, 1'b0);
        expect_response(11, 4, 32'h0, 1'b1);
        expect_response(12, 5, 32'h0000_3050, 1'b0);
        expect_response(13, 0, 32'h0000_3000, 1'b0);
        if (accepted != 4) begin
            $display("FAIL: controller saw %0d requests, expected 4", accepted);
            $finish(1);
        end

        // Credit limit: with a very slow controller and every destination
        // blocked, requests pile up until the credits run out, and nothing is
        // lost or overflows when the destinations are released.
        lat = 40;
        rsp_full = 6'b111111;
        for (k = 0; k < 6; k = k + 1) begin
            enqueue(k, 1'b0, 32'h0000_4000 + k * 16);
            repeat (4) @(posedge clk);
        end
        repeat (400) @(posedge clk);
        for (k = 0; k < 6; k = k + 1) begin
            enqueue(k, 1'b0, 32'h0000_5000 + k * 16);
            repeat (4) @(posedge clk);
        end
        repeat (400) @(posedge clk);
        if (max_rsp_count > 8) begin
            $display("FAIL: response queue reached %0d entries", max_rsp_count);
            $finish(1);
        end
        rsp_full = 6'd0;
        wait_responses(14 + 12);
        for (k = 0; k < 6; k = k + 1) begin
            expect_response(14 + k, k, 32'h0000_4000 + k * 16, 1'b0);
            expect_response(20 + k, k, 32'h0000_5000 + k * 16, 1'b0);
        end
        repeat (200) @(posedge clk);
        if (busy) begin
            $display("FAIL: fabric still busy after all responses");
            $finish(1);
        end
        if (dut.outstanding != 0) begin
            $display("FAIL: %0d requests still outstanding", dut.outstanding);
            $finish(1);
        end

        $display("PASS: memory_fabric_fifo_6 command/response queues and routing");
        $finish;
    end
endmodule

`default_nettype wire



