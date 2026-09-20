`default_nettype none
// Sistema GPU sobre el camino de memoria de 128 bits.
//
//   gpu_sm ──┬── gpu_lsu2             ── p0 ─┐
//            └── gpu_imem_buffer      ── p1 ─┼── memory_fabric_4 ── sdram_controller_128
//   host ─────── gpu_aux_adapter_128  ── p3 ─┘   (p2 libre para video)
//
// Respecto a gpu_system.v (la version BL1) cambian tres cosas: la LSU coalesce
// y habla de 128 bits; el fetch pasa por un bufer de 4 lineas de 16 bytes; y
// fetch y host ya no comparten un canal unico con arbitraje casero -- cada uno
// tiene su puerto y el arbitraje lo hace el fabric. Todo lo demas (el MMIO, la
// maquina del host) es identico a proposito, para que la comparacion de ciclos
// contra la base mida el camino de memoria y no otra cosa.
module gpu_system_bl8 #(parameter SIMT_DEPTH=8, SIMT_REGION_DEPTH=SIMT_DEPTH, SIMT_PATH_DEPTH=8,
    // Tamano del bufer de instrucciones, en lineas de 16 bytes.
    // INDEX_BITS tiene que ser $clog2(LINES).
    //
    // 16 lineas = 256 bytes, y no las 4 de 21. Medido con examples/plasma.asm,
    // cuyo bucle ocupa ~160 bytes y por tanto NO cabe en 64:
    //
    //    4 lineas: 4 480 403 ciclos/frame, 188 778 fallos (29%)
    //   16 lineas: 3 320 606 ciclos/frame,      14 fallos (0%)
    //
    // -26% de tiempo por 2048 biestables en vez de 512, o sea el 2,4% del
    // presupuesto de FF de esta FPGA. No hay razon para dejarlo en 4.
    parameter integer IMEM_LINES=16, IMEM_INDEX_BITS=4) (
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
    input init_done,

    // Puerto 2 del fabric, expuesto para un cliente de video. Va hacia fuera y
    // no atado aqui dentro para que enchufar un scanout no obligue a tocar este
    // fichero; `top_bl8` lo ata a cero mientras no haya video.
    input  wire         p2_req_valid,
    output wire         p2_req_ready,
    input  wire         p2_req_write,
    input  wire [31:0]  p2_req_addr,
    input  wire [127:0] p2_req_wdata,
    input  wire [15:0]  p2_req_wmask,
    input  wire         p2_urgent,
    output wire         p2_rsp_valid,
    input  wire         p2_rsp_ready,
    output wire [127:0] p2_rsp_rdata,
    output wire         p2_rsp_error,

    // Control de video. El bloque de video en si vive en top_bl8 (igual que en
    // 21): aqui solo estan sus registros, porque cuelgan de la ventana MMIO.
    output wire [1:0]  video_mode,
    output wire [23:0] video_fb_base,
    output wire        video_underflow_clear,
    input  wire        video_underflow,
    input  wire        video_frame_pulse,

    output mem_req_valid, mem_req_write,
    output [23:0] mem_req_addr,
    output [127:0] mem_req_wdata,
    output [15:0] mem_req_wmask,
    input mem_req_ready, mem_done,
    input [127:0] mem_rdata
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
    wire [7:0] sm_retired_lanes;
    reg [1:0] host_state;
    reg [31:0] address;
    reg [7:0] write_data;
    reg writing;
    reg [31:0] write_word;
    reg writing_word;
    // Dos paginas de 4 KiB, no una. La primera (0x80000000) es de perifericos
    // compartidos con la CPU -aqui video y contadores-; la segunda
    // (0x80001000) es control exclusivo de la GPU. Cuesta un bit mas en este
    // comparador de prefijo, y es lo que permite que el reparto siga valiendo
    // el dia que CPU y GPU compartan bitstream. Ver docs/resumen-prototipos.md.
    //
    // La LSU solo deja pasar la primera pagina (`sel_addr[31:12]==20'h80000` en
    // gpu_lsu2.v), asi que la GPU alcanza el video y NO alcanza la
    // configuracion de warps. Antes eso habia que razonarlo mirando regiones;
    // ahora sale del reparto de paginas.
    // MMIO v2 (1.isa/mmio.md §2). Bloques de 64 KiB alineados: el bloque es
    // address[31:16] y el offset dentro de el, address[15:0].
    //
    //   0x8000_xxxx  SYSTEM     identificacion (§5)
    //   0x8020_xxxx  VIDEO      (§9) -- solo esta carpeta, de las cuatro GPU
    //   0x8201_xxxx  GPU WARPS  descriptores (§14.2)
    //   0x8202_xxxx  GPU SIMT   depuracion (§14.3)
    //   0x8203_xxxx  GPU PERF   contadores (§14.4)
    //
    // GPU CORE (0x8200_0000, §14.1) NO se implementa: arranque y parada van
    // por el protocolo del monitor. Contesta error, como pide §4.3.
    wire mmio=address[31];
    wire [15:0] block=address[31:16];
    wire sel_system=block==16'h8000;
    wire sel_warps =block==16'h8201;
    wire sel_simt  =block==16'h8202;
    // Con el nucleo EN MARCHA el host puede LEER el MMIO, no la RAM ni escribir
    // nada. Los registros son registros y leerlos no molesta a nadie; la RAM
    // esta detras del camino que la GPU esta usando, y escribir VIDEO_CTRL o
    // FB_FRONT mientras el kernel los toca seria una carrera con el programa.
    //
    // Hace falta de verdad y no por comodidad: parar la GPU NO congela
    // `frame_count`, porque el scanout cuelga de `reset` y no de `core_reset`.
    // Sin esto se juntaba lo peor de las dos cosas -- solo se podia leer parada,
    // y estar parada no detenia el contador.
    //
    // Se decide sobre `host_address`, la direccion SIN latear: en este punto
    // `address` es todavia la de la transaccion anterior.
    wire host_mmio=host_address[31];
    wire host_permitted=halted || (host_read_enable && !host_write_enable && host_mmio);
    // Configuracion de warps: 8 descriptores de 16 B en 0x80001000-0x8000107F.
    wire cfg_region=sel_warps && address[15:7]==0;
    wire [3:0] byte_strobe=writing_word ? 4'b1111 : (4'b0001 << address[1:0]);
    wire [31:0] expanded_data=writing_word ? write_word : {4{write_data}};
    assign cfg_write=host_state==1 && mmio && cfg_region && writing && halted;
    wire aux_valid,aux_ready,aux_rsp_valid,aux_rsp_ready,aux_error;
    wire [31:0] aux_address,aux_write_data,aux_read_data;
    wire [3:0] aux_strobe;
    // A diferencia de la version BL1, fetch y host YA NO comparten puerto: cada
    // uno tiene el suyo en el fabric. El mux de aux_* se queda solo con el host.
    assign aux_valid=host_state==1 && !mmio;
    assign aux_address={address[31:2],2'b0};
    assign aux_write_data=expanded_data;
    assign aux_strobe=writing ? byte_strobe : 4'b0;
    assign aux_rsp_ready=host_state==2;
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
        .lsu_rsp_data(lsu_rsp_data),.lsu_rsp_error(lsu_rsp_error),.lsu_occupied(occupied),
        .retired_lanes(sm_retired_lanes)
    );

    // Camino MMIO de la GPU. El bloque que lo sirve esta mas abajo, junto a los
    // registros; aqui solo las senales, que la LSU necesita antes.
    wire gm_valid,gm_ready,gm_write,gm_rsp_valid,gm_rsp_ready,gm_rsp_error;
    wire [31:0] gm_addr,gm_wdata,gm_rsp_rdata;

    // Puerto 0 del fabric: la LSU vectorial.
    wire p0_valid,p0_ready,p0_write,p0_rsp_valid,p0_rsp_ready,p0_rsp_error;
    wire [31:0] p0_addr;
    wire [127:0] p0_wdata,p0_rsp_rdata;
    wire [15:0] p0_wmask;

    gpu_lsu2 lsu (
        .clk(clk),.reset(core_reset),.req_valid(lsu_valid),.req_ready(lsu_ready),
        .req_tag(lsu_tag),.req_mask(lsu_mask),.req_write(lsu_write),
        .req_address(lsu_address),.req_data(lsu_data),.rsp_valid(lsu_rsp_valid),
        .rsp_ready(lsu_rsp_ready),.rsp_tag(lsu_rsp_tag),.rsp_data(lsu_rsp_data),
        .rsp_error(lsu_rsp_error),.occupied(occupied),
        .mem_req_valid(p0_valid),.mem_req_ready(p0_ready),.mem_req_write(p0_write),
        .mem_req_addr(p0_addr),.mem_req_wdata(p0_wdata),.mem_req_wmask(p0_wmask),
        .mem_rsp_valid(p0_rsp_valid),.mem_rsp_ready(p0_rsp_ready),
        .mem_rsp_rdata(p0_rsp_rdata),.mem_rsp_error(p0_rsp_error),
        .mmio_req_valid(gm_valid),.mmio_req_ready(gm_ready),
        .mmio_req_write(gm_write),.mmio_req_addr(gm_addr),
        .mmio_req_wdata(gm_wdata),
        .mmio_rsp_valid(gm_rsp_valid),.mmio_rsp_ready(gm_rsp_ready),
        .mmio_rsp_rdata(gm_rsp_rdata),.mmio_rsp_error(gm_rsp_error)
    );

    // Puerto 1: fetch de instrucciones, con bufer de 4 lineas de 16 bytes.
    // Aqui esta el trafico: medido sobre los 32 casos diferenciales, el fetch
    // mueve ~400 veces mas transacciones que la LSU vectorial. Sin bufer, pasar
    // el fetch de BL1 a BL8 es una REGRESION (ver lsu-v2.md).
    wire p1_valid,p1_ready,p1_write,p1_rsp_valid,p1_rsp_ready,p1_rsp_error;
    wire [31:0] p1_addr;
    wire [127:0] p1_wdata,p1_rsp_rdata;
    wire [15:0] p1_wmask;
    wire [31:0] imem_hits,imem_misses;

    gpu_imem_buffer #(.LINES(IMEM_LINES),.INDEX_BITS(IMEM_INDEX_BITS)) ibuf (
        .clk(clk),.reset(core_reset),.init_done(init_done),.halted(halted),
        .imem_valid(fetch_valid),.imem_ready(fetch_ready),.imem_address(fetch_address),
        .imem_rsp_valid(fetch_rsp_valid),.imem_rsp_ready(fetch_rsp_ready),
        .imem_data(fetch_data),.imem_error(fetch_error),
        .req_valid(p1_valid),.req_ready(p1_ready),.req_write(p1_write),
        .req_addr(p1_addr),.req_wdata(p1_wdata),.req_wmask(p1_wmask),
        .rsp_valid(p1_rsp_valid),.rsp_ready(p1_rsp_ready),
        .rsp_rdata(p1_rsp_rdata),.rsp_error(p1_rsp_error),
        .hit_count(imem_hits),.miss_count(imem_misses)
    );

    // Puerto 3: host/monitor, byte a byte, solo cuando la GPU esta parada.
    wire p3_valid,p3_ready,p3_write,p3_rsp_valid,p3_rsp_ready,p3_rsp_error;
    wire [31:0] p3_addr;
    wire [127:0] p3_wdata,p3_rsp_rdata;
    wire [15:0] p3_wmask;

    gpu_aux_adapter_128 aux (
        .clk(clk),.reset(core_reset),.init_done(init_done),
        .aux_valid(aux_valid),.aux_ready(aux_ready),.aux_address(aux_address),
        .aux_write_data(aux_write_data),.aux_strobe(aux_strobe),
        .aux_rsp_valid(aux_rsp_valid),.aux_rsp_ready(aux_rsp_ready),
        .aux_read_data(aux_read_data),.aux_error(aux_error),
        .req_valid(p3_valid),.req_ready(p3_ready),.req_write(p3_write),
        .req_addr(p3_addr),.req_wdata(p3_wdata),.req_wmask(p3_wmask),
        .rsp_valid(p3_rsp_valid),.rsp_ready(p3_rsp_ready),
        .rsp_rdata(p3_rsp_rdata),.rsp_error(p3_rsp_error)
    );

    memory_fabric_4 fabric (
        .clk(clk),.reset(core_reset),// busy no se observa desde aqui.
        .busy(),
        .p0_req_valid(p0_valid),.p0_req_ready(p0_ready),.p0_req_write(p0_write),
        .p0_req_addr(p0_addr),.p0_req_wdata(p0_wdata),.p0_req_wmask(p0_wmask),
        .p0_rsp_valid(p0_rsp_valid),.p0_rsp_ready(p0_rsp_ready),
        .p0_rsp_rdata(p0_rsp_rdata),.p0_rsp_error(p0_rsp_error),
        .p1_req_valid(p1_valid),.p1_req_ready(p1_ready),.p1_req_write(p1_write),
        .p1_req_addr(p1_addr),.p1_req_wdata(p1_wdata),.p1_req_wmask(p1_wmask),
        .p1_rsp_valid(p1_rsp_valid),.p1_rsp_ready(p1_rsp_ready),
        .p1_rsp_rdata(p1_rsp_rdata),.p1_rsp_error(p1_rsp_error),
        .p2_req_valid(p2_req_valid),.p2_req_ready(p2_req_ready),
        .p2_req_write(p2_req_write),.p2_req_addr(p2_req_addr),
        .p2_req_wdata(p2_req_wdata),.p2_req_wmask(p2_req_wmask),
        .p2_urgent(p2_urgent),
        .p2_rsp_valid(p2_rsp_valid),.p2_rsp_ready(p2_rsp_ready),
        .p2_rsp_rdata(p2_rsp_rdata),.p2_rsp_error(p2_rsp_error),
        .p3_req_valid(p3_valid),.p3_req_ready(p3_ready),.p3_req_write(p3_write),
        .p3_req_addr(p3_addr),.p3_req_wdata(p3_wdata),.p3_req_wmask(p3_wmask),
        .p3_rsp_valid(p3_rsp_valid),.p3_rsp_ready(p3_rsp_ready),
        .p3_rsp_rdata(p3_rsp_rdata),.p3_rsp_error(p3_rsp_error),
        .sdram_req_valid(mem_req_valid),.sdram_req_ready(mem_req_ready),
        .sdram_req_write(mem_req_write),.sdram_req_addr(mem_req_addr),
        .sdram_req_wdata(mem_req_wdata),.sdram_req_wmask(mem_req_wmask),
        .sdram_done(mem_done),.sdram_rdata(mem_rdata)
    );

    // Bloque de video en 0x80000000-0x8000003F: la MISMA direccion y los mismos
    // offsets que en 16, 18, 19 y 21. Lo portable entre cores ya no es solo la
    // semantica, tambien la direccion.
    // ===================================================================
    // Ventana MMIO, compartida entre el host y la GPU
    //
    // El host solo accede con la GPU parada y la GPU solo cuando corre, asi
    // que no compiten de verdad: basta con multiplexar la direccion, y la GPU
    // gana el mux en su ciclo de aceptacion.
    //
    // La GPU NO llega a la region de configuracion de warps: que un warp
    // reconfigure los warps es justo el tipo de cosa que no se quiere poder
    // hacer por accidente. Solo ve video (0x000) y contadores (0x300), y los
    // contadores solo de lectura.
    // ===================================================================
    reg gm_busy;
    reg [31:0] gm_rd;
    reg gm_err;
    wire gm_accept=gm_valid && !gm_busy;
    assign gm_ready=!gm_busy;
    assign gm_rsp_valid=gm_busy;
    assign gm_rsp_rdata=gm_rd;
    assign gm_rsp_error=gm_err;

    wire [31:0] mmio_addr_mux  = gm_accept ? gm_addr  : address;
    wire [31:0] mmio_wdata_mux = gm_accept ? gm_wdata : expanded_data;
    wire [3:0]  mmio_strobe_mux= gm_accept ? 4'hf     : byte_strobe;

    // Ambas en la PRIMERA pagina. El mux sirve al host (que puede direccionar
    // las dos paginas) y a la GPU (que solo llega a la primera), asi que la
    // condicion de pagina se comprueba sobre la direccion ya multiplexada.
    // VIDEO y PERF los alcanza TAMBIEN el maestro GPU (§4.2), no solo el host,
    // asi que se deciden sobre la direccion muxada y no sobre `address`. Es la
    // diferencia que hace que estas dos lineas no se puedan copiar de la 17:
    // alli no hay maestro GPU con acceso a MMIO porque no hay dispositivos.
    wire video_region=mmio_addr_mux[31:16]==16'h8020;
    wire perf_region =mmio_addr_mux[31:16]==16'h8203;
    wire [31:0] video_read_data, perf_read_data;
    wire video_bad, perf_bad;
    wire video_write=gm_accept ? (gm_write && video_region)
                               : (host_state==1 && mmio && video_region && writing && halted);

    // OJO: `reset` y NO `core_reset`. El video es un periferico, no parte del
    // nucleo: `gpu_reset` lo lanza el monitor antes de cargar cada programa, y
    // si arrastrase los registros de video, la configuracion de pantalla se
    // perderia en cada carga y nunca se podria dejar el scanout encendido.
    gpu_video_regs vregs (
        .clk(clk),.reset(reset),
        .sel(video_region),.word(mmio_addr_mux[5:2]),.write(video_write),
        .write_data(mmio_wdata_mux),.write_strobe(mmio_strobe_mux),
        .read_data(video_read_data),.bad(video_bad),
        .underflow(video_underflow),.frame_pulse(video_frame_pulse),
        // VIDEO_TX se ha mudado de `perf` a aqui (§9.7), con su `running`.
        .video_tx(p2_req_valid && p2_req_ready),.running(!halted),
        .video_mode(video_mode),.fb_base(video_fb_base),
        .underflow_clear(video_underflow_clear));

    gpu_perf_counters perf (
        // `core_reset`, NO `reset`, y es un cambio de v2 con motivo.
        //
        // En v1 el contador global de retiros que leia el host estaba en el
        // bloque de depuracion (+0x108) y era el del SM, que cuelga de
        // `core_reset`: un `reset` del monitor lo ponia a cero y cada caso de
        // prueba empezaba a contar de nuevo. En v2 ese contador es de GPU
        // PERFORMANCE (§14.4) y lo sirve ESTE modulo, que colgaba de `reset`
        // y por tanto acumulaba entre casos.
        //
        // Se vio en placa: `instructions_executed` daba 20.864.707 donde el
        // caso esperaba 22. No es que el contador estuviera mal, es que era
        // otro contador. Mientras `PERF_CTRL` no exista --y no existe, ver
        // TODO.md 2.4-- el unico modo de ponerlos a cero es el reset, asi que
        // tienen que compartir dominio con el nucleo que miden.
        .clk(clk),.reset(core_reset),
        // Solo se cuenta mientras la GPU corre: si no, la medida desde el host
        // incluye el ir y venir por serie y el sondeo de "¿ha parado ya?".
        .running(!halted),
        .sel(perf_region),.word(mmio_addr_mux[5:2]),
        .read_data(perf_read_data),.bad(perf_bad),
        .retired(instruction_retired),.retired_lanes(sm_retired_lanes),
        .imem_hits(imem_hits),.imem_misses(imem_misses),
        .lsu_tx(p0_valid && p0_ready),
        .stall_mem(lsu_valid && !lsu_ready));

    always @(posedge clk) begin
        if(core_reset) begin gm_busy<=1'b0; gm_rd<=32'd0; gm_err<=1'b0; end
        else if(gm_accept) begin
            gm_rd<=video_region ? video_read_data :
                   perf_region  ? perf_read_data  : 32'd0;
            // Escribir un contador, o tocar cualquier cosa fuera de los dos
            // bloques permitidos, es fault para la GPU.
            gm_err<=!((video_region && !video_bad) ||
                      (perf_region && !perf_bad && !gm_write));
            gm_busy<=1'b1;
        end else if(gm_busy && gm_rsp_ready) gm_busy<=1'b0;
    end

    wire [31:0] sysid_data;
    // Bloque SYSTEM de v2: siete palabras, en 0x80000000. `DEVICES` (§5.4)
    // declara SYSTEM, SDRAM, VIDEO y GPU: esta es la unica de las cuatro GPU
    // con video, y por eso es la unica que enciende el bit 5.
    // La identidad NO se escribe aqui: sale de `sysid_params.vh`, generado por
    // `tools/generate-sysid`. OJO: este fichero y `gpu_system.v` comparten
    // carpeta, asi que los dos leen el MISMO `DEVICES` -- el de la carpeta, que
    // declara VIDEO porque el bitstream de `default` lo tiene. El entorno
    // `base-bl1`, que monta el otro sistema, declara de mas por eso; es el
    // mismo reparto que ya tienen las ventanas del monitor y por la misma
    // razon: la identidad es del PROTOTIPO, no del entorno.
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
        else if(video_region) begin
            mmio_data=video_read_data; mmio_bad=video_bad;
        end else if(perf_region) begin
            mmio_data=perf_read_data; mmio_bad=perf_bad || writing;
        end else if(sel_system) begin
            // Solo lectura, y solo las siete palabras que existen.
            if(address[15:5]==0) begin
                mmio_data=sysid_data; mmio_bad=writing || address[4:2]==3'd7;
            end else mmio_bad=1;
        end else if(sel_simt) case(address[15:2])
            // §14.3. OJO: FIRST_ERROR y los dos de abajo BAJAN cuatro bytes
            // respecto de v1, porque el contador global de retiros se va a
            // PERF y deja de estar intercalado en +0x08. Aqui PERF si existe
            // de verdad, asi que el contador cambia de bloque, no de nombre.
            14'h0000: mmio_data={24'b0,2'b0,debug_warp,debug_lane};
            14'h0001: begin mmio_data={24'b0,occupied}; mmio_bad=writing; end
            14'h0002: begin mmio_data={16'b0,error_code,1'b0,error_lane_valid,error_warp,error_lane}; mmio_bad=writing; end
            14'h0003: begin mmio_data=error_pc; mmio_bad=writing; end
            14'h0004: begin mmio_data=debug_warp_retired_count; mmio_bad=writing; end
            default: mmio_bad=1;
        endcase
        else mmio_bad=1;   // bloque ausente (GPU CORE, SERIAL...)
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
                // `!gm_accept`: el mux de mas arriba da el bloque MMIO a la GPU
                // cuando ella lo pide, y `mmio_data` sale de ahi. Con el nucleo
                // en marcha, latear en un ciclo que gana la GPU devolveria el
                // registro que pidio ELLA en vez del pedido por el host, sin
                // error ni senal: el host solo esperaba un ciclo de mas. No hay
                // inanicion porque tras aceptar, `gm_busy` baja `gm_accept`
                // hasta que se consume la respuesta.
                if(mmio) begin
                    if(!gm_accept) begin
                        host_read_data<=mmio_data[address[1:0]*8 +: 8]; host_read_word<=mmio_data;
                        host_error<=mmio_bad; host_ready<=1; host_state<=0;
                        // CONTEXT (§14.3 +0x00) es el unico registro de GPU que se
                    // escribe. En v1 estaba en 0x80000100; ahora es el offset
                    // cero del bloque SIMT.
                    if(writing && sel_simt && address[15:0]==16'h0000) begin
                            debug_lane<=expanded_data[2:0]; debug_warp<=expanded_data[5:3];
                        end
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
