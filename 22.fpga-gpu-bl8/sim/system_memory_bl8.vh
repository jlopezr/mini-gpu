    // El modelo representa la PLACA, asi que su retardo de lectura tiene que
    // ser el real, no el que le venga bien al controlador. Se calcula con la
    // misma formula que sdram_controller_128 deriva de CLK_FREQ_HZ (25 MHz -> 0).
    localparam integer BOARD_READ_DELAY = (25_000_000/1_000_000)*18_000/1_000_000;
    wire init_done,mem_req_valid,mem_req_ready,mem_req_write,mem_done;
    wire [23:0] mem_req_addr;
    wire [127:0] mem_req_wdata,mem_rdata;
    wire [15:0] mem_req_wmask;
    wire sdram_clk,sdram_cke,sdram_csn,sdram_rasn,sdram_casn,sdram_wen;
    wire [12:0] sdram_a;
    wire [1:0] sdram_ba,sdram_dqm;
    wire [15:0] sdram_d;
    sdram_controller_128 #(.CLK_FREQ_HZ(25_000_000),.POWERUP_DELAY_US(0)) controller (
        .clk(clk),.reset(reset),.req_valid(mem_req_valid),.req_ready(mem_req_ready),
        .req_write(mem_req_write),.req_addr(mem_req_addr),.req_wdata(mem_req_wdata),
        .req_wmask(mem_req_wmask),.done(mem_done),.rdata(mem_rdata),
        .init_done(init_done),.busy(),.sdram_clk(sdram_clk),.sdram_cke(sdram_cke),
        .sdram_csn(sdram_csn),.sdram_rasn(sdram_rasn),.sdram_casn(sdram_casn),
        .sdram_wen(sdram_wen),.sdram_a(sdram_a),.sdram_ba(sdram_ba),
        .sdram_dqm(sdram_dqm),.sdram_d(sdram_d));
    // OJO: aqui va el modelo de 21 (sdram_model.v), no el de sim/sdram_model.vh.
    // El de 17 es funcional BL1 y NO implementa rafagas, asi que contra el
    // controlador BL8 devuelve basura -- que es exactamente como se manifesto
    // este fallo la primera vez: opcode invalido en la primera instruccion.
    sdram_model #(.ROWS(512),.POWERUP_DELAY_NS(0),.READ_DELAY_CYCLES(BOARD_READ_DELAY)) ram(.clk(sdram_clk),.cke(sdram_cke),.csn(sdram_csn),
        .rasn(sdram_rasn),.casn(sdram_casn),.wen(sdram_wen),
        .a(sdram_a),.ba(sdram_ba),.dqm(sdram_dqm),.dq(sdram_d));
