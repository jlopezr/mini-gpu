`default_nettype none
`include "sysid_params.vh"
`timescale 1ns/1ps
// Verifica que la GPU llega a la ventana MMIO por su cuenta: escribe
// VIDEO_CTRL, lo relee, y se cronometra leyendo los contadores.
//
// Antes esto era imposible por dos barreras (fault de la LSU por encima de
// 0x02000000, y `halted` exigido para escribir el MMIO). Que este banco pase es
// exactamente la diferencia.
module gpu_mmio_bl8_error_tb;
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

    integer cycles,k,w;
    task access(input wr,input [31:0] addr,input bad);
      begin
        @(negedge clk);host_address=addr;host_write_enable=wr;host_read_enable=!wr;
        @(negedge clk);host_write_enable=0;host_read_enable=0;cycles=0;
        while(!host_ready && cycles<100) begin @(negedge clk);cycles=cycles+1;end
        if(!host_ready || host_error!==bad) $fatal(1,"MMIO %h wr %b error %b",addr,wr,host_error);
      end
    endtask
    // Bases de MMIO v2 (1.isa/mmio.md §2). Este banco ataca `gpu_system_bl8`,
    // que SI tiene video y contadores -- al contrario que `gpu_mmio_error_tb`,
    // que ataca el `gpu_system` del entorno `base-bl1` y no los tiene. Los dos
    // bancos comprueban la misma regla sobre dos decodificadores distintos de
    // la misma carpeta, y esa es la razon de que existan los dos.
    localparam [31:0] SYSTEM_BASE = 32'h8000_0000;
    localparam [31:0] VIDEO_BASE  = 32'h8020_0000;
    localparam [31:0] GPU_BASE    = 32'h8200_0000;   // CORE: NO implementado
    localparam [31:0] WARPS_BASE  = 32'h8201_0000;
    localparam [31:0] SIMT_BASE   = 32'h8202_0000;
    localparam [31:0] PERF_BASE   = 32'h8203_0000;
    localparam [31:0] SERIAL_BASE = 32'h8010_0000;   // no lo tiene ninguna GPU
    initial begin
      repeat(4) @(negedge clk);reset=0;
      wait(halted);
      for(w=0;w<2;w=w+1) begin
        for(k=0;k<28;k=k+4) access(w,SYSTEM_BASE+k,w!=0);
        for(k=28;k<256;k=k+4) access(w,SYSTEM_BASE+k,1);
        // Bloques AUSENTES: dan ERROR, no cero.
        access(w,GPU_BASE,1);            // GPU CORE (§14.1), no implementado
        access(w,SERIAL_BASE,1);
        // Dentro de un bloque PRESENTE, lo que sobra tambien es error.
        access(w,WARPS_BASE+32'h80,1);   // pasados los 8 descriptores
        access(w,SIMT_BASE+32'h14,1);    // pasados los 5 registros de §14.3
        access(w,VIDEO_BASE+32'h28,1);   // pasados los 10 registros de §9
        access(w,PERF_BASE+32'h1c,1);    // pasados los 7 contadores
      end
      // VIDEO_TX (§9.7) vive AQUI y ya no en los contadores. Que conteste en
      // VIDEO+0x24 y NO en PERF+0x14 es la mudanza entera en dos lineas.
      access(0,VIDEO_BASE+32'h24,0);
      // PERF+0x14 es ahora STALL_MEM, que existe: lo que ya no existe es
      // VIDEO_TX en ese sitio. La prueba de que se movio es la de arriba.
      access(0,PERF_BASE+32'h14,0);
      access(1,PERF_BASE+32'h14,1);      // los contadores son de solo lectura
      // DEVICES (§5.4): esta es la unica GPU con video, o sea el unico bit 5.
      access(0,SYSTEM_BASE+32'h0c,0);
      if(host_read_word!==`SYSID_DEVICES)
        $fatal(1,"DEVICES %h no es el de sysid_params.vh (%h)",host_read_word,`SYSID_DEVICES);
$display("PASS: bl8 rechaza bloques ausentes y declara los presentes");$finish;
    end
    initial begin #1000000;$fatal(1,"timeout");end
endmodule
