`default_nettype none
`timescale 1ns/1ps
// Mide el PICO del canal de memoria: un solo cliente pidiendo lineas de 16
// bytes sin parar, sin GPU compitiendo. Es el techo contra el que hay que
// comparar cualquier cliente nuevo -- por ejemplo un scanout de video, que
// consume ancho de banda constante y con plazo fijo.
//
// No mide lo que la GPU consigue (eso es gpu_bench_tb), mide lo que hay.
module sdram_bandwidth_tb;
    reg clk=0, reset=1;
    always #20 clk=~clk;   // 25 MHz, el reloj real de top_bl8

    reg p_valid=0;
    reg [31:0] p_addr=0;
    wire p_ready,p_rsp_valid,p_rsp_error;
    wire [127:0] p_rsp_rdata;

    wire init_done,mem_req_valid,mem_req_ready,mem_req_write,mem_done;
    wire [23:0] mem_req_addr;
    wire [127:0] mem_req_wdata,mem_rdata;
    wire [15:0] mem_req_wmask;
    wire sdram_clk,sdram_cke,sdram_csn,sdram_rasn,sdram_casn,sdram_wen;
    wire [12:0] sdram_a;
    wire [1:0] sdram_ba,sdram_dqm;
    wire [15:0] sdram_d;

    memory_fabric_4 fabric(
        .clk(clk),.reset(reset),
        .p0_req_valid(p_valid),.p0_req_ready(p_ready),.p0_req_write(1'b0),
        .p0_req_addr(p_addr),.p0_req_wdata(128'd0),.p0_req_wmask(16'd0),
        .p0_rsp_valid(p_rsp_valid),.p0_rsp_ready(1'b1),
        .p0_rsp_rdata(p_rsp_rdata),.p0_rsp_error(p_rsp_error),
        .p1_req_valid(1'b0),.p1_req_write(1'b0),.p1_req_addr(32'd0),
        .p1_req_wdata(128'd0),.p1_req_wmask(16'd0),.p1_rsp_ready(1'b1),.p1_req_ready(),.p1_rsp_valid(),.p1_rsp_rdata(),.p1_rsp_error(),
        .p2_req_valid(1'b0),.p2_req_write(1'b0),.p2_req_addr(32'd0),
        .p2_req_wdata(128'd0),.p2_req_wmask(16'd0),.p2_urgent(1'b0),.p2_rsp_ready(1'b1),.p2_req_ready(),.p2_rsp_valid(),.p2_rsp_rdata(),.p2_rsp_error(),
        .p3_req_valid(1'b0),.p3_req_write(1'b0),.p3_req_addr(32'd0),
        .p3_req_wdata(128'd0),.p3_req_wmask(16'd0),.p3_rsp_ready(1'b1),.p3_req_ready(),.p3_rsp_valid(),.p3_rsp_rdata(),.p3_rsp_error(),
        .sdram_req_valid(mem_req_valid),.sdram_req_ready(mem_req_ready),
        .sdram_req_write(mem_req_write),.sdram_req_addr(mem_req_addr),
        .sdram_req_wdata(mem_req_wdata),.sdram_req_wmask(mem_req_wmask),
        .busy(),.sdram_done(mem_done),.sdram_rdata(mem_rdata));

    localparam integer BOARD_READ_DELAY = (25_000_000/1_000_000)*18_000/1_000_000;
    sdram_controller_128 #(.CLK_FREQ_HZ(25_000_000),.POWERUP_DELAY_US(0)) controller(
        .clk(clk),.reset(reset),.req_valid(mem_req_valid),.req_ready(mem_req_ready),
        .req_write(mem_req_write),.req_addr(mem_req_addr),.req_wdata(mem_req_wdata),
        .req_wmask(mem_req_wmask),.done(mem_done),.rdata(mem_rdata),
        .init_done(init_done),.busy(),.sdram_clk(sdram_clk),.sdram_cke(sdram_cke),
        .sdram_csn(sdram_csn),.sdram_rasn(sdram_rasn),.sdram_casn(sdram_casn),
        .sdram_wen(sdram_wen),.sdram_a(sdram_a),.sdram_ba(sdram_ba),
        .sdram_dqm(sdram_dqm),.sdram_d(sdram_d));

    sdram_model #(.ROWS(512),.POWERUP_DELAY_NS(0),.READ_DELAY_CYCLES(BOARD_READ_DELAY))
        ram(.clk(sdram_clk),.cke(sdram_cke),.csn(sdram_csn),
            .rasn(sdram_rasn),.casn(sdram_casn),.wen(sdram_wen),
            .a(sdram_a),.ba(sdram_ba),.dqm(sdram_dqm),.dq(sdram_d));

    integer done_count=0, cyc=0;
    reg counting=0;
    always @(posedge clk) if(!reset && counting) begin
        cyc=cyc+1;
        if(p_rsp_valid) done_count=done_count+1;
    end

    localparam integer N = 2000;
    integer bytes_per_s;

    initial begin
        repeat(4) @(posedge clk); reset=0;
        while(!init_done) @(posedge clk);
        @(negedge clk); counting=1; p_valid=1;
        // Lectura secuencial de lineas contiguas, que es el patron de un
        // scanout de video leyendo el framebuffer.
        while(done_count<N) begin
            @(posedge clk);
            if(p_valid && p_ready) begin
                @(negedge clk); p_addr=p_addr+32'd16;
            end
        end
        counting=0; p_valid=0;
        $display("PICO: %0d transacciones en %0d ciclos = %0d ciclos/tx",
                 done_count, cyc, cyc/done_count);
        // 16 bytes por transaccion, 25 MHz.
        bytes_per_s = (16 * 25000000) / (cyc/done_count);
        $display("PICO: %0d KB/s  (%0d MB/s)", bytes_per_s/1000, bytes_per_s/1000000);
        $display("Video 320x240 RGB565 a 60 Hz necesita 9216 KB/s");
        $finish;
    end
    initial begin #500000000; $fatal(1,"timeout"); end
endmodule
`default_nettype wire
