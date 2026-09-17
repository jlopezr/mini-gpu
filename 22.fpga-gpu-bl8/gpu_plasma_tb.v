`default_nettype none
`timescale 1ns/1ps
// Corre examples/plasma.asm con el scanout encendido, comprueba que el
// framebuffer queda bien y mide cuanto cuesta un frame.
//
// TEST-LENTO: 463 s, cuatro frames completos de 320x240. Es la mitad del
// tiempo de la suite del prototipo, asi que `test` lo omite por defecto y hay
// que pedirlo con `test -p 22 --full`. No se encoge a proposito: de aqui salen
// los ciclos/frame y los fps que cita video-scanout.md, y es la unica
// cobertura de extremo a extremo sobre la carga real. La version barata, con
// 24 filas y el bufer de instrucciones al limite, es gpu_plasma4_tb (~50 s),
// que si entra en la pasada normal.
//
// Como en gpu_video_bench_tb, el dominio de pixel se deja fuera (lleva
// primitivas del ECP5) y `fill_start` lo genera aqui un temporizador con el
// mismo ritmo que video_scanout.
module gpu_plasma_tb;
    reg clk=0;
    always #20 clk=~clk;
    reg reset=1,gpu_reset=0,run_request=0,halt_request=0,step_request=0;
    wire halted,error,retired;
    wire [7:0] error_code;
    reg [31:0] host_address=0;
    reg [7:0] host_write_data=0;
    reg host_write_enable=0,host_read_enable=0;
    wire [7:0] host_read_data;
    wire host_ready,host_error;
    reg [4:0] debug_register=0;
    wire [31:0] debug_data,debug_pc;
    `include "sim/system_memory_bl8.vh"

    // vsync a 60 Hz. Antes estaba a cero, que con doble buffer cuelga el
    // programa: el intercambio ocurre EN el vsync, asi que sin vsync no llega
    // nunca y la GPU se queda esperando en el poll.
    reg [19:0] vsync_tick=0;
    reg vsync_pulse=0;
    always @(posedge clk) begin
        vsync_pulse<=1'b0;
        if(!reset) begin
            if(vsync_tick>=20'd416666) begin
                vsync_tick<=0; vsync_pulse<=1'b1;
            end else vsync_tick<=vsync_tick+1'b1;
        end
    end

    wire [1:0] video_mode;
    wire [23:0] video_fb_base;
    wire video_underflow_clear;
    wire p2_valid,p2_ready,p2_write,p2_urgent,p2_rsp_valid,p2_rsp_error;
    wire [31:0] p2_addr;
    wire [127:0] p2_wdata,p2_rsp_rdata;
    wire [15:0] p2_wmask;

    gpu_system_bl8 dut(.*,.instruction_retired(retired),
        .p2_req_valid(p2_valid),.p2_req_ready(p2_ready),.p2_req_write(p2_write),
        .p2_req_addr(p2_addr),.p2_req_wdata(p2_wdata),.p2_req_wmask(p2_wmask),
        .p2_urgent(p2_urgent),.p2_rsp_valid(p2_rsp_valid),.p2_rsp_ready(1'b1),
        .p2_rsp_rdata(p2_rsp_rdata),.p2_rsp_error(p2_rsp_error),
        .video_mode(video_mode),.video_fb_base(video_fb_base),
        .video_underflow_clear(video_underflow_clear),
        .video_underflow(1'b0),.video_frame_pulse(vsync_pulse));


    reg [15:0] line_tick=0;
    reg fill_start=0;
    reg [7:0] fill_line=0;
    wire burst_we,burst_done;
    wire [8:0] burst_addr;
    wire [15:0] burst_data;
    always @(posedge clk) begin
        fill_start<=1'b0;
        if(!reset) begin
            if(line_tick>=16'd1587) begin
                line_tick<=0; fill_start<=1'b1;
                fill_line<=(fill_line==8'd239) ? 8'd0 : fill_line+8'd1;
            end else line_tick<=line_tick+1'b1;
        end
    end
    wire scanout_on=(video_mode==2'd2);
    video_line_source_burst source_i(
        .clk(clk),.reset(reset),.fb_base(video_fb_base),
        .fill_start(fill_start && scanout_on),.fill_line(fill_line),
        .fill_we(burst_we),.fill_addr(burst_addr),.fill_data(burst_data),
        .fill_done(burst_done),
        .req_valid(p2_valid),.req_ready(p2_ready),.req_write(p2_write),
        .req_addr(p2_addr),.req_wdata(p2_wdata),.req_wmask(p2_wmask),
        .urgent(p2_urgent),
        .rsp_valid(p2_rsp_valid),.rsp_ready(),
        .rsp_rdata(p2_rsp_rdata),.rsp_error(p2_rsp_error));

    reg [31:0] program_words[0:255];
    reg [7:0] byte_result;
    reg [31:0] word_result;
    integer i,cycles,errors=0,frames;
    integer h0,m0;

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
    task read_word;
        input [31:0] addr;
        integer j;
        begin for(j=0;j<4;j=j+1) begin access(0,addr+j,0); word_result[j*8 +: 8]=byte_result; end end
    endtask

    // El color que deberia tener la palabra w en el frame t.
    function [31:0] expected_word(input integer w, input integer t);
        integer x2,y,x,rx,gy,texl,texr,pl,pr;
        begin
            x2=w%160; y=w/160; x=x2*2;
            rx=x2/16; gy=y/4;
            texl=((x+t)^y)%16;
            texr=((x+1+t)^y)%16;
            pl=((rx+texl)*2048)+(gy*32)+(texl*2);
            pr=((rx+texr)*2048)+(gy*32)+(texr*2);
            expected_word=(pr*65536)+pl;
        end
    endfunction

    initial begin
        for(i=0;i<256;i=i+1) program_words[i]=32'h0;
        $readmemh("examples/plasma.hex",program_words);
        repeat(4) @(negedge clk); reset=0;
        wait(halted); @(negedge clk);

        // El host NO prepara nada de video: plasma.asm pone FB_FRONT, FB_BACK y
        // VIDEO_CTRL en su prologo, y pide los intercambios el solo. Antes se
        // preparaban aqui, y esa era justo la trampa: el banco pasaba mientras
        // `run-board --program` fallaba en placa, porque tras el reset FB_BACK
        // vale CERO y el programa acababa pintando sobre su propio codigo.
        // Con la direccion viviendo solo en el kernel no hay dos sitios que
        // puedan discrepar -- y de hecho ya discrepaban: plasma_1frame.asm
        // documentaba 0x00200000 mientras gpu_profile_tb usaba 0x00140000.

        for(i=0;i<96;i=i+1) write_word(i*4,program_words[i]);   // holgura sobre las 75 del programa

        h0=dut.imem_hits; m0=dut.imem_misses;
        @(negedge clk); run_request=1;
        @(negedge clk); run_request=0;
        cycles=0;
        while(!halted && cycles<40000000) begin @(negedge clk); cycles=cycles+1; end
        if(!halted) $fatal(1,"no termino");
        if(error) $fatal(1,"error_code=%h pc=%h",error_code,debug_pc);

        frames=4;   // el MOVI R28 de plasma.asm
        $display("");
        $display("plasma: %0d ciclos para %0d frames = %0d ciclos/frame",
                 cycles, frames, cycles/frames);
        $display("plasma: %0d ms/frame a 25 MHz  ->  %0d fps",
                 (cycles/frames)/25000, 25000000/(cycles/frames));
        $display("bufer de instrucciones: %0d aciertos, %0d fallos (%0d%% de fallos)",
                 dut.imem_hits-h0, dut.imem_misses-m0,
                 ((dut.imem_misses-m0)*100)/((dut.imem_hits-h0)+(dut.imem_misses-m0)));
        $display("");

        // Con 4 frames y un intercambio por frame, el ultimo dibujado (t=3)
        // acaba en 0x00100000 y ademas es el que se esta mostrando.
        read_word(32'h80000010);
        if(word_result!==32'd4) begin
            $display("FAIL: SWAP_COUNT=%0d, esperaba 4",word_result);
            errors=errors+1;
        end else $display("OK: 4 intercambios completados");
        read_word(32'h80000000);
        if(word_result!==32'h0010_0000) begin
            $display("FAIL: FB_FRONT=%h, esperaba 00100000",word_result);
            errors=errors+1;
        end else $display("OK: el frente acabo en 0x00100000");

        // Comprobar unas cuantas palabras del framebuffer contra el modelo.
        for(i=0;i<4;i=i+1) begin
            read_word(32'h0010_0000 + (i*9973)*4);
            if(word_result!==expected_word(i*9973,frames-1)) begin
                $display("FAIL palabra %0d: %h, esperaba %h",
                         i*9973, word_result, expected_word(i*9973,frames-1));
                errors=errors+1;
            end
        end
        if(errors==0) $display("gpu_plasma_tb: el framebuffer es correcto");
        else $fatal(1,"gpu_plasma_tb: %0d FALLOS",errors);
        $finish;
    end
    initial begin #40000000000; $fatal(1,"timeout"); end
endmodule
`default_nettype wire
