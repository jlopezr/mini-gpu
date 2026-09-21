`timescale 1ns/1ps
// La identidad se contrasta contra el fichero generado, no contra un numero
// escrito aqui: este banco comprueba que el valor LLEGA al registro. Que el
// valor sea el correcto lo comprueba `x.tests/test_sysid_params.py`, contra
// numeros a mano, igual que `test_mmio_map.py` hace con el mapa.
`include "sysid_params.vh"
module gpu_mmio_error_tb;
    reg clk=0;
    always #5 clk=~clk;
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
    gpu_system dut(.*,.instruction_retired(retired));
    integer cycles,k,w;
    task access(input wr,input [31:0] addr,input bad);
      begin
        @(negedge clk);host_address=addr;host_write_enable=wr;host_read_enable=!wr;
        @(negedge clk);host_write_enable=0;host_read_enable=0;cycles=0;
        while(!host_ready && cycles<100) begin @(negedge clk);cycles=cycles+1;end
        if(!host_ready || host_error!==bad) $fatal(1,"MMIO %h wr %b error %b",addr,wr,host_error);
      end
    endtask
    // Bases de MMIO v2 (1.isa/mmio.md §2), con nombre antes de usarlas.
    localparam [31:0] SYSTEM_BASE = 32'h8000_0000;
    localparam [31:0] GPU_BASE    = 32'h8200_0000;   // CORE: NO implementado
    localparam [31:0] WARPS_BASE  = 32'h8201_0000;
    localparam [31:0] SIMT_BASE   = 32'h8202_0000;
    localparam [31:0] PERF_BASE   = 32'h8203_0000;
    localparam [31:0] VIDEO_BASE  = 32'h8020_0000;   // este prototipo no tiene
    localparam [31:0] SERIAL_BASE = 32'h8010_0000;   // este prototipo no tiene
    initial begin
      repeat(4) @(negedge clk);reset=0;
      wait(halted);
      for(w=0;w<2;w=w+1) begin
        for(k=0;k<28;k=k+4) access(w,SYSTEM_BASE+k,w!=0);
        for(k=28;k<256;k=k+4) access(w,SYSTEM_BASE+k,1);
        // Bloques AUSENTES. Lo que se comprueba no es que den cero sino que
        // dan ERROR: un cero es indistinguible de un registro a cero.
        access(w,GPU_BASE,1);            // GPU CORE (§14.1), no implementado
        access(w,VIDEO_BASE,1);          // sin video en esta carpeta
        access(w,SERIAL_BASE,1);         // sin puerto serie en ninguna GPU
        access(w,WARPS_BASE+32'h80,1);   // pasados los 8 descriptores
        access(w,SIMT_BASE+32'h14,1);    // pasados los 5 registros de §14.3
        access(w,PERF_BASE,1);           // ranura 0 (CYCLES): no hay contador
      end
      access(0,PERF_BASE+32'h04,0);      // ranura 1 (RETIRED) si existe
      access(1,PERF_BASE+32'h04,1);      // y es de solo lectura
      // DEVICES (§5.4) declara SYSTEM, EBR y GPU. Esta es la unica carpeta de
      // la familia con EBR en vez de SDRAM, asi que el bit 3 y no el 2.
      access(0,SYSTEM_BASE+32'h0c,0);
      if(host_read_word!==`SYSID_DEVICES)
        $fatal(1,"DEVICES %h no es el de sysid_params.vh (%h)",host_read_word,`SYSID_DEVICES);
// MEM_SIZE (§5.5) son los 128 KiB de EBR de ESTA carpeta, que NO son los
      // 32 KiB de `MMIO_MEM_SIZE_EBR`: esa constante describe la 6, no esta.
      access(0,SYSTEM_BASE+32'h14,0);
      if(host_read_word!==32'h0002_0000)
        $fatal(1,"MEM_SIZE %h no son los 128 KiB de EBR",host_read_word);
      $display("PASS: GPU rechaza bloques ausentes y declara los presentes");$finish;
    end
    initial begin #1000000;$fatal(1,"timeout");end
endmodule
