`default_nettype none
// Sistema GPU de la 36: el nucleo de la 29 sin su fabric, sin video y con GPU CORE.
//
//   gpu_sm ──┬── gpu_lsu2        ── p0 ──> fuera (puerto 4 del fabric)
//            └── gpu_imem_buffer ── p1 ──> fuera (puerto 5 del fabric)
//   h_* ───── MMIO de la CPU (GPU CORE, WARPS, SIMT, PERF), ya en este dominio
//
// Respecto a gpu_system_bl8.v de la 29:
//
//  * NO tiene memory_fabric_4 ni gpu_aux_adapter_128. La LSU y el bufer de
//    instrucciones salen como dos puertos de memoria, y los arbitra el fabric de
//    seis puertos del top. El acceso del host a la RAM sobra: la CPU y el
//    monitor ya llegan a ella por sus propios puertos.
//  * NO tiene video. Hay un solo bloque VIDEO en el sistema, el de la CPU; el
//    puerto p2, `gpu_video_regs` y sus senales se han ido.
//  * La GPU NO es maestro de MMIO (de momento): un warp que toque cualquier
//    direccion de MMIO recibe error. La unica ruta de MMIO va de la CPU a este
//    modulo, por `h_*`.
//  * Nuevo: GPU CORE (0x8200_xxxx, mmio.md §14.1), con GPU_CONTROL, GPU_STATUS,
//    WARP_LIVE y WARP_DONE. Los comandos usan las mismas entradas que el
//    monitor usaba en la 29 (`run_request`, `halt_request`, `step_request`).
//
// LIMITACIONES DEL HITO 1, a quitar en el hito 2 (ver README.md):
//
//  * WARP_START da error. Se lanza con RUN, que reanuda lo que escribieron los
//    descriptores; `gpu_sm` pone `live = ACTIVE` al escribir el descriptor.
//  * Por eso WARP_LIVE ya refleja un warp configurado ANTES de RUN.
//  * RESET reinicia tambien los descriptores (el unico reset de `gpu_sm`). El
//    contrato dice que los conserva.
//
// Todas las lecturas y escrituras del host son de palabra de 32 bits. El host
// pone `h_valid` UN ciclo con `h_addr`, `h_wdata` y `h_write` validos, y recibe
// `h_done` UN ciclo cuando `h_rdata` y `h_error` ya valen.
module gpu_system #(parameter SIMT_DEPTH=8, SIMT_REGION_DEPTH=SIMT_DEPTH, SIMT_PATH_DEPTH=8,
    // 16 lineas de 16 bytes: ver la medida en gpu_system_bl8.v de la 29.
    parameter integer IMEM_LINES=16, IMEM_INDEX_BITS=4) (
    input wire clk, reset,
    input wire init_done,

    // MMIO de la CPU.
    input  wire        h_valid,
    input  wire        h_write,
    input  wire [31:0] h_addr,
    input  wire [31:0] h_wdata,
    output reg         h_done,
    output reg  [31:0] h_rdata,
    output reg         h_error,

    // Puerto de memoria 0: la LSU vectorial.
    output wire         p0_req_valid,
    input  wire         p0_req_ready,
    output wire         p0_req_write,
    output wire [31:0]  p0_req_addr,
    output wire [127:0] p0_req_wdata,
    output wire [15:0]  p0_req_wmask,
    input  wire         p0_rsp_valid,
    output wire         p0_rsp_ready,
    input  wire [127:0] p0_rsp_rdata,
    input  wire         p0_rsp_error,

    // Puerto de memoria 1: busqueda de instrucciones.
    output wire         p1_req_valid,
    input  wire         p1_req_ready,
    output wire         p1_req_write,
    output wire [31:0]  p1_req_addr,
    output wire [127:0] p1_req_wdata,
    output wire [15:0]  p1_req_wmask,
    input  wire         p1_rsp_valid,
    output wire         p1_rsp_ready,
    input  wire [127:0] p1_rsp_rdata,
    input  wire         p1_rsp_error,

    // Para el LED y la depuracion.
    output wire         gpu_halted,
    output wire         gpu_error
);
    // ------------------------------------------------------------------
    // Identidad de GPU CORE. Mismos valores que el modelo (32.cpu-gpu-func-sim).
    // ------------------------------------------------------------------
    localparam [31:0] GPU_ID_VALUE      = 32'd11;
    localparam [31:0] GPU_VERSION_VALUE = 32'd1;
    localparam [31:0] GPU_ISA_VALUE     = 32'h0000_000f;   // perfil de la 29
    localparam [31:0] GPU_FEATURES_VALUE= 32'd0;
    localparam [31:0] GPU_CAPS_VALUE    = 32'h0000_0808;   // 8 warps, 8 lanes

    // Comandos de GPU_CONTROL.
    localparam CTRL_RUN = 0, CTRL_HALT = 1, CTRL_RESUME = 2, CTRL_STEP = 3, CTRL_RESET = 4;

    reg run_request, halt_request, step_request, gpu_reset;
    wire core_reset = reset || gpu_reset;

    reg [2:0] debug_warp, debug_lane;
    wire [2:0] error_warp, error_lane;
    wire error_lane_valid;
    wire [31:0] error_pc, retired_count, debug_warp_retired_count;
    wire [7:0] error_code;
    wire [31:0] debug_data, debug_pc;
    wire [31:0] cfg_read_data;
    reg cfg_write;
    wire halted, sm_running, sm_error, instruction_retired, sm_no_warp_stall;
    wire [7:0] live_warps;
    // Warps con ACTIVE != 0 en su descriptor: los que RUN arranca y los unicos
    // que WARP_START acepta.
    wire [7:0] desc_enabled;
    // Lanzamiento hacia el SM (RUN, WARP_START): pulso de un ciclo.
    reg launch, launch_run, launch_all;
    reg [7:0] launch_mask;
    wire [7:0] sm_retired_lanes;
    assign gpu_halted = halted;
    assign gpu_error = sm_error;

    wire fetch_valid, fetch_ready, fetch_rsp_valid, fetch_rsp_ready, fetch_error;
    wire [31:0] fetch_address, fetch_data;
    wire lsu_valid, lsu_ready, lsu_write, lsu_signed, lsu_rsp_valid, lsu_rsp_ready;
    wire [1:0] lsu_size;
    wire [2:0] lsu_tag, lsu_rsp_tag;
    wire [7:0] lsu_mask, lsu_rsp_error, occupied;
    wire [255:0] lsu_address, lsu_data, lsu_rsp_data;

    // Cola elastica de una entrada entre el SM y la LSU. Registra el paquete
    // ancho despues de los ocho sumadores de direccion y antes de los arrays
    // internos de la LSU, para cortar esa frontera de routing. Puede consumir
    // y reemplazar la entrada en el mismo ciclo, por lo que conserva una
    // peticion por ciclo aunque anade un ciclo de latencia a cada operacion.
    reg lsu_req_valid_q, lsu_req_write_q, lsu_req_signed_q;
    reg [1:0] lsu_req_size_q;
    reg [2:0] lsu_req_tag_q;
    reg [7:0] lsu_req_mask_q;
    reg [255:0] lsu_req_address_q, lsu_req_data_q;
    wire lsu_core_ready;
    wire [7:0] lsu_core_occupied;

    assign lsu_ready = !lsu_req_valid_q || lsu_core_ready;
    assign occupied = lsu_core_occupied |
                      (lsu_req_valid_q ? (8'b1 << lsu_req_tag_q) : 8'b0);

    always @(posedge clk) begin
        if(core_reset) begin
            lsu_req_valid_q <= 1'b0;
            lsu_req_write_q <= 1'b0;
            lsu_req_signed_q <= 1'b0;
            lsu_req_size_q <= 2'b0;
            lsu_req_tag_q <= 3'b0;
            lsu_req_mask_q <= 8'b0;
            lsu_req_address_q <= 256'b0;
            lsu_req_data_q <= 256'b0;
        end else if(lsu_ready) begin
            lsu_req_valid_q <= lsu_valid;
            if(lsu_valid) begin
                lsu_req_write_q <= lsu_write;
                lsu_req_signed_q <= lsu_signed;
                lsu_req_size_q <= lsu_size;
                lsu_req_tag_q <= lsu_tag;
                lsu_req_mask_q <= lsu_mask;
                lsu_req_address_q <= lsu_address;
                lsu_req_data_q <= lsu_data;
            end
        end
    end

    // ------------------------------------------------------------------
    // Transaccion del host: se captura, se evalua con los registros ya
    // estables y se contesta con h_done.
    // ------------------------------------------------------------------
    reg        host_busy;
    reg        writing;
    reg [31:0] address, write_data;

    wire [15:0] block = address[31:16];
    wire sel_core  = block == 16'h8200;
    wire sel_warps = block == 16'h8201;
    wire sel_simt  = block == 16'h8202;
    wire sel_perf  = block == 16'h8203;

    // GPU WARPS (§14.2): ocho descriptores de 16 B en +0x000..+0x07F y los dos
    // arrays de ocho palabras, LOGICAL_WARP_ID en +0x200 y WARP_ARG en +0x280.
    wire cfg_desc = sel_warps && address[15:7] == 0;
    wire cfg_lid  = sel_warps && address[15:5] == 11'h010;
    wire cfg_arg  = sel_warps && address[15:5] == 11'h014;
    wire cfg_region = cfg_desc || cfg_lid || cfg_arg;
    wire [1:0] cfg_bank = {cfg_arg, cfg_lid};
    // El warp al que apunta el acceso: descriptor n en +16n, arrays en +4n.
    wire [2:0] cfg_warp = cfg_desc ? address[6:4] : address[4:2];
    wire cfg_warp_live = live_warps[cfg_warp];
    wire [3:0] byte_strobe = 4'b1111;

    // ------------------------------------------------------------------
    // GPU CORE
    // ------------------------------------------------------------------
    reg paused;                 // HALT pendiente de RESUME (GPU_STATUS.HALTED)
    reg [7:0] done_mask;        // WARP_DONE, pegajoso
    reg [7:0] live_prev;
    reg [3:0] live_count;
    integer k;
    always @* begin
        live_count = 4'd0;
        for (k = 0; k < 8; k = k + 1) live_count = live_count + live_warps[k];
    end

    // HALTED solo cuando el SM ya ha drenado: asi un RESUME o un STEP que la CPU
    // lance al verlo no se pierde (`gpu_sm` solo acepta `run_request` y
    // `step_request` con `halted`).
    wire paused_now = paused && halted;

    wire [31:0] core_status =
        {16'b0, 4'b0, live_count, 4'b0,
         sm_error,
         (live_warps == 8'b0),
         paused_now,
         (sm_running && !sm_error)};

    reg [31:0] core_data;
    reg        core_bad;
    always @* begin
        core_data = 32'd0;
        core_bad  = 1'b0;
        case (address[15:0])
            16'h0000: begin core_data = GPU_ID_VALUE;       core_bad = writing; end
            16'h0004: begin core_data = GPU_VERSION_VALUE;  core_bad = writing; end
            16'h0008: begin core_data = GPU_ISA_VALUE;      core_bad = writing; end
            16'h000c: begin core_data = GPU_FEATURES_VALUE; core_bad = writing; end
            16'h0010: begin core_data = GPU_CAPS_VALUE;     core_bad = writing; end
            16'h0014: begin core_data = core_status;        core_bad = writing; end
            16'h0018: core_data = 32'd0;                    // comandos: leen cero
            16'h001c: core_bad = !writing;                  // WARP_START: solo escritura
            16'h0020: begin core_data = {24'b0, live_warps}; core_bad = writing; end
            16'h0024: core_data = {24'b0, done_mask};
            default:  core_bad = 1'b1;
        endcase
    end

    // Resultado de ejecutar un comando de GPU_CONTROL: error de contrato.
    reg ctrl_bad;
    always @* begin
        ctrl_bad = 1'b0;
        if (write_data[31:5] != 0) ctrl_bad = 1'b1;                 // bits reservados
        else if ((write_data[4:0] & (write_data[4:0] - 5'd1)) != 0) ctrl_bad = 1'b1;   // varios a la vez
        // RUN (mmio.md §14.1, «Reglas de lanzamiento»): solo sin warps vivos y
        // con algun descriptor habilitado. No exige `halted`: justo despues de
        // que el ultimo warp acabe, el SM tarda unos ciclos en parar del todo.
        else if (write_data[CTRL_RUN] && (live_warps != 0 || sm_error || desc_enabled == 0)) ctrl_bad = 1'b1;
        // `gpu_sm` solo acepta estos pulsos con `halted`; si no, se perderian.
        else if (write_data[CTRL_RESUME] && (!paused_now || sm_error)) ctrl_bad = 1'b1;
        else if (write_data[CTRL_STEP] && !paused_now) ctrl_bad = 1'b1;
    end

    // WARP_START: todo o nada. Error si algun bit pedido es de un warp que no
    // existe, que ya esta vivo o cuyo descriptor tiene ACTIVE == 0, o si la GPU
    // esta en error. Pedir cero warps no hace nada y no es error.
    wire start_bad = (write_data[31:8] != 0) || sm_error ||
                     ((write_data[7:0] & (live_warps | ~desc_enabled)) != 0);

    // ------------------------------------------------------------------
    // GPU SIMT DEBUG (§14.3) y GPU PERFORMANCE (§14.4)
    // ------------------------------------------------------------------
    reg [31:0] simt_data;
    reg        simt_bad;
    always @* begin
        simt_data = 32'd0;
        simt_bad  = 1'b0;
        case (address[15:2])
            14'h0000: simt_data = {24'b0, 2'b0, debug_warp, debug_lane};
            14'h0001: begin simt_data = {24'b0, occupied}; simt_bad = writing; end
            14'h0002: begin simt_data = {16'b0, error_code, 1'b0, error_lane_valid, error_warp, error_lane}; simt_bad = writing; end
            14'h0003: begin simt_data = error_pc; simt_bad = writing; end
            14'h0004: begin simt_data = debug_warp_retired_count; simt_bad = writing; end
            default:  simt_bad = 1'b1;
        endcase
    end

    wire [31:0] perf_read_data;
    wire        perf_bad;
    wire [31:0] imem_hits, imem_misses;
    wire        p0_fire = p0_req_valid && p0_req_ready;

    reg [31:0] mmio_data;
    reg        mmio_bad;
    always @* begin
        mmio_data = 32'd0;
        mmio_bad  = 1'b0;
        if (sel_core) begin
            mmio_data = core_data;
            mmio_bad  = core_bad;
        end else if (cfg_region) begin
            mmio_data = cfg_read_data;
            // SIMT_STATE (+0xC de cada descriptor) es de solo lectura. Un
            // descriptor (y los dos arrays) se escribe mientras SU warp no este
            // vivo; los de otros warps no importan (mmio.md §14.1).
            if (writing && (cfg_warp_live || (cfg_desc && address[3:2] == 2'd3))) mmio_bad = 1'b1;
        end else if (sel_warps) begin
            mmio_bad = 1'b1;                   // resto del bloque: no hay nada
        end else if (sel_simt) begin
            mmio_data = simt_data;
            mmio_bad  = simt_bad;
        end else if (sel_perf) begin
            mmio_data = perf_read_data;
            mmio_bad  = perf_bad || writing;   // los contadores son de solo lectura
        end else begin
            mmio_bad = 1'b1;                   // lo que no es de la GPU
        end
    end

    // El comando se ejecuta en el mismo ciclo en que se contesta al host; las
    // peticiones al SM son pulsos de un ciclo registrados, que ven el ciclo
    // siguiente.
    wire cmd_write = host_busy && writing && sel_core && address[15:0] == 16'h0018 && !ctrl_bad;

    always @(posedge clk) begin
        h_done <= 1'b0;
        if (reset) begin
            host_busy <= 1'b0;
            writing <= 1'b0;
            address <= 32'd0;
            write_data <= 32'd0;
            h_rdata <= 32'd0;
            h_error <= 1'b0;
        end else if (!host_busy) begin
            if (h_valid) begin
                address <= h_addr;
                write_data <= h_wdata;
                writing <= h_write;
                host_busy <= 1'b1;
            end
        end else begin
            // Evaluacion: `address`, `writing` y `write_data` llevan un ciclo estables.
            host_busy <= 1'b0;
            h_done <= 1'b1;
            h_rdata <= mmio_data;
            h_error <= mmio_bad ||
                       (writing && sel_core && address[15:0] == 16'h0018 && ctrl_bad) ||
                       (writing && sel_core && address[15:0] == 16'h001c && start_bad);
        end
    end

    // Pulsos hacia el SM y estado de GPU CORE.
    always @(posedge clk) begin
        run_request  <= 1'b0;
        halt_request <= 1'b0;
        step_request <= 1'b0;
        gpu_reset    <= 1'b0;
        cfg_write    <= 1'b0;
        launch       <= 1'b0;
        live_prev    <= live_warps;
        if (reset) begin
            paused <= 1'b0;
            done_mask <= 8'd0;
            launch_run <= 1'b0; launch_all <= 1'b0; launch_mask <= 8'd0;
            debug_warp <= 3'd0;
            debug_lane <= 3'd0;
        end else begin
            // Warps que acaban de terminar: pegajoso hasta que la CPU lo borre.
            done_mask <= done_mask | (live_prev & ~live_warps);

            if (host_busy) begin
                // CONTEXT (§14.3 +0x00) es el unico registro de depuracion que se escribe.
                if (writing && sel_simt && address[15:0] == 16'h0000 && !simt_bad) begin
                    debug_lane <= write_data[2:0];
                    debug_warp <= write_data[5:3];
                end
                // WARP_DONE es W1C.
                if (writing && sel_core && address[15:0] == 16'h0024)
                    done_mask <= (done_mask | (live_prev & ~live_warps)) & ~write_data[7:0];
                // WARP_START: arranca los warps pedidos y limpia su "terminado".
                // En reposo la GPU pasa a RUNNING; parada (HALT) o con otros
                // warps ejecutando, solo se anaden. Todo o nada: `start_bad`.
                if (writing && sel_core && address[15:0] == 16'h001c && !start_bad) begin
                    launch <= 1'b1; launch_all <= 1'b0; launch_mask <= write_data[7:0];
                    launch_run <= !paused;
                    done_mask <= (done_mask | (live_prev & ~live_warps)) & ~write_data[7:0];
                end
                if (cmd_write) begin
                    // RUN lanza todos los descriptores habilitados y pone la GPU
                    // en marcha, aunque estuviera pausada.
                    if (write_data[CTRL_RUN]) begin
                        launch <= 1'b1; launch_all <= 1'b1; launch_mask <= 8'd0;
                        launch_run <= 1'b1; paused <= 1'b0;
                        done_mask <= (done_mask | (live_prev & ~live_warps)) & ~desc_enabled;
                    end
                    if (write_data[CTRL_HALT])   begin halt_request <= 1'b1; paused <= 1'b1; end
                    if (write_data[CTRL_RESUME]) begin run_request  <= 1'b1; paused <= 1'b0; end
                    if (write_data[CTRL_STEP])         step_request <= 1'b1;
                    if (write_data[CTRL_RESET]) begin
                        gpu_reset <= 1'b1; paused <= 1'b0; done_mask <= 8'd0;
                    end
                end
                // `mmio_bad` ya incluye "descriptor de solo lectura" y "GPU en marcha".
                cfg_write <= writing && cfg_region && !mmio_bad;
            end
        end
    end

    gpu_sm #(.SIMT_DEPTH(SIMT_DEPTH), .SIMT_REGION_DEPTH(SIMT_REGION_DEPTH), .SIMT_PATH_DEPTH(SIMT_PATH_DEPTH)) sm (
        .clk(clk), .reset(reset), .soft_reset(gpu_reset), .run_request(run_request),
        .launch(launch), .launch_run(launch_run), .launch_all(launch_all),
        .launch_mask(launch_mask), .desc_enabled(desc_enabled),
        .halt_request(halt_request), .step_request(step_request),
        .halted(halted), .sm_running(sm_running), .live_warps(live_warps),
        .error(sm_error), .error_code(error_code),
        .error_warp(error_warp), .error_lane(error_lane), .error_lane_valid(error_lane_valid),
        .error_pc(error_pc), .instruction_retired(instruction_retired), .retired_count(retired_count),
        .debug_warp(debug_warp), .debug_lane(debug_lane), .debug_register(5'd0),
        .debug_data(debug_data), .debug_pc(debug_pc),
        .debug_warp_retired_count(debug_warp_retired_count),
        .cfg_write(cfg_write), .cfg_bank(cfg_bank), .cfg_word(address[6:2]), .cfg_data(write_data),
        .cfg_strobe(byte_strobe), .cfg_read_data(cfg_read_data),
        .imem_valid(fetch_valid), .imem_ready(fetch_ready), .imem_address(fetch_address),
        .imem_rsp_valid(fetch_rsp_valid), .imem_rsp_ready(fetch_rsp_ready),
        .imem_data(fetch_data), .imem_error(fetch_error),
        .lsu_valid(lsu_valid), .lsu_ready(lsu_ready), .lsu_tag(lsu_tag), .lsu_mask(lsu_mask),
        .lsu_write(lsu_write), .lsu_size(lsu_size), .lsu_signed(lsu_signed),
        .lsu_address(lsu_address), .lsu_data(lsu_data),
        .lsu_rsp_valid(lsu_rsp_valid), .lsu_rsp_ready(lsu_rsp_ready), .lsu_rsp_tag(lsu_rsp_tag),
        .lsu_rsp_data(lsu_rsp_data), .lsu_rsp_error(lsu_rsp_error), .lsu_occupied(occupied),
        .retired_lanes(sm_retired_lanes), .no_warp_stall(sm_no_warp_stall)
    );

    // MMIO de los warps: de momento ninguno. La LSU espera una respuesta, y la
    // respuesta es siempre error.
    wire gm_valid, gm_ready, gm_write, gm_rsp_valid, gm_rsp_ready, gm_rsp_error;
    wire [31:0] gm_addr, gm_wdata, gm_rsp_rdata;
    reg gm_busy;
    assign gm_ready = !gm_busy;
    assign gm_rsp_valid = gm_busy;
    assign gm_rsp_rdata = 32'd0;
    assign gm_rsp_error = 1'b1;
    always @(posedge clk) begin
        if (core_reset) gm_busy <= 1'b0;
        else if (gm_valid && !gm_busy) gm_busy <= 1'b1;
        else if (gm_busy && gm_rsp_ready) gm_busy <= 1'b0;
    end

    gpu_lsu2 lsu (
        .clk(clk), .reset(core_reset), .req_valid(lsu_req_valid_q), .req_ready(lsu_core_ready),
        .req_tag(lsu_req_tag_q), .req_mask(lsu_req_mask_q), .req_write(lsu_req_write_q),
        .req_size(lsu_req_size_q), .req_signed(lsu_req_signed_q),
        .req_address(lsu_req_address_q), .req_data(lsu_req_data_q), .rsp_valid(lsu_rsp_valid),
        .rsp_ready(lsu_rsp_ready), .rsp_tag(lsu_rsp_tag), .rsp_data(lsu_rsp_data),
        .rsp_error(lsu_rsp_error), .occupied(lsu_core_occupied),
        .mem_req_valid(p0_req_valid), .mem_req_ready(p0_req_ready), .mem_req_write(p0_req_write),
        .mem_req_addr(p0_req_addr), .mem_req_wdata(p0_req_wdata), .mem_req_wmask(p0_req_wmask),
        .mem_rsp_valid(p0_rsp_valid), .mem_rsp_ready(p0_rsp_ready),
        .mem_rsp_rdata(p0_rsp_rdata), .mem_rsp_error(p0_rsp_error),
        .mmio_req_valid(gm_valid), .mmio_req_ready(gm_ready),
        .mmio_req_write(gm_write), .mmio_req_addr(gm_addr),
        .mmio_req_wdata(gm_wdata),
        .mmio_rsp_valid(gm_rsp_valid), .mmio_rsp_ready(gm_rsp_ready),
        .mmio_rsp_rdata(gm_rsp_rdata), .mmio_rsp_error(gm_rsp_error)
    );

    gpu_imem_buffer #(.LINES(IMEM_LINES), .INDEX_BITS(IMEM_INDEX_BITS)) ibuf (
        .clk(clk), .reset(core_reset), .init_done(init_done), .halted(halted),
        .imem_valid(fetch_valid), .imem_ready(fetch_ready), .imem_address(fetch_address),
        .imem_rsp_valid(fetch_rsp_valid), .imem_rsp_ready(fetch_rsp_ready),
        .imem_data(fetch_data), .imem_error(fetch_error),
        .req_valid(p1_req_valid), .req_ready(p1_req_ready), .req_write(p1_req_write),
        .req_addr(p1_req_addr), .req_wdata(p1_req_wdata), .req_wmask(p1_req_wmask),
        .rsp_valid(p1_rsp_valid), .rsp_ready(p1_rsp_ready),
        .rsp_rdata(p1_rsp_rdata), .rsp_error(p1_rsp_error),
        .hit_count(imem_hits), .miss_count(imem_misses)
    );

    gpu_perf_counters perf (
        .clk(clk), .reset(core_reset),
        .running(!halted),
        .sel(sel_perf), .word(address[5:2]),
        .read_data(perf_read_data), .bad(perf_bad),
        .retired(instruction_retired), .retired_lanes(sm_retired_lanes),
        .imem_hits(imem_hits), .imem_misses(imem_misses),
        .lsu_tx(p0_fire),
        .stall_mem(lsu_valid && !lsu_ready),
        .no_warp_stall(sm_no_warp_stall));
endmodule
`default_nettype wire
