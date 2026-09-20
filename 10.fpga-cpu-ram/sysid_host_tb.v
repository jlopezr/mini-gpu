`default_nettype none
`timescale 1ns/1ps
// Se instancia el top real: el bloque SYSTEM en 6/10 intercepta el bus fuera
// del adaptador de RAM. Forzar reloj/reset evita depender del modelo del PLL.
//
// MMIO v2 (1.isa/mmio.md seccion 5): siete palabras de solo lectura en
// 0x80000000. Lo que este banco fija, y es lo unico que lo distingue del de
// v1, es DONDE acaba el bloque: la palabra 7 (+0x1C) NO existe y tiene que dar
// error, igual que el resto del slot. Sin esa comprobacion, una seleccion de
// `[31:5]` a secas --que es lo barato-- pasaria: contestaria el `default` del
// modulo, o sea un cero, y un cero es un valor perfectamente legitimo para
// varios de los registros de al lado.
module sysid_host_tb;
  reg clk=0, reset=1;
  always #5 clk=~clk;
  reg [31:0] address=0;
  reg reading=0,writing=0;
  top dut(.clk_25mhz(clk),.ftdi_txd(1'b1),.btn_pwr_n(1'b1));
  integer guard,k,w;
  initial begin
    force dut.clk=clk;
    force dut.reset=reset;
    force dut.mem_address=address;
    force dut.mem_write_enable=writing;
    force dut.mem_read_enable=reading;
    force dut.mem_write_data=8'd0;
  end
  task access(input [31:0] addr,input wr,input bad);
    begin
      @(negedge clk);address=addr;writing=wr;reading=!wr;
      @(negedge clk);writing=0;reading=0;guard=0;
      while(!dut.mem_ready && guard<100) begin @(negedge clk);guard=guard+1;end
      if(!dut.mem_ready || dut.mem_error!==bad) $fatal(1,"SYS_ID %h wr %b err %b",addr,wr,dut.mem_error);
      if(!bad && addr==32'h80000000 && dut.mem_read_word!==32'h4d474155)
        $fatal(1,"MAGIC incorrecto %h",dut.mem_read_word);
      if(!bad && addr==32'h80000004 && dut.mem_read_word!==32'h00000200)
        $fatal(1,"MMIO_VERSION incorrecta %h",dut.mem_read_word);
      if(!bad && addr==32'h80000008 && dut.mem_read_word!==32'd10)
        $fatal(1,"SYSTEM_ID incorrecto %h",dut.mem_read_word);
      if(!bad && addr==32'h8000000c && dut.mem_read_word!==32'h00000005)
        $fatal(1,"DEVICES incorrecto %h",dut.mem_read_word);
      if(!bad && addr==32'h80000014 && dut.mem_read_word!==32'h02000000)
        $fatal(1,"MEM_SIZE incorrecto %h",dut.mem_read_word);
      if(!bad && addr==32'h80000018 && dut.mem_read_word!==32'h0000030a)
        $fatal(1,"MONITOR_VERSION incorrecta %h",dut.mem_read_word);
      repeat(4) @(negedge clk);
    end
  endtask
  initial begin
    repeat(4) @(negedge clk);reset=0;
    repeat(4) @(negedge clk);
    for(w=0;w<2;w=w+1) begin
      // Las SIETE que existen: se leen, y escribirlas da error.
      for(k=0;k<28;k=k+4) access(32'h80000000+k,w,w!=0);
      // +0x1C es la palabra 7, que NO existe, y de ahi hasta el final del slot
      // de 256 B. Todo error, tambien leyendo: ni cero ni alias.
      for(k=28;k<256;k=k+4) access(32'h80000000+k,w,1);
    end
    $display("PASS: bloque SYSTEM del top sin alias ni escrituras silenciosas");$finish;
  end
  initial begin #1000000;$fatal(1,"timeout");end
endmodule
`default_nettype wire
