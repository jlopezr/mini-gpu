`default_nettype none
`timescale 1ns/1ps
// Comprueba el camino host -> gpu_aux_adapter_128 -> memory_fabric_4 ->
// sdram_controller_128 -> sdram_model: escribir palabras byte a byte y
// releerlas. Es el camino por el que el banco del sistema carga el programa,
// asi que si esto falla no arranca nada.
module gpu_aux_adapter_128_tb;
    reg clk=0, reset=1;
    always #5 clk=~clk;

    reg aux_valid=0;
    reg [31:0] aux_address=0, aux_write_data=0;
    reg [3:0] aux_strobe=0;
    reg aux_rsp_ready=1;
    wire aux_ready, aux_rsp_valid, aux_error;
    wire [31:0] aux_read_data;

    wire p_valid,p_ready,p_write,p_rsp_valid,p_rsp_ready,p_rsp_error;
    wire [31:0] p_addr;
    wire [127:0] p_wdata,p_rsp_rdata;
    wire [15:0] p_wmask;

    wire init_done,mem_req_valid,mem_req_ready,mem_req_write,mem_done;
    wire [23:0] mem_req_addr;
    wire [127:0] mem_req_wdata,mem_rdata;
    wire [15:0] mem_req_wmask;
    wire sdram_clk,sdram_cke,sdram_csn,sdram_rasn,sdram_casn,sdram_wen;
    wire [12:0] sdram_a;
    wire [1:0] sdram_ba,sdram_dqm;
    wire [15:0] sdram_d;

    gpu_aux_adapter_128 dut(
        .clk(clk),.reset(reset),.init_done(init_done),
        .aux_valid(aux_valid),.aux_ready(aux_ready),.aux_address(aux_address),
        .aux_write_data(aux_write_data),.aux_strobe(aux_strobe),
        .aux_rsp_valid(aux_rsp_valid),.aux_rsp_ready(aux_rsp_ready),
        .aux_read_data(aux_read_data),.aux_error(aux_error),
        .req_valid(p_valid),.req_ready(p_ready),.req_write(p_write),
        .req_addr(p_addr),.req_wdata(p_wdata),.req_wmask(p_wmask),
        .rsp_valid(p_rsp_valid),.rsp_ready(p_rsp_ready),
        .rsp_rdata(p_rsp_rdata),.rsp_error(p_rsp_error));

    memory_fabric_4 fabric(
        .clk(clk),.reset(reset),
        .p0_req_valid(1'b0),.p0_req_write(1'b0),.p0_req_addr(32'd0),
        .p0_req_wdata(128'd0),.p0_req_wmask(16'd0),.p0_rsp_ready(1'b1),.p0_req_ready(),.p0_rsp_valid(),.p0_rsp_rdata(),.p0_rsp_error(),
        .p1_req_valid(p_valid),.p1_req_ready(p_ready),.p1_req_write(p_write),
        .p1_req_addr(p_addr),.p1_req_wdata(p_wdata),.p1_req_wmask(p_wmask),
        .p1_rsp_valid(p_rsp_valid),.p1_rsp_ready(p_rsp_ready),
        .p1_rsp_rdata(p_rsp_rdata),.p1_rsp_error(p_rsp_error),
        .p2_req_valid(1'b0),.p2_req_write(1'b0),.p2_req_addr(32'd0),
        .p2_req_wdata(128'd0),.p2_req_wmask(16'd0),.p2_urgent(1'b0),.p2_rsp_ready(1'b1),.p2_req_ready(),.p2_rsp_valid(),.p2_rsp_rdata(),.p2_rsp_error(),
        .p3_req_valid(1'b0),.p3_req_write(1'b0),.p3_req_addr(32'd0),
        .p3_req_wdata(128'd0),.p3_req_wmask(16'd0),.p3_rsp_ready(1'b1),.p3_req_ready(),.p3_rsp_valid(),.p3_rsp_rdata(),.p3_rsp_error(),
        .sdram_req_valid(mem_req_valid),.sdram_req_ready(mem_req_ready),
        .sdram_req_write(mem_req_write),.sdram_req_addr(mem_req_addr),
        .sdram_req_wdata(mem_req_wdata),.sdram_req_wmask(mem_req_wmask),
        .busy(),.sdram_done(mem_done),.sdram_rdata(mem_rdata));

    sdram_controller_128 #(.CLK_FREQ_HZ(25_000_000),.POWERUP_DELAY_US(0)) controller(
        .clk(clk),.reset(reset),.req_valid(mem_req_valid),.req_ready(mem_req_ready),
        .req_write(mem_req_write),.req_addr(mem_req_addr),.req_wdata(mem_req_wdata),
        .req_wmask(mem_req_wmask),.done(mem_done),.rdata(mem_rdata),
        .init_done(init_done),.busy(),.sdram_clk(sdram_clk),.sdram_cke(sdram_cke),
        .sdram_csn(sdram_csn),.sdram_rasn(sdram_rasn),.sdram_casn(sdram_casn),
        .sdram_wen(sdram_wen),.sdram_a(sdram_a),.sdram_ba(sdram_ba),
        .sdram_dqm(sdram_dqm),.sdram_d(sdram_d));

    // MISMA formula que sdram_controller_128.v: el modelo representa la PLACA,
    // asi que el retardo de ida y vuelta se deriva del reloj, no se fija a mano.
    // Fijarlo a 1 (heredado de 21, que corre a 80 MHz) contra un controlador que
    // a 25 MHz deriva 0 descuadra la rafaga un beat, y la lectura vuelve
    // desplazada una palabra de 16 bits. Ver README, "READ_DELAY_CYCLES".
    localparam integer BOARD_READ_DELAY = (25_000_000/1_000_000)*18_000/1_000_000;
    sdram_model #(.ROWS(512),.POWERUP_DELAY_NS(0),.READ_DELAY_CYCLES(BOARD_READ_DELAY)) ram(.clk(sdram_clk),.cke(sdram_cke),.csn(sdram_csn),
        .rasn(sdram_rasn),.casn(sdram_casn),.wen(sdram_wen),
        .a(sdram_a),.ba(sdram_ba),.dqm(sdram_dqm),.dq(sdram_d));

    integer errors=0, j;
    reg [31:0] got;

    task access;
        input [31:0] addr;
        input [31:0] wdata;
        input [3:0] strobe;
        begin
            @(negedge clk);
            aux_address=addr; aux_write_data=wdata; aux_strobe=strobe; aux_valid=1;
            while(!aux_ready) @(negedge clk);
            @(negedge clk); aux_valid=0;
            while(!aux_rsp_valid) @(negedge clk);
            got=aux_read_data;
            if(aux_error) begin
                $display("FAIL error en %h", addr); errors=errors+1;
            end
            @(negedge clk);
        end
    endtask

    // Escribe una palabra de 32 bits como cuatro accesos de un byte, igual que
    // hace el monitor en el banco del sistema. OJO: gpu_system.v manda siempre
    // la direccion ALINEADA ({address[31:2],2'b0}) y distingue el byte con
    // aux_strobe; una direccion sin alinear es fault por contrato.
    task write_word;
        input [31:0] addr;
        input [31:0] data;
        integer b;
        begin
            for(b=0;b<4;b=b+1)
                access(addr, {4{data[b*8 +: 8]}}, 4'b0001<<b);
        end
    endtask

    // Sin $dumpfile/$dumpvars a proposito: apio los rechaza porque el VCD lo
    // genera el -- `apio sim` lo vuelca solo. Ponerlos aqui dejaba el
    // prototipo entero sin `lint`, y ningun otro banco del repo los lleva.
    initial begin
        repeat(4) @(posedge clk);
        reset=0;
        while(!init_done) @(posedge clk);

        // Cuatro palabras dentro de la MISMA linea de 16 bytes: es el caso que
        // rompe si la mascara o el slot estan mal, porque cada escritura toca
        // una palabra distinta de la linea sin pisar las otras.
        for(j=0;j<4;j=j+1) write_word(32'h0000_0000 + j*4, 32'hA0B0_C000 + j);
        for(j=0;j<4;j=j+1) begin
            access(32'h0000_0000 + j*4, 32'd0, 4'b0000);
            if(got !== 32'hA0B0_C000 + j) begin
                $display("FAIL lectura %0d: got %h expected %h", j, got, 32'hA0B0_C000+j);
                errors=errors+1;
            end
        end

        // Y una palabra en otra linea, para descartar que el slot se quede pegado.
        write_word(32'h0000_1234 & ~32'd3, 32'hDEAD_BEEF);
        access(32'h0000_1234 & ~32'd3, 32'd0, 4'b0000);
        if(got !== 32'hDEAD_BEEF) begin
            $display("FAIL otra linea: got %h", got); errors=errors+1;
        end

        if(errors==0) $display("gpu_aux_adapter_128_tb: TODAS LAS PRUEBAS PASAN");
        else $fatal(1,"gpu_aux_adapter_128_tb: %0d FALLOS", errors);
        $finish;
    end

    initial begin
        #2000000; $fatal(1,"FAIL: timeout");
    end
endmodule
`default_nettype wire
