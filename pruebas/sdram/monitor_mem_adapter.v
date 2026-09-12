`default_nettype none

module monitor_mem_adapter #(
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000
) (
    input  wire         clk,
    input  wire         reset,

    // ============================================================
    // Interfaz existente del monitor
    // ============================================================

    input  wire [31:0]  mem_address,
    input  wire [7:0]   mem_write_data,
    input  wire         mem_write_enable,
    input  wire         mem_read_enable,

    output reg  [7:0]   mem_read_data,
    output reg          mem_ready,
    output reg          mem_error,

    // ============================================================
    // Puerto común hacia memory_fabric
    //
    // req_addr es dirección BYTE y debe estar alineada a 16 bytes.
    // ============================================================

    output wire         req_valid,
    input  wire         req_ready,

    output reg          req_write,
    output reg  [31:0]  req_addr,
    output reg  [127:0] req_wdata,
    output reg  [15:0]  req_wmask,

    input  wire         rsp_valid,
    output wire         rsp_ready,
    input  wire [127:0] rsp_rdata,
    input  wire         rsp_error
);

    localparam [1:0]
        ST_IDLE     = 2'd0,
        ST_ISSUE    = 2'd1,
        ST_WAIT_RSP = 2'd2;

    reg [1:0] state;

    reg [3:0] byte_offset;
    reg       saved_write;

    assign req_valid = (state == ST_ISSUE);
    assign rsp_ready = (state == ST_WAIT_RSP);

    always @(posedge clk) begin
        if (reset) begin

            state <= ST_IDLE;

            mem_read_data <= 8'h00;
            mem_ready <= 1'b0;
            mem_error <= 1'b0;

            req_write <= 1'b0;
            req_addr <= 32'h0000_0000;
            req_wdata <= 128'd0;
            req_wmask <= 16'd0;

            byte_offset <= 4'd0;
            saved_write <= 1'b0;

        end else begin

            // Pulsos de un ciclo hacia el monitor.
            mem_ready <= 1'b0;
            mem_error <= 1'b0;

            case (state)

                // =================================================
                // Espera operación del monitor
                // =================================================

                ST_IDLE: begin

                    if (mem_write_enable || mem_read_enable) begin

                        // Este adapter atiende únicamente SDRAM.
                        //
                        // Los MMIO 0x8000_xxxx de tu sistema deben seguir
                        // siendo decodificados fuera de este módulo.
                        if (mem_address >= SDRAM_SIZE_BYTES) begin

                            mem_error <= 1'b1;
                            mem_ready <= 1'b1;

                        end else begin

                            saved_write <= mem_write_enable;

                            byte_offset <= mem_address[3:0];

                            // Base de la línea de 16 bytes.
                            req_addr <= {
                                mem_address[31:4],
                                4'b0000
                            };

                            req_write <= mem_write_enable;

                            // ------------------------------------------------
                            // Escritura:
                            //
                            // coloca el byte en su lane correspondiente.
                            //
                            // Para lectura estos valores no importan.
                            // ------------------------------------------------

                            req_wdata <=
                                ({120'd0, mem_write_data}
                                 << {mem_address[3:0], 3'b000});

                            req_wmask <=
                                (16'h0001 << mem_address[3:0]);

                            state <= ST_ISSUE;
                        end
                    end
                end

                // =================================================
                // Handshake de request con el fabric
                // =================================================

                ST_ISSUE: begin
                    if (req_ready) begin
                        state <= ST_WAIT_RSP;
                    end
                end

                // =================================================
                // Espera respuesta
                // =================================================

                ST_WAIT_RSP: begin

                    if (rsp_valid) begin

                        mem_error <= rsp_error;

                        if (!saved_write && !rsp_error) begin

                            mem_read_data <=
                                rsp_rdata >>
                                {byte_offset, 3'b000};
                        end

                        mem_ready <= 1'b1;
                        state <= ST_IDLE;
                    end
                end

                default: begin
                    state <= ST_IDLE;
                end

            endcase
        end
    end

endmodule

`default_nettype wire