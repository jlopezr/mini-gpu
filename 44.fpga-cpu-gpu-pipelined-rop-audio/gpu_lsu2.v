`default_nettype none
// LSU v2.0: coalescencia por linea de 16 bytes sobre un puerto de
// memory_fabric_4 (128 bits, BL8). Ocho slots vectoriales; tras servir UN grupo
// se vuelve a arbitrar. Sin puerto auxiliar: fetch y monitor van por sus
// propios puertos del fabric. Sin segmentacion todavia (ver lsu-v2.md, v2.1).
//
// ESCRITURAS POSTED (parametro MAX_POSTED, 0 = como antes). Una escritura a RAM
// no espera su respuesta: al aceptarla el puerto, la LSU retira el grupo y sigue
// con el siguiente, y cuenta la respuesta pendiente en `st_out` (hasta MAX_POSTED).
// Las respuestas llegan en orden por puerto y se consumen aparte. Reglas:
//   * una carga o un acceso MMIO no sale mientras haya escrituras sin confirmar
//     (`st_out==0`), asi que el orden escritura -> lectura se conserva y la
//     respuesta que llega en WAIT es siempre la de la carga;
//   * `wr_pending` dice que quedan escrituras sin confirmar: quien declare
//     terminada la GPU (halted, WARP_DONE) debe esperar a que baje;
//   * un error de memoria en una escritura llega tarde, cuando la instruccion ya
//     retiro: se anota en la bandera pegajosa `wr_error` (la borra `reset`).
module gpu_lsu2 #(parameter integer MAX_POSTED=8) (
    input clk, reset,
    input req_valid, output req_ready,
    input [2:0] req_tag, input [7:0] req_mask, input req_write,
    // Tamano del acceso (0 palabra, 1 byte, 2 media palabra) y, en las cargas,
    // si se extiende el signo. Es del warp entero: todas sus lanes ejecutan la
    // misma instruccion. En un STORE pequeno `req_data` llega ya replicado en
    // los carriles de la palabra y es la mascara de bytes la que elige.
    input [1:0] req_size, input req_signed,
    input [255:0] req_address, req_data,
    output reg rsp_valid, input rsp_ready,
    output reg [2:0] rsp_tag, output reg [255:0] rsp_data,
    output reg [7:0] rsp_error, output [7:0] occupied,
    output mem_req_valid, input mem_req_ready,
    output mem_req_write, output [31:0] mem_req_addr,
    output [127:0] mem_req_wdata, output [15:0] mem_req_wmask,
    input mem_rsp_valid, output mem_rsp_ready,
    input [127:0] mem_rsp_rdata, input mem_rsp_error,
    output wr_pending, output reg wr_error,

    // Ventana MMIO (todo 0x8xxx_xxxx en v2). Antes era fault y solo la alcanzaba el host
    // con la GPU parada; ahora la GPU puede leerla y escribirla mientras corre,
    // que es lo que hace falta para que sincronice con el video y para que se
    // mida a si misma.
    //
    // Es un camino ESCALAR a proposito: un acceso a MMIO se sirve de una lane
    // cada vez, la de menor indice pendiente, sin coalescer. Un registro de 32
    // bits no es una linea de 16 bytes, y ocho lanes escribiendo registros
    // distintos a la vez no tiene semantica util. Como los accesos a MMIO son
    // contados (unos pocos por frame), que sean lentos da igual.
    output mmio_req_valid, input mmio_req_ready,
    output mmio_req_write, output [31:0] mmio_req_addr,
    output [31:0] mmio_req_wdata,
    input mmio_rsp_valid, output mmio_rsp_ready,
    input [31:0] mmio_rsp_rdata, input mmio_rsp_error
);
    localparam IDLE=0, GROUP=1, ISSUE=2, WAIT=3, RETIRE=4, VECTOR_RESPONSE=5;
    reg [2:0] state, cursor, selected;
    reg [7:0] busy, has_pending, pending[0:7], errors[0:7];
    reg [255:0] addresses[0:7], values[0:7];
    reg stores[0:7];
    reg [1:0] sizes[0:7];
    reg signeds[0:7];
    // Grupo en vuelo, registrado en GROUP.
    reg [7:0] grp_lanes;
    reg [15:0] grp_sel;          // 2 bits por lane: que palabra de la linea le toca
    reg [31:0] grp_addr;
    reg [127:0] grp_wdata, rsp_line;
    reg [15:0] grp_wmask;
    reg grp_write, line_error, grp_mmio;
    reg [3:0] st_out;            // escrituras a RAM aceptadas y sin respuesta
    integer i;

    // Arbitraje de warp: identico al paso 7 de v1 (mascara plana rotada por
    // cursor + priority encoder fijo). Es independiente del ancho del backend.
    reg [2:0] rot_idx;
    wire [7:0] eligible=busy & (has_pending | {8{!rsp_valid}});
    wire [15:0] eligible_rot2={eligible,eligible};
    wire [7:0] rotated=eligible_rot2[{1'b0,cursor} +: 8];
    wire found=|rotated;
    always @* begin
        casez (rotated)
            8'b???????1: rot_idx=3'd0;
            8'b??????10: rot_idx=3'd1;
            8'b?????100: rot_idx=3'd2;
            8'b????1000: rot_idx=3'd3;
            8'b???10000: rot_idx=3'd4;
            8'b??100000: rot_idx=3'd5;
            8'b?1000000: rot_idx=3'd6;
            8'b10000000: rot_idx=3'd7;
            default:     rot_idx=3'd0;
        endcase
    end
    wire [2:0] pick=cursor+rot_idx;
    wire has_any=|pending[pick];

    // Formacion de grupo. Los muxes de 2048 bits se indexan con selected, ya
    // registrado en IDLE, para no encadenarlos tras la prioridad.
    wire [255:0] sel_addr=addresses[selected], sel_value=values[selected];
    wire [7:0] sel_pending=pending[selected];
    wire sel_write=stores[selected];
    wire [1:0] sel_size=sizes[selected];
    wire sel_signed=signeds[selected];
    reg [7:0] fault_lanes, cand_lanes, mmio_lanes;
    always @* begin
        for(i=0;i<8;i=i+1) begin
            // La ventana MMIO deja de ser fault: es un destino legitimo, solo
            // que por otro camino.
            //
            // MMIO v2: el espacio de dispositivos es TODO 0x8000_0000 arriba
            // (§2), no una pagina de 4 KiB. Aqui estaba la comparacion de 20
            // bits contra 0x80000, y es el SEXTO sitio de esta familia que
            // decide "esto es MMIO" por su cuenta -- despues de los cuatro
            // `gpu_system.v`, `gpu_system_bl8.v`, y sin contar el host.
            //
            // No lo encuentra ninguna busqueda de `32'h8000...`: aqui la
            // direccion no es un literal, es un RANGO DE BITS comparado contra
            // un prefijo. Es una septima forma de escribir una direccion,
            // ademas de las seis que el encargo lista.
            mmio_lanes[i]=sel_pending[i] && sel_addr[i*32+31];
            // Alineacion segun el tamano: la palabra a 4, la media palabra a 2 y
            // el byte a nada. MMIO es SOLO de palabras (mmio.md §4.1): un acceso
            // pequeno a un registro es fault, no se parte ni se trunca.
            fault_lanes[i]=sel_pending[i] &&
                ((|sel_addr[i*32+25 +: 7] && !mmio_lanes[i]) ||
                 (sel_size==2'd0 && |sel_addr[i*32 +: 2]) ||
                 (sel_size==2'd2 && sel_addr[i*32]) ||
                 (mmio_lanes[i] && sel_size!=2'd0));
            cand_lanes[i]=sel_pending[i] && !fault_lanes[i];
        end
    end
    // Lider = lane candidata de menor indice. Se elige con el MISMO priority
    // encoder fijo que el arbitraje de warp, no con un escaneo que propague un
    // "ya encontrado" lane a lane: eso ultimo sintetizaba como 8 niveles
    // encadenados y era la mitad del camino critico (ver lsu-v2.md).
    reg [2:0] leader_idx;
    always @* begin
        casez (cand_lanes)
            8'b???????1: leader_idx=3'd0;
            8'b??????10: leader_idx=3'd1;
            8'b?????100: leader_idx=3'd2;
            8'b????1000: leader_idx=3'd3;
            8'b???10000: leader_idx=3'd4;
            8'b??100000: leader_idx=3'd5;
            8'b?1000000: leader_idx=3'd6;
            8'b10000000: leader_idx=3'd7;
            default:     leader_idx=3'd0;
        endcase
    end
    wire [27:0] grp_line=sel_addr[{leader_idx,5'b0}+4 +: 28];

    // Pertenencia al grupo: las 8 comparaciones contra la linea de la lider
    // salen a la vez, no una detras de otra.
    wire [7:0] match;
    // Mascara de bytes de cada lane dentro de su palabra: las cuatro de una
    // palabra entera, o el byte / la mitad que toca segun la direccion.
    wire [3:0] lane_strb[0:7];
    genvar s, k, j;
    generate
        for(k=0;k<8;k=k+1) begin: group_match
            assign match[k]=cand_lanes[k] && (sel_addr[k*32+4 +: 28]==grp_line);
            assign lane_strb[k]=sel_size==2'd0 ? 4'b1111 :
                sel_size==2'd1 ? (4'b0001 << sel_addr[k*32 +: 2]) :
                (sel_addr[k*32+1] ? 4'b1100 : 4'b0011);
        end
    endgenerate
    // STORE: fusion por bytes. Entra en la transaccion toda lane del grupo
    // cuyos bytes no toca ninguna lane anterior del grupo (misma palabra y
    // mascaras que se solapan); si alguna los toca, espera otra vuelta. Asi dos
    // STOREH a las dos mitades de una palabra (dos pixeles RGB565 de lanes
    // vecinas) van en la misma transaccion, y cuando de verdad escriben el
    // mismo byte el orden sigue siendo el de siempre, la de menor lane
    // primero. Antes la unidad era la palabra: una lane por palabra aunque
    // escribieran bytes distintos, y 8 pixeles seguidos costaban 2
    // transacciones en vez de 1. Una palabra entera (STORE) solapa siempre con
    // otra en su palabra: ahi no cambia nada. En LOAD el duplicado es
    // inofensivo y se sirve gratis (match entero).
    //
    // Son 28 comparaciones de pareja, todas en paralelo: profundidad
    // constante, no un acumulador que recorra las lanes.
    wire [7:0] st_lanes;
    generate
        for(k=0;k<8;k=k+1) begin: store_lanes
            wire [7:0] overlap;
            for(j=0;j<8;j=j+1) begin: lower
                if(j<k) begin: earlier
                    assign overlap[j]=match[j] &&
                        (sel_addr[j*32+2 +: 2]==sel_addr[k*32+2 +: 2]) &&
                        |(lane_strb[j] & lane_strb[k]);
                end else begin: later
                    assign overlap[j]=1'b0;
                end
            end
            assign st_lanes[k]=match[k] && !(|overlap);
        end
    endgenerate
    // Cada byte de la linea, de la unica lane incluida que lo cubre (one-hot:
    // dos que lo cubrieran se solaparian y la mayor no estaria incluida). El
    // dato de un STOREB/STOREH llega replicado en la palabra, asi que el byte
    // b de la linea es el byte b%4 del valor de su lane.
    wire [127:0] n_wdata;
    wire [15:0] n_wmask;
    generate
        for(s=0;s<16;s=s+1) begin: line_bytes
            localparam integer WORD=s/4;
            wire [7:0] owner;
            for(k=0;k<8;k=k+1) begin: owners
                assign owner[k]=st_lanes[k] && (sel_addr[k*32+2 +: 2]==WORD[1:0]) && lane_strb[k][s%4];
            end
            assign n_wmask[s]=|owner;
            assign n_wdata[s*8 +: 8]=
                ({8{owner[0]}} & sel_value[0*32+(s%4)*8 +: 8]) |
                ({8{owner[1]}} & sel_value[1*32+(s%4)*8 +: 8]) |
                ({8{owner[2]}} & sel_value[2*32+(s%4)*8 +: 8]) |
                ({8{owner[3]}} & sel_value[3*32+(s%4)*8 +: 8]) |
                ({8{owner[4]}} & sel_value[4*32+(s%4)*8 +: 8]) |
                ({8{owner[5]}} & sel_value[5*32+(s%4)*8 +: 8]) |
                ({8{owner[6]}} & sel_value[6*32+(s%4)*8 +: 8]) |
                ({8{owner[7]}} & sel_value[7*32+(s%4)*8 +: 8]);
        end
    endgenerate
    // Si la lane lider apunta a MMIO, el grupo es ELLA SOLA: acceso escalar.
    // `cand_lanes[leader_idx]`: sin ella, cuando TODAS las lanes pendientes
    // fallan no hay lider y `leader_idx` vale 0 por defecto, asi que una lane 0
    // a MMIO que acaba de ser declarada fault salia igualmente por el bus. Una
    // escritura pequena a un registro habria escrito la palabra entera.
    wire leader_is_mmio=mmio_lanes[leader_idx] && cand_lanes[leader_idx];
    wire [7:0] leader_onehot=8'b1<<leader_idx;
    wire [31:0] leader_addr=sel_addr[{leader_idx,5'b0} +: 32];
    wire [31:0] leader_value=sel_value[{leader_idx,5'b0} +: 32];
    wire [7:0] n_lanes=leader_is_mmio ? leader_onehot
                     : sel_write ? st_lanes
                                 : match;
    // Cada lane lee la palabra que le toca por su propia direccion: esto no
    // necesita ni lazo ni logica, es una concatenacion.
    wire [15:0] n_sel={sel_addr[7*32+2 +: 2], sel_addr[6*32+2 +: 2],
                       sel_addr[5*32+2 +: 2], sel_addr[4*32+2 +: 2],
                       sel_addr[3*32+2 +: 2], sel_addr[2*32+2 +: 2],
                       sel_addr[1*32+2 +: 2], sel_addr[0*32+2 +: 2]};
    // pending tras retirar lo que se cierra en cada punto.
    wire [7:0] pending_after_fault=sel_pending & ~fault_lanes;
    wire [7:0] pending_after_group=sel_pending & ~grp_lanes;

    assign occupied=busy;
    assign req_ready=!reset && !busy[req_tag];
    // Una escritura posted sale mientras quepa en la cuenta; todo lo demas, con la
    // cuenta a cero (orden respecto a las escrituras anteriores).
    wire post_this=MAX_POSTED>0 && grp_write && !grp_mmio;
    assign mem_req_valid=!reset && state==ISSUE && !grp_mmio &&
                         (post_this ? st_out<MAX_POSTED : st_out==4'd0);
    assign mem_req_write=grp_write;
    assign mem_req_addr=grp_addr;
    assign mem_req_wdata=grp_wdata;
    assign mem_req_wmask=grp_wmask;
    assign mem_rsp_ready=(st_out!=4'd0) || (state==WAIT && !grp_mmio);
    assign wr_pending=st_out!=4'd0;
    wire st_inc=state==ISSUE && post_this && mem_req_valid && mem_req_ready;
    wire st_dec=mem_rsp_valid && mem_rsp_ready && st_out!=4'd0;

    assign mmio_req_valid=!reset && state==ISSUE && grp_mmio && st_out==4'd0;
    assign mmio_req_write=grp_write;
    assign mmio_req_addr=grp_addr;
    assign mmio_req_wdata=grp_wdata[31:0];
    assign mmio_rsp_ready=state==WAIT && grp_mmio;

    wire [255:0] completed_data;
    genvar lane;
    generate for(lane=0;lane<8;lane=lane+1) begin: response_lanes
        reg [31:0] words[0:7];
        wire [1:0] wsel=grp_sel[lane*2 +: 2];
        wire [31:0] word=rsp_line[{wsel,5'b0} +: 32];
        // Carga pequena: se elige el byte o la mitad de la palabra que trae la
        // linea, segun los dos bits bajos de la direccion de ESTA lane, y se
        // extiende con signo o con ceros. La palabra va tal cual.
        wire [1:0] low=sel_addr[lane*32 +: 2];
        wire [7:0] byte_sel=word[{low,3'b0} +: 8];
        wire [15:0] half_sel=low[1] ? word[31:16] : word[15:0];
        wire [31:0] loaded=
            sel_size==2'd1 ? (sel_signed ? {{24{byte_sel[7]}},byte_sel} : {24'b0,byte_sel}) :
            sel_size==2'd2 ? (sel_signed ? {{16{half_sel[15]}},half_sel} : {16'b0,half_sel}) :
            word;
        always @(posedge clk)
            if(!reset && state==RETIRE && grp_lanes[lane] && !grp_write)
                words[selected]<=loaded;
        assign completed_data[lane*32 +: 32]=words[selected];
    end endgenerate

    always @(posedge clk) begin
        if(reset) begin
            state<=IDLE; cursor<=0; selected<=0; busy<=0; has_pending<=0;
            rsp_valid<=0; rsp_tag<=0; rsp_data<=0; rsp_error<=0;
            grp_lanes<=0; grp_sel<=0; grp_addr<=0; grp_wdata<=0; grp_wmask<=0;
            grp_write<=0; rsp_line<=0; line_error<=0; grp_mmio<=0;
            st_out<=4'd0; wr_error<=1'b0;
            for(i=0;i<8;i=i+1) begin pending[i]<=0; errors[i]<=0; end
        end else begin
            st_out<=st_out+{3'b0,st_inc}-{3'b0,st_dec};
            if(st_dec && mem_rsp_error) wr_error<=1'b1;
            if(rsp_valid && rsp_ready) begin rsp_valid<=0; busy[rsp_tag]<=0; end
            if(req_valid && req_ready) begin
                busy[req_tag]<=1; pending[req_tag]<=req_mask; has_pending[req_tag]<=|req_mask;
                errors[req_tag]<=0;
                addresses[req_tag]<=req_address; values[req_tag]<=req_data; stores[req_tag]<=req_write;
                sizes[req_tag]<=req_size; signeds[req_tag]<=req_signed;
            end
            case(state)
                IDLE: if(found) begin
                    selected<=pick;
                    state<=has_any ? GROUP : VECTOR_RESPONSE;
                end
                // Las lanes fuera de rango se retiran aqui mismo, sin gastar
                // transaccion: un warp con 8 direcciones malas cuesta una vuelta,
                // no ocho como en v1.
                GROUP: begin
                    if(|fault_lanes) errors[selected]<=errors[selected] | fault_lanes;
                    if(|n_lanes) begin
                        grp_lanes<=n_lanes; grp_sel<=n_sel;
                        grp_mmio<=leader_is_mmio;
                        // El MMIO usa la direccion EXACTA de la lane, no la
                        // linea alineada: son registros de 32 bits.
                        grp_addr<=leader_is_mmio ? leader_addr : {grp_line,4'b0};
                        grp_wdata<=leader_is_mmio ? {4{leader_value}} : n_wdata;
                        grp_wmask<=sel_write ? n_wmask : 16'd0;
                        grp_write<=sel_write;
                        pending[selected]<=pending_after_fault;
                        state<=ISSUE;
                    end else begin
                        // Solo habia faults: cerrar y re-arbitrar.
                        pending[selected]<=pending_after_fault;
                        has_pending[selected]<=|pending_after_fault;
                        cursor<=selected+1'b1; state<=IDLE;
                    end
                end
                ISSUE: if(grp_mmio ? (mmio_req_valid && mmio_req_ready) : (mem_req_valid && mem_req_ready)) begin
                    // Escritura posted: no hay respuesta que esperar aqui.
                    if(post_this) begin line_error<=1'b0; state<=RETIRE; end
                    else state<=WAIT;
                end
                WAIT: if(grp_mmio) begin
                    if(mmio_rsp_valid) begin
                        // Se replica el dato en las cuatro palabras de la linea
                        // para que RETIRE lo reparta sin saber que era MMIO:
                        // elija el `sel` que elija, saca el valor correcto.
                        rsp_line<={4{mmio_rsp_rdata}};
                        line_error<=mmio_rsp_error; state<=RETIRE;
                    end
                end else if(mem_rsp_valid) begin
                    rsp_line<=mem_rsp_rdata; line_error<=mem_rsp_error; state<=RETIRE;
                end
                // El reparto de las 4 palabras a sus lanes vive en su propio
                // estado: encadenarlo con el ISSUE del grupo siguiente es justo
                // el tipo de cadena que costo Fmax en los pasos 1-7 de v1.
                RETIRE: begin
                    if(line_error) errors[selected]<=errors[selected] | grp_lanes;
                    pending[selected]<=pending_after_group;
                    has_pending[selected]<=|pending_after_group;
                    cursor<=selected+1'b1; state<=IDLE;
                end
                VECTOR_RESPONSE: begin
                    rsp_tag<=selected; rsp_data<=completed_data; rsp_error<=errors[selected];
                    rsp_valid<=1; cursor<=selected+1'b1; state<=IDLE;
                end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
