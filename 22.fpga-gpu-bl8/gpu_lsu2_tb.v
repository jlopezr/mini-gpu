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

    // El camino escalar de MMIO (ver mmio.md). Estaba sin conectar, asi que
    // este banco no lo probaba: la cobertura del MMIO vivia entera en
    // gpu_mmio_tb, que va por el sistema completo y no distingue si el fallo
    // es de la LSU o del decodificador.
    wire mmio_req_valid, mmio_req_write, mmio_rsp_ready;
    wire [31:0] mmio_req_addr, mmio_req_wdata;
    reg mmio_req_ready=1, mmio_rsp_valid=0, mmio_rsp_error=0;
    reg [31:0] mmio_rsp_rdata=0;

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
        .mem_rsp_rdata(mem_rsp_rdata), .mem_rsp_error(mem_rsp_error),
        .mmio_req_valid(mmio_req_valid), .mmio_req_ready(mmio_req_ready),
        .mmio_req_write(mmio_req_write), .mmio_req_addr(mmio_req_addr),
        .mmio_req_wdata(mmio_req_wdata),
        .mmio_rsp_valid(mmio_rsp_valid), .mmio_rsp_ready(mmio_rsp_ready),
        .mmio_rsp_rdata(mmio_rsp_rdata), .mmio_rsp_error(mmio_rsp_error));

    // ---- Modelo de esclavo MMIO: un registro de 32 bits por palabra ----
    // Responde en un ciclo, que es lo que hace el de verdad: la lectura de
    // gpu_video_regs es combinacional.
    reg [31:0] mmio_regs[0:15];
    integer mmio_transactions=0;
    reg [3:0] mmio_word;
    always @(posedge clk) begin
        if(!reset && mmio_req_valid && mmio_req_ready && !mmio_rsp_valid) begin
            mmio_transactions=mmio_transactions+1;
            mmio_word=mmio_req_addr[5:2];
            if(mmio_req_write) begin
                mmio_regs[mmio_word]<=mmio_req_wdata;
                mmio_rsp_rdata<=32'd0;
            end else mmio_rsp_rdata<=mmio_regs[mmio_word];
            mmio_rsp_error<=1'b0;
            mmio_rsp_valid<=1'b1;
        end else if(mmio_rsp_valid && mmio_rsp_ready) mmio_rsp_valid<=1'b0;
    end

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

    // Sin $dumpfile/$dumpvars a proposito: apio los rechaza porque el VCD lo
    // genera el -- `apio sim` lo vuelca solo. Ponerlos aqui dejaba el
    // prototipo entero sin `lint`, y ningun otro banco del repo los lleva.
    initial begin
        for(j=0;j<1024;j=j+1) mem[j]=128'd0;
        for(j=0;j<16;j=j+1) mmio_regs[j]=32'd0;
        mmio_regs[1]=32'hCAFE_0001;   // el que esta en 0x80000204
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

        // ---- 7. MMIO: una lane, sin coalescer, y sin fault por rango ----
        // Una direccion >= 0x02000000 es fault salvo si cae en 0x80000xxx.
        addr=0; addr[0 +: 32]=32'h8000_0204;
        base_tx=mmio_transactions;
        issue(3'd1, 1'b0, 8'h01, addr, 256'd0);
        await_rsp(got, err, tag);
        check_eq(err, 8'd0, "mmio load sin fault");
        check_eq(got[0 +: 32], 32'hCAFE_0001, "mmio load");
        check_eq(mmio_transactions-base_tx, 1, "mmio load: una transaccion");

        // ---- 8. MMIO: escritura y relectura ----
        addr=0; addr[0 +: 32]=32'h8000_0208;
        data=0; data[0 +: 32]=32'hDEAD_BEEF;
        issue(3'd2, 1'b1, 8'h01, addr, data);
        await_rsp(got, err, tag);
        check_eq(err, 8'd0, "mmio store sin fault");
        issue(3'd3, 1'b0, 8'h01, addr, 256'd0);
        await_rsp(got, err, tag);
        check_eq(got[0 +: 32], 32'hDEAD_BEEF, "mmio relectura");

        // ---- 9. MMIO: dos lanes NO se coalescen ----
        // Un registro de 32 bits no es una linea de 16 bytes: cada lane sale
        // por su cuenta, la de menor indice primero.
        addr=0;
        addr[0 +: 32]=32'h8000_0204;
        addr[32 +: 32]=32'h8000_0208;
        base_tx=mmio_transactions;
        issue(3'd4, 1'b0, 8'h03, addr, 256'd0);
        await_rsp(got, err, tag);
        check_eq(err, 8'd0, "mmio dos lanes sin fault");
        check_eq(mmio_transactions-base_tx, 2, "mmio dos lanes: dos transacciones");
        // Cada lane recibe SU valor aunque cada transaccion traiga un unico
        // registro de 32 bits. Eso es lo que compra replicar la respuesta en
        // las cuatro palabras de `rsp_line`: RETIRE reparte sin saber que
        // venia de MMIO, y elija el `sel` que elija saca el valor bueno.
        check_eq(got[0 +: 32], 32'hCAFE_0001, "mmio lane 0");
        check_eq(got[32 +: 32], 32'hDEAD_BEEF, "mmio lane 1");

        repeat(20) @(posedge clk);
        if(errors==0) $display("gpu_lsu2_tb: TODAS LAS PRUEBAS PASAN");
        else $fatal(1,"gpu_lsu2_tb: %0d FALLOS", errors);
        $finish;
    end

    initial begin
        #500000;
        $fatal(1,"FAIL: timeout");
    end
endmodule
`default_nettype wire
