`timescale 1ns/1ps
module rop_core_tb;
  reg clk=0; always #5 clk=~clk;
  reg reset=1;
  reg cmd_valid=0;
  wire cmd_ready, done_valid, done_error, busy;
  reg [2:0] cmd_op=0;
  reg [12:0] cmd_mode=0;
  reg [319:0] cmd_params=0;
  reg [255:0] cmd_frag_colors=0, cmd_frag_z=0;
  wire req_valid, req_write, rsp_ready;
  reg req_ready=1;
  // stress: req_ready cae al azar (contrapresion) y cada respuesta tarda de 1
  // a 8 ciclos, siempre en orden. err_at: numero de peticion (contando desde
  // el reset) cuya respuesta llega con error; -1 ninguna.
  reg stress=0;
  integer err_at=-1, req_count=0;
  always @(negedge clk) req_ready = stress ? (($random & 3) != 0) : 1'b1;
  wire [31:0] req_addr;
  wire [127:0] req_wdata;
  wire [15:0] req_wmask;
  wire [127:0] rsp_rdata;
  wire rsp_valid;
  wire rsp_error;
  rop_core #(.TAG_DEPTH(8)) dut (.*);

  reg [7:0] ram [0:16383];
  reg [127:0] replies [0:8191];
  reg err_flag [0:8191];
  integer due [0:8191];
  integer head=0,tail=0,cycle=0;
  assign rsp_valid=(head!=tail && cycle>=due[head]);
  assign rsp_rdata=replies[head];
  assign rsp_error=(head!=tail) && err_flag[head];
  integer i,j;
  reg [127:0] temp;
  // head, tail, cycle, replies y due se actualizan con asignaciones NO
  // bloqueantes: rsp_valid y rsp_rdata salen de ellos combinacionalmente, y con
  // asignaciones bloqueantes cambiaban en el mismo flanco en que el DUT los
  // muestrea. Segun el orden de evaluacion, el DUT veia la respuesta
  // siguiente (vacia, x): v0.4 pasaba por suerte y area1, que registra
  // rsp_rdata en read_buffer, fallaba en el primer SPAN con comparacion.
  always @(posedge clk) begin
    if (reset) begin head<=0; tail<=0; cycle<=0; end
    else begin
      cycle<=cycle+1;
      if (rsp_valid && rsp_ready) head<=head+1;
      if (req_valid && req_ready) begin
        if (req_addr+15 >=16384) $fatal(1,"memory address outside test RAM");
        temp=0;
        if (req_write) begin
          for (j=0;j<16;j=j+1)
            if (req_wmask[j]) ram[req_addr+j]=req_wdata[j*8+:8];
        end else begin
          for (j=0;j<16;j=j+1) temp[j*8+:8]=ram[req_addr+j];
        end
        replies[tail]<=temp;
        err_flag[tail]<=(req_count==err_at);
        due[tail]<=cycle+(stress ? 1+($random & 7) : 3);
        tail<=tail+1;
        req_count<=req_count+1;
      end
    end
  end
  function [31:0] get32(input integer addr);
    get32={ram[addr+3],ram[addr+2],ram[addr+1],ram[addr]};
  endfunction
  function [15:0] get16(input integer addr);
    get16={ram[addr+1],ram[addr]};
  endfunction
  task automatic run(input [2:0] op,input [12:0] mode,input [319:0] params);
    integer watch;
    begin
      watch=0;
      @(negedge clk);
      while (!cmd_ready) begin
        @(negedge clk); watch=watch+1;
        if(watch>2000) $fatal(1,"timeout on cmd_ready");
      end
      cmd_op=op; cmd_mode=mode; cmd_params=params;cmd_valid=1;
      @(negedge clk); cmd_valid=0;
      watch=0;
      while (!done_valid) begin
        @(negedge clk); watch=watch+1;
        if(watch>10000) $fatal(1,"timeout on command completion");
      end
      if(done_error) $fatal(1,"ROP reported command error");
    end
  endtask
  // Como run, pero la respuesta numero `nth` (0 = la primera) de ESTE comando
  // llega con error: el comando tiene que acabar con done_error.
  task automatic run_error(input [2:0] op,input [12:0] mode,input [319:0] params,
                           input integer nth);
    integer watch;
    begin
      @(negedge clk);
      while (!cmd_ready) @(negedge clk);
      err_at=req_count+nth;
      cmd_op=op; cmd_mode=mode; cmd_params=params;cmd_valid=1;
      @(negedge clk); cmd_valid=0;
      watch=0;
      while (!done_valid) begin
        @(negedge clk); watch=watch+1;
        if(watch>10000) $fatal(1,"timeout on command completion (error case)");
      end
      if(!done_error) $fatal(1,"error response not reported (op %0d, nth %0d)", op, nth);
      err_at=-1;
    end
  endtask
  function [319:0] span_params(
      input [31:0] color_addr, z_addr, width, height,
      color_stride, z_stride, color, z0, xstep, ystep);
    span_params={ystep,xstep,z0,color,z_stride,color_stride,height,width,z_addr,color_addr};
  endfunction
  task automatic set16(input integer addr,input integer data);
    begin ram[addr]=data[7:0]; ram[addr+1]=data[15:8]; end
  endtask
  task automatic set32(input integer addr,input integer data);
    begin ram[addr]=data[7:0]; ram[addr+1]=data[15:8];
          ram[addr+2]=data[23:16];ram[addr+3]=data[31:24];end
  endtask
  task automatic check_span(input integer c32,input integer z32,
      input integer cbase,input integer zbase,
      input integer cs,input integer zs,input integer w,input integer h,
      input integer compare);
    integer x,y,caddr,zaddr,oldz,expectedz,expectedc,actualz,actualc;
    reg [12:0] flags;
    begin
      for (y=0;y<h;y=y+1)
        for (x=0;x<w;x=x+1) begin
          caddr=cbase+y*cs+x*(c32?4:2);
          zaddr=zbase+y*zs+x*(z32?4:2);
          oldz=(compare && (x%3 == 1))?50:1000;
          if(z32) set32(zaddr,oldz); else set16(zaddr,oldz);
          if(c32) set32(caddr,32'h1badc0de); else set16(caddr,16'hcafe);
        end
      // cmp LT (3) or ALWAYS (0), color32 bit3, z32 bit4,
      // z_write bit5, color_write bit6.
      flags = (compare?13'd3:13'd0) | (c32?13'h8:0) |
              (z32?13'h10:0) | 13'h60;
      run(3,flags,span_params(cbase,zbase,w,h,cs,zs,
              32'h1234abcd,100,3,20));
      for (y=0;y<h;y=y+1)
        for (x=0;x<w;x=x+1) begin
          caddr=cbase+y*cs+x*(c32?4:2);
          zaddr=zbase+y*zs+x*(z32?4:2);
          oldz=(compare && (x%3 == 1))?50:1000;
          expectedz=(compare && oldz==50)?50:(100+y*20+x*3);
          expectedc=(compare && oldz==50)?(c32?32'h1badc0de:16'hcafe):
                      (c32?32'h1234abcd:16'habcd);
          actualz=z32?get32(zaddr):get16(zaddr);
          actualc=c32?get32(caddr):get16(caddr);
          if(actualz!==expectedz || actualc!==expectedc) begin
            $display("SPAN mismatch c32=%0d z32=%0d x=%0d y=%0d actualz=%h expectedz=%h actualc=%h expectedc=%h",c32,z32,x,y,actualz,expectedz,actualc,expectedc);
            $fatal(1,"SPAN mismatch");
          end
        end
    end
  endtask
  // FRAGMENT: each lane has independent color and Z. The coverage mask
  // suppresses writes even when a lane would pass the Z-test.
  task automatic check_fragment(input integer c32,input integer z32,
      input integer cbase,input integer zbase,input integer n,
      input [7:0] coverage,input integer compare);
    integer q,ca,za,oldz,expectedz,expectedc,actualz,actualc;
    reg [12:0] flags;
    reg [255:0] colors, depths;
    reg pass;
    begin
      colors=0; depths=0;
      for (q=0;q<n;q=q+1) begin
        ca=cbase+q*(c32?4:2);
        za=zbase+q*(z32?4:2);
        oldz= (q%3==1)?50:1000;
        if(z32) set32(za,oldz); else set16(za,oldz);
        if(c32) set32(ca,32'h1badc0de); else set16(ca,16'hcafe);
        colors[q*32 +:32]=32'h12340000+q*17+32'habcd;
        depths[q*32 +:32]=100+q*7;
      end
      flags=(compare?13'd3:13'd0) | (c32?13'h8:0) |
            (z32?13'h10:0) | 13'h60;
      @(negedge clk);
      while (!cmd_ready) @(negedge clk);
      cmd_op=3'd4;
      cmd_mode=flags;
      cmd_params={192'd0,{24'd0,coverage},n,zbase,cbase};
      cmd_frag_colors=colors;
      cmd_frag_z=depths;
      cmd_valid=1;
      @(negedge clk); cmd_valid=0;
      begin : wait_fragment
        integer watchdog;
        watchdog=0;
        while (!done_valid && watchdog<10000) begin
          @(negedge clk); watchdog=watchdog+1;
        end
        if (!done_valid) $fatal(1,"FRAGMENT timeout");
        if (done_error) $fatal(1,"FRAGMENT invalid command/error");
      end
      for (q=0;q<n;q=q+1) begin
        ca=cbase+q*(c32?4:2);
        za=zbase+q*(z32?4:2);
        oldz=(q%3==1)?50:1000;
        pass=coverage[q] && (!compare || (100+q*7<oldz));
        expectedz=pass?(100+q*7):oldz;
        expectedc=pass?(c32?(32'h12340000+q*17+32'habcd):
                         ((32'h12340000+q*17+32'habcd)&16'hffff)):
                      (c32?32'h1badc0de:16'hcafe);
        actualz=z32?get32(za):get16(za);
        actualc=c32?get32(ca):get16(ca);
        if(actualz!==expectedz || actualc!==expectedc) begin
          $display("FRAGMENT mismatch c32=%0d z32=%0d lane=%0d cov=%b old=%d got Z=%h C=%h expected Z=%h C=%h",
                   c32,z32,q,coverage,oldz,actualz,actualc,expectedz,expectedc);
          $fatal(1,"FRAGMENT mismatch");
        end
      end
    end
  endtask
  task automatic suite;
    begin
    for(i=0;i<16384;i=i+1) ram[i]=0;
    // FILL two 32-byte rows, 48-byte destination stride.
    run(0,0,{160'd0,32'h11223344,32'd48,32'd2,32'd32,32'h100});
    for(i=0;i<2;i=i+1)
      for(j=0;j<8;j=j+1)
        if(get32('h100+i*48+j*4)!==32'h11223344) $fatal(1,"FILL mismatch");
    // COPY source rows at 0x100 to destination 0x200.
    run(1,0,{128'd0,32'd48,32'd48,32'd2,32'd32,32'h200,32'h100});
    for(i=0;i<2;i=i+1)
      for(j=0;j<8;j=j+1)
        if(get32('h200+i*48+j*4)!==32'h11223344) $fatal(1,"COPY mismatch");
    // GEN32: width=4, height=2, dx=2, dy=100, stride=32.
    run(2,13'h8,{96'd0,32'd100,32'd2,32'd100,32'd32,32'd2,32'd4,32'h300});
    for(i=0;i<2;i=i+1)
      for(j=0;j<4;j=j+1)
        if(get32('h300+i*32+j*4)!==(100+i*100+j*2)) $fatal(1,"GEN32 mismatch");
    // GEN16 LT: initialize depth destination to 0xFFFF.
    for(i=0;i<2;i=i+1)
      for(j=0;j<16;j=j+1) ram['h400+i*32+j]=8'hff;
    run(2,13'h3,{96'd0,32'd100,32'd2,32'd10,32'd32,32'd2,32'd8,32'h400});
    for(i=0;i<2;i=i+1)
      for(j=0;j<8;j=j+1)
        if(get16('h400+i*32+j*2)!==(10+i*100+j*2)) $fatal(1,"GEN16 LT mismatch");
    // GEN16 GT with the same candidate must not overwrite any depth.
    run(2,13'h5,{96'd0,32'd100,32'd2,32'd10,32'd32,32'd2,32'd8,32'h400});
    for(i=0;i<2;i=i+1)
      for(j=0;j<8;j=j+1)
        if(get16('h400+i*32+j*2)!==(10+i*100+j*2)) $fatal(1,"GEN16 GT wrote incorrectly");
    // GEN16 LT, dos bloques por fila y carriles mezclados: cada carril usa su
    // propio k*dx (dx_mult) y el segundo bloque arranca en cur_z + 8*dx. Los
    // impares tienen Z vieja 0 (no pasan), los pares 0xFFFF (pasan).
    for(j=0;j<16;j=j+1) begin
      ram['h600+j*2]   = (j%2) ? 8'h00 : 8'hff;
      ram['h600+j*2+1] = (j%2) ? 8'h00 : 8'hff;
    end
    run(2,13'h3,{96'd0,32'd0,32'd3,32'd7,32'd32,32'd1,32'd16,32'h600});
    for(j=0;j<16;j=j+1)
      if(get16('h600+j*2)!==((j%2) ? 16'd0 : 16'd7+j*3))
        $fatal(1,"GEN16 LT mixed mismatch at %0d: %h", j, get16('h600+j*2));
    // Distinct color and Z buffers, mixed widths, partial 128b blocks.
    // Bases are pixel-aligned but deliberately not necessarily 128b-aligned.
    check_span(0,0,'h502,'h806,22,26,7,3,1);
    check_span(0,1,'h902,'ha04,26,40,9,2,1);
    check_span(1,0,'hb04,'hd02,44,28,9,2,1);
    check_span(1,1,'he0c,'h1008,48,52,8,2,1);
    // No read required for unconditional SPAN, same two independent outputs.
    check_span(0,0,'h1202,'h1406,24,26,5,2,0);
    // Four fragment formats, mixed coverage, independent alignment, Z-test.
    check_fragment(0,0,'h1602,'h1806,8,8'b11010101,1);
    check_fragment(0,1,'h1a02,'h1c04,8,8'b10111011,1);
    check_fragment(1,0,'h1e04,'h2002,8,8'b01110111,1);
    check_fragment(1,1,'h220c,'h2408,8,8'b11100111,1);
    // No comparison, one pixel and no covered pixel.
    check_fragment(0,0,'h260e,'h280e,1,8'b00000001,0);
    check_fragment(1,1,'h2a04,'h2c08,5,8'b00000000,1);
    // v0.4: reject compact command prior to full CONFIG.
    // Earlier tests covered the explicit descriptor path.
    // CONFIG all groups: bases, strides, color, Z interpolation, render mode.
    // flags 0x60 = ALWAYS + writes to both color and Z, both 16-bit.
    run(5,13'h01f,{32'd0,32'h60,32'd20,32'd3,32'd100,
                    32'h00001234,32'd40,32'd32,32'h3200,32'h3000});
    // Compact SPAN: p0/p1 are byte offsets, p2=width, p3=height.
    // Offsets differ between the color and depth surfaces.
    run(3,13'h1000,{192'd0,32'd2,32'd5,32'd6,32'd2});
    for(i=0;i<2;i=i+1) for(j=0;j<5;j=j+1) begin
      if(get16('h3002+i*32+j*2)!==16'h1234) $fatal(1,"compact SPAN color");
      if(get16('h3206+i*40+j*2)!==(100+i*20+j*3)) $fatal(1,"compact SPAN Z");
    end
    // CONFIG updates only color. Other configuration must persist.
    run(5,13'h004,{160'd0,32'h00005678,128'd0});
    run(3,13'h1000,{192'd0,32'd1,32'd3,32'd80,32'd64});
    for(j=0;j<3;j=j+1) begin
      if(get16('h3040+j*2)!==16'h5678) $fatal(1,"partial CONFIG color not retained");
      if(get16('h3250+j*2)!==(100+j*3)) $fatal(1,"partial CONFIG Z not retained");
    end
    // Compact SPAN override COLOR and INITIAL while preserving dx,dy.
    run(3,13'h1300,{64'd0,32'd500,32'h00009abc,
                    32'd1,32'd2,32'd112,32'd96});
    for(j=0;j<2;j=j+1) begin
      if(get16('h3060+j*2)!==16'h9abc) $fatal(1,"SPAN override color");
      if(get16('h3270+j*2)!==(500+j*3)) $fatal(1,"SPAN override z");
    end
    // Switch CONFIG for compact FRAGMENT, with independent color and Z32.
    run(5,13'h01f,{32'd0,32'h78,32'd0,32'd0,32'd0,
                    32'd0,32'd64,32'd64,32'h3700,32'h3500});
    for(j=0;j<4;j=j+1) begin
      set32('h3504+j*4,32'hf0f0f0f0);
      set32('h3708+j*4,32'hffffffff);
    end
    cmd_frag_colors=0; cmd_frag_z=0;
    for(j=0;j<4;j=j+1) begin
      cmd_frag_colors[j*32 +: 32]=32'h00112200+j;
      cmd_frag_z[j*32 +: 32]=32'd700+j;
    end
    run(4,13'h1000,{192'd0,32'h00000005,32'd4,32'd8,32'd4});
    for(j=0;j<4;j=j+1) begin
      if(get32('h3504+j*4)!==(j%2==0?32'h00112200+j:32'hf0f0f0f0))
        $fatal(1,"compact FRAGMENT color coverage");
      if(get32('h3708+j*4)!==(j%2==0?32'd700+j:32'hffffffff))
        $fatal(1,"compact FRAGMENT Z coverage");
    end
    end
  endtask

  initial begin
    repeat(4) @(negedge clk);
    reset=0;
    suite;
    // La misma bateria con contrapresion y latencias variables.
    stress=1;
    suite;
    // Errores: en una escritura (FILL), en la lectura de un COPY y en la
    // lectura de Z de un SPAN con comparacion. Despues, el ROP tiene que
    // aceptar y terminar bien el comando siguiente.
    run_error(0,0,{160'd0,32'h55555555,32'd48,32'd2,32'd32,32'h100},1);
    run_error(1,0,{128'd0,32'd48,32'd48,32'd2,32'd32,32'h200,32'h100},0);
    for(i=0;i<3;i=i+1) for(j=0;j<7;j=j+1) begin
      set16('h806+i*26+j*2,1000); set16('h502+i*22+j*2,16'hcafe);
    end
    run_error(3,13'h63,span_params('h502,'h806,7,3,22,26,32'h1234abcd,100,3,20),0);
    run(0,0,{160'd0,32'h77777777,32'd48,32'd2,32'd32,32'h100});
    for(i=0;i<2;i=i+1)
      for(j=0;j<8;j=j+1)
        if(get32('h100+i*48+j*4)!==32'h77777777) $fatal(1,"FILL after error mismatch");
    $display("PASS rop_core_tb: dos pasadas (sin y con contrapresion) + errores");
    $finish;
  end
endmodule
