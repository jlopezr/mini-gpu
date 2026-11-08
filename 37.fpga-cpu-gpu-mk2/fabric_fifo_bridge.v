`default_nettype none

module fabric_fifo_bridge #(
    parameter FIFO_ADDR_WIDTH = 2   // depth = 4
)(
    // ================================================================
    // Master clock domain
    // ================================================================
    input wire master_clk,
    input wire master_reset,

    input  wire         req_valid,
    output wire         req_ready,
    input  wire         req_urgent,
    input  wire         req_write,
    input  wire [31:0]  req_addr,
    input  wire [127:0] req_wdata,
    input  wire [15:0]  req_wmask,

    output wire         rsp_valid,
    input  wire         rsp_ready,
    output wire [127:0] rsp_rdata,
    output wire         rsp_error,

    // ================================================================
    // Memory clock domain
    // ================================================================
    input wire mem_clk,
    input wire mem_reset,

    // Request FIFO -> memory fabric
    output wire         mem_req_empty,
    input  wire         mem_req_rd_en,
    output wire         mem_req_rd_valid,
    output wire [177:0] mem_req_data,

    // Response FIFO <- memory fabric
    output wire         mem_rsp_full,
    input  wire         mem_rsp_wr_en,
    input  wire [128:0] mem_rsp_data,

    // Solo diagnostico: {puntero de lectura, puntero de escritura} en Gray de
    // la FIFO de peticion. Se dejan sin conectar si no hacen falta.
    output wire [2*FIFO_ADDR_WIDTH+1:0] dbg_req_ptrs,
    // Solo diagnostico: {rsp_full, rsp_empty, rsp_hold_valid, rsp_read_pending}.
    output wire [3:0] dbg_rsp
);

    // Cada mitad de las FIFO se resetea con el reset de su dominio. Se probo un
    // reset combinado (cualquiera resetea ambos lados) y no arreglo nada, ademas
    // de bajar clk_mem a 81,6 MHz (395 errores de TRACE).
    wire rst_m = master_reset;
    wire rst_f = mem_reset;

    // ================================================================
    // Coordinacion de la salida de reset entre los dos dominios (RDC)
    //
    // Los dos resets nacen del mismo evento asincrono pero cada uno se libera
    // sincronizado con SU reloj, asi que salen en ciclos distintos. Mientras un
    // lado sigue en reset, sus punteros Gray no son validos para el otro: si el
    // otro empezara a escribir o leer, la FIFO quedaria desfasada (entrada
    // fantasma). Cada lado publica "estoy arriba" al otro con dos flops, y NO
    // pasa trafico hasta que los dos lo estan:
    //   - maestro: `req_ready` sigue en 0 hasta que el lado de memoria esta arriba;
    //   - memoria: la FIFO de peticiones se ve VACIA y la de respuestas LLENA
    //     hasta que el lado maestro esta arriba.
    // Las FIFO se siguen reseteando con el reset de cada dominio (asincrono, a la
    // vez en los dos lados porque la fuente es comun); esto solo retiene el
    // trafico durante la diferencia de liberacion.
    // ================================================================
    (* syn_preserve = "true" *) reg up_m = 1'b0;                // en master_clk
    (* syn_preserve = "true" *) reg up_f = 1'b0;                // en mem_clk
    (* syn_preserve = "true" *) reg [1:0] up_f_in_m = 2'b00;    // up_f visto en master_clk
    (* syn_preserve = "true" *) reg [1:0] up_m_in_f = 2'b00;    // up_m visto en mem_clk

    always @(posedge master_clk) begin
        up_m      <= ~rst_m;
        up_f_in_m <= {up_f_in_m[0], up_f};
    end
    always @(posedge mem_clk) begin
        up_f      <= ~rst_f;
        up_m_in_f <= {up_m_in_f[0], up_m};
    end

    wire run_m = ~rst_m & up_m & up_f_in_m[1];
    wire run_f = ~rst_f & up_f & up_m_in_f[1];

    // ================================================================
    // Request FIFO
    //
    // master -> memory
    //
    // [177]     urgent
    // [176]     write
    // [175:144] address
    // [143:16]  write data
    // [15:0]    write mask
    // ================================================================

    wire [FIFO_ADDR_WIDTH:0] req_dbg_wr, req_dbg_rd;
    wire         req_fifo_full;
    wire         req_fifo_empty;
    wire [177:0] req_fifo_data_out;
    wire         req_fifo_rd_valid;

    wire [177:0] req_fifo_data_in = {
        req_urgent,
        req_write,
        req_addr,
        req_wdata,
        req_wmask
    };

    assign req_ready = !req_fifo_full && run_m;

    wire req_fifo_wr_en =
        req_valid && req_ready;

    async_fifo #(
        .DATA_WIDTH (178),
        .ADDR_WIDTH (FIFO_ADDR_WIDTH)
    ) u_req_fifo (
        .clk_wr    (master_clk),
        .clk_rd    (mem_clk),

        .rst_wr_n  (~rst_m),
        .rst_rd_n  (~rst_f),

        .wr_en     (req_fifo_wr_en),
        .rd_en     (mem_req_rd_en),

        .data_in   (req_fifo_data_in),
        .data_out  (req_fifo_data_out),

        .rd_valid  (req_fifo_rd_valid),
        .full      (req_fifo_full),
        .empty     (req_fifo_empty),
        .dbg_wr_ptr_gray (req_dbg_wr),
        .dbg_rd_ptr_gray (req_dbg_rd)
    );
    assign dbg_req_ptrs = {req_dbg_rd, req_dbg_wr};

    assign mem_req_empty    = req_fifo_empty || !run_f;
    assign mem_req_rd_valid = req_fifo_rd_valid;
    assign mem_req_data     = req_fifo_data_out;

    // ================================================================
    // Response FIFO
    //
    // memory -> master
    //
    // [128]     error
    // [127:0]   read data
    // ================================================================

    wire         rsp_fifo_full;
    wire         rsp_fifo_empty;
    wire [128:0] rsp_fifo_data_out;
    wire         rsp_fifo_rd_valid;

    // A response that has left the async FIFO and is being held for
    // the master.
    reg          rsp_hold_valid;
    reg [128:0]  rsp_hold_data;

    // A synchronous FIFO read has already been requested and we're
    // waiting for rd_valid.
    reg rsp_read_pending;

    wire rsp_fifo_rd_en =
        !rsp_hold_valid &&
        !rsp_read_pending &&
        !rsp_fifo_empty;

    async_fifo #(
        .DATA_WIDTH (129),
        .ADDR_WIDTH (FIFO_ADDR_WIDTH)
    ) u_rsp_fifo (
        .clk_wr    (mem_clk),
        .clk_rd    (master_clk),

        .rst_wr_n  (~rst_f),
        .rst_rd_n  (~rst_m),

        .wr_en     (mem_rsp_wr_en),
        .rd_en     (rsp_fifo_rd_en),

        .data_in   (mem_rsp_data),
        .data_out  (rsp_fifo_data_out),

        .rd_valid  (rsp_fifo_rd_valid),
        .full      (rsp_fifo_full),
        .empty     (rsp_fifo_empty)
    );

    assign mem_rsp_full = rsp_fifo_full || !run_f;

    // ================================================================
    // Master-side response holding register
    //
    // async_fifo has synchronous read semantics:
    //
    //   rd_en
    //      |
    //      +--- one read cycle ---> rd_valid + data_out
    //
    // Once received, hold the response until rsp_ready.
    // ================================================================

    // ----------------------------------------------------------------
    // Respuestas sin peticion (fantasma)
    //
    // Una respuesta solo es valida si hay una peticion SUYA sin contestar. Las
    // respuestas llegan en el orden de las peticiones, asi que si una sobra, el
    // consumidor la toma por la contestacion a su siguiente peticion y TODAS las
    // posteriores llegan corridas una posicion. En la placa pasaba justo asi:
    // nada mas programarla, con el controlador sin ninguna transaccion, los
    // puertos 0 y 1 tenian ya una respuesta retenida; la primera busqueda de
    // instrucciones la tomaba como suya y el programa corria 16 bytes desplazado
    // (el PC final salia +0x10 en todas las pruebas, y los saltos caian mal).
    // En simulacion no ocurre; el origen en la placa sigue sin conocerse.
    //
    // Se cuenta lo pedido y lo entregado, y una respuesta que llega con la
    // cuenta a cero se TIRA sin ensenarla al consumidor. `phantom_seen` se queda
    // a 1 si alguna vez se tiro una, para poder ver en que puertos ocurre.
    // ----------------------------------------------------------------
    reg [7:0] outstanding;
    reg       phantom_seen;
    wire have_req = (outstanding != 8'd0);
    wire req_fire = req_valid && req_ready;
    wire rsp_take = rsp_hold_valid && have_req && rsp_ready;
    wire rsp_drop = rsp_hold_valid && !have_req;

    always @(posedge master_clk) begin
        if (rst_m) begin
            rsp_hold_valid  <= 1'b0;
            rsp_hold_data   <= 129'd0;
            rsp_read_pending <= 1'b0;
            outstanding     <= 8'd0;
            phantom_seen    <= 1'b0;
        end else begin

            // Bandera de UN ciclo (rd_en retrasado), no un flag que espere un
            // rd_valid: asi no puede quedarse pegada a 1 y dejar sin leer las
            // respuestas (mismo arreglo que prefetch_pending del fabric).
            rsp_read_pending <= rsp_fifo_rd_en;

            outstanding <= outstanding + {7'd0, req_fire} - {7'd0, rsp_take};
            if (rsp_drop) phantom_seen <= 1'b1;

            if (rsp_fifo_rd_valid) begin
                rsp_hold_data    <= rsp_fifo_data_out;
                rsp_hold_valid   <= 1'b1;
            end

            // `rd_en` solo se pide con la retencion vacia, asi que no coincide
            // con la carga de arriba.
            if (rsp_take || rsp_drop)
                rsp_hold_valid <= 1'b0;
        end
    end

    // {full, empty, hold_valid, phantom_seen}
    assign dbg_rsp = {rsp_fifo_full, rsp_fifo_empty, rsp_hold_valid, phantom_seen};

    assign rsp_valid = rsp_hold_valid && have_req;
    assign rsp_error = rsp_hold_data[128];
    assign rsp_rdata = rsp_hold_data[127:0];

endmodule

`default_nettype wire