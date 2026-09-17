`default_nettype none
`timescale 1ns/1ps
// Cambia VIDEO_CTRL A MITAD DE UN LLENADO DE LINEA y comprueba que el video
// sigue vivo despues.
//
// Por que existe
// --------------
// En placa el subsistema de video se quedo ENCALLADO: con VIDEO_CTRL=2 y
// FB_FRONT correcto no salia ni una peticion al fabric, el contador de frames
// seguia avanzando y no habia underflow. `monitor.py reset` no lo recuperaba;
// solo reprogramar la FPGA.
//
// La sospecha esta en top_bl8.v:144-162. Las DOS fuentes de linea comparten
// contrato, y tanto su arranque como su terminacion van puerteados por el modo:
//
//     .fill_start(fill_start && scanout_on)     <- fuente SDRAM
//     .fill_start(fill_start && !scanout_on)    <- fuente patron
//     assign fill_done = scanout_on ? burst_done : pat_done;
//
// `video_mode` vive en el dominio de sistema y cambia cuando le da la gana al
// software, sin relacion con el llenado en curso. Si cambia con una linea a
// medias, la fuente que estaba trabajando deja de estar seleccionada y su
// `fill_done` ya no pasa el mux; la otra nunca vio su `fill_start`, asi que no
// tiene nada que terminar. Nadie da el `fill_done` que el scanout espera.
//
// Eso importa mas desde que los kernels se configuran el video ellos mismos:
// el salto PATTERN -> SCANOUT lo hace ahora la GPU en marcha, en un instante
// arbitrario, en CADA arranque de programa.
//
// Como se comprueba
// -----------------
// gpu_video_bench_tb instancia solo la fuente de SDRAM y no tiene mux, asi que
// no puede ver esto. Aqui se replica la estructura de top_bl8 con las dos
// fuentes y el mux, y se modela el consumidor como lo que es: video_scanout
// pide UNA linea y espera su `fill_done` antes de pedir la siguiente. Con ese
// modelo el encallamiento se ve solo -- si se pierde un `fill_done`, no vuelve
// a salir ningun `fill_start` y las lineas dejan de fluir.
module gpu_video_mode_switch_tb;
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

    // ---------------------------------------------------------------------
    // Modelo del consumidor: una linea en vuelo, como video_scanout.
    //
    // A diferencia de gpu_video_bench_tb, aqui `fill_start` NO corre libre.
    // Sale cuando toca por tiempo Y no hay ninguna linea a medias. Asi, perder
    // un `fill_done` deja `fill_busy` clavado a 1 para siempre y el
    // encallamiento se manifiesta como ausencia de lineas, que es justo lo que
    // pasa en la placa.
    // ---------------------------------------------------------------------
    reg [15:0] line_tick=0;
    reg fill_start=0;
    reg fill_busy=0;
    reg [7:0] fill_line=0;
    integer lines_done=0;

    wire burst_we,burst_done,pat_we,pat_done;
    wire [8:0] burst_addr,pat_addr;
    wire [15:0] burst_data,pat_data;

    // Reset local de las fuentes, del mux y del consumidor. Modela lo unico que
    // saca a la placa del encallamiento: reprogramar la FPGA. Sin esto, el
    // primer caso que encalla deja muertos a todos los siguientes y no se puede
    // probar la otra direccion del cambio de modo.
    reg src_reset_pulse=0;
    wire src_reset = reset | src_reset_pulse;

    // El mux REAL, el mismo modulo que instancia top_bl8. Antes esto era una
    // copia de sus `assign` dentro del banco, y eso lo hacia inutil como
    // regresion: probaba su propia copia, asi que un arreglo en top_bl8 no lo
    // habria hecho pasar nunca.
    wire fill_we,fill_done;
    wire [8:0] fill_addr;
    wire [15:0] fill_data;
    wire start_sdram,start_pattern;

    video_line_source_mux source_mux_i(
        .clk(clk),.reset(src_reset),
        .video_mode(video_mode),.fill_start(fill_start),
        .start_sdram(start_sdram),.start_pattern(start_pattern),
        .burst_we(burst_we),.burst_addr(burst_addr),
        .burst_data(burst_data),.burst_done(burst_done),
        .pat_we(pat_we),.pat_addr(pat_addr),
        .pat_data(pat_data),.pat_done(pat_done),
        .fill_we(fill_we),.fill_addr(fill_addr),
        .fill_data(fill_data),.fill_done(fill_done));

    always @(posedge clk) begin
        fill_start<=1'b0;
        if(src_reset) begin
            line_tick<=0; fill_busy<=0; fill_line<=0;
        end else begin
            if(fill_done && fill_busy) begin
                fill_busy<=1'b0;
                lines_done=lines_done+1;
            end
            if(line_tick>=16'd1587) begin
                if(!fill_busy) begin
                    line_tick<=0; fill_start<=1'b1; fill_busy<=1'b1;
                    fill_line<=(fill_line==8'd239) ? 8'd0 : fill_line+8'd1;
                end
            end else line_tick<=line_tick+1'b1;
        end
    end

    video_line_source_burst source_sdram_i(
        .clk(clk),.reset(src_reset),.fb_base(video_fb_base),
        .fill_start(start_sdram),.fill_line(fill_line),
        .fill_we(burst_we),.fill_addr(burst_addr),.fill_data(burst_data),
        .fill_done(burst_done),
        .req_valid(p2_valid),.req_ready(p2_ready),.req_write(p2_write),
        .req_addr(p2_addr),.req_wdata(p2_wdata),.req_wmask(p2_wmask),
        .urgent(p2_urgent),
        .rsp_valid(p2_rsp_valid),.rsp_ready(),
        .rsp_rdata(p2_rsp_rdata),.rsp_error(p2_rsp_error));

    video_line_source_pattern source_pat_i(
        .clk(clk),.reset(src_reset),
        .fill_start(start_pattern),.fill_line(fill_line),
        .fill_we(pat_we),.fill_addr(pat_addr),.fill_data(pat_data),
        .fill_done(pat_done));

    reg [7:0] byte_result;
    integer i,cycles,errors=0;
    integer before_count;

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

    // Espera a que arranque un llenado y devuelve con la linea A MEDIAS, que es
    // la ventana en la que el cambio de modo hace dano.
    //
    // La espera va ACOTADA a proposito. Si el video ya esta encallado no habra
    // ningun `fill_start` nunca mas, y una espera infinita aqui convertiria un
    // fallo claro en una simulacion de horas hasta el timeout global.
    task wait_mid_fill;
        integer guard;
        begin
            @(posedge clk);
            guard=0;
            while(!fill_start && guard<4000) begin @(posedge clk); guard=guard+1; end
            if(!fill_start) begin
                $display("FAIL: ningun fill_start en 4000 ciclos -- el video ya estaba encallado (fill_busy=%0b)",fill_busy);
                errors=errors+1;
            end else begin
                repeat(20) @(posedge clk);   // dentro de la linea, lejos del final
                if(!fill_busy) begin
                    $display("FAIL: la linea termino antes de poder cambiar el modo");
                    errors=errors+1;
                end
            end
        end
    endtask

    // Comprueba que en `window` ciclos se completa al menos una linea.
    task recover;
        begin
            @(negedge clk); src_reset_pulse=1;
            repeat(4) @(negedge clk); src_reset_pulse=0;
            repeat(2) @(negedge clk);
        end
    endtask

    task expect_lines_flowing;
        input [511:0] etiqueta;
        input integer window;
        begin
            before_count=lines_done;
            repeat(window) @(posedge clk);
            if(lines_done==before_count) begin
                $display("FAIL: %0s -- el video se ENCALLO (0 lineas en %0d ciclos, fill_busy=%0b)",
                         etiqueta, window, fill_busy);
                errors=errors+1;
            end else $display("OK: %0s -- %0d lineas completadas",
                              etiqueta, lines_done-before_count);
        end
    endtask

    initial begin
        repeat(4) @(negedge clk); reset=0;
        wait(halted);

        if(video_mode!==2'd1) begin
            $display("FAIL: tras el reset video_mode=%0d, esperaba 1 (PATTERN)",video_mode);
            errors=errors+1;
        end

        write_word(32'h80000204,32'h0010_0000);   // FB_BASE, para la fuente SDRAM

        // ---- 1. Referencia: en PATTERN las lineas fluyen ----
        expect_lines_flowing("PATTERN en reposo", 8000);

        // ---- 2. Control: cambiar el modo ENTRE lineas no debe romper nada ----
        // Va antes que los casos destructivos a proposito: si fallara este, el
        // problema no seria la ventana del llenado sino algo mas gordo.
        @(posedge clk);
        while(fill_busy) @(posedge clk);
        access(1,32'h80000200,8'd2);
        expect_lines_flowing("cambio de modo ENTRE lineas (control)", 20000);

        // ---- 3. PATTERN -> SCANOUT con una linea A MEDIAS ----
        // Es exactamente lo que hace ahora el prologo de plasma.asm: la GPU
        // escribe VIDEO_CTRL mientras el video esta a lo suyo.
        recover;
        access(1,32'h80000200,8'd1);
        expect_lines_flowing("vuelta a PATTERN tras recuperar", 8000);
        wait_mid_fill;
        access(1,32'h80000200,8'd2);
        if(video_mode!==2'd2) begin
            $display("FAIL: VIDEO_CTRL no cambio a SCANOUT (modo=%0d)",video_mode);
            errors=errors+1;
        end
        expect_lines_flowing("tras PATTERN->SCANOUT a mitad de linea", 20000);

        // ---- 4. Y la vuelta, SCANOUT -> PATTERN, tambien a medias ----
        recover;
        expect_lines_flowing("SCANOUT tras recuperar", 20000);
        wait_mid_fill;
        access(1,32'h80000200,8'd1);
        expect_lines_flowing("tras SCANOUT->PATTERN a mitad de linea", 20000);

        $display("");
        if(errors==0) $display("gpu_video_mode_switch_tb: TODAS LAS PRUEBAS PASAN");
        else $fatal(1,"gpu_video_mode_switch_tb: %0d FALLOS",errors);
        $finish;
    end
    // La prueba entera son ~120 000 ciclos (4,8 ms de simulacion). El margen es
    // amplio pero acotado: con el timeout viejo, de 2 segundos simulados, un
    // encallamiento se pasaba media hora moliendo ciclos antes de avisar.
    initial begin #20000000; $fatal(1,"timeout"); end
endmodule
`default_nettype wire
