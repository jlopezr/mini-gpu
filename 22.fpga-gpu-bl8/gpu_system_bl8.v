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
    input host_write_enable, host_read_enable,
    output reg [7:0] host_read_data,
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
    wire mmio=address[31:12]==20'h80000;
    wire cfg_region=address[11:7]==0;
    wire [3:0] byte_strobe=4'b0001 << address[1:0];
    wire [31:0] expanded_data={4{write_data}};
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
        .clk(clk),.reset(core_reset),
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

    // Bloque de video en 0x80000200-0x8000023F. En 21 estos registros viven en
    // 0x80000000, pero ahi la GPU tiene la configuracion de warps: lo portable
    // entre cores es la semantica, no la direccion.
    // ===================================================================
    // Ventana MMIO, compartida entre el host y la GPU
    //
    // El host solo accede con la GPU parada y la GPU solo cuando corre, asi
    // que no compiten de verdad: basta con multiplexar la direccion, y la GPU
    // gana el mux en su ciclo de aceptacion.
    //
    // La GPU NO llega a la region de configuracion de warps: que un warp
    // reconfigure los warps es justo el tipo de cosa que no se quiere poder
    // hacer por accidente. Solo ve video (0x200) y contadores (0x300), y los
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

    wire video_region=mmio_addr_mux[11:6]==6'b001000;
    wire perf_region =mmio_addr_mux[11:6]==6'b001100;
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
        .video_mode(video_mode),.fb_base(video_fb_base),
        .underflow_clear(video_underflow_clear));

    gpu_perf_counters perf (
        .clk(clk),.reset(reset),
        // Solo se cuenta mientras la GPU corre: si no, la medida desde el host
        // incluye el ir y venir por serie y el sondeo de "¿ha parado ya?".
        .running(!halted),
        .sel(perf_region),.word(mmio_addr_mux[5:2]),
        .read_data(perf_read_data),.bad(perf_bad),
        .retired(instruction_retired),.retired_lanes(sm_retired_lanes),
        .imem_hits(imem_hits),.imem_misses(imem_misses),
        .lsu_tx(p0_valid && p0_ready),
        .video_tx(p2_req_valid && p2_req_ready),
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

    reg [31:0] mmio_data;
    reg mmio_bad;
    always @* begin
        mmio_data=0; mmio_bad=0;
        if(cfg_region) begin
            mmio_data=cfg_read_data;
            if(writing && address[3:2]==3) mmio_bad=1;
        end else if(video_region) begin
            mmio_data=video_read_data; mmio_bad=video_bad;
        end else if(perf_region) begin
            mmio_data=perf_read_data; mmio_bad=perf_bad || writing;
        end else case(address[11:2])
            10'h040: mmio_data={24'b0,2'b0,debug_warp,debug_lane};
            10'h041: begin mmio_data={24'b0,occupied}; mmio_bad=writing; end
            10'h042: begin mmio_data=retired_count; mmio_bad=writing; end
            10'h043: begin mmio_data={16'b0,error_code,1'b0,error_lane_valid,error_warp,error_lane}; mmio_bad=writing; end
            10'h044: begin mmio_data=error_pc; mmio_bad=writing; end
            10'h045: begin mmio_data=debug_warp_retired_count; mmio_bad=writing; end
            default: mmio_bad=1;
        endcase
    end
    always @(posedge clk) begin
        host_ready<=0;
        if(core_reset) begin
            host_state<=0; address<=0; write_data<=0; writing<=0;
            host_ready<=0; host_error<=0; host_read_data<=0;
            debug_warp<=0; debug_lane<=0;
        end else case(host_state)
            0: if(host_write_enable || host_read_enable) begin
                if(!halted) begin host_ready<=1; host_error<=1; end
                else begin
                    address<=host_address; write_data<=host_write_data;
                    writing<=host_write_enable; host_state<=1;
                end
            end
            1: begin
                if(mmio) begin
                    host_read_data<=mmio_data[address[1:0]*8 +: 8];
                    host_error<=mmio_bad; host_ready<=1; host_state<=0;
                    if(writing && address[11:0]==12'h100) begin
                        debug_lane<=write_data[2:0]; debug_warp<=write_data[5:3];
                    end
                end else if(aux_ready) host_state<=2;
            end
            2: if(aux_rsp_valid) begin
                host_read_data<=aux_read_data[address[1:0]*8 +: 8];
                host_error<=aux_error; host_ready<=1; host_state<=0;
            end
        endcase
    end
endmodule
`default_nettype wire
