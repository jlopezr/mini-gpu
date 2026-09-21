`default_nettype none
// Identidad del prototipo (MMIO v2 §5). GENERADO por `tools/generate-sysid`
// desde el RTL de esta carpeta; se resuelve dentro de ella, que es lo que
// deja este fichero identico entre prototipos.
`include "sysid_params.vh"
module gpu_system #(parameter SIMT_DEPTH=8, SIMT_REGION_DEPTH=SIMT_DEPTH, SIMT_PATH_DEPTH=8) (
    input clk, reset, gpu_reset,
    input run_request, halt_request, step_request,
    output halted, error,
    output [7:0] error_code,
    output instruction_retired,
    input [31:0] host_address,
    input [7:0] host_write_data,
    // WRITE_WORD del monitor. El puerto auxiliar ya era de 32 bits con strobe
    // por byte, asi que una palabra es el mismo acceso con las cuatro
    // habilitaciones puestas: ni una rafaga extra ni un estado nuevo.
    input [31:0] host_write_word,
    input host_write_word_enable,
    input host_write_enable, host_read_enable,
    output reg [7:0] host_read_data,
    // La MISMA palabra sin trocear, para READ_WORD. Ya se calculaba entera y
    // se tiraban tres bytes; sacarla aparte la hace atomica por construccion
    // sin tocar el camino de byte, que usan dieciocho bancos.
    output reg [31:0] host_read_word,
    output reg host_ready, host_error,
    input [4:0] debug_register,
    output [31:0] debug_data, debug_pc,
    input init_done, mem_req_ready, mem_done,
    input [15:0] mem_rdata,
    output mem_req_valid, mem_req_write,
    output [23:0] mem_req_addr,
    output [15:0] mem_req_wdata,
    output [1:0] mem_req_wmask
);
    wire core_reset=reset || gpu_reset;
    reg [2:0] debug_warp, debug_lane;
    wire [2:0] error_warp,error_lane;
    wire error_lane_valid;
    wire [31:0] error_pc,retired_count,debug_warp_retired_count;
    wire [31:0] cfg_read_data;
    wire cfg_write;
    wire fetch_valid,fetch_ready,fetch_rsp_valid,fetch_rsp_ready,fetch_error;
    wire [31:0] fetch_address,fetch_data;
    wire lsu_valid,lsu_ready,lsu_write,lsu_rsp_valid,lsu_rsp_ready;
    wire [2:0] lsu_tag,lsu_rsp_tag;
    wire [7:0] lsu_mask,lsu_rsp_error,occupied;
    wire [255:0] lsu_address,lsu_data,lsu_rsp_data;
    // Capture the byte monitor's single-cycle request. It remains stable until
    // the backend responds; host ownership is granted only after LSU drains.
    reg [1:0] host_state;
    reg [31:0] address;
    reg [7:0] write_data;
    reg writing;
    reg [31:0] write_word;
    reg writing_word;
    // MMIO v2 (1.isa/mmio.md §2). Se acabaron las dos paginas de 4 KiB: cada
    // bloque son 64 KiB alineados, asi que el bloque es address[31:16] y el
    // offset dentro de el es address[15:0]. No hay ranuras ni paginas.
    //
    //   0x8000_xxxx  SYSTEM        identificacion (§5)
    //   0x8201_xxxx  GPU WARPS     descriptores (§14.2)
    //   0x8202_xxxx  GPU SIMT      depuracion (§14.3)
    //   0x8203_xxxx  GPU PERF      contadores (§14.4)
    //
    // GPU CORE (0x8200_0000, §14.1) NO se implementa aqui, y es deliberado:
    // arranque y parada de la GPU van por el protocolo del monitor, no por
    // MMIO, igual que CPU CORE (§13.1) tampoco existe en la familia CPU --lo
    // dice la cabecera de `sysid.v`--. El bloque contesta error, que es lo que
    // §4.3 pide de un bloque ausente, y no cero.
    wire mmio=address[31];
    wire [15:0] block=address[31:16];
    wire sel_system=block==16'h8000;
    wire sel_warps =block==16'h8201;
    wire sel_simt  =block==16'h8202;
    wire sel_perf  =block==16'h8203;
    // Con el nucleo EN MARCHA el host puede LEER el MMIO, no la RAM ni escribir
    // nada. Los registros son registros y leerlos no molesta a nadie; la RAM
    // esta detras del camino que la GPU esta usando, y escribir VIDEO_CTRL o
    // FB_FRONT mientras el kernel los toca seria una carrera con el programa.
    //
    // Hace falta de verdad y no por comodidad: parar la GPU NO congela
    // `frame_count`, porque el scanout cuelga de `reset` y no de `core_reset`.
    //
    // Se decide sobre `host_address`, la direccion SIN latear: en este punto
    // `address` es todavia la de la transaccion anterior.
    wire host_mmio=host_address[31];
    wire host_permitted=halted || (host_read_enable && !host_write_enable && host_mmio);
    // Descriptores de warp: 8 de 16 B, ahora en 0x82010000-0x8201007F. El
    // reparto DENTRO del descriptor no cambia --PC/ACTIVE/GROUP/SIMT, que es
    // lo que §14.2 congela-- asi que `cfg_word` sigue siendo address[6:2] y
    // `gpu_sm.v` no se toca. Lo unico que se mueve es el bloque.
    //
    // El bloque de v2 da sitio a 32 warps; aqui hay 8, y el resto del bloque
    // contesta error en vez de reflejar los ocho primeros. Un alias silencioso
    // es peor que un error: el dia que haya 16 warps, el programa que leia el
    // alias seguiria compilando y leeria otro warp.
    wire cfg_region=sel_warps && address[15:7]==0;
    wire [3:0] byte_strobe=writing_word ? 4'b1111 : (4'b0001 << address[1:0]);
    wire [31:0] expanded_data=writing_word ? write_word : {4{write_data}};
    assign cfg_write=host_state==1 && mmio && cfg_region && writing && halted;
    wire aux_valid,aux_ready,aux_rsp_valid,aux_rsp_ready,aux_error;
    wire [31:0] aux_address,aux_write_data,aux_read_data;
    wire [3:0] aux_strobe;
    assign aux_valid=halted ? (host_state==1 && !mmio) : fetch_valid;
    assign aux_address=halted ? {address[31:2],2'b0} : fetch_address;
    assign aux_write_data=expanded_data;
    assign aux_strobe=halted && writing ? byte_strobe : 4'b0;
    assign aux_rsp_ready=halted ? host_state==2 : fetch_rsp_ready;
    assign fetch_ready=!halted && aux_ready;
    assign fetch_rsp_valid=!halted && aux_rsp_valid;
    assign fetch_data=aux_read_data;
    assign fetch_error=aux_error;
    // Do not launch while a host transaction owns the auxiliary port.
    wire host_idle=host_state==0 && !host_write_enable && !host_read_enable;
    gpu_sm #(.SIMT_DEPTH(SIMT_DEPTH), .SIMT_REGION_DEPTH(SIMT_REGION_DEPTH), .SIMT_PATH_DEPTH(SIMT_PATH_DEPTH)) sm (
        .clk(clk),.reset(core_reset),.run_request(run_request && host_idle),
        .halt_request(halt_request),.step_request(step_request && host_idle),
        .halted(halted),.error(error),.error_code(error_code),
        .error_warp(error_warp),.error_lane(error_lane),.error_lane_valid(error_lane_valid),
        .error_pc(error_pc),.instruction_retired(instruction_retired),.retired_count(retired_count),
        .debug_warp(debug_warp),.debug_lane(debug_lane),.debug_register(debug_register),
        .debug_data(debug_data),.debug_pc(debug_pc),
        .debug_warp_retired_count(debug_warp_retired_count),
        .cfg_write(cfg_write),.cfg_word(address[6:2]),.cfg_data(expanded_data),
        .cfg_strobe(byte_strobe),.cfg_read_data(cfg_read_data),
        .imem_valid(fetch_valid),.imem_ready(fetch_ready),.imem_address(fetch_address),
        .imem_rsp_valid(fetch_rsp_valid),.imem_rsp_ready(fetch_rsp_ready),
        .imem_data(fetch_data),.imem_error(fetch_error),
        .lsu_valid(lsu_valid),.lsu_ready(lsu_ready),.lsu_tag(lsu_tag),.lsu_mask(lsu_mask),
        .lsu_write(lsu_write),.lsu_address(lsu_address),.lsu_data(lsu_data),
        .lsu_rsp_valid(lsu_rsp_valid),.lsu_rsp_ready(lsu_rsp_ready),.lsu_rsp_tag(lsu_rsp_tag),
        .lsu_rsp_data(lsu_rsp_data),.lsu_rsp_error(lsu_rsp_error),.lsu_occupied(occupied)
    );
    gpu_lsu lsu (
        .clk(clk),.reset(core_reset),.req_valid(lsu_valid),.req_ready(lsu_ready),
        .req_tag(lsu_tag),.req_mask(lsu_mask),.req_write(lsu_write),
        .req_address(lsu_address),.req_data(lsu_data),.rsp_valid(lsu_rsp_valid),
        .rsp_ready(lsu_rsp_ready),.rsp_tag(lsu_rsp_tag),.rsp_data(lsu_rsp_data),
        .rsp_error(lsu_rsp_error),.occupied(occupied),
        .aux_valid(aux_valid),.aux_ready(aux_ready),.aux_address(aux_address),
        .aux_write_data(aux_write_data),.aux_strobe(aux_strobe),
        .aux_rsp_valid(aux_rsp_valid),.aux_rsp_ready(aux_rsp_ready),
        .aux_read_data(aux_read_data),.aux_error(aux_error),
        .init_done(init_done),.mem_req_valid(mem_req_valid),.mem_req_ready(mem_req_ready),
        .mem_req_write(mem_req_write),.mem_req_addr(mem_req_addr),
        .mem_req_wdata(mem_req_wdata),.mem_req_wmask(mem_req_wmask),
        .mem_done(mem_done),.mem_rdata(mem_rdata)
    );
    // Bloque SYSTEM de v2: siete palabras, en 0x80000000. `DEVICES` declara lo
    // que este prototipo tiene de verdad (§5.4): SYSTEM, SDRAM y GPU. No lleva
    // VIDEO ni SERIAL, y por eso esos bloques contestan error.
    wire [31:0] sysid_data;
    // La identidad NO se escribe aqui: sale de `sysid_params.vh`, que genera
    // `tools/generate-sysid` leyendo el RTL de esta carpeta. Lo pide §5.4 --«un
    // bitmap escrito a mano seria una tercera gemela»-- y ademas es lo que
    // permite que este fichero sea IDENTICO entre prototipos: el `include` se
    // resuelve en la carpeta, asi que el texto puede ser el mismo y los
    // numeros distintos.
    sysid #(.FOLDER(`SYSID_FOLDER),.ISA_PROFILE(`SYSID_ISA_PROFILE),
            .DEVICES(`SYSID_DEVICES),
            .MEM_BASE(`SYSID_MEM_BASE),.MEM_SIZE(`SYSID_MEM_SIZE),
            .MONITOR_VERSION(`SYSID_MONITOR_VERSION))
        sysid_i(.word(address[4:2]),.read_data(sysid_data));
    reg [31:0] mmio_data;
    reg mmio_bad;
    always @* begin
        mmio_data=0; mmio_bad=0;
        if(cfg_region) begin
            mmio_data=cfg_read_data;
            if(writing && address[3:2]==3) mmio_bad=1;
        end else if(sel_warps) mmio_bad=1;   // resto del bloque WARPS: no hay
        else if(sel_system) begin
            // Solo lectura, y solo las siete palabras que existen. Escribir es
            // `bad`, como el resto de registros de estado.
            if(address[15:5]==0) begin
                mmio_data=sysid_data; mmio_bad=writing || address[4:2]==3'd7;
            end else mmio_bad=1;
        end else if(sel_simt) case(address[15:2])
            // §14.3. OJO: FIRST_ERROR y los dos de abajo BAJAN cuatro bytes
            // respecto de v1, porque el contador global de retiros se va a
            // PERF y deja de estar intercalado en +0x08. Mover una base da
            // error; mover un offset hace que conteste el registro de al lado,
            // asi que este es el sitio donde un despiste no se nota.
            14'h0000: mmio_data={24'b0,2'b0,debug_warp,debug_lane};
            14'h0001: begin mmio_data={24'b0,occupied}; mmio_bad=writing; end
            14'h0002: begin mmio_data={16'b0,error_code,1'b0,error_lane_valid,error_warp,error_lane}; mmio_bad=writing; end
            14'h0003: begin mmio_data=error_pc; mmio_bad=writing; end
            14'h0004: begin mmio_data=debug_warp_retired_count; mmio_bad=writing; end
            default: mmio_bad=1;
        endcase
        else if(sel_perf) case(address[15:2])
            // §14.4, ranura 1. Este prototipo no tiene contador de ciclos, asi
            // que la ranura 0 contesta error y no cero: un cero en CYCLES es
            // indistinguible de un contador parado, que es justo el fallo
            // silencioso que §4.3 quiere evitar.
            14'h0001: begin mmio_data=retired_count; mmio_bad=writing; end
            default: mmio_bad=1;
        endcase
        else mmio_bad=1;   // bloque ausente (GPU CORE, VIDEO, SERIAL...)
    end
    always @(posedge clk) begin
        host_ready<=0;
        if(core_reset) begin
            host_state<=0; address<=0; write_data<=0; writing<=0;
            write_word<=0; writing_word<=0;
            host_ready<=0; host_error<=0; host_read_data<=0; host_read_word<=0;
            debug_warp<=0; debug_lane<=0;
        end else case(host_state)
            0: if(host_write_enable || host_write_word_enable || host_read_enable) begin
                if(!host_permitted) begin host_ready<=1; host_error<=1; end
                else begin
                    address<=host_address; write_data<=host_write_data;
                    write_word<=host_write_word; writing_word<=host_write_word_enable;
                    writing<=host_write_enable || host_write_word_enable; host_state<=1;
                end
            end
            1: begin
                if(mmio) begin
                    host_read_data<=mmio_data[address[1:0]*8 +: 8]; host_read_word<=mmio_data;
                    host_error<=mmio_bad; host_ready<=1; host_state<=0;
                    // CONTEXT (§14.3 +0x00) es el unico registro de GPU que se
                    // escribe. En v1 estaba en 0x80000100; ahora es el offset
                    // cero del bloque SIMT.
                    if(writing && sel_simt && address[15:0]==16'h0000) begin
                        debug_lane<=expanded_data[2:0]; debug_warp<=expanded_data[5:3];
                    end
                end else if(aux_ready) host_state<=2;
            end
            2: if(aux_rsp_valid) begin
                host_read_data<=aux_read_data[address[1:0]*8 +: 8]; host_read_word<=aux_read_data;
                host_error<=aux_error; host_ready<=1; host_state<=0;
            end
        endcase
    end
endmodule
`default_nettype wire
