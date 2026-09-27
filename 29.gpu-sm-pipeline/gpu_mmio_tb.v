`default_nettype none
`timescale 1ns/1ps
// Verifica que la GPU llega a la ventana MMIO por su cuenta: escribe
// VIDEO_CTRL, lo relee, y se cronometra leyendo los contadores.
//
// Antes esto era imposible por dos barreras (fault de la LSU por encima de
// 0x02000000, y `halted` exigido para escribir el MMIO). Que este banco pase es
// exactamente la diferencia.
module gpu_mmio_tb;
    reg clk=0;
    always #20 clk=~clk;
    reg reset=1,gpu_reset=0,run_request=0,halt_request=0,step_request=0;
    wire halted,error,retired;
    wire [7:0] error_code;
    reg [31:0] host_address=0;
    reg [7:0] host_write_data=0;
  // WRITE_WORD. La instanciacion es .*, asi que estas dos tienen que
  // existir con el nombre exacto del puerto o el banco no elabora.
  reg [31:0] host_write_word=0; reg host_write_word_enable=0;
    reg host_write_enable=0,host_read_enable=0;
    wire [7:0] host_read_data;
    wire [31:0] host_read_word;   // la misma lectura sin trocear
    wire host_ready,host_error;
    reg [4:0] debug_register=0;
    wire [31:0] debug_data,debug_pc;
    `include "sim/system_memory_bl8.vh"

    wire [1:0] video_mode;
    wire [23:0] video_fb_base;
    wire video_underflow_clear;
    wire p2_ready_u,p2_rsp_valid_u,p2_rsp_error_u;
    wire [127:0] p2_rsp_rdata_u;

    gpu_system_bl8 dut(.*,.instruction_retired(retired),
        .p2_req_valid(1'b0),.p2_req_ready(p2_ready_u),.p2_req_write(1'b0),
        .p2_req_addr(32'd0),.p2_req_wdata(128'd0),.p2_req_wmask(16'd0),
        .p2_urgent(1'b0),.p2_rsp_valid(p2_rsp_valid_u),.p2_rsp_ready(1'b1),
        .p2_rsp_rdata(p2_rsp_rdata_u),.p2_rsp_error(p2_rsp_error_u),
        .video_mode(video_mode),.video_fb_base(video_fb_base),
        .video_underflow_clear(video_underflow_clear),
        .video_underflow(1'b0),.video_frame_pulse(1'b0));

    reg [31:0] program_words[0:255];
    reg [7:0] byte_result;
    integer i,cycles,errors=0;

    task access;
        input wr;
        input [31:0] addr;
        input [7:0] data;
        begin
            @(negedge clk); host_address=addr; host_write_data=data;
            host_write_enable=wr; host_read_enable=!wr;
            @(negedge clk); host_write_enable=0; host_read_enable=0;
            cycles=0;
            while(!host_ready && cycles<100) begin @(negedge clk); cycles=cycles+1; end
            if(!host_ready || host_error) $fatal(1,"host access failed %h",addr);
            byte_result=host_read_data;
        end
    endtask
    task write_word;
        input [31:0] addr,data;
        integer j;
        begin for(j=0;j<4;j=j+1) access(1,addr+j,data[j*8 +: 8]); end
    endtask

    // Lee un registro de la lane 0 del warp 0 por el camino de depuracion.
    task read_reg;
        input [4:0] r;
        output [31:0] value;
        begin
            access(1,32'h82020000,8'd0);
            @(negedge clk); debug_register=r;
            repeat(3) @(negedge clk);
            value=debug_data;
        end
    endtask

    reg [31:0] r10,r11,r12;

    initial begin
        for(i=0;i<256;i=i+1) program_words[i]=32'h0;
        $readmemh("examples/mmio_selftest.hex",program_words);
        repeat(4) @(negedge clk); reset=0;
        wait(halted); @(negedge clk);

        // Arranca en PATTERN; el programa lo pondra en SCANOUT desde la GPU.
        if(video_mode!==2'd1) begin
            $display("FAIL: modo inicial %0d, esperaba 1",video_mode);
            errors=errors+1;
        end

        for(i=0;i<32;i=i+1) write_word(i*4,program_words[i]);
        @(negedge clk); run_request=1;
        @(negedge clk); run_request=0;
        cycles=0;
        while(!halted && cycles<2000000) begin @(negedge clk); cycles=cycles+1; end
        if(!halted) $fatal(1,"no termino");
        if(error) $fatal(1,"error_code=%h pc=%h",error_code,debug_pc);

        // 1. La escritura de la GPU llego al registro de video.
        if(video_mode!==2'd2) begin
            $display("FAIL: la GPU no cambio VIDEO_CTRL (modo=%0d)",video_mode);
            errors=errors+1;
        end else $display("OK: la GPU escribio VIDEO_CTRL");

        // 2. Y la lectura de vuelta le devolvio lo que escribio.
        read_reg(5'd10,r10);
        if(r10!==32'd2) begin
            $display("FAIL: la GPU leyo VIDEO_CTRL=%0d, esperaba 2",r10);
            errors=errors+1;
        end else $display("OK: la GPU releyo VIDEO_CTRL");

        // 3. Los contadores avanzan y son coherentes.
        read_reg(5'd11,r11);
        read_reg(5'd12,r12);
        $display("medido por la propia GPU: %0d ciclos, %0d instrucciones",r11,r12);
        if(r11===32'd0 || r11>32'd2000000) begin
            $display("FAIL: CYCLES no es creible (%0d)",r11);
            errors=errors+1;
        end else if(r12===32'd0 || r12>r11) begin
            $display("FAIL: RETIRED no es creible (%0d en %0d ciclos)",r12,r11);
            errors=errors+1;
        end else $display("OK: los contadores son coherentes (%0d ciclos/instr)",r11/r12);

        if(errors==0) $display("gpu_mmio_tb: TODAS LAS PRUEBAS PASAN");
        else $fatal(1,"gpu_mmio_tb: %0d FALLOS",errors);
        $finish;
    end
    initial begin #200000000; $fatal(1,"timeout"); end
endmodule
`default_nettype wire
