`default_nettype none

module top (
    input  wire        clk_25mhz,
    input  wire        btn_pwr_n,
    output wire [7:0]  led,
    output wire        sdram_clk,
    output wire        sdram_cke,
    output wire        sdram_csn,
    output wire        sdram_rasn,
    output wire        sdram_casn,
    output wire        sdram_wen,
    output wire [12:0] sdram_a,
    output wire [1:0]  sdram_ba,
    output wire [1:0]  sdram_dqm,
    inout  wire [15:0] sdram_d
);
    reg [7:0] reset_count = 8'hff;
    always @(posedge clk_25mhz) begin
        if (!btn_pwr_n)
            reset_count <= 8'hff;
        else if (reset_count != 0)
            reset_count <= reset_count - 1'b1;
    end
    wire reset = (reset_count != 0);

    wire        req_valid;
    wire        req_write;
    wire [23:0] req_addr;
    wire [15:0] req_wdata;
    wire        req_ready;
    wire        done;
    wire [15:0] rdata;
    wire        init_done;
    wire        testing_write;
    wire        testing_read;
    wire        pass;
    wire        fail;
    wire [2:0]  progress;

    sdram_controller controller (
        .clk(clk_25mhz), .reset(reset),
        .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr),
        .req_wdata(req_wdata), .req_ready(req_ready), .done(done),
        .rdata(rdata), .init_done(init_done),
        .sdram_clk(sdram_clk), .sdram_cke(sdram_cke), .sdram_csn(sdram_csn),
        .sdram_rasn(sdram_rasn), .sdram_casn(sdram_casn), .sdram_wen(sdram_wen),
        .sdram_a(sdram_a), .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm),
        .sdram_d(sdram_d)
    );

    // change to 16 to test only 128 KiB
    memory_test #(.TEST_ADDR_BITS(24)) tester (
        .clk(clk_25mhz), .reset(reset), .init_done(init_done),
        .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr),
        .req_wdata(req_wdata), .req_ready(req_ready), .done(done), .rdata(rdata),
        .testing_write(testing_write), .testing_read(testing_read),
        .pass(pass), .fail(fail), .progress(progress)
    );

    assign led[0]   = init_done;
    assign led[1]   = testing_write;
    assign led[2]   = testing_read;
    assign led[3]   = pass;
    assign led[4]   = fail;
    assign led[7:5] = progress;
endmodule

`default_nettype wire
