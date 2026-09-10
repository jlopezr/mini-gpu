`timescale 1ns/1ps
module gpu_uart_tb;
    reg clk_25mhz=0; always #20 clk_25mhz=~clk_25mhz;
    reg ftdi_txd=1;
    wire ftdi_rxd,wifi_gpio0;
    wire [7:0] led;
    top dut(.*);
    reg [7:0] request[0:31],response[0:31];
    integer tx_count,rx_count;
    task send_byte;
        input [7:0] value;
        integer b;
        begin
            @(negedge clk_25mhz); ftdi_txd=0;
            repeat(100) @(negedge clk_25mhz);
            for(b=0;b<8;b=b+1) begin
                ftdi_txd=value[b]; repeat(100) @(negedge clk_25mhz);
            end
            ftdi_txd=1; repeat(100) @(negedge clk_25mhz);
        end
    endtask
    task receive_byte;
        output [7:0] value;
        integer b;
        begin
            @(negedge ftdi_rxd);
            repeat(150) @(negedge clk_25mhz);
            for(b=0;b<8;b=b+1) begin
                value[b]=ftdi_rxd; repeat(100) @(negedge clk_25mhz);
            end
            if(ftdi_rxd!==1) $fatal(1,"UART stop bit");
        end
    endtask
    task exchange;
        input integer tx_size,rx_size;
        begin
            fork
                begin for(tx_count=0;tx_count<tx_size;tx_count=tx_count+1) send_byte(request[tx_count]); end
                begin for(rx_count=0;rx_count<rx_size;rx_count=rx_count+1) receive_byte(response[rx_count]); end
            join
            repeat(150) @(negedge clk_25mhz);
        end
    endtask
    initial begin
        repeat(1000) @(negedge clk_25mhz);
        request[0]=2; exchange(1,3);
        if(response[0]!==8'h82 || response[1]!==2 || response[2]!==0) $fatal(1,"GPU monitor version");
        // WRITE_BLOCK 0, 8 bytes: GETTID R1; HALT.
        request[0]=8'h20; request[1]=0; request[2]=0; request[3]=0; request[4]=0;
        request[5]=0; request[6]=8;
        request[7]=0; request[8]=0; request[9]=8'h20; request[10]=8'hc0;
        request[11]=0; request[12]=0; request[13]=0; request[14]=8'hfc;
        exchange(15,1); if(response[0]!==8'ha0) $fatal(1,"program load");
        // Block commands must cover all 128 KiB, not only the first 16 KiB.
        request[0]=8'h20; request[1]=0; request[2]=1; request[3]=8'hff; request[4]=8'hfc;
        request[5]=0; request[6]=4;
        request[7]=8'hde; request[8]=8'had; request[9]=8'hbe; request[10]=8'hef;
        exchange(11,1); if(response[0]!==8'ha0) $fatal(1,"high RAM block write");
        request[0]=8'h21; request[1]=0; request[2]=1; request[3]=8'hff; request[4]=8'hfc;
        request[5]=0; request[6]=4;
        exchange(7,5);
        if(response[0]!==8'ha1 || {response[1],response[2],response[3],response[4]}!==32'hdeadbeef)
            $fatal(1,"high RAM block read");
        // This is the path used by monitor.py configure: write one warp's PC,
        // masks and workgroup as little-endian words through MMIO.
        request[0]=8'h20; request[1]=8'h80; request[2]=0; request[3]=0; request[4]=8'h30;
        request[5]=0; request[6]=12;
        request[7]=0; request[8]=0; request[9]=0; request[10]=0;
        request[11]=8'h20; request[12]=0; request[13]=0; request[14]=0;
        request[15]=7; request[16]=0; request[17]=0; request[18]=0;
        exchange(19,1); if(response[0]!==8'ha0) $fatal(1,"warp configuration block write");
        // This is the path used by warp-status: read the complete 16-byte slot.
        request[0]=8'h21; request[1]=8'h80; request[2]=0; request[3]=0; request[4]=8'h30;
        request[5]=0; request[6]=16;
        exchange(7,17);
        if(response[0]!==8'ha1 || response[5]!==8'h20 || response[9]!==7 ||
           response[13]!==0 || response[14]!==0 || response[15]!==0 || response[16]!==0)
            $fatal(1,"warp status block read");
        request[0]=8'h30; exchange(1,1); if(response[0]!==8'hb0) $fatal(1,"run");
        request[0]=8'h33; exchange(1,7);
        if(response[0]!==8'hb3 || response[1]!==1 || response[2]!==0 || response[6]!==8) $fatal(1,"GPU status");
        // Select warp 3, lane 5 through the byte-oriented MMIO window.
        request[0]=8'h10; request[1]=8'h80; request[2]=0; request[3]=1; request[4]=0; request[5]=29;
        exchange(6,1); if(response[0]!==8'h90) $fatal(1,"context select");
        request[0]=8'h34; request[1]=1; exchange(2,5);
        if({response[1],response[2],response[3],response[4]}!==32'd29 || response[0]!==8'hb4)
            $fatal(1,"READ_REG must select warp/lane: %h %h %h %h %h",response[0],response[1],response[2],response[3],response[4]);
        request[0]=8'h35; exchange(1,1); if(response[0]!==8'hb5) $fatal(1,"reset");
        request[0]=8'h30; exchange(1,1); if(response[0]!==8'hb0) $fatal(1,"rerun preserved program");
        $display("PASS physical UART path: version, block load, default 8x8 run, status, warp/lane debug, reset");
        $finish;
    end
    initial begin #20000000; $fatal(1,"UART watchdog"); end
endmodule
