`default_nettype none
`timescale 1ns/1ps
// Banco de la LSU v2.0. Detras del puerto de 128 bits hay un modelo de memoria
// trivial con latencia configurable -- lo que se prueba aqui es la coalescencia
// y el reparto, no el controlador SDRAM (ese ya tiene sdram_controller_128_tb).
module gpu_lsu2_tb;
    reg clk=0, reset=1;
    always #5 clk=~clk;

    reg req_valid=0, req_write=0;
    reg [2:0] req_tag=0;
    reg [7:0] req_mask=0;
    reg [255:0] req_address=0, req_data=0;
    wire req_ready, rsp_valid;
    reg rsp_ready=1;
    wire [2:0] rsp_tag;
    wire [255:0] rsp_data;
    wire [7:0] rsp_error, occupied;

    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [127:0] mem_req_wdata;
    wire [15:0] mem_req_wmask;
    reg mem_req_ready=1, mem_rsp_valid=0, mem_rsp_error=0;
    reg [127:0] mem_rsp_rdata=0;

    gpu_lsu2 dut(
        .clk(clk), .reset(reset),
        .req_valid(req_valid), .req_ready(req_ready), .req_tag(req_tag),
        .req_mask(req_mask), .req_write(req_write),
        .req_address(req_address), .req_data(req_data),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_tag(rsp_tag),
        .rsp_data(rsp_data), .rsp_error(rsp_error), .occupied(occupied),
        .mem_req_valid(mem_req_valid), .mem_req_ready(mem_req_ready),
        .mem_req_write(mem_req_write), .mem_req_addr(mem_req_addr),
        .mem_req_wdata(mem_req_wdata), .mem_req_wmask(mem_req_wmask),
        .mem_rsp_valid(mem_rsp_valid), .mem_rsp_ready(mem_rsp_ready),
        .mem_rsp_rdata(mem_rsp_rdata), .mem_rsp_error(mem_rsp_error));

    // ---- Modelo de memoria de 128 bits, mapeado por linea de 16 bytes ----
    reg [127:0] mem[0:1023];
    integer transactions=0, latency=6, errors=0;
    integer j;
    reg [27:0] line;
    reg [127:0] cur;
    always @(posedge clk) begin
        if(!reset && mem_req_valid && mem_req_ready && !mem_rsp_valid) begin
            transactions=transactions+1;
            line=mem_req_addr[31:4];
            if(mem_req_write) begin
                cur=mem[line[9:0]];
                for(j=0;j<16;j=j+1)
                    if(mem_req_wmask[j]) cur[j*8 +: 8]=mem_req_wdata[j*8 +: 8];
                mem[line[9:0]]=cur;
                mem_rsp_rdata<=128'd0;
            end else mem_rsp_rdata<=mem[line[9:0]];
            mem_rsp_error<=1'b0;
            repeat(latency) @(posedge clk);
            mem_rsp_valid<=1'b1;
        end else if(mem_rsp_valid && mem_rsp_ready) mem_rsp_valid<=1'b0;
    end

    task check_eq;
        input [255:0] got;
        input [255:0] want;
        input [255:0] name;
        begin
            if(got!==want) begin
                $display("FAIL %0s: got %h expected %h", name, got, want);
                errors=errors+1;
            end
        end
    endtask

    task issue;
        input [2:0] tag;
        input write;
        input [7:0] mask;
        input [255:0] addr;
        input [255:0] data;
    begin
        @(negedge clk);
        req_valid=1; req_tag=tag; req_write=write; req_mask=mask;
        req_address=addr; req_data=data;
        @(posedge clk);
        while(!req_ready) @(posedge clk);
        @(negedge clk); req_valid=0;
    end
    endtask

    task await_rsp;
        output [255:0] data;
        output [7:0] err;
        output [2:0] tag;
    begin
        while(!rsp_valid) @(posedge clk);
        data=rsp_data; err=rsp_error; tag=rsp_tag;
        @(posedge clk);
    end
    endtask

    // Construye 8 direcciones consecutivas base + lane*4.
    function [255:0] consecutive(input [31:0] base);
        integer k;
        begin
            consecutive=0;
            for(k=0;k<8;k=k+1) consecutive[k*32 +: 32]=base+k*4;
        end
    endfunction

    reg [255:0] addr, data, got;
    reg [7:0] err;
    reg [2:0] tag;
    integer base_tx;

    initial begin
        $dumpfile("gpu_lsu2_tb.vcd");
        $dumpvars(0, gpu_lsu2_tb);
        for(j=0;j<1024;j=j+1) mem[j]=128'd0;
        // Dos lineas contiguas con un patron reconocible por palabra.
        mem[16]={32'h0000_0003,32'h0000_0002,32'h0000_0001,32'h0000_0000};
        mem[17]={32'h0000_0007,32'h0000_0006,32'h0000_0005,32'h0000_0004};

        repeat(4) @(posedge clk);
        reset=0;

        // ---- 1. Load totalmente coalescido: 8 lanes consecutivas ----
        // Esperado: 2 transacciones (una por linea de 16 bytes), no 8.
        base_tx=transactions;
        issue(3'd0, 1'b0, 8'hff, consecutive(32'h0000_0100), 256'd0);
        await_rsp(got, err, tag);
        for(j=0;j<8;j=j+1)
            check_eq(got[j*32 +: 32], j, "load coalescido");
        check_eq(err, 8'd0, "load coalescido sin error");
        check_eq(tag, 3'd0, "tag del load coalescido");
        if(transactions-base_tx !== 2) begin
            $display("FAIL coalescencia: %0d transacciones, esperadas 2",
                     transactions-base_tx);
            errors=errors+1;
        end else $display("OK load coalescido en 2 transacciones");

        // ---- 2. Load disperso: 8 lanes en 8 lineas distintas ----
        // Sigue siendo correcto aunque no gane nada: 8 transacciones.
        for(j=0;j<8;j=j+1) begin
            addr[j*32 +: 32]=32'h0000_1000 + j*16;
            mem[256+j]={96'd0, 32'hA000_0000 + j};
        end
        base_tx=transactions;
        issue(3'd1, 1'b0, 8'hff, addr, 256'd0);
        await_rsp(got, err, tag);
        for(j=0;j<8;j=j+1)
            check_eq(got[j*32 +: 32], 32'hA000_0000+j, "load disperso");
        if(transactions-base_tx !== 8) begin
            $display("FAIL disperso: %0d transacciones, esperadas 8",
                     transactions-base_tx);
            errors=errors+1;
        end else $display("OK load disperso en 8 transacciones");

        // ---- 3. Store coalescido y relectura ----
        for(j=0;j<8;j=j+1) data[j*32 +: 32]=32'hBEEF_0000 + j;
        base_tx=transactions;
        issue(3'd2, 1'b1, 8'hff, consecutive(32'h0000_2000), data);
        await_rsp(got, err, tag);
        if(transactions-base_tx !== 2) begin
            $display("FAIL store coalescido: %0d transacciones, esperadas 2",
                     transactions-base_tx);
            errors=errors+1;
        end else $display("OK store coalescido en 2 transacciones");
        issue(3'd3, 1'b0, 8'hff, consecutive(32'h0000_2000), 256'd0);
        await_rsp(got, err, tag);
        for(j=0;j<8;j=j+1)
            check_eq(got[j*32 +: 32], 32'hBEEF_0000+j, "relectura del store");

        // ---- 4. Mascara parcial: solo lanes 2 y 5 ----
        // mem[N] cubre los bytes N*16 .. N*16+15: mem[300] es 0x12C0.
        mem[300]={32'h5555_0003,32'h5555_0002,32'h5555_0001,32'h5555_0000};
        for(j=0;j<8;j=j+1) addr[j*32 +: 32]=32'h0000_12C0 + (j%4)*4;
        issue(3'd4, 1'b0, 8'b0010_0100, addr, 256'd0);
        await_rsp(got, err, tag);
        check_eq(got[2*32 +: 32], 32'h5555_0002, "mascara parcial lane 2");
        check_eq(got[5*32 +: 32], 32'h5555_0001, "mascara parcial lane 5");
        check_eq(err, 8'd0, "mascara parcial sin error");

        // ---- 5. Faults: direccion fuera de rango y desalineada ----
        addr=consecutive(32'h0000_3000);
        addr[0*32 +: 32]=32'hF000_0000;   // fuera de rango
        addr[1*32 +: 32]=32'h0000_3002;   // desalineada
        base_tx=transactions;
        issue(3'd5, 1'b0, 8'hff, addr, 256'd0);
        await_rsp(got, err, tag);
        check_eq(err, 8'b0000_0011, "faults de rango y alineacion");

        // ---- 6. Dos warps entrelazados, lineas distintas ----
        mem[768]={32'hC000_0003,32'hC000_0002,32'hC000_0001,32'hC000_0000};
        mem[769]={32'hD000_0003,32'hD000_0002,32'hD000_0001,32'hD000_0000};
        issue(3'd6, 1'b0, 8'h0f, consecutive(32'h0000_3000), 256'd0);
        issue(3'd7, 1'b0, 8'h0f, consecutive(32'h0000_3010), 256'd0);
        await_rsp(got, err, tag);
        if(tag===3'd6) check_eq(got[0 +: 32], 32'hC000_0000, "warp 6");
        else check_eq(got[0 +: 32], 32'hD000_0000, "warp 7");
        await_rsp(got, err, tag);
        if(tag===3'd6) check_eq(got[0 +: 32], 32'hC000_0000, "warp 6 (2)");
        else check_eq(got[0 +: 32], 32'hD000_0000, "warp 7 (2)");

        repeat(20) @(posedge clk);
        if(errors==0) $display("gpu_lsu2_tb: TODAS LAS PRUEBAS PASAN");
        else $display("gpu_lsu2_tb: %0d FALLOS", errors);
        $finish;
    end

    initial begin
        #500000;
        $display("FAIL: timeout");
        $finish;
    end
endmodule
`default_nettype wire
