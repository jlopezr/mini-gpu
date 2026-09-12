`default_nettype none

module memory_fabric_4 #(
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000
) (
    input wire clk,
    input wire reset,

    // ============================================================
    // PORT 0
    // Ejemplo: CPU
    // ============================================================

    input  wire         p0_req_valid,
    output wire         p0_req_ready,
    input  wire         p0_req_write,
    input  wire [31:0]  p0_req_addr,
    input  wire [127:0] p0_req_wdata,
    input  wire [15:0]  p0_req_wmask,

    output wire         p0_rsp_valid,
    input  wire         p0_rsp_ready,
    output wire [127:0] p0_rsp_rdata,
    output wire         p0_rsp_error,

    // ============================================================
    // PORT 1
    // Ejemplo: GPU
    // ============================================================

    input  wire         p1_req_valid,
    output wire         p1_req_ready,
    input  wire         p1_req_write,
    input  wire [31:0]  p1_req_addr,
    input  wire [127:0] p1_req_wdata,
    input  wire [15:0]  p1_req_wmask,

    output wire         p1_rsp_valid,
    input  wire         p1_rsp_ready,
    output wire [127:0] p1_rsp_rdata,
    output wire         p1_rsp_error,

    // ============================================================
    // PORT 2
    // Ejemplo: vídeo
    //
    // urgent permite saltarse temporalmente el round-robin.
    // ============================================================

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

    // ============================================================
    // PORT 3
    // Ejemplo: monitor/debug
    // ============================================================

    input  wire         p3_req_valid,
    output wire         p3_req_ready,
    input  wire         p3_req_write,
    input  wire [31:0]  p3_req_addr,
    input  wire [127:0] p3_req_wdata,
    input  wire [15:0]  p3_req_wmask,

    output wire         p3_rsp_valid,
    input  wire         p3_rsp_ready,
    output wire [127:0] p3_rsp_rdata,
    output wire         p3_rsp_error,

    // ============================================================
    // sdram_controller_128
    //
    // El controller usa dirección de PALABRAS de 16 bits.
    // ============================================================

    output wire         sdram_req_valid,
    input  wire         sdram_req_ready,
    output wire         sdram_req_write,
    output wire [23:0]  sdram_req_addr,
    output wire [127:0] sdram_req_wdata,
    output wire [15:0]  sdram_req_wmask,

    input  wire         sdram_done,
    input  wire [127:0] sdram_rdata,

    output wire         busy
);

    localparam [1:0]
        MASTER_0 = 2'd0,
        MASTER_1 = 2'd1,
        MASTER_2 = 2'd2,
        MASTER_3 = 2'd3;

    localparam [1:0]
        ST_IDLE  = 2'd0,
        ST_ISSUE = 2'd1,
        ST_WAIT  = 2'd2,
        ST_RESP  = 2'd3;

    reg [1:0] state;

    // Master al que daremos prioridad primero.
    reg [1:0] rr_ptr;

    // Master propietario de la transacción actual.
    reg [1:0] active_master;

    // Request latched.
    reg         active_write;
    reg [31:0]  active_addr;
    reg [127:0] active_wdata;
    reg [15:0]  active_wmask;

    // Response latched.
    reg [127:0] response_data;
    reg         response_error;

    // ============================================================
    // Arbitration
    // ============================================================

    reg       grant_valid;
    reg [1:0] grant_master;

    always @* begin

        grant_valid  = 1'b0;
        grant_master = MASTER_0;

        // --------------------------------------------------------
        // Vídeo urgente.
        // --------------------------------------------------------

        if (p2_req_valid && p2_urgent) begin

            grant_valid  = 1'b1;
            grant_master = MASTER_2;

        end else begin

            // ----------------------------------------------------
            // Round-robin.
            // ----------------------------------------------------

            case (rr_ptr)

                MASTER_0: begin

                    if (p0_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_0;

                    end else if (p1_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_1;

                    end else if (p2_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_2;

                    end else if (p3_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_3;
                    end
                end

                MASTER_1: begin

                    if (p1_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_1;

                    end else if (p2_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_2;

                    end else if (p3_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_3;

                    end else if (p0_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_0;
                    end
                end

                MASTER_2: begin

                    if (p2_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_2;

                    end else if (p3_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_3;

                    end else if (p0_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_0;

                    end else if (p1_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_1;
                    end
                end

                default: begin

                    if (p3_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_3;

                    end else if (p0_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_0;

                    end else if (p1_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_1;

                    end else if (p2_req_valid) begin
                        grant_valid  = 1'b1;
                        grant_master = MASTER_2;
                    end
                end

            endcase
        end
    end

    // ============================================================
    // Request ready
    //
    // Solo un master puede ser aceptado en cada ciclo.
    // ============================================================

    assign p0_req_ready =
        (state == ST_IDLE) &&
        grant_valid &&
        (grant_master == MASTER_0);

    assign p1_req_ready =
        (state == ST_IDLE) &&
        grant_valid &&
        (grant_master == MASTER_1);

    assign p2_req_ready =
        (state == ST_IDLE) &&
        grant_valid &&
        (grant_master == MASTER_2);

    assign p3_req_ready =
        (state == ST_IDLE) &&
        grant_valid &&
        (grant_master == MASTER_3);

    // ============================================================
    // Response routing
    // ============================================================

    assign p0_rsp_valid =
        (state == ST_RESP) &&
        (active_master == MASTER_0);

    assign p1_rsp_valid =
        (state == ST_RESP) &&
        (active_master == MASTER_1);

    assign p2_rsp_valid =
        (state == ST_RESP) &&
        (active_master == MASTER_2);

    assign p3_rsp_valid =
        (state == ST_RESP) &&
        (active_master == MASTER_3);

    assign p0_rsp_rdata = response_data;
    assign p1_rsp_rdata = response_data;
    assign p2_rsp_rdata = response_data;
    assign p3_rsp_rdata = response_data;

    assign p0_rsp_error = response_error;
    assign p1_rsp_error = response_error;
    assign p2_rsp_error = response_error;
    assign p3_rsp_error = response_error;

    // ============================================================
    // Current master response-ready mux
    // ============================================================

    reg active_rsp_ready;

    always @* begin
        case (active_master)
            MASTER_0: active_rsp_ready = p0_rsp_ready;
            MASTER_1: active_rsp_ready = p1_rsp_ready;
            MASTER_2: active_rsp_ready = p2_rsp_ready;
            default:  active_rsp_ready = p3_rsp_ready;
        endcase
    end

    // ============================================================
    // SDRAM controller interface
    // ============================================================

    assign sdram_req_valid =
        (state == ST_ISSUE);

    assign sdram_req_write =
        active_write;

    /*
     * Fabric: dirección BYTE.
     * SDRAM controller: dirección de palabra de 16 bits.
     *
     * Como active_addr está alineada a 16 bytes:
     *
     *   byte address    xxxx xxxx xxxx 0000
     *   >> 1            xxxx xxxx xxxx x000
     *
     * Por tanto el controller recibe siempre alineación BL8.
     */
    assign sdram_req_addr =
        active_addr[24:1];

    assign sdram_req_wdata =
        active_wdata;

    assign sdram_req_wmask =
        active_wmask;

    assign busy =
        (state != ST_IDLE);

    // ============================================================
    // Validation
    // ============================================================

    wire active_address_valid =
        (active_addr < SDRAM_SIZE_BYTES) &&
        (active_addr[3:0] == 4'b0000);

    // ============================================================
    // Main FSM
    // ============================================================

    always @(posedge clk) begin

        if (reset) begin

            state <= ST_IDLE;

            rr_ptr <= MASTER_0;

            active_master <= MASTER_0;
            active_write <= 1'b0;
            active_addr <= 32'd0;
            active_wdata <= 128'd0;
            active_wmask <= 16'd0;

            response_data <= 128'd0;
            response_error <= 1'b0;

        end else begin

            case (state)

                // =================================================
                // Accept request
                // =================================================

                ST_IDLE: begin

                    response_error <= 1'b0;

                    if (grant_valid) begin

                        active_master <= grant_master;

                        case (grant_master)

                            MASTER_0: begin
                                active_write <= p0_req_write;
                                active_addr  <= p0_req_addr;
                                active_wdata <= p0_req_wdata;
                                active_wmask <= p0_req_wmask;
                            end

                            MASTER_1: begin
                                active_write <= p1_req_write;
                                active_addr  <= p1_req_addr;
                                active_wdata <= p1_req_wdata;
                                active_wmask <= p1_req_wmask;
                            end

                            MASTER_2: begin
                                active_write <= p2_req_write;
                                active_addr  <= p2_req_addr;
                                active_wdata <= p2_req_wdata;
                                active_wmask <= p2_req_wmask;
                            end

                            default: begin
                                active_write <= p3_req_write;
                                active_addr  <= p3_req_addr;
                                active_wdata <= p3_req_wdata;
                                active_wmask <= p3_req_wmask;
                            end

                        endcase

                        /*
                         * Validamos la dirección directamente a partir
                         * del puerto concedido porque active_addr todavía
                         * contiene la transacción anterior en este ciclo.
                         */
                        case (grant_master)

                            MASTER_0:
                                if ((p0_req_addr >= SDRAM_SIZE_BYTES) ||
                                    (p0_req_addr[3:0] != 4'b0000)) begin
                                    response_data <= 128'd0;
                                    response_error <= 1'b1;
                                    state <= ST_RESP;
                                end else begin
                                    state <= ST_ISSUE;
                                end

                            MASTER_1:
                                if ((p1_req_addr >= SDRAM_SIZE_BYTES) ||
                                    (p1_req_addr[3:0] != 4'b0000)) begin
                                    response_data <= 128'd0;
                                    response_error <= 1'b1;
                                    state <= ST_RESP;
                                end else begin
                                    state <= ST_ISSUE;
                                end

                            MASTER_2:
                                if ((p2_req_addr >= SDRAM_SIZE_BYTES) ||
                                    (p2_req_addr[3:0] != 4'b0000)) begin
                                    response_data <= 128'd0;
                                    response_error <= 1'b1;
                                    state <= ST_RESP;
                                end else begin
                                    state <= ST_ISSUE;
                                end

                            default:
                                if ((p3_req_addr >= SDRAM_SIZE_BYTES) ||
                                    (p3_req_addr[3:0] != 4'b0000)) begin
                                    response_data <= 128'd0;
                                    response_error <= 1'b1;
                                    state <= ST_RESP;
                                end else begin
                                    state <= ST_ISSUE;
                                end

                        endcase
                    end
                end

                // =================================================
                // Request hacia SDRAM
                // =================================================

                ST_ISSUE: begin

                    if (sdram_req_ready) begin
                        state <= ST_WAIT;
                    end
                end

                // =================================================
                // Esperar SDRAM
                // =================================================

                ST_WAIT: begin

                    if (sdram_done) begin

                        response_data <= sdram_rdata;
                        response_error <= 1'b0;

                        state <= ST_RESP;
                    end
                end

                // =================================================
                // Mantener response hasta handshake
                // =================================================

                ST_RESP: begin

                    if (active_rsp_ready) begin

                        // Round robin empieza por el siguiente master.
                        case (active_master)
                            MASTER_0: rr_ptr <= MASTER_1;
                            MASTER_1: rr_ptr <= MASTER_2;
                            MASTER_2: rr_ptr <= MASTER_3;
                            default:  rr_ptr <= MASTER_0;
                        endcase

                        state <= ST_IDLE;
                    end
                end

                default: begin
                    state <= ST_IDLE;
                end

            endcase
        end
    end

    // ============================================================
    // Simulation assertions
    // ============================================================

`ifndef SYNTHESIS

    always @(posedge clk) begin
        if (!reset) begin

            if (p0_req_valid && p0_req_ready &&
                p0_req_addr[3:0] != 4'b0000)
                $error("memory_fabric_4: port 0 address not 16-byte aligned");

            if (p1_req_valid && p1_req_ready &&
                p1_req_addr[3:0] != 4'b0000)
                $error("memory_fabric_4: port 1 address not 16-byte aligned");

            if (p2_req_valid && p2_req_ready &&
                p2_req_addr[3:0] != 4'b0000)
                $error("memory_fabric_4: port 2 address not 16-byte aligned");

            if (p3_req_valid && p3_req_ready &&
                p3_req_addr[3:0] != 4'b0000)
                $error("memory_fabric_4: port 3 address not 16-byte aligned");

        end
    end

`endif

endmodule

`default_nettype wire