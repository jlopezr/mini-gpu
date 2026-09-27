`default_nettype none
`timescale 1ns/1ps
// Prueba y mide el camino de video REAL (video_line_source_burst sobre el
// puerto 2 del fabric), no el generador sintetico.
//
// Reproduce la parte de top_bl8 que toca memoria y deja fuera el dominio de
// pixel, que no se puede simular con iverilog porque lleva primitivas del ECP5
// (EHXPLLL, ODDRX1F). `fill_start` lo genera aqui un temporizador con el mismo
// ritmo que video_scanout: una linea fuente cada ~1588 ciclos a 25 MHz.
//
// Comprueba las dos cosas que justifican VIDEO_CTRL:
//   1. En PATTERN no sale NI UNA peticion al fabric.
//   2. En SCANOUT salen, y el programa tarda mas.
module gpu_video_bench_tb;
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
        .video_underflow(1'b0),.video_frame_pulse(1'b0));

    // Mismo temporizador de lineas que video_scanout, sin dominio de pixel.
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

    // Igual que en top_bl8: la fuente de SDRAM solo arranca en SCANOUT.
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

    integer video_tx=0;
    reg counting=0;
    reg [31:0] first_addr=32'hffff_ffff;
    reg [7:0] first_line;
    always @(posedge clk) if(!reset && counting && p2_valid && p2_ready) begin
        video_tx=video_tx+1;
        // Se guarda la primera peticion Y la linea que se estaba rellenando.
        // Comprobar la direccion es lo unico que verifica que la conversion
        // byte -> palabra de 16 bits es la correcta; sin esto, un factor 2 de
        // mas pasa desapercibido, que es justo lo que paso la primera vez.
        // No se puede exigir que sea FB_BASE a secas: el temporizador de
        // lineas corre libre, asi que al encender el scanout la linea en curso
        // es cualquiera.
        if(first_addr===32'hffff_ffff) begin
            first_addr=p2_addr;
            first_line=fill_line;
        end
    end

    reg [31:0] program_words[0:255];
    reg [7:0] byte_result;
    reg [31:0] word_result;
    integer i,cycles,run_cycles,errors=0;

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

    task run_program;
        output integer took;
        begin
            @(negedge clk); gpu_reset=1;
            @(negedge clk); gpu_reset=0;
            wait(halted); @(negedge clk);
            for(i=0;i<16;i=i+1) write_word(i*4,program_words[i]);
            @(negedge clk); run_request=1;
            @(negedge clk); run_request=0;
            cycles=0;
            while(!halted && cycles<20000000) begin @(negedge clk); cycles=cycles+1; end
            took=cycles;
            if(error) $fatal(1,"el programa fallo: code=%h",error_code);
        end
    endtask

    integer t_pattern, t_scanout, tx_pattern, tx_scanout;

    initial begin
        for(i=0;i<256;i=i+1) program_words[i]=32'h0;
        $readmemh("examples/bench.hex",program_words);
        repeat(4) @(negedge clk); reset=0;
        wait(halted);

        // ---- 1. Por defecto tiene que ser PATTERN, no SCANOUT ----
        if(video_mode!==2'd1) begin
            $display("FAIL: tras el reset video_mode=%0d, esperaba 1 (PATTERN)",video_mode);
            errors=errors+1;
        end else $display("OK: tras el reset el modo es PATTERN");

        // ---- 2. En PATTERN no puede salir ni una peticion al fabric ----
        counting=1; video_tx=0;
        run_program(t_pattern);
        tx_pattern=video_tx;
        if(tx_pattern!==0) begin
            $display("FAIL: en PATTERN salieron %0d peticiones de video",tx_pattern);
            errors=errors+1;
        end else $display("OK: en PATTERN, 0 peticiones de video");

        // ---- 3. Cambiar a SCANOUT por MMIO ----
        access(1,32'h80200000,8'd2);
        access(0,32'h80200000,8'd0);
        if(byte_result!==8'd2) begin
            $display("FAIL: VIDEO_CTRL leyo %0d, esperaba 2",byte_result);
            errors=errors+1;
        end else $display("OK: VIDEO_CTRL se escribe y se relee");
        write_word(32'h80200004,32'h0010_0000);   // FB_BASE

        video_tx=0;
        run_program(t_scanout);
        tx_scanout=video_tx;
        if(tx_scanout==0) begin
            $display("FAIL: en SCANOUT no salio ninguna peticion de video");
            errors=errors+1;
        end else $display("OK: en SCANOUT salieron %0d peticiones de video",tx_scanout);

        // La linea N empieza en FB_BASE + N*640 (320 pixeles x 2 bytes).
        if(first_addr!==(32'h0010_0000 + first_line*640)) begin
            $display("FAIL: linea %0d pedida en %h, esperaba %h",
                     first_line, first_addr, 32'h0010_0000+first_line*640);
            errors=errors+1;
        end else $display("OK: el video lee en FB_BASE + linea*640 (linea %0d -> %h)",
                          first_line, first_addr);

        // Y el registro se relee como se escribio.
        read_word(32'h80200004);
        if(word_result!==32'h0010_0000) begin
            $display("FAIL: FB_BASE leyo %h, esperaba 00100000",word_result);
            errors=errors+1;
        end else $display("OK: FB_BASE se relee bien");

        $display("");
        $display("bench en PATTERN : %0d ciclos", t_pattern);
        $display("bench en SCANOUT : %0d ciclos  (+%0d%%)",
                 t_scanout, ((t_scanout-t_pattern)*100)/t_pattern);
        $display("");
        if(errors==0) $display("gpu_video_bench_tb: TODAS LAS PRUEBAS PASAN");
        else $fatal(1,"gpu_video_bench_tb: %0d FALLOS",errors);
        $finish;
    end
    initial begin #10000000000; $fatal(1,"timeout"); end
endmodule
`default_nettype wire
