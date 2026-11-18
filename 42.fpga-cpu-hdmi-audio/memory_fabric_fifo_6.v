`default_nettype none

module memory_fabric_fifo_6 #(
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000
)(
    input wire clk,
    input wire reset,

    // ================================================================
    // PORT 0
    // ================================================================
    input  wire         p0_req_empty,
    output wire         p0_req_rd_en,
    input  wire         p0_req_rd_valid,
    input  wire [177:0] p0_req_data,

    input  wire         p0_rsp_full,
    output wire         p0_rsp_wr_en,
    output wire [128:0] p0_rsp_data,

    // ================================================================
    // PORT 1
    // ================================================================
    input  wire         p1_req_empty,
    output wire         p1_req_rd_en,
    input  wire         p1_req_rd_valid,
    input  wire [177:0] p1_req_data,

    input  wire         p1_rsp_full,
    output wire         p1_rsp_wr_en,
    output wire [128:0] p1_rsp_data,

    // ================================================================
    // PORT 2
    // ================================================================
    input  wire         p2_req_empty,
    output wire         p2_req_rd_en,
    input  wire         p2_req_rd_valid,
    input  wire [177:0] p2_req_data,

    input  wire         p2_rsp_full,
    output wire         p2_rsp_wr_en,
    output wire [128:0] p2_rsp_data,

    // ================================================================
    // PORT 3
    // ================================================================
    input  wire         p3_req_empty,
    output wire         p3_req_rd_en,
    input  wire         p3_req_rd_valid,
    input  wire [177:0] p3_req_data,

    input  wire         p3_rsp_full,
    output wire         p3_rsp_wr_en,
    output wire [128:0] p3_rsp_data,

    // ================================================================
    // PORT 4
    // ================================================================
    input  wire         p4_req_empty,
    output wire         p4_req_rd_en,
    input  wire         p4_req_rd_valid,
    input  wire [177:0] p4_req_data,

    input  wire         p4_rsp_full,
    output wire         p4_rsp_wr_en,
    output wire [128:0] p4_rsp_data,

    // ================================================================
    // PORT 5
    // ================================================================
    input  wire         p5_req_empty,
    output wire         p5_req_rd_en,
    input  wire         p5_req_rd_valid,
    input  wire [177:0] p5_req_data,

    input  wire         p5_rsp_full,
    output wire         p5_rsp_wr_en,
    output wire [128:0] p5_rsp_data,

    // ================================================================
    // SDRAM controller
    // ================================================================
    output wire         sdram_req_valid,
    input  wire         sdram_req_ready,
    output wire         sdram_req_write,
    output wire [23:0]  sdram_req_addr,
    output wire [127:0] sdram_req_wdata,
    output wire [15:0]  sdram_req_wmask,

    input  wire         sdram_done,
    input  wire [127:0] sdram_rdata,

    output wire         busy,

    // Solo diagnostico: [5:0] head_valid, [11:6] prefetch_pending, [13:12]
    // state, [14] grant_valid, [15] cmd_full.
    output wire [15:0]  dbg,
    // Solo diagnostico: [3:0] cmd_count, [7:4] outstanding, [11:8] meta_count,
    // [15:12] rsp_count, [16] issue_valid, [17] rp_valid, [18] route_valid,
    // [19] go_q.
    output wire [19:0]  dbg2,
    // Solo diagnostico: puerto (one-hot) al que apunta el router de respuestas.
    output wire [5:0]   dbg3,
    // Solo diagnostico: primer valor que pasa por cada etapa del puerto de
    // destino. [2:0] cmd_master al primer cmd_pop, [8:3] backend_port al primer
    // go_q, [14:9] rp_port al primer rp_valid, [20:15] route (rsp_port_mem) al
    // primer rsp_pop, [21] cmd visto, [22] go visto, [23] rp visto, [24] route.
    output wire [24:0]  dbg4,
    // Solo diagnostico: foto del estado en el PRIMER ciclo tras soltar el reset.
    // [0] foto tomada, [1] issue_valid, [2] route_valid, [3] rp_valid, [4] go_q,
    // [6:5] state, [10:7] cmd_count, [14:11] outstanding, [15] 0.
    output wire [15:0]  dbg5,
    // Solo diagnostico: traza de los primeros 32 eventos tras el reset. Cada
    // entrada: [37:30] ciclo (8 bits, modulo 256), [29] route_fire, [28] rsp_pop,
    // [27] rsp_push, [26] complete, [25] go_q, [24] issue_go, [23] cmd_pop,
    // [22] cmd_push, [21:16] backend_port, [15:10] route_port, [9] issue_valid,
    // [8] route_valid, [7:4] cmd_count, [3:0] outstanding. Se congela al llenarse.
    input  wire [4:0]   dbg_trace_idx,
    output wire [37:0]  dbg_trace_data,
    output wire [5:0]   dbg_trace_n
);

    // ================================================================
    // Packet formats
    //
    // Request:
    //
    //   [177]     urgent
    //   [176]     write
    //   [175:144] byte address
    //   [143:16]  write data
    //   [15:0]    write mask
    //
    // Response:
    //
    //   [128]     error
    //   [127:0]   read data
    // ================================================================


    // Reset LOCAL, registrado: la red `reset` que llega de top.v tiene mucho
    // fanout y en Diamond (que fusiona las copias pese a `keep`) se suelta con
    // desfase entre flops; con un registro propio, junto al fabric, todo su
    // estado interno ve el mismo flanco de liberacion.
    reg rst_q = 1'b1;
    always @(posedge clk) rst_q <= reset;

    localparam MASTER_0 = 3'd0;
    localparam MASTER_1 = 3'd1;
    localparam MASTER_2 = 3'd2;
    localparam MASTER_3 = 3'd3;
    localparam MASTER_4 = 3'd4;
    localparam MASTER_5 = 3'd5;

    localparam ST_IDLE    = 2'd0;
    localparam ST_CAPTURE = 2'd1;
    localparam ST_CHECK   = 2'd2;

    reg [1:0] state;

    reg [2:0] grant; reg grant_valid; reg [2:0] active_master;

    // ================================================================
    // One prefetched request per port
    // ================================================================

    reg [177:0] head0_data;
    reg [177:0] head1_data;
    reg [177:0] head2_data;
    reg [177:0] head3_data;
    reg [177:0] head4_data;
    reg [177:0] head5_data;

    reg head0_valid;
    reg head1_valid;
    reg head2_valid;
    reg head3_valid;
    reg head4_valid;
    reg head5_valid;

    // A read has been issued to the FIFO but rd_valid has not arrived yet.
    reg prefetch0_pending;
    reg prefetch1_pending;
    reg prefetch2_pending;
    reg prefetch3_pending;
    reg prefetch4_pending;
    reg prefetch5_pending;

    // Start a FIFO read whenever its head register is free.
    //
    // pending prevents issuing several reads while waiting for the
    // synchronous FIFO read result.
    assign p0_req_rd_en =
        !head0_valid && !prefetch0_pending && !p0_req_empty;

    assign p1_req_rd_en =
        !head1_valid && !prefetch1_pending && !p1_req_empty;

    assign p2_req_rd_en =
        !head2_valid && !prefetch2_pending && !p2_req_empty;

    assign p3_req_rd_en =
        !head3_valid && !prefetch3_pending && !p3_req_empty;

    assign p4_req_rd_en =
        !head4_valid && !prefetch4_pending && !p4_req_empty;

    assign p5_req_rd_en =
        !head5_valid && !prefetch5_pending && !p5_req_empty;

    // ================================================================
    // Prefetch engines
    // ================================================================

    always @(posedge clk) begin
        if (rst_q) begin
            head0_valid      <= 1'b0;
            prefetch0_pending <= 1'b0;
        end else begin

            // Bandera de UN ciclo (rd_en retrasado), no un flag que espere un
            // rd_valid: asi no puede quedarse pegada a 1 y dejar el puerto sordo.
            prefetch0_pending <= p0_req_rd_en;

            if (p0_req_rd_valid) begin
                head0_data         <= p0_req_data;
                head0_valid        <= 1'b1;
            end

            if (state == ST_CAPTURE &&
                active_master == MASTER_0)
                head0_valid <= 1'b0;
        end
    end

    always @(posedge clk) begin
        if (rst_q) begin
            head1_valid       <= 1'b0;
            prefetch1_pending <= 1'b0;
        end else begin

            // Bandera de UN ciclo (rd_en retrasado), no un flag que espere un
            // rd_valid: asi no puede quedarse pegada a 1 y dejar el puerto sordo.
            prefetch1_pending <= p1_req_rd_en;

            if (p1_req_rd_valid) begin
                head1_data         <= p1_req_data;
                head1_valid        <= 1'b1;
            end

            if (state == ST_CAPTURE &&
                active_master == MASTER_1)
                head1_valid <= 1'b0;
        end
    end

    always @(posedge clk) begin
        if (rst_q) begin
            head2_valid       <= 1'b0;
            prefetch2_pending <= 1'b0;
        end else begin

            // Bandera de UN ciclo (rd_en retrasado), no un flag que espere un
            // rd_valid: asi no puede quedarse pegada a 1 y dejar el puerto sordo.
            prefetch2_pending <= p2_req_rd_en;

            if (p2_req_rd_valid) begin
                head2_data         <= p2_req_data;
                head2_valid        <= 1'b1;
            end

            if (state == ST_CAPTURE &&
                active_master == MASTER_2)
                head2_valid <= 1'b0;
        end
    end

    always @(posedge clk) begin
        if (rst_q) begin
            head3_valid       <= 1'b0;
            prefetch3_pending <= 1'b0;
        end else begin

            // Bandera de UN ciclo (rd_en retrasado), no un flag que espere un
            // rd_valid: asi no puede quedarse pegada a 1 y dejar el puerto sordo.
            prefetch3_pending <= p3_req_rd_en;

            if (p3_req_rd_valid) begin
                head3_data         <= p3_req_data;
                head3_valid        <= 1'b1;
            end

            if (state == ST_CAPTURE &&
                active_master == MASTER_3)
                head3_valid <= 1'b0;
        end
    end

    always @(posedge clk) begin
        if (rst_q) begin
            head4_valid       <= 1'b0;
            prefetch4_pending <= 1'b0;
        end else begin
            // Bandera de UN ciclo (rd_en retrasado), no un flag que espere un
            // rd_valid: asi no puede quedarse pegada a 1 y dejar el puerto sordo.
            prefetch4_pending <= p4_req_rd_en;
            if (p4_req_rd_valid) begin
                head4_data        <= p4_req_data;
                head4_valid       <= 1'b1;
            end
            if (state == ST_CAPTURE && active_master == MASTER_4)
                head4_valid <= 1'b0;
        end
    end

    always @(posedge clk) begin
        if (rst_q) begin
            head5_valid       <= 1'b0;
            prefetch5_pending <= 1'b0;
        end else begin
            // Bandera de UN ciclo (rd_en retrasado), no un flag que espere un
            // rd_valid: asi no puede quedarse pegada a 1 y dejar el puerto sordo.
            prefetch5_pending <= p5_req_rd_en;
            if (p5_req_rd_valid) begin
                head5_data        <= p5_req_data;
                head5_valid       <= 1'b1;
            end
            if (state == ST_CAPTURE && active_master == MASTER_5)
                head5_valid <= 1'b0;
        end
    end

    // ================================================================
    // Arbitration
    // ================================================================

    reg [2:0] rr_next;

    wire urgent0 = head0_valid && head0_data[177];
    wire urgent1 = head1_valid && head1_data[177];
    wire urgent2 = head2_valid && head2_data[177];
    wire urgent3 = head3_valid && head3_data[177];
    wire urgent4 = head4_valid && head4_data[177];
    wire urgent5 = head5_valid && head5_data[177];

    // Round-robin con dos pasadas: primero las urgentes y, si no hay ninguna,
    // todas las peticiones, siempre empezando en `rr_next`.
    //
    // Antes eran dos `case (rr_next)` de seis ramas con cadenas `if/else if` de
    // seis peticiones, y el camino critico de la 36 (sdram_clk 95,5 MHz) era
    // `head3_valid -> grant`: 11 LUT en serie. Ahora las dos pasadas se calculan
    // A LA VEZ con la misma funcion y solo al final se elige una:
    //   * `ge` deja pasar las posiciones >= rr_next; si hay alguna, gana la de
    //     menor indice entre ellas (la primera tras rr_next);
    //   * si no, gana la de menor indice de todas (se da la vuelta).
    // Es el orden de las cadenas de antes, sin la cadena.
    function [3:0] rr_pick;           // {hay alguna, indice}
        input [5:0] v;
        input [2:0] r;
        reg [5:0] ge, hi, p;
        reg [2:0] idx;
        begin
            ge = 6'b111111 << r;
            hi = v & ge;
            p  = (hi != 6'd0) ? hi : v;
            casez (p)
                6'b?????1: idx = 3'd0;
                6'b????10: idx = 3'd1;
                6'b???100: idx = 3'd2;
                6'b??1000: idx = 3'd3;
                6'b?10000: idx = 3'd4;
                default:   idx = 3'd5;
            endcase
            rr_pick = {(v != 6'd0), idx};
        end
    endfunction

    wire [5:0] arb_urgent = {urgent5, urgent4, urgent3, urgent2, urgent1, urgent0};
    wire [5:0] arb_any    = {head5_valid, head4_valid, head3_valid,
                             head2_valid, head1_valid, head0_valid};
    wire [3:0] pick_urgent = rr_pick(arb_urgent, rr_next);
    wire [3:0] pick_any    = rr_pick(arb_any, rr_next);

    always @* begin
        grant       = rr_next;
        grant_valid = 1'b0;
        if (pick_urgent[3]) begin
            grant       = pick_urgent[2:0];
            grant_valid = 1'b1;
        end else if (pick_any[3]) begin
            grant       = pick_any[2:0];
            grant_valid = 1'b1;
        end
    end

    // ================================================================
    // Selected head
    // ================================================================

    wire [177:0] active_head_data =
        (active_master == MASTER_0) ? head0_data :
        (active_master == MASTER_1) ? head1_data :
        (active_master == MASTER_2) ? head2_data :
        (active_master == MASTER_3) ? head3_data :
        (active_master == MASTER_4) ? head4_data :
                                      head5_data;

    // ================================================================
    // Global command queue
    // ================================================================

    localparam QUEUE_ADDR_WIDTH = 3;
    localparam QUEUE_DEPTH = (1 << QUEUE_ADDR_WIDTH);

    (* syn_ramstyle = "registers" *) reg [2:0]   cmd_master [0:QUEUE_DEPTH-1];
    (* syn_ramstyle = "registers" *) reg         cmd_write  [0:QUEUE_DEPTH-1];
    (* syn_ramstyle = "registers" *) reg [31:0]  cmd_addr   [0:QUEUE_DEPTH-1];
    (* syn_ramstyle = "registers" *) reg [127:0] cmd_wdata  [0:QUEUE_DEPTH-1];
    (* syn_ramstyle = "registers" *) reg [15:0]  cmd_wmask  [0:QUEUE_DEPTH-1];
    (* syn_ramstyle = "registers" *) reg         cmd_error  [0:QUEUE_DEPTH-1];

    reg [QUEUE_ADDR_WIDTH-1:0] cmd_wr_ptr;
    reg [QUEUE_ADDR_WIDTH-1:0] cmd_rd_ptr;
    reg [QUEUE_ADDR_WIDTH:0]   cmd_count;

    reg         intake_write;
    reg [31:0]  intake_addr;
    reg [127:0] intake_wdata;
    reg [15:0]  intake_wmask;

    wire cmd_full  = (cmd_count == QUEUE_DEPTH);
    wire cmd_empty = (cmd_count == 0);
    wire cmd_push  = (state == ST_CHECK) && !cmd_full;

    // ================================================================
    // Pipelined SDRAM backend
    //
    // The controller accepts a request whenever the slot of the target bank
    // is free, so several requests can be inside it at once. It returns one
    // `sdram_done` per accepted request, IN ORDER.
    //
    // Because completions are in order, the destination of each response is
    // kept in a plain FIFO (`meta`), pushed when the controller accepts the
    // request and popped when its `sdram_done` arrives. Invalid addresses
    // never reach the controller; they travel through the same FIFO flagged
    // as errors so they cannot overtake earlier requests.
    //
    // Credit rule: a request is issued only if
    //     outstanding = meta entries + response-queue entries
    // is below QUEUE_DEPTH. Then every `sdram_done` finds room in the
    // response queue and the controller never needs backpressure on its
    // output.
    // ================================================================

    reg         issue_valid;
    reg         issue_error;
    reg [5:0]   backend_port;
    reg         backend_write;
    reg [31:0]  backend_addr;
    reg [127:0] backend_wdata;
    reg [15:0]  backend_wmask;

    reg [QUEUE_ADDR_WIDTH:0] outstanding;

    wire credit_ok = (outstanding < QUEUE_DEPTH);

    // The issue stage is consumed when the controller takes the request, or
    // immediately for an error.
    wire issue_go = issue_valid && credit_ok &&
                    (issue_error || sdram_req_ready);

    // `issue_go` depende de `sdram_req_ready`, que sale del FSM del controlador.
    // Alimentando ademas el empuje a `meta` (RAM con escritura condicionada), su
    // contador y el de creditos, llegaba a tener fan-out 32-51 y 2,6-3,3 ns de
    // ruteo: era el muro de sdram_clk de la 36 (85,5 / 88,9 MHz). Ahora solo
    // limpia `issue_valid` y se REGISTRA en `go_q`; el empuje ocurre un ciclo
    // despues, con `backend_port` e `issue_error` todavia intactos (la etapa de
    // emision no se recarga hasta ese mismo flanco, ver `cmd_pop`). Un `done`
    // tarda al menos cuatro ciclos en llegar tras aceptar el controlador, y el
    // siguiente `issue_go` no puede ocurrir antes de dos ciclos, cuando
    // `outstanding` ya cuenta esta peticion.
    reg go_q;

    // El siguiente comando solo entra cuando la etapa de emision ya esta
    // VACIA, no en el mismo ciclo en que el controlador toma el anterior.
    // Con `(!issue_valid || issue_go)`, `sdram_req_ready` (que sale del FSM del
    // controlador) llegaba a los ~200 enables de backend_* y a los punteros de
    // la cola: era el camino de 10,7 ns de la 36 (issue_go con fan-out 51 y
    // 3,3 ns de ruteo, sdram_clk 93,7 MHz). Cuesta un ciclo de vacio entre dos
    // peticiones: el controlador no admite una rafaga BL8 en menos de cuatro.
    wire cmd_pop = !issue_valid && !cmd_empty;

    (* syn_ramstyle = "registers" *) reg [5:0]  meta_port  [0:QUEUE_DEPTH-1];
    (* syn_ramstyle = "registers" *) reg        meta_error [0:QUEUE_DEPTH-1];
    reg [QUEUE_ADDR_WIDTH-1:0] meta_wr_ptr;
    reg [QUEUE_ADDR_WIDTH-1:0] meta_rd_ptr;
    reg [QUEUE_ADDR_WIDTH:0]   meta_count;

    wire meta_empty = (meta_count == 0);

    // Head of the in-order completion FIFO. An error completes on its own; a
    // normal request completes with the controller's `sdram_done`.
    wire complete = !meta_empty &&
                    (meta_error[meta_rd_ptr] || sdram_done);

    // ================================================================
    // Global response queue and registered router
    // ================================================================

    // El puerto viaja en los bits [134:129], junto al dato.
    (* syn_ramstyle = "registers" *) reg [134:0] rsp_data_mem [0:QUEUE_DEPTH-1];
    reg [QUEUE_ADDR_WIDTH-1:0] rsp_wr_ptr;
    reg [QUEUE_ADDR_WIDTH-1:0] rsp_rd_ptr;
    reg [QUEUE_ADDR_WIDTH:0]   rsp_count;

    wire rsp_queue_full  = (rsp_count == QUEUE_DEPTH);
    wire rsp_queue_empty = (rsp_count == 0);
    // La finalizacion se REGISTRA antes de entrar en la cola: `complete` mira
    // `meta_error[meta_rd_ptr]` y `sdram_done`, y si ademas habilitaba los 129
    // bits de `rsp_data_mem` era un fanout combinacional que cruzaba media
    // FPGA. `rp_data` captura sin habilitacion (`sdram_rdata` solo vale en el
    // ciclo de `done`, y `rp_valid` dice cuando importa).
    //
    // La regla de creditos sigue valiendo: `outstanding` baja con `rsp_pop`, asi
    // que la peticion que espera en `rp_*` sigue contando y la cola tiene sitio.
    reg         rp_valid;
    reg [5:0]   rp_port;
    reg [128:0] rp_data;

    always @(posedge clk) begin
        rp_valid <= !rst_q && complete;
        rp_port  <= meta_port[meta_rd_ptr];
        rp_data  <= meta_error[meta_rd_ptr] ? {1'b1, 128'd0}
                                            : {1'b0, sdram_rdata};
    end

    wire rsp_push = rp_valid;

    reg         route_valid;
    reg [5:0]   route_port;
    reg [128:0] route_data;
    wire rsp_pop = !route_valid && !rsp_queue_empty;

    assign p0_rsp_wr_en = route_valid && route_port[0] && !p0_rsp_full;
    assign p1_rsp_wr_en = route_valid && route_port[1] && !p1_rsp_full;
    assign p2_rsp_wr_en = route_valid && route_port[2] && !p2_rsp_full;
    assign p3_rsp_wr_en = route_valid && route_port[3] && !p3_rsp_full;
    assign p4_rsp_wr_en = route_valid && route_port[4] && !p4_rsp_full;
    assign p5_rsp_wr_en = route_valid && route_port[5] && !p5_rsp_full;

    wire route_fire =
        p0_rsp_wr_en || p1_rsp_wr_en || p2_rsp_wr_en ||
        p3_rsp_wr_en || p4_rsp_wr_en || p5_rsp_wr_en;

    assign p0_rsp_data = route_data;
    assign p1_rsp_data = route_data;
    assign p2_rsp_data = route_data;
    assign p3_rsp_data = route_data;
    assign p4_rsp_data = route_data;
    assign p5_rsp_data = route_data;

    // ================================================================
    // SDRAM interface
    // ================================================================

    assign sdram_req_valid = issue_valid && !issue_error && credit_ok;
    assign sdram_req_write = backend_write;
    assign sdram_req_addr  = backend_addr[24:1];
    assign sdram_req_wdata = backend_wdata;
    assign sdram_req_wmask = backend_wmask;

    assign dbg = {cmd_full, grant_valid, state,
                  prefetch5_pending, prefetch4_pending, prefetch3_pending,
                  prefetch2_pending, prefetch1_pending, prefetch0_pending,
                  head5_valid, head4_valid, head3_valid,
                  head2_valid, head1_valid, head0_valid};

    assign dbg3 = route_port;
    assign dbg2 = {go_q, route_valid, rp_valid, issue_valid,
                   rsp_count, meta_count, outstanding, cmd_count};

    assign busy = (state != ST_IDLE) || !cmd_empty || issue_valid ||
                  (outstanding != 0) || go_q || rp_valid || route_valid;

    // Command and response queue storage/counts. Both queues support one push
    // and one pop in the same cycle without changing their occupancy.
    always @(posedge clk) begin
        if (rst_q) begin
            cmd_wr_ptr <= 0;
            cmd_rd_ptr <= 0;
            cmd_count  <= 0;
            rsp_wr_ptr <= 0;
            rsp_rd_ptr <= 0;
            rsp_count  <= 0;
        end else begin
            if (cmd_push) begin
                cmd_master[cmd_wr_ptr] <= active_master;
                cmd_write[cmd_wr_ptr]  <= intake_write;
                cmd_addr[cmd_wr_ptr]   <= intake_addr;
                cmd_wdata[cmd_wr_ptr]  <= intake_wdata;
                cmd_wmask[cmd_wr_ptr]  <= intake_wmask;
                cmd_error[cmd_wr_ptr]  <=
                    (intake_addr >= SDRAM_SIZE_BYTES) ||
                    (intake_addr[3:0] != 4'b0000);
                cmd_wr_ptr <= cmd_wr_ptr + 1'b1;
            end
            if (cmd_pop)
                cmd_rd_ptr <= cmd_rd_ptr + 1'b1;
            case ({cmd_push, cmd_pop})
                2'b10: cmd_count <= cmd_count + 1'b1;
                2'b01: cmd_count <= cmd_count - 1'b1;
                default: cmd_count <= cmd_count;
            endcase

            if (rsp_push) begin
                rsp_data_mem[rsp_wr_ptr] <= {rp_port, rp_data};
                rsp_wr_ptr <= rsp_wr_ptr + 1'b1;
            end
            if (rsp_pop)
                rsp_rd_ptr <= rsp_rd_ptr + 1'b1;
            case ({rsp_push, rsp_pop})
                2'b10: rsp_count <= rsp_count + 1'b1;
                2'b01: rsp_count <= rsp_count - 1'b1;
                default: rsp_count <= rsp_count;
            endcase
        end
    end

    // Frontend: arbitrate, capture and enqueue independently of SDRAM.
    always @(posedge clk) begin
        if (rst_q) begin
            state         <= ST_IDLE;
            rr_next       <= MASTER_0;
            active_master <= MASTER_0;
            intake_write  <= 1'b0;
            intake_addr   <= 32'd0;
            intake_wdata  <= 128'd0;
            intake_wmask  <= 16'd0;
        end else begin
            case (state)
                ST_IDLE: begin
                    if (grant_valid && !cmd_full) begin
                        active_master <= grant;
                        state <= ST_CAPTURE;
                    end
                end
                ST_CAPTURE: begin
                    intake_write <= active_head_data[176];
                    intake_addr  <= active_head_data[175:144];
                    intake_wdata <= active_head_data[143:16];
                    intake_wmask <= active_head_data[15:0];
                    state <= ST_CHECK;
                end
                ST_CHECK: begin
                    if (!cmd_full) begin
                        case (active_master)
                            MASTER_0: rr_next <= MASTER_1;
                            MASTER_1: rr_next <= MASTER_2;
                            MASTER_2: rr_next <= MASTER_3;
                            MASTER_3: rr_next <= MASTER_4;
                            MASTER_4: rr_next <= MASTER_5;
                            default:  rr_next <= MASTER_0;
                        endcase
                        state <= ST_IDLE;
                    end
                end
                default: state <= ST_IDLE;
            endcase
        end
    end

    // Issue stage: holds the next request until the controller takes it.
    always @(posedge clk) begin
        if (rst_q) begin
            issue_valid   <= 1'b0;
            issue_error   <= 1'b0;
            backend_port  <= 6'b000001;
            backend_write <= 1'b0;
            backend_addr  <= 32'd0;
            backend_wdata <= 128'd0;
            backend_wmask <= 16'd0;
        end else begin
            if (issue_go)
                issue_valid <= 1'b0;

            if (cmd_pop) begin
                case (cmd_master[cmd_rd_ptr])
                    MASTER_0: backend_port <= 6'b000001;
                    MASTER_1: backend_port <= 6'b000010;
                    MASTER_2: backend_port <= 6'b000100;
                    MASTER_3: backend_port <= 6'b001000;
                    MASTER_4: backend_port <= 6'b010000;
                    default:  backend_port <= 6'b100000;
                endcase
                backend_write <= cmd_write[cmd_rd_ptr];
                backend_addr  <= cmd_addr[cmd_rd_ptr];
                backend_wdata <= cmd_wdata[cmd_rd_ptr];
                backend_wmask <= cmd_wmask[cmd_rd_ptr];
                issue_error   <= cmd_error[cmd_rd_ptr];
                issue_valid   <= 1'b1;
            end
        end
    end

    // In-order completion FIFO and credit counter.
    // El reset de esta etapa se alarga un ciclo mas que rst_q.
    reg rst_qq = 1'b1;
    always @(posedge clk) rst_qq <= rst_q;
    always @(posedge clk) begin
        if (rst_q || rst_qq) begin
            meta_wr_ptr <= 0;
            meta_rd_ptr <= 0;
            meta_count  <= 0;
            outstanding <= 0;
            go_q        <= 1'b0;
        end else begin
            go_q <= issue_go;
            if (go_q) begin
                meta_port[meta_wr_ptr]  <= backend_port;
                meta_error[meta_wr_ptr] <= issue_error;
                meta_wr_ptr <= meta_wr_ptr + 1'b1;
            end
            if (complete)
                meta_rd_ptr <= meta_rd_ptr + 1'b1;
            case ({go_q, complete})
                2'b10: meta_count <= meta_count + 1'b1;
                2'b01: meta_count <= meta_count - 1'b1;
                default: meta_count <= meta_count;
            endcase

            case ({go_q, rsp_pop})
                2'b10: outstanding <= outstanding + 1'b1;
                2'b01: outstanding <= outstanding - 1'b1;
                default: outstanding <= outstanding;
            endcase
        end
    end

`ifndef SYNTHESIS
    // A completion without a pending request would mean the controller broke
    // the one-done-per-request contract.
    always @(posedge clk) begin
        if (!rst_q && sdram_done && meta_empty)
            $error("memory_fabric_fifo_6: sdram_done sin peticion pendiente");
        if (!rst_q && sdram_done && !meta_empty && meta_error[meta_rd_ptr])
            $error("memory_fabric_fifo_6: sdram_done con un error en cabeza");
    end
`endif

    // Diagnostico: captura el PRIMER valor de puerto en cada etapa.
    reg [2:0] f_cmd_master = 3'd0;
    reg [5:0] f_backend = 6'd0, f_rp = 6'd0, f_route = 6'd0;
    reg f_cmd_seen = 1'b0, f_go_seen = 1'b0, f_rp_seen = 1'b0, f_route_seen = 1'b0;
    always @(posedge clk) begin
        if (cmd_pop && !f_cmd_seen) begin
            f_cmd_master <= cmd_master[cmd_rd_ptr];
            f_cmd_seen <= 1'b1;
        end
        if (go_q && !f_go_seen) begin
            f_backend <= backend_port;
            f_go_seen <= 1'b1;
        end
        if (rp_valid && !f_rp_seen) begin
            f_rp <= rp_port;
            f_rp_seen <= 1'b1;
        end
        if (rsp_pop && !f_route_seen) begin
            f_route <= rsp_data_mem[rsp_rd_ptr][134:129];
            f_route_seen <= 1'b1;
        end
    end
    assign dbg4 = {f_route_seen, f_rp_seen, f_go_seen, f_cmd_seen,
                   f_route, f_rp, f_backend, f_cmd_master};

    // Foto del estado justo cuando `reset` pasa de 1 a 0 por primera vez.
    reg prev_reset = 1'b1, rel_seen = 1'b0;
    reg [14:0] rel_snap = 15'd0;
    always @(posedge clk) begin
        prev_reset <= rst_q;
        if (prev_reset && !rst_q && !rel_seen) begin
            rel_seen <= 1'b1;
            rel_snap <= {outstanding, cmd_count, state, go_q, rp_valid,
                         route_valid, issue_valid};
        end
    end
    assign dbg5 = {rel_snap, rel_seen};

    // Traza de los primeros 32 eventos tras el reset local.
    // Traza corta (16 entradas) de la etapa meta: en cada go_q / complete /
    // sdram_done guarda {ciclo[37:30], go_q[29], complete[28], sdram_done[27],
    // meta_wr_ptr[26:24], meta_rd_ptr[23:21], meta_count[20:17],
    // meta_port[rd_ptr][16:11], backend_port[10:5]}.
    (* syn_ramstyle = "registers" *) reg [37:0] trace_mem [0:15];
    reg [4:0] trace_n = 5'd0;
    reg [7:0] trace_cyc = 8'd0;
    wire trace_ev = go_q | complete | sdram_done;
    // Sin reset: captura tambien durante el reset. Bits [4]=rst_q, [3]=rst_qq.
    always @(posedge clk) begin
        trace_cyc <= trace_cyc + 1'b1;
        if (trace_ev && !trace_n[4]) begin
            trace_mem[trace_n[3:0]] <= {trace_cyc, go_q, complete, sdram_done,
                                        meta_wr_ptr, meta_rd_ptr, meta_count,
                                        meta_port[meta_rd_ptr], backend_port,
                                        rst_q, rst_qq, 3'd0};
            trace_n <= trace_n + 1'b1;
        end
    end
    assign dbg_trace_data = trace_mem[dbg_trace_idx[3:0]];
    assign dbg_trace_n = {1'b0, trace_n};

    // Registered response router. A blocked destination cannot alter or lose
    // the staged response, while the global response queue absorbs later ones.
    always @(posedge clk) begin
        if (rst_q) begin
            route_valid <= 1'b0;
            route_port  <= 6'b000001;
            route_data  <= 129'd0;
        end else begin
            if (rsp_pop) begin
                route_valid <= 1'b1;
                route_port  <= rsp_data_mem[rsp_rd_ptr][134:129];
                route_data  <= rsp_data_mem[rsp_rd_ptr][128:0];
            end else if (route_fire) begin
                route_valid <= 1'b0;
            end
        end
    end

endmodule

`default_nettype wire
