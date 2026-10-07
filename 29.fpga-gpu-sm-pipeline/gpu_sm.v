`default_nettype none
// SM segmentado: S -> F -> I -> D -> X -> W, diseno en sm-pipeline.md,
// especificacion ejecutable en 25.gpu-sim-cycle-uarch/DESIGN.md.
//
// Una instruccion en vuelo por warp (`busy[w]`), finalizacion en orden por
// recurso, sin bypass de registros ni de PC: el warp no vuelve a ser elegible
// hasta que su token comete (W). gpu_lane.v (la ALU/X) y la interfaz externa
// (imem_*/lsu_*/cfg_*/debug_*) no cambian frente a la FSM monolitica que
// sustituye.
//
// Registros de etapa (packet por token, uno por letra salvo W, que es un
// evento de compromiso combinacional, no una cola):
//   F: {valid,warp,pc,accepted}                     -- presenta imem_address
//   I: {valid,warp,pc,instruction,sequential_pc}     -- presenta la direccion de RF
//   D: {valid,warp,pc,instruction,sequential_pc,     -- decodifica; rf_a/rf_b ya
//       target,branch_target,rf_a,rf_b}                 resueltos (RF de 1 ciclo)
//   X: igual que D + `done` (mascara de lanes que ya retiraron)
//
// El mismo warp nunca ocupa dos etapas a la vez: `busy[w]` se fija al elegir
// en S y se libera solo al comprometer (commit), sea por X, por una especial
// (SSY/BAR/EXIT/HALT resueltas en D) o por una respuesta de LSU. La mascara
// no se guarda en el packet: `active[warp]` no puede cambiar mientras el warp
// esta `busy`, asi que leerlo en vivo con el warp del token basta.
//
// Contrapresion sin bypass: cada etapa comprueba la ocupacion de la
// siguiente con el valor de PRE-flanco (nunca "estara libre tras este
// flanco"), igual que documenta DESIGN.md. Cuesta una burbuja extra en cada
// transicion pero evita carreras de dos escritores sobre el mismo registro.
module gpu_sm #(parameter SIMT_DEPTH=8, SIMT_REGION_DEPTH=SIMT_DEPTH, SIMT_PATH_DEPTH=8) (
    input clk, reset,
    input run_request, halt_request, step_request,
    output halted,
    output reg error,
    output reg [7:0] error_code,
    output reg [2:0] error_warp, error_lane,
    output reg error_lane_valid,
    output reg [31:0] error_pc,
    output reg instruction_retired,
    output reg [7:0] retired_lanes,
    output reg [31:0] retired_count,
    output no_warp_stall,
    output [31:0] debug_warp_retired_count,
    input [2:0] debug_warp, debug_lane,
    input [4:0] debug_register,
    output [31:0] debug_data, debug_pc,
    input cfg_write,
    // Que bloque de GPU WARPS (§14.2): 0 descriptores, 1 LOGICAL_WARP_ID[n]
    // (+0x200), 2 WARP_ARG[n] (+0x280). En los dos arrays el warp es
    // cfg_word[2:0]; en los descriptores, cfg_word[4:2].
    input [1:0] cfg_bank,
    input [4:0] cfg_word,
    input [31:0] cfg_data,
    input [3:0] cfg_strobe,
    output reg [31:0] cfg_read_data,
    output imem_valid,
    input imem_ready,
    output [31:0] imem_address,
    input imem_rsp_valid,
    output imem_rsp_ready,
    input [31:0] imem_data,
    input imem_error,
    output lsu_valid,
    input lsu_ready,
    output [2:0] lsu_tag,
    output [7:0] lsu_mask,
    output lsu_write,
    // Tamano del acceso: 0 palabra, 1 byte, 2 media palabra. `lsu_signed` solo
    // importa en las cargas: LOADB y LOADH extienden el signo, el resto ceros.
    output [1:0] lsu_size,
    output lsu_signed,
    output [255:0] lsu_address, lsu_data,
    input lsu_rsp_valid,
    output lsu_rsp_ready,
    input [2:0] lsu_rsp_tag,
    input [255:0] lsu_rsp_data,
    input [7:0] lsu_rsp_error,
    input [7:0] lsu_occupied
);
    localparam [7:0] ERROR_NONE = 8'h00;
    localparam [7:0] ERROR_MEMORY_ACCESS = 8'h02;
    localparam [7:0] ERROR_DIVISION_BY_ZERO = 8'h04;
    localparam [7:0] ERROR_INVALID_ENCODING = 8'h05;
    localparam [7:0] ERROR_SIMT = 8'h06;
    localparam [7:0] ERROR_BARRIER = 8'h07;

    reg init_done;
    reg [7:0] init_address;
    reg running, pause_pending, stepping, step_locked;
    reg [2:0] cursor;
    reg [31:0] pc[0:7], groups[0:7], generation[0:7];
    // LOGICAL_WARP_ID[n] y WARP_ARG[n] (§14.2): lo que leen GETLWARP y GETARG.
    reg [31:0] logical_id[0:7], warp_arg[0:7];
    reg [7:0] active[0:7], live[0:7];
    reg [7:0] busy, wait_bar;
    reg [4:0] load_rd[0:7];
    reg [7:0] load_is_write;
    reg [31:0] warp_retired_count[0:7];
    assign debug_warp_retired_count=warp_retired_count[debug_warp];
    localparam SP_BITS=$clog2(SIMT_REGION_DEPTH+1);
    localparam PP_BITS=$clog2(SIMT_PATH_DEPTH+1);
    reg [SP_BITS-1:0] sp[0:7];
    reg [PP_BITS-1:0] pp[0:7];
    reg [31:0] ssy_pc[0:8*SIMT_REGION_DEPTH-1], join_pc[0:8*SIMT_REGION_DEPTH-1];
    reg [7:0] entry_mask[0:8*SIMT_REGION_DEPTH-1];
    reg [PP_BITS-1:0] path_base[0:8*SIMT_REGION_DEPTH-1];
    reg [31:0] pending_pc[0:8*SIMT_PATH_DEPTH-1];
    reg [7:0] pending_mask[0:8*SIMT_PATH_DEPTH-1];
    // Copia de la cima de cada pila, una entrada por warp (misma razon que
    // antes de segmentar: evita indexar los arrays de 8*DEPTH entradas en el
    // mismo ciclo que la comparacion y la escritura de pc).
    reg [31:0] join_pc_top[0:7], ssy_pc_top[0:7];
    reg [7:0] entry_mask_top[0:7];
    reg [PP_BITS-1:0] path_base_top[0:7];
    reg [31:0] pending_pc_top[0:7];
    reg [7:0] pending_mask_top[0:7];

    // ------------------------------------------------------------------
    // Registros de etapa.
    // ------------------------------------------------------------------
    reg f_valid, f_accepted;
    reg [2:0] f_warp;
    reg [31:0] f_pc;

    reg i_valid;
    reg [2:0] i_warp;
    reg [31:0] i_pc, i_instruction, i_sequential_pc;

    reg d_valid, d_settled, d_ready;
    reg [2:0] d_warp;
    reg [31:0] d_pc, d_instruction, d_sequential_pc, d_target, d_branch_target;
    reg [255:0] d_rf_a, d_rf_b;

    reg x_valid, x_started;
    reg [2:0] x_warp;
    // Id logico y argumento del warp de X, copiados al entrar: asi la lane no
    // cuelga de un mux de 8 entradas indexado por `x_warp`.
    reg [31:0] x_logical_id, x_warp_arg;
    reg [31:0] x_pc, x_instruction, x_sequential_pc, x_target, x_branch_target;
    reg [255:0] x_rf_a, x_rf_b;
    reg [7:0] done;

    // Solo para %d de diagnostico en testbenches (dut.sm.state): no hay una
    // FSM unica que describir, asi que es un resumen de ocupacion del cauce.
    wire [3:0] state = {x_valid,d_valid,i_valid,f_valid};

    assign halted=!running && busy==8'b0 && lsu_occupied==0;
    assign debug_pc=error ? error_pc : pc[debug_warp];

    // -- F: fetch ----------------------------------------------------------
    assign imem_valid=f_valid && !f_accepted;
    assign imem_address=f_pc;
    assign imem_rsp_ready=f_valid && f_accepted && !i_valid;

    // -- I: registro puente entre F y D. No presenta direccion de RF: eso
    // haria falta un ciclo antes de que D exista, y el puerto de lectura de
    // gpu_register_file tiene un ciclo de latencia -- si "I" dejara de
    // presentarla en cuanto entra en D, la lectura llegaria tarde. Es D quien
    // la presenta, con sus propios campos (disponibles ya el primer ciclo),
    // y espera un ciclo mas (`d_ready`) a que el dato se asiente.
    // Accesos a memoria. Palabra: LOAD 0x15, STORE 0x16. Sub-palabra (isa.md,
    // capability subword_memory): LOADB 0x18, LOADUB 0x19, STOREB 0x1A, LOADH
    // 0x1B, LOADUH 0x1C, STOREH 0x1D. Los tres de escritura sacan el dato de Rd.
    localparam [5:0] OPCODE_LOAD = 6'h15, OPCODE_STORE = 6'h16;
    localparam [5:0] OPCODE_LOADB = 6'h18, OPCODE_LOADUB = 6'h19, OPCODE_STOREB = 6'h1a;
    localparam [5:0] OPCODE_LOADH = 6'h1b, OPCODE_LOADUH = 6'h1c, OPCODE_STOREH = 6'h1d;
    wire [5:0] i_opcode=i_instruction[31:26];
    wire i_branch=i_opcode>=6'h20 && i_opcode<=6'h25;
    wire i_is_store=i_opcode==OPCODE_STORE || i_opcode==OPCODE_STOREB || i_opcode==OPCODE_STOREH;
    wire [4:0] i_ra=i_branch ? i_instruction[25:21] : i_instruction[20:16];
    wire [4:0] i_rb=i_branch ? i_instruction[20:16] :
        (i_is_store ? i_instruction[25:21] : i_instruction[15:11]);

    wire [255:0] rf_a, rf_b, lane_pc, lane_write_data;
    wire [39:0] lane_write_address;
    wire [7:0] lane_we, lane_retired, lane_halted, lane_error;
    wire [63:0] lane_error_code;
    wire response_commit=lsu_rsp_valid && lsu_rsp_ready;

    // -- D: decodificacion ---------------------------------------------------
    wire [5:0] d_opcode=d_instruction[31:26];
    wire d_branch_for_ra=d_opcode>=6'h20 && d_opcode<=6'h25;
    wire d_is_store=d_opcode==OPCODE_STORE || d_opcode==OPCODE_STOREB || d_opcode==OPCODE_STOREH;
    wire [4:0] d_ra=d_branch_for_ra ? d_instruction[25:21] : d_instruction[20:16];
    wire [4:0] d_rb=d_branch_for_ra ? d_instruction[20:16] :
        (d_is_store ? d_instruction[25:21] : d_instruction[15:11]);
    // D activo para efectos de despacho/compromiso solo tras asentarse el
    // puerto de lectura de RF (ver `d_ready` en el always secuencial).
    wire d_active=d_valid && d_ready;
    wire d_is_byte=d_opcode==OPCODE_LOADB || d_opcode==OPCODE_LOADUB || d_opcode==OPCODE_STOREB;
    wire d_is_half=d_opcode==OPCODE_LOADH || d_opcode==OPCODE_LOADUH || d_opcode==OPCODE_STOREH;
    wire d_is_memory=d_opcode==OPCODE_LOAD || d_opcode==OPCODE_STORE || d_is_byte || d_is_half;
    wire d_is_special=d_opcode==6'h31 || d_opcode==6'h32 || d_opcode==6'h33 || d_opcode==6'h3f;
    wire d_encoding_bad=(d_opcode==6'h32 || d_opcode==6'h33 || d_opcode==6'h3f) && d_instruction[25:0]!=0;
    wire d_write=d_is_store;
    wire [31:0] d_immediate={{16{d_instruction[15]}},d_instruction[15:0]};
    wire [31:0] d_ssy_index={29'b0,d_warp}*SIMT_REGION_DEPTH+{{(32-SP_BITS){1'b0}},sp[d_warp]};

    // -- X: la lane ALU y la deteccion de compromiso -------------------------
    wire [5:0] x_opcode=x_instruction[31:26];
    wire x_branch=x_opcode>=6'h20 && x_opcode<=6'h25;
    wire x_opcode_is_bra=x_opcode==6'h2f;
    wire [31:0] x_path_index={29'b0,x_warp}*SIMT_PATH_DEPTH+{{(32-PP_BITS){1'b0}},pp[x_warp]};

    // X siempre gana el puerto de escritura de RF frente a una respuesta de
    // LSU. `lane_we` pulsa un ciclo ANTES de que `lane_retired` lo haga (ver
    // gpu_lane.v: STATE_EXECUTE deja la escritura lista, y el retiro no se ve
    // hasta STATE_RETIRE, un ciclo despues) -- por eso la escritura de RF se
    // gobierna con `x_valid && lane_we`, no con `x_completes`, y el arbitraje
    // frente a LSU cubre las DOS ventanas para no dejar una en el aire.
    wire x_completes = x_valid && (&done);
    wire x_writes_this_cycle = x_valid && |(lane_we & active[x_warp]);
    assign lsu_rsp_ready = !x_writes_this_cycle && !x_completes;
    wire lsu_commits = response_commit;
    // Una especial en D nunca adelanta a un compromiso de X ni a una
    // respuesta de LSU del mismo ciclo: el puerto de retiro
    // (instruction_retired/retired_lanes) es de un solo evento por ciclo.
    wire d_special_commits = d_active && d_is_special && !d_encoding_bad &&
        !x_completes && !lsu_commits;
    wire d_fault_commits = d_active && d_encoding_bad && !x_completes && !lsu_commits;

    // -- D -> X: arranca la ejecucion de lane el mismo ciclo que X se ocupa --
    wire d_is_alu = d_active && !d_is_memory && !d_is_special && !d_encoding_bad;
    wire d_to_x_fire = d_is_alu && !x_valid;

    genvar l;
    generate for(l=0;l<8;l=l+1) begin: lanes
        // R0 cableado a cero: se descarta cualquier escritura cuyo numero de
        // registro sea 0. Ver 1.isa/isa.md seccion 1. El barrido de INIT
        // queda fuera del guardian a proposito (ver !init_done abajo): es
        // quien pone el banco a cero, porque esta BRAM no tiene reset.
        wire [4:0] write_register=!init_done ? 5'd0 :
            (lsu_commits ? load_rd[lsu_rsp_tag] : lane_write_address[l*5 +: 5]);
        wire rf_write=!init_done ||
            ((write_register!=5'd0) &&
             ((lsu_commits && active[lsu_rsp_tag][l] && !load_is_write[lsu_rsp_tag] && !lsu_rsp_error[l]) ||
              (x_valid && active[x_warp][l] && lane_we[l])));
        wire [7:0] wa=!init_done ? init_address :
            (lsu_commits ? {lsu_rsp_tag,load_rd[lsu_rsp_tag]} : {x_warp,lane_write_address[l*5 +: 5]});
        wire [31:0] wd=!init_done ? 32'b0 :
            (lsu_commits ? lsu_rsp_data[l*32 +: 32] : lane_write_data[l*32 +: 32]);
        gpu_register_file rf (
            .clk(clk), .read_address_a(halted ? {debug_warp,debug_register} :
                (d_valid ? {d_warp,d_ra} : {i_warp,i_ra})),
            .read_address_b(d_valid ? {d_warp,d_rb} : {i_warp,i_rb}), .read_data_a(rf_a[l*32 +: 32]),
            .read_data_b(rf_b[l*32 +: 32]), .write_enable(rf_write),
            .write_address(wa), .write_data(wd)
        );
        wire fetch_valid;
        // EXTERNAL_FETCH: el SM ya trae la instruccion, la lane no la busca.
        gpu_lane #(.EXTERNAL_FETCH(1)) alu (
            .clk(clk), .reset(reset), .launch_pc(x_pc),
            .thread_id({26'b0,x_warp,l[2:0]}),
            .lane_id(l[2:0]), .warp_id(x_warp),
            .logical_warp_id(x_logical_id), .warp_arg(x_warp_arg),
            .register_a(x_rf_a[l*32 +: 32]), .register_b(x_rf_b[l*32 +: 32]),
            .register_write_enable(lane_we[l]),
            .register_write_address(lane_write_address[l*5 +: 5]),
            .register_write_data(lane_write_data[l*32 +: 32]),
            .run_request(1'b0), .halt_request(1'b0),
            // Un ciclo despues de instalar X (no en el mismo flanco: la lane
            // muestreria `imem_read_data`/`x_instruction` con el valor viejo,
            // porque los dos modulos ven el mismo flanco con NBA -- misma
            // razon que `d_settled`/`d_ready` para el puerto de RF).
            .step_request(x_valid && !x_started && active[x_warp][l]),
            .halted(lane_halted[l]), .error(lane_error[l]),
            .error_code(lane_error_code[l*8 +: 8]), .instruction_retired(lane_retired[l]),
            .imem_valid(fetch_valid), .imem_address(), .imem_read_data(x_instruction),
            .imem_ready(fetch_valid), .dmem_valid(), .dmem_address(),
            .dmem_write_data(), .dmem_write_enable(), .dmem_read_data(32'b0),
            .dmem_ready(1'b0), .dmem_error(1'b0), .debug_register_address(5'b0),
            .debug_register_data(), .debug_pc(lane_pc[l*32 +: 32])
        );
    end endgenerate
    assign debug_data=rf_a[debug_lane*32 +: 32];

    // -- LSU: D despacha directamente. No compite por el puerto de retiro ni
    // por el de escritura de RF (es una peticion, no una compromiso), asi que
    // no hace falta arbitrarlo contra X ni contra la respuesta de LSU.
    wire d_dispatch_mem = d_active && d_is_memory;
    assign lsu_valid=d_dispatch_mem;
    assign lsu_tag=d_warp;
    assign lsu_mask=active[d_warp];
    assign lsu_write=d_write;
    assign lsu_size=d_is_byte ? 2'd1 : d_is_half ? 2'd2 : 2'd0;
    assign lsu_signed=d_opcode==OPCODE_LOADB || d_opcode==OPCODE_LOADH;
    // Ocho sumadores de 32 bits, uno por lane. Escrito como
    // `d_rf_a+{8{d_immediate}}` era UN sumador de 256 bits, y el acarreo de la
    // lane n entraba en la lane n+1: con un desplazamiento negativo (el
    // inmediato extendido en signo vale 0xFFFFFFFx) cada lane sumaba uno de mas
    // a la siguiente. En 12, 14, 17 y 22 ya era por lane.
    genvar al;
    generate for(al=0;al<8;al=al+1) begin: address_lanes
        assign lsu_address[al*32 +: 32]=d_rf_a[al*32 +: 32]+d_immediate;
    end endgenerate
    // El dato de un STOREB/STOREH se replica en todos los carriles de la
    // palabra: lo que decide cual vale es la mascara de bytes que forma la LSU
    // con la direccion, asi que aqui no hace falta saber a que byte va.
    genvar sl;
    generate for(sl=0;sl<8;sl=sl+1) begin: store_lanes
        wire [31:0] v=d_rf_b[sl*32 +: 32];
        assign lsu_data[sl*32 +: 32]=d_is_byte ? {4{v[7:0]}} : d_is_half ? {2{v[15:0]}} : v;
    end endgenerate

    // -- Mantenimiento independiente: reconvergencia SIMT y barreras ---------
    reg normalize_found;
    reg [2:0] normalize_warp;
    reg [7:0] release_bar;
    reg [7:0] releasing;
    reg release_found;
    reg [2:0] release_warp;
    // -- S: eleccion round-robin ---------------------------------------------
    reg pick_found;
    reg [2:0] pick_warp;
    reg any_live, all_bar, bar_mismatch_for_d;
    integer a,b;
    reg [2:0] candidate;
    reg candidate_needs_reconvergence;
    always @* begin
        normalize_found=0; normalize_warp=0;
        pick_found=0; pick_warp=cursor; any_live=0; release_bar=0;
        all_bar=0; bar_mismatch_for_d=0; candidate=0; candidate_needs_reconvergence=0;
        for(a=0;a<8;a=a+1) begin
            if (live[a]!=0) any_live=1;
            if (!normalize_found && live[a]!=0 && !busy[a] && !wait_bar[a] &&
                (active[a]==0 || (sp[a]!=0 && pc[a]==join_pc_top[a]))) begin
                normalize_found=1; normalize_warp=a[2:0];
            end
            candidate=cursor+a[2:0];
            candidate_needs_reconvergence=(active[candidate]==0 ||
                (sp[candidate]!=0 && pc[candidate]==join_pc_top[candidate]));
            if (!pick_found && live[candidate]!=0 && !busy[candidate] && !wait_bar[candidate] &&
                !candidate_needs_reconvergence) begin
                pick_found=1; pick_warp=candidate;
            end
            all_bar=wait_bar[a];
            for(b=0;b<8;b=b+1) begin
                if (groups[a]==groups[b] && live[b]!=0 && !wait_bar[b]) all_bar=0;
                if (d_valid && d_opcode==6'h32 && wait_bar[b] && groups[b]==groups[d_warp] &&
                    (pc[b]!=d_pc || generation[b]!=generation[d_warp])) bar_mismatch_for_d=1;
            end
            release_bar[a]=all_bar;
        end
        release_found=0; release_warp=0;
        for(a=0;a<8;a=a+1)
            if(!release_found && releasing[a]) begin release_found=1; release_warp=a[2:0]; end
    end

    // Burbuja de S por falta de warp elegible: F esta libre (no es
    // contrapresion del cauce) y aun asi ningun warp pasa el filtro de
    // pick_found, con algo todavia vivo (si nada esta vivo el programa ha
    // terminado y eso no es una burbuja, es el final). Separa "el cauce no
    // tiene con que llenarse" de "el cauce esta lleno", que es justo la
    // pregunta que profiling.md deja abierta al segmentar S/F/I/D/X/W.
    assign no_warp_stall = init_done && running && !error && !f_valid &&
                           !pick_found && any_live && !step_locked;

    // -- X: deteccion de fallo y de divergencia -------------------------------
    reg [7:0] taken;
    reg alu_fault;
    reg [2:0] fault_lane;
    reg [7:0] fault_code;
    integer t;
    always @* begin
        taken=0; alu_fault=0; fault_lane=0; fault_code=ERROR_NONE;
        for(t=0;t<8;t=t+1) begin
            taken[t]=x_valid && active[x_warp][t] && lane_pc[t*32 +: 32] != x_sequential_pc;
            if (x_valid && !alu_fault && active[x_warp][t] && lane_error[t]) begin
                alu_fault=1; fault_lane=t[2:0]; fault_code=lane_error_code[t*8 +: 8];
            end
        end
    end
    wire x_would_fault = x_completes && alu_fault;
    wire x_commits_ok = x_completes && !alu_fault;

    always @* begin
        if(cfg_bank==2'd1) cfg_read_data=logical_id[cfg_word[2:0]];
        else if(cfg_bank==2'd2) cfg_read_data=warp_arg[cfg_word[2:0]];
        else case(cfg_word[1:0])
            0: cfg_read_data=pc[cfg_word[4:2]];
            1: cfg_read_data={16'b0,live[cfg_word[4:2]],active[cfg_word[4:2]]};
            2: cfg_read_data=groups[cfg_word[4:2]];
            3: begin
                cfg_read_data=0;
                cfg_read_data[SP_BITS-1:0]=sp[cfg_word[4:2]];
                cfg_read_data[8 +: PP_BITS]=pp[cfg_word[4:2]];
                cfg_read_data[16]=busy[cfg_word[4:2]];
                cfg_read_data[17]=wait_bar[cfg_word[4:2]];
            end
        endcase
    end

    task fault;
        input [7:0] code;
        input [2:0] warp_id, lane_id;
        input lane_valid;
        begin
            if (!error) begin
                error<=1; error_code<=code; error_warp<=warp_id;
                error_lane<=lane_id; error_lane_valid<=lane_valid; error_pc<=pc[warp_id];
            end
            running<=0; pause_pending<=0;
            releasing<=0;
            f_valid<=0; i_valid<=0; d_valid<=0; x_valid<=0;
            busy<=8'b0;
        end
    endtask

    integer w,c;
    always @(posedge clk) begin
        instruction_retired<=0; retired_lanes<=8'd0;
        if (reset) begin
            init_address<=0; init_done<=0; running<=0; pause_pending<=0; stepping<=0; step_locked<=0;
            cursor<=0; busy<=0; wait_bar<=0; releasing<=0; load_is_write<=0;
            error<=0; error_code<=ERROR_NONE; error_pc<=0; error_warp<=0; error_lane<=0; error_lane_valid<=0;
            retired_count<=0;
            f_valid<=0; f_accepted<=0; f_warp<=0; f_pc<=0;
            i_valid<=0; i_warp<=0; i_pc<=0; i_instruction<=0; i_sequential_pc<=0;
            d_valid<=0; d_settled<=0; d_ready<=0; d_warp<=0; d_pc<=0; d_instruction<=0; d_sequential_pc<=0; d_target<=0; d_branch_target<=0;
            d_rf_a<=0; d_rf_b<=0;
            x_valid<=0; x_started<=0; x_warp<=0; x_logical_id<=0; x_warp_arg<=0; x_pc<=0; x_instruction<=0; x_sequential_pc<=0; x_target<=0; x_branch_target<=0;
            x_rf_a<=0; x_rf_b<=0; done<=0;
            for(w=0;w<8;w=w+1) begin
                pc[w]<=0; active[w]<=8'hff; live[w]<=8'hff; groups[w]<=0;
                logical_id[w]<=0; warp_arg[w]<=0;
                warp_retired_count[w]<=0; generation[w]<=0; sp[w]<=0; pp[w]<=0; load_rd[w]<=0;
                join_pc_top[w]<=0; ssy_pc_top[w]<=0; entry_mask_top[w]<=0; path_base_top[w]<=0;
                pending_pc_top[w]<=0; pending_mask_top[w]<=0;
            end
        end else begin
            if (!init_done) begin
                init_address<=init_address+1'b1;
                if(init_address==255) init_done<=1;
            end
            if (halt_request && running) pause_pending<=1;
            // Los dos arrays (§14.2) son de lectura y escritura y no tienen
            // efectos laterales: tocarlos no reinicia el estado SIMT del warp,
            // a diferencia de los descriptores (abajo).
            if (halted && cfg_write && cfg_bank!=2'd0) begin
                for(c=0;c<4;c=c+1) if(cfg_strobe[c]) begin
                    if(cfg_bank==2'd1) logical_id[cfg_word[2:0]][c*8 +: 8]<=cfg_data[c*8 +: 8];
                    else warp_arg[cfg_word[2:0]][c*8 +: 8]<=cfg_data[c*8 +: 8];
                end
            end
            if (halted && cfg_write && cfg_bank==2'd0) begin
                for(c=0;c<4;c=c+1) if(cfg_strobe[c]) begin
                    if(cfg_word[1:0]==0) pc[cfg_word[4:2]][c*8 +: 8]<=cfg_data[c*8 +: 8];
                    if(cfg_word[1:0]==2) groups[cfg_word[4:2]][c*8 +: 8]<=cfg_data[c*8 +: 8];
                end
                if(cfg_word[1:0]==1 && cfg_strobe[0]) begin
                    active[cfg_word[4:2]]<=cfg_data[7:0]; live[cfg_word[4:2]]<=cfg_data[7:0];
                end
                warp_retired_count[cfg_word[4:2]]<=0; sp[cfg_word[4:2]]<=0; pp[cfg_word[4:2]]<=0;
                wait_bar[cfg_word[4:2]]<=0; releasing[cfg_word[4:2]]<=0; generation[cfg_word[4:2]]<=0;
            end

            // ---------------------------------------------------------
            // Compromiso (W): X > respuesta de LSU > especial de D.
            // Como mucho un evento de retiro por ciclo.
            // ---------------------------------------------------------
            if (x_would_fault) begin
                fault(fault_code,x_warp,fault_lane,fault_code==ERROR_DIVISION_BY_ZERO);
            end else if (x_commits_ok) begin
                if(x_branch && taken!=0 && taken!=active[x_warp]) begin
                    if(sp[x_warp]==0) fault(ERROR_SIMT,x_warp,0,0);
                    else if(x_branch_target==join_pc_top[x_warp]) begin
                        active[x_warp]<=active[x_warp] & ~taken;
                        pc[x_warp]<=x_sequential_pc;
                        instruction_retired<=1; retired_lanes<=active[x_warp]; retired_count<=retired_count+1'b1;
                        warp_retired_count[x_warp]<=warp_retired_count[x_warp]+1'b1;
                        busy[x_warp]<=0; x_valid<=0;
                    end else if(x_sequential_pc==join_pc_top[x_warp]) begin
                        active[x_warp]<=taken; pc[x_warp]<=x_branch_target;
                        instruction_retired<=1; retired_lanes<=active[x_warp]; retired_count<=retired_count+1'b1;
                        warp_retired_count[x_warp]<=warp_retired_count[x_warp]+1'b1;
                        busy[x_warp]<=0; x_valid<=0;
                    end else if(pp[x_warp]==SIMT_PATH_DEPTH[PP_BITS-1:0]) begin
                        fault(ERROR_SIMT,x_warp,0,0);
                    end else begin
                        pending_pc[x_path_index]<=x_branch_target; pending_mask[x_path_index]<=taken;
                        pending_pc_top[x_warp]<=x_branch_target; pending_mask_top[x_warp]<=taken;
                        pp[x_warp]<=pp[x_warp]+1'b1; active[x_warp]<=active[x_warp] & ~taken;
                        pc[x_warp]<=x_sequential_pc;
                        instruction_retired<=1; retired_lanes<=active[x_warp]; retired_count<=retired_count+1'b1;
                        warp_retired_count[x_warp]<=warp_retired_count[x_warp]+1'b1;
                        busy[x_warp]<=0; x_valid<=0;
                    end
                end else begin
                    if (x_branch && taken!=0) pc[x_warp]<=x_branch_target;
                    else if(x_opcode_is_bra) pc[x_warp]<=x_target;
                    else pc[x_warp]<=x_sequential_pc;
                    instruction_retired<=1; retired_lanes<=active[x_warp]; retired_count<=retired_count+1'b1;
                    warp_retired_count[x_warp]<=warp_retired_count[x_warp]+1'b1;
                    busy[x_warp]<=0; x_valid<=0;
                end
            end else if (lsu_commits) begin
                if(|lsu_rsp_error) begin
                    for(w=7;w>=0;w=w-1) if(lsu_rsp_error[w]) fault(ERROR_MEMORY_ACCESS,lsu_rsp_tag,w[2:0],1'b1);
                end else begin
                    pc[lsu_rsp_tag]<=pc[lsu_rsp_tag]+4;
                    instruction_retired<=1; retired_lanes<=active[lsu_rsp_tag]; retired_count<=retired_count+1'b1;
                    warp_retired_count[lsu_rsp_tag]<=warp_retired_count[lsu_rsp_tag]+1'b1;
                    busy[lsu_rsp_tag]<=0;
                end
            end else if (d_fault_commits) begin
                fault(ERROR_INVALID_ENCODING,d_warp,0,0);
            end else if (d_special_commits) begin
                if(bar_mismatch_for_d && d_opcode==6'h32) begin
                    fault(ERROR_BARRIER,d_warp,0,0);
                end else case(d_opcode)
                    6'h31: begin // SSY
                        if(|d_target[31:17] || |d_target[1:0]) fault(ERROR_MEMORY_ACCESS,d_warp,0,0);
                        else if(sp[d_warp]!=0 && ssy_pc_top[d_warp]==d_pc) begin
                            if(join_pc_top[d_warp]!=d_target) fault(ERROR_SIMT,d_warp,0,0);
                            else begin
                                pc[d_warp]<=d_sequential_pc;
                                instruction_retired<=1; retired_lanes<=active[d_warp]; retired_count<=retired_count+1'b1;
                                warp_retired_count[d_warp]<=warp_retired_count[d_warp]+1'b1;
                                busy[d_warp]<=0; d_valid<=0;
                            end
                        end else if(sp[d_warp]==SIMT_REGION_DEPTH[SP_BITS-1:0]) fault(ERROR_SIMT,d_warp,0,0);
                        else begin
                            join_pc[d_ssy_index]<=d_target; entry_mask[d_ssy_index]<=active[d_warp];
                            ssy_pc[d_ssy_index]<=d_pc; path_base[d_ssy_index]<=pp[d_warp];
                            join_pc_top[d_warp]<=d_target; entry_mask_top[d_warp]<=active[d_warp];
                            ssy_pc_top[d_warp]<=d_pc; path_base_top[d_warp]<=pp[d_warp];
                            sp[d_warp]<=sp[d_warp]+1'b1; pc[d_warp]<=d_sequential_pc;
                            instruction_retired<=1; retired_lanes<=active[d_warp]; retired_count<=retired_count+1'b1;
                            warp_retired_count[d_warp]<=warp_retired_count[d_warp]+1'b1;
                            busy[d_warp]<=0; d_valid<=0;
                        end
                    end
                    6'h32: begin // BAR
                        if(active[d_warp]!=live[d_warp]) fault(ERROR_BARRIER,d_warp,0,0);
                        else begin
                            wait_bar[d_warp]<=1;
                            instruction_retired<=1; retired_lanes<=active[d_warp]; retired_count<=retired_count+1'b1;
                            warp_retired_count[d_warp]<=warp_retired_count[d_warp]+1'b1;
                            busy[d_warp]<=0; d_valid<=0;
                        end
                    end
                    6'h33,6'h3f: begin // EXIT, HALT
                        live[d_warp]<=live[d_warp] & ~active[d_warp];
                        active[d_warp]<=0;
                        pc[d_warp]<=d_sequential_pc;
                        if ((live[d_warp] & ~active[d_warp])==0) begin
                            sp[d_warp]<=0; pp[d_warp]<=0;
                        end
                        instruction_retired<=1; retired_lanes<=active[d_warp]; retired_count<=retired_count+1'b1;
                        warp_retired_count[d_warp]<=warp_retired_count[d_warp]+1'b1;
                        busy[d_warp]<=0; d_valid<=0;
                    end
                endcase
            end

            // ---------------------------------------------------------
            // Mantenimiento independiente: no toca S/F/I/D/X ni consume
            // el puerto de retiro. Un pop de pila por ciclo, o liberar UN
            // warp de barrera por ciclo.
            // ---------------------------------------------------------
            if (release_found && !error) begin
                wait_bar[release_warp]<=0; releasing[release_warp]<=0;
                pc[release_warp]<=pc[release_warp]+4;
                generation[release_warp]<=generation[release_warp]+1'b1;
            end else if (|release_bar && !error) begin
                releasing<=release_bar;
            end else if (normalize_found && !error) begin
                if (sp[normalize_warp]!=0 && (active[normalize_warp]==0 || pc[normalize_warp]==join_pc_top[normalize_warp])) begin
                    if (pp[normalize_warp]>path_base_top[normalize_warp]) begin
                        pc[normalize_warp]<=pending_pc_top[normalize_warp];
                        active[normalize_warp]<=pending_mask_top[normalize_warp] & live[normalize_warp];
                        pp[normalize_warp]<=pp[normalize_warp]-1'b1;
                        pending_pc_top[normalize_warp]<=pending_pc[
                            {29'b0,normalize_warp}*SIMT_PATH_DEPTH+
                            ({{(32-PP_BITS){1'b0}},pp[normalize_warp]}>=2 ?
                             {{(32-PP_BITS){1'b0}},pp[normalize_warp]}-2 : 0)];
                        pending_mask_top[normalize_warp]<=pending_mask[
                            {29'b0,normalize_warp}*SIMT_PATH_DEPTH+
                            ({{(32-PP_BITS){1'b0}},pp[normalize_warp]}>=2 ?
                             {{(32-PP_BITS){1'b0}},pp[normalize_warp]}-2 : 0)];
                    end else begin
                        pc[normalize_warp]<=join_pc_top[normalize_warp];
                        active[normalize_warp]<=entry_mask_top[normalize_warp] & live[normalize_warp];
                        sp[normalize_warp]<=sp[normalize_warp]-1'b1;
                        join_pc_top[normalize_warp]<=join_pc[
                            {29'b0,normalize_warp}*SIMT_REGION_DEPTH+
                            ({{(32-SP_BITS){1'b0}},sp[normalize_warp]}>=2 ?
                             {{(32-SP_BITS){1'b0}},sp[normalize_warp]}-2 : 0)];
                        ssy_pc_top[normalize_warp]<=ssy_pc[
                            {29'b0,normalize_warp}*SIMT_REGION_DEPTH+
                            ({{(32-SP_BITS){1'b0}},sp[normalize_warp]}>=2 ?
                             {{(32-SP_BITS){1'b0}},sp[normalize_warp]}-2 : 0)];
                        entry_mask_top[normalize_warp]<=entry_mask[
                            {29'b0,normalize_warp}*SIMT_REGION_DEPTH+
                            ({{(32-SP_BITS){1'b0}},sp[normalize_warp]}>=2 ?
                             {{(32-SP_BITS){1'b0}},sp[normalize_warp]}-2 : 0)];
                        path_base_top[normalize_warp]<=path_base[
                            {29'b0,normalize_warp}*SIMT_REGION_DEPTH+
                            ({{(32-SP_BITS){1'b0}},sp[normalize_warp]}>=2 ?
                             {{(32-SP_BITS){1'b0}},sp[normalize_warp]}-2 : 0)];
                    end
                end else begin
                    // live!=0 garantizado por la eleccion de normalize_warp:
                    // active==0 sin pila que restaurar es un fallo SIMT.
                    fault(ERROR_SIMT,normalize_warp,0,0);
                end
            end

            // ---------------------------------------------------------
            // S -> F: elegir un warp nuevo si F esta libre.
            // ---------------------------------------------------------
            if (init_done && running && !error && !f_valid && pick_found && !step_locked) begin
                busy[pick_warp]<=1; cursor<=pick_warp+1'b1;
                f_valid<=1; f_accepted<=0; f_warp<=pick_warp; f_pc<=pc[pick_warp];
                // En modo paso a paso, esta es LA UNICA instruccion que se
                // deja entrar: sin este cerrojo, en cuanto ella compromete y
                // libera `busy` puede haber otro warp elegible ese mismo
                // ciclo (o el propio, si vuelve a quedar `busy==0` antes de
                // que se reconozca la pausa), y STEP retiraria dos.
                if (stepping) step_locked<=1;
            end
            if (init_done && stepping && d_valid && !x_valid) begin
                // El paso a paso marca la pausa en cuanto la instruccion
                // elegida llega a D; se aplica cuando ya no queda nada vivo.
                pause_pending<=1; stepping<=0;
            end
            if ((pause_pending || (running && !any_live)) &&
                busy==8'b0 && !f_valid && !i_valid && !d_valid && !x_valid) begin
                running<=0; pause_pending<=0;
            end
            if (halted && (run_request || step_request) && !error) begin
                running<=1; stepping<=!run_request && step_request; step_locked<=0;
            end

            // ---------------------------------------------------------
            // F -> I: llega la respuesta del buffer de instrucciones.
            // ---------------------------------------------------------
            if (f_valid && !f_accepted && imem_valid && imem_ready) f_accepted<=1;
            if (imem_rsp_valid && imem_rsp_ready) begin
                if (imem_error) begin
                    fault(ERROR_MEMORY_ACCESS,f_warp,0,0);
                end else begin
                    i_valid<=1; i_warp<=f_warp; i_pc<=f_pc;
                    i_instruction<=imem_data; i_sequential_pc<=f_pc+32'd4;
                    f_valid<=0;
                end
            end

            // ---------------------------------------------------------
            // I -> D: la lectura de RF ya esta en marcha; calcula target y
            // branch_target, e instala el packet en D.
            // ---------------------------------------------------------
            if (i_valid && !d_valid) begin
                d_valid<=1; d_settled<=0; d_ready<=0; d_warp<=i_warp; d_pc<=i_pc;
                d_instruction<=i_instruction; d_sequential_pc<=i_sequential_pc;
                d_target<=i_sequential_pc+{{4{i_instruction[25]}},i_instruction[25:0],2'b00};
                d_branch_target<=i_sequential_pc+{{14{i_instruction[15]}},i_instruction[15:0],2'b00};
                i_valid<=0;
            end else if (d_valid && !d_settled) begin
                // D lleva un ciclo presentando su propia direccion (arriba,
                // `d_valid ? {d_warp,d_ra} : ...`). Este flanco es cuando el
                // puerto de RF POR FIN la muestrea; su dato de salida no se
                // asienta hasta el flanco siguiente (`d_ready`, mas abajo).
                d_settled<=1;
            end else if (d_valid && d_settled && !d_ready) begin
                d_rf_a<=rf_a; d_rf_b<=rf_b; d_ready<=1;
            end

            // ---------------------------------------------------------
            // D -> LSU: despacha si hay hueco.
            // ---------------------------------------------------------
            if (d_dispatch_mem && lsu_ready) begin
                load_rd[d_warp]<=d_instruction[25:21]; load_is_write[d_warp]<=d_write;
                d_valid<=0;
                // busy[d_warp] sigue a 1: el warp queda parado en memoria
                // hasta que la respuesta compromete arriba.
            end

            // ---------------------------------------------------------
            // D -> X: arranca la ejecucion (mismo ciclo que X se ocupa).
            // ---------------------------------------------------------
            if (d_to_x_fire) begin
                x_valid<=1; x_started<=0; x_warp<=d_warp; x_pc<=d_pc;
                x_logical_id<=logical_id[d_warp]; x_warp_arg<=warp_arg[d_warp];
                x_instruction<=d_instruction; x_sequential_pc<=d_sequential_pc;
                x_target<=d_target; x_branch_target<=d_branch_target;
                x_rf_a<=d_rf_a; x_rf_b<=d_rf_b;
                done<=~active[d_warp];
                d_valid<=0;
            end else if (x_valid && !x_started) begin
                // El ciclo anterior x_instruction/x_rf_a ya estaban estables
                // y `step_request` (arriba) estaba en alto: aqui es cuando la
                // lane los captura. Deja de pulsar a partir de ahora.
                x_started<=1;
            end else if (x_valid && !x_completes) begin
                // Una lane que falla termina la instruccion sin retirarla.
                // Si solo esperamos `lane_retired`, TRAP, DIV por cero y los
                // fallos de opcode/encoding dejan el token de X ocupado para
                // siempre y el monitor nunca llega a observar `halted`.
                done<=done | lane_retired | lane_halted;
            end
        end
    end
endmodule
`default_nettype wire
