`default_nettype none
`timescale 1ns/1ps
// Regression del protocolo ante errores al principio y a mitad de un bloque.
// Un ff de datos es legitimo; un error nunca puede viajar dentro del payload.
module mmio_monitor_tb;
  reg clk=0, reset=1;
  always #5 clk=~clk;
  reg [7:0] rx_data=0;
  reg rx_strobe=0, tx_ready=1;
  wire [7:0] tx_data;
  wire tx_strobe, busy;
  wire [31:0] mem_address;
  wire [7:0] mem_write_data;
  wire mem_write_enable, mem_read_enable;
  reg [7:0] mem_read_data=0;
  reg [31:0] mem_read_word=0;
  reg mem_ready=0, mem_error=0;
  reg inject_error=0;
  reg [31:0] fail_address=0;
  integer writes=0, count=0, cooldown=0;
  reg [7:0] received[0:2047];
  monitor #(.RAM_END(33'd1024)) dut(
    .clk(clk),.reset(reset),.rx_data(rx_data),.rx_strobe(rx_strobe),
    .tx_data(tx_data),.tx_strobe(tx_strobe),.tx_ready(tx_ready),.busy(busy),
    .mem_address(mem_address),.mem_write_data(mem_write_data),
    .mem_write_enable(mem_write_enable),.mem_read_enable(mem_read_enable),
    .mem_read_data(mem_read_data),.mem_read_word(mem_read_word),
    .mem_ready(mem_ready),.mem_error(mem_error),
    .cpu_halted(1'b1),.cpu_error(1'b0),.cpu_error_code(8'd0),
    .cpu_pc(32'd0),.cpu_debug_register_data(32'd0),
    .serial_rx_free(8'd0),.serial_tx_count(8'd0),.serial_tx_data(8'd0));
  always @(posedge clk) begin
    mem_ready<=0; mem_error<=0;
    if(!reset && (mem_read_enable || mem_write_enable)) begin
      mem_ready<=1;
      if(inject_error && mem_address==fail_address) mem_error<=1;
      else if(mem_address>=33'd1024 && mem_address[31:12]!=20'h80000 && mem_address[31:8]!=24'hffffff && mem_address[31:12]!=20'h40000) mem_error<=1;  // hueco (hay un dispositivo en la ultima pagina, para probar la vuelta)
      else begin
        mem_read_data<=8'hff;
        mem_read_word<=32'hffffffff;
        if(mem_write_enable) writes<=writes+1;
      end
    end
    if(tx_strobe && tx_ready) begin
      received[count]<=tx_data; count<=count+1;
      tx_ready<=0; cooldown<=2;
    end else if(cooldown>0) begin
      cooldown<=cooldown-1;
      if(cooldown==1) tx_ready<=1;
    end
  end
  task send(input [7:0] data);
    begin
      @(negedge clk);rx_data=data;rx_strobe=1;
      @(negedge clk);rx_strobe=0;
      repeat(10) @(negedge clk);
    end
  endtask
  task address(input [31:0] addr);
    begin send(addr[31:24]);send(addr[23:16]);send(addr[15:8]);send(addr[7:0]);end
  endtask
  task ping;
    integer start;
    begin
      wait(!busy && tx_ready);start=count;send(8'h01);
      wait(count==start+1);repeat(10) @(negedge clk);
      if(received[start]!==8'h81 || count!=start+1) $fatal(1,"desincronizacion");
    end
  endtask
  integer base,i,n;
  // Bordes de block_last (longitud 1, 2, 3 y 256), en lectura y en escritura: tienen que
  // mover EXACTAMENTE n bytes y contestar bien, sin quedarse uno corto ni uno largo.
  task read_block_ok(input integer len);
    begin
      wait(!busy && tx_ready);base=count;
      send(8'h21);address(0);send(len>>8);send(len);
      wait(count==base+len+1);wait(!busy);
      if(received[base]!==8'ha1) $fatal(1,"read_block %0d: falta cabecera",len);
      for(i=1;i<=len;i=i+1) if(received[base+i]!==8'hff) $fatal(1,"read_block %0d: dato perdido",len);
      ping;
    end
  endtask
  task write_block_ok(input integer len);
    begin
      wait(!busy && tx_ready);base=count;writes=0;
      send(8'h20);address(0);send(len>>8);send(len);
      for(i=0;i<len;i=i+1) send(8'ha5);
      wait(count==base+1);wait(!busy);
      if(received[base]!==8'ha0 || writes!=len) $fatal(1,"write_block %0d: escritos %0d",len,writes);
      ping;
    end
  endtask
  initial begin
    repeat(3) @(negedge clk);reset=0;
    // Tamano minimo y maximo, incluyendo datos ff indistinguibles de NACK.
    for(n=1;n<=256;n=n+255) begin
      wait(!busy && tx_ready);base=count;
      send(8'h21);address(0);send(n>>8);send(n);
      wait(count==base+n+1);wait(!busy);
      if(received[base]!==8'ha1) $fatal(1,"falta cabecera");
      for(i=1;i<=n;i=i+1) if(received[base+i]!==8'hff) $fatal(1,"dato ff perdido");
    end
    read_block_ok(2); read_block_ok(3);
    write_block_ok(1); write_block_ok(2); write_block_ok(3); write_block_ok(256);
    // El error aparece en el primer, segundo o ultimo byte. Nunca emitir a1.
    for(n=0;n<4;n=n+1) begin
      wait(!busy && tx_ready);base=count;
      inject_error=1;fail_address=32'h80000f00+n;
      send(8'h21);address(32'h80000f00);send(0);send(4);
      wait(count==base+1);wait(!busy);
      if(received[base]!==8'hff) $fatal(1,"error convertido en datos");
      ping;
      wait(!busy && tx_ready);base=count;writes=0;
      send(8'h20);address(32'h80000f00);send(0);send(4);
      // Son comandos validos si por error el monitor vuelve a IDLE demasiado pronto.
      repeat(4) send(8'h01);
      wait(count==base+1);wait(!busy);
      if(received[base]!==8'hff || writes!=n) $fatal(1,"write parcial no se detuvo");
      ping;
    end
    // Un bloque que EMPIEZA fuera de la RAM no se valida: va al bus, que dice error en el
    // primer byte. No se escribe nada y se consume el payload entero.
    wait(!busy && tx_ready);base=count;writes=0;
    send(8'h20);address(32'h90000000);send(0);send(4);repeat(4) send(8'h01);
    wait(count==base+1);wait(!busy);
    if(received[base]!==8'hff || writes!=0) $fatal(1,"hueco aceptado");
    ping;
    // El hueco entre RAM_END y la mitad alta del mapa se rechaza ENTERO sin tocar el bus, aunque
    // el bus de la prueba tenga ahi un dispositivo (0x4000_0xxx): lo protege solo el monitor.
    wait(!busy && tx_ready);base=count;writes=0;
    send(8'h20);address(32'h40000000);send(0);send(4);for(i=0;i<4;i=i+1) send(8'h5a);
    wait(count==base+1);wait(!busy);
    if(received[base]!==8'hff || writes!=0) $fatal(1,"hueco entre RAM y MMIO aceptado");
    ping;
    // Un bloque que empieza en RAM y se sale de ella se rechaza ENTERO, sin tocar el bus.
    wait(!busy && tx_ready);base=count;writes=0;
    send(8'h20);address(1020);send(0);send(8);for(i=0;i<8;i=i+1) send(8'h5a);
    wait(count==base+1);wait(!busy);
    if(received[base]!==8'hff || writes!=0) $fatal(1,"bloque que cruza RAM_END aceptado");
    ping;
    // Un bloque que da la vuelta al espacio de 32 bits tambien: sin ello mem_address se
    // enrollaria sobre la direccion 0.
    wait(!busy && tx_ready);base=count;writes=0;
    send(8'h20);address(32'hfffffff0);send(0);send(32);for(i=0;i<32;i=i+1) send(8'h5a);
    wait(count==base+1);wait(!busy);
    if(received[base]!==8'hff || writes!=0) $fatal(1,"bloque que da la vuelta aceptado");
    ping;    $display("PASS: errores MMIO y bloques sin desincronizacion");$finish;
  end
  initial begin #1000000;$fatal(1,"timeout");end
endmodule
`default_nettype wire
