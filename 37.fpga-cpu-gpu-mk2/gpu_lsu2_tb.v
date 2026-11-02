`default_nettype none
`timescale 1ns/1ps
// Banco de la LSU v2.0. Detras del puerto de 128 bits hay un modelo de memoria
// trivial con latencia configurable -- lo que se prueba aqui es la coalescencia
// y el reparto, no el controlador SDRAM (ese ya tiene sdram_controller_128_tb).
// Viene del de 22.fpga-gpu-bl8, con el tamano de acceso de la 37 (req_size) y
// los casos de la fusion por bytes de los STOREB/STOREH (casos 10 a 15).
module gpu_lsu2_tb;
    reg clk=0, reset=1;
    always #5 clk=~clk;

    reg req_valid=0, req_write=0;
    reg [2:0] req_tag=0;
    reg [7:0] req_mask=0;
    reg [255:0] req_address=0, req_data=0;
    reg [1:0] req_size=0;   // 0 palabra, 1 byte, 2 media palabra
    reg req_signed=0;
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
        .req_size(req_size), .req_signed(req_signed),
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

    // Como issue, con tamano. El SM replica el dato de un STOREB/STOREH en toda
    // la palabra; aqui lo hace quien llama (ver replicate).
    task issue_sized;
        input [2:0] tag;
        input write;
        input [1:0] size;
        input [7:0] mask;
        input [255:0] addr;
        input [255:0] data;
    begin
        req_size=size;
        issue(tag, write, mask, addr, data);
        req_size=2'd0;
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

    // Direcciones base + lane*step y datos de un STOREB/STOREH replicados como
    // los deja el SM: la media palabra dos veces, el byte cuatro.
    function [255:0] strided(input [31:0] base, input [31:0] step);
        integer k;
        begin
            strided=0;
            for(k=0;k<8;k=k+1) strided[k*32 +: 32]=base+k*step;
        end
    endfunction
    function [255:0] halves(input [15:0] first);
        integer k;
        begin
            halves=0;
            for(k=0;k<8;k=k+1) halves[k*32 +: 32]={2{first+k[15:0]}};
        end
    endfunction
    function [255:0] bytes(input [7:0] first);
        integer k;
        begin
            bytes=0;
            for(k=0;k<8;k=k+1) bytes[k*32 +: 32]={4{first+k[7:0]}};
        end
    endfunction
    task check_tx;
        input integer got_tx;
        input integer want_tx;
        input [255:0] name;
        begin
            if(got_tx!==want_tx) begin
                $display("FAIL %0s: %0d transacciones, esperadas %0d", name, got_tx, want_tx);
                errors=errors+1;
            end else $display("OK %0s en %0d transacciones", name, got_tx);
        end
    endtask

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
        // El modelo indexa por mmio_req_addr[5:2], asi que el indice ES el
        // offset dentro del bloque. FB_BACK era el offset 4 (indice 1) en v1 y
        // en v2 es el 8 (indice 2), porque CTRL se puso delante. Este numero
        // tuvo que moverse aunque la direccion del caso no cambiara de nombre:
        // es la misma trampa que en los .asm, vista desde el modelo.
        mmio_regs[2]=32'hCAFE_0001;   // FB_BACK, ahora en VIDEO+0x08
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
        // OJO: en v1 este caso usaba 0xF000_0000, y en v2 esa direccion YA NO
        // esta fuera de rango -- tiene el bit 31, o sea que cae en el espacio
        // de dispositivos y la LSU la manda por el camino MMIO. Quien la
        // rechaza entonces es el decodificador, con un error de bloque
        // ausente, no la LSU con un fault; son dos caminos distintos y este
        // caso mide el de la LSU. 0x7000_0000 sigue siendo lo que el caso
        // queria decir: por encima de la RAM y por debajo de los dispositivos.
        addr[0*32 +: 32]=32'h7000_0000;   // fuera de rango
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
        addr=0; addr[0 +: 32]=32'h8020_0008;
        base_tx=mmio_transactions;
        issue(3'd1, 1'b0, 8'h01, addr, 256'd0);
        await_rsp(got, err, tag);
        check_eq(err, 8'd0, "mmio load sin fault");
        check_eq(got[0 +: 32], 32'hCAFE_0001, "mmio load");
        check_eq(mmio_transactions-base_tx, 1, "mmio load: una transaccion");

        // ---- 8. MMIO: escritura y relectura ----
        addr=0; addr[0 +: 32]=32'h8020_000c;
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
        addr[0 +: 32]=32'h8020_0008;
        addr[32 +: 32]=32'h8020_000c;
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

        // ---- 10. STOREH de 8 pixeles seguidos, en una linea ----
        // Las 8 lanes escriben las dos mitades de 4 palabras: con la fusion por
        // bytes es UNA transaccion (antes, una lane por palabra: 2).
        mem[896]=128'd0;
        base_tx=transactions;
        issue_sized(3'd0, 1'b1, 2'd2, 8'hff, strided(32'h0000_3800, 2), halves(16'hA100));
        await_rsp(got, err, tag);
        check_eq(err, 8'd0, "storeh linea sin error");
        check_tx(transactions-base_tx, 1, "storeh 8 px en una linea");
        check_eq(mem[896], {16'hA107,16'hA106,16'hA105,16'hA104,16'hA103,16'hA102,16'hA101,16'hA100},
            "storeh 8 px: memoria");

        // ---- 11. STOREH de 8 pixeles que cruzan de linea ----
        // Empieza en el byte 8: 4 lanes en cada linea, 2 transacciones (antes 4).
        mem[912]=128'd0; mem[913]=128'd0;
        base_tx=transactions;
        issue_sized(3'd1, 1'b1, 2'd2, 8'hff, strided(32'h0000_3908, 2), halves(16'hB100));
        await_rsp(got, err, tag);
        check_tx(transactions-base_tx, 2, "storeh 8 px cruzando linea");
        check_eq(mem[912], {16'hB103,16'hB102,16'hB101,16'hB100,64'd0}, "storeh cruzando: linea 1");
        check_eq(mem[913], {64'd0,16'hB107,16'hB106,16'hB105,16'hB104}, "storeh cruzando: linea 2");

        // ---- 12. STOREB de 8 bytes seguidos ----
        // Dos palabras, cuatro lanes en cada una: 1 transaccion (antes 4).
        mem[928]={128{1'b1}};
        base_tx=transactions;
        issue_sized(3'd2, 1'b1, 2'd1, 8'hff, strided(32'h0000_3A04, 1), bytes(8'h40));
        await_rsp(got, err, tag);
        check_tx(transactions-base_tx, 1, "storeb 8 bytes");
        check_eq(mem[928], {32'hFFFF_FFFF,64'h4746_4544_4342_4140,32'hFFFF_FFFF}, "storeb 8 bytes: memoria");

        // ---- 13. Dos lanes en la MISMA media palabra ----
        // Solapan: la de menor lane va primero y la otra espera otra vuelta, asi
        // que queda el dato de la mayor (lane 5), como antes de la fusion.
        mem[944]=128'd0;
        addr=0; addr[2*32 +: 32]=32'h0000_3B02; addr[5*32 +: 32]=32'h0000_3B02;
        data=0; data[2*32 +: 32]={2{16'h2222}}; data[5*32 +: 32]={2{16'h5555}};
        base_tx=transactions;
        issue_sized(3'd3, 1'b1, 2'd2, 8'b0010_0100, addr, data);
        await_rsp(got, err, tag);
        check_tx(transactions-base_tx, 2, "storeh misma media");
        check_eq(mem[944], {96'd0,16'h5555,16'h0000}, "storeh misma media: lane mayor");

        // ---- 14. Solape parcial mezclado con bytes que si se fusionan ----
        // Lanes 0..3 escriben los bytes 0,1,2,3 de una palabra; la lane 4 vuelve
        // al byte 1 (solapa con la 1) y las 5..7 escriben la palabra siguiente.
        // Primera vuelta: todas menos la 4 (una transaccion); segunda: la 4.
        mem[960]=128'd0;
        addr=strided(32'h0000_3C00, 1);
        addr[4*32 +: 32]=32'h0000_3C01;
        addr[5*32 +: 32]=32'h0000_3C04; addr[6*32 +: 32]=32'h0000_3C05; addr[7*32 +: 32]=32'h0000_3C06;
        base_tx=transactions;
        issue_sized(3'd4, 1'b1, 2'd1, 8'hff, addr, bytes(8'h10));
        await_rsp(got, err, tag);
        check_tx(transactions-base_tx, 2, "storeb con un solape");
        check_eq(mem[960], {72'd0, 8'h17, 8'h16, 8'h15, 8'h13, 8'h12, 8'h14, 8'h10},
            "storeb solape: memoria");

        // ---- 15. STORE de palabras y de medias palabras parciales ----
        // Palabra entera: dos lanes en la misma palabra siguen solapando (2
        // transacciones, gana la mayor). Medias palabras de lanes alternas
        // (mascara 0x55): las cuatro en dos palabras, una transaccion.
        mem[976]=128'd0;
        addr=0; addr[1*32 +: 32]=32'h0000_3D00; addr[6*32 +: 32]=32'h0000_3D00;
        data=0; data[1*32 +: 32]=32'h1111_1111; data[6*32 +: 32]=32'h6666_6666;
        base_tx=transactions;
        issue_sized(3'd5, 1'b1, 2'd0, 8'b0100_0010, addr, data);
        await_rsp(got, err, tag);
        check_tx(transactions-base_tx, 2, "store palabra misma palabra");
        check_eq(mem[976], {96'd0,32'h6666_6666}, "store palabra: lane mayor");
        mem[992]=128'd0;
        base_tx=transactions;
        issue_sized(3'd6, 1'b1, 2'd2, 8'h55, strided(32'h0000_3E00, 2), halves(16'hC000));
        await_rsp(got, err, tag);
        check_tx(transactions-base_tx, 1, "storeh lanes alternas");
        check_eq(mem[992], {64'd0,16'h0000,16'hC006,16'h0000,16'hC004,16'h0000,16'hC002,16'h0000,16'hC000},
            "storeh alternas: memoria");

        // ---- 16. LOADH de 8 medias palabras seguidas: sin cambios ----
        base_tx=transactions;
        req_signed=1'b0;
        issue_sized(3'd7, 1'b0, 2'd2, 8'hff, strided(32'h0000_3800, 2), 256'd0);
        await_rsp(got, err, tag);
        check_tx(transactions-base_tx, 1, "loadh 8 px");
        for(j=0;j<8;j=j+1)
            check_eq(got[j*32 +: 32], 32'h0000_A100+j, "loadh 8 px: dato");

        repeat(20) @(posedge clk);
        if(errors==0) $display("gpu_lsu2_tb: TODAS LAS PRUEBAS PASAN");
        else $fatal(1,"gpu_lsu2_tb: %0d FALLOS", errors);
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1,"FAIL: timeout");
    end
endmodule
`default_nettype wire
