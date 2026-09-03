`timescale 1ns/1ps
`default_nettype none
module monitor_tb;
  reg clk=0,reset=1; reg [7:0] rx_data=0; reg rx_strobe=0;
  wire [7:0] tx_data; wire tx_strobe; reg tx_ready=1;
  wire [31:0] mem_address; wire [7:0] mem_write_data;
  wire mem_write_enable,mem_read_enable; reg [7:0] mem_read_data=0;
  reg mem_ready=0,mem_error=0; wire [7:0] last_command; wire busy;
  reg [7:0] memory[0:1023]; reg [7:0] received[0:31];
  integer received_count=0, tx_delay=0;
  always #5 clk=~clk;
  monitor dut(.*);

  always @(posedge clk) begin
    mem_ready<=0; mem_error<=0;
    if(mem_write_enable) begin
      if(mem_address<1024) memory[mem_address]<=mem_write_data; else mem_error<=1;
      mem_ready<=1;
    end else if(mem_read_enable) begin
      if(mem_address<1024) mem_read_data<=memory[mem_address]; else mem_error<=1;
      mem_ready<=1;
    end
    if(tx_strobe && tx_ready) begin
      received[received_count]<=tx_data; received_count<=received_count+1;
      tx_ready<=0; tx_delay<=2;
    end else if(tx_delay>0) begin
      tx_delay<=tx_delay-1; if(tx_delay==1) tx_ready<=1;
    end
  end
  task send(input [7:0] value);
    begin @(negedge clk); rx_data=value; rx_strobe=1; @(negedge clk); rx_strobe=0; end
  endtask

  initial begin
    repeat(2) @(negedge clk); reset=0;
    send(8'h01); wait(received_count==1);
    if(received[0]!==8'h81) $fatal(1,"PING failed");
    wait(!busy && tx_ready);
    send(8'h02); wait(received_count==4);
    if({received[1],received[2],received[3]}!==24'h820200) $fatal(1,"VERSION failed");
    wait(!busy && tx_ready);
    // Four-byte address 0x00000025.
    send(8'h10); send(0); send(0); send(0); send(8'h25); send(8'hab);
    wait(received_count==5); if(received[4]!==8'h90 || memory[8'h25]!==8'hab) $fatal(1,"WRITE_BYTE failed");
    wait(!busy && tx_ready);
    send(8'h11); send(0); send(0); send(0); send(8'h25);
    wait(received_count==7); if({received[5],received[6]}!==16'h91ab) $fatal(1,"READ_BYTE failed");
    wait(!busy && tx_ready);
    // Odd start and odd length exercise consecutive byte addressing.
    send(8'h20); send(0); send(0); send(0); send(8'h31); send(0); send(3);
    send(8'hde); send(8'had); send(8'hbe); wait(received_count==8);
    if(received[7]!==8'ha0) $fatal(1,"WRITE_BLOCK failed");
    wait(!busy && tx_ready);
    send(8'h21); send(0); send(0); send(0); send(8'h31); send(0); send(3);
    wait(received_count==12);
    if({received[8],received[9],received[10],received[11]}!==32'ha1deadbe) $fatal(1,"READ_BLOCK failed");
    wait(!busy && tx_ready);
    send(8'h11); send(8'h02); send(0); send(0); send(0); wait(received_count==13);
    if(received[12]!==8'hff) $fatal(1,"range check failed");
    $display("PASS: 32-bit monitor protocol is correct"); $finish;
  end
endmodule
`default_nettype wire
