`default_nettype none
// Cruce de reloj del MMIO de la CPU hacia la GPU: un acceso de palabra cada vez,
// con peticion y confirmacion por cambio de nivel (toggle) y sincronizadores de
// dos biestables en cada sentido.
//
//   dominio CPU (clk)                              dominio GPU (gclk)
//   start ──> req_t ───────── 2 FF ──> req_s2 ──┐
//   address, write, write_data ───────────────> captura ──> h_valid, h_*
//   done  <── ack_s2 <── 2 FF ─────────── ack_t <── h_done, h_rdata, h_error
//
// Los datos NO se sincronizan bit a bit: `address`, `write` y `write_data` los
// mantiene estables quien llama --`mmio_mux` los retiene hasta confirmar-- desde
// ANTES de `start`, y la GPU los captura cuando ya ha visto el cambio de
// `req_t`, al menos dos ciclos de `gclk` despues. `read_data` y `error` se
// registran en el dominio de la GPU antes de cambiar `ack_t` y no se mueven
// hasta la siguiente peticion, asi que la CPU los muestrea con seguridad en
// cuanto ve `done`.
//
// Un solo acceso en vuelo. `done` es un pulso de un ciclo de `clk`.
module gpu_mmio_bridge (
    input  wire        clk,
    input  wire        reset,
    input  wire        start,
    input  wire        write,
    input  wire [31:0] address,
    input  wire [31:0] write_data,
    output reg         done,
    output wire [31:0] read_data,
    output wire        error,

    input  wire        gclk,
    input  wire        greset,
    output reg         h_valid,
    output reg         h_write,
    output reg  [31:0] h_addr,
    output reg  [31:0] h_wdata,
    input  wire        h_done,
    input  wire [31:0] h_rdata,
    input  wire        h_error
);
    // ---- CPU -> GPU ----
    reg req_t;
    always @(posedge clk) begin
        if (reset) req_t <= 1'b0;
        else if (start) req_t <= ~req_t;
    end

    (* async_reg = "true" *) reg req_s1, req_s2;
    reg req_s3;
    reg [31:0] r_data;
    reg        r_err;
    reg        ack_t;
    reg        waiting;

    always @(posedge gclk) begin
        h_valid <= 1'b0;
        if (greset) begin
            req_s1 <= 1'b0; req_s2 <= 1'b0; req_s3 <= 1'b0;
            ack_t <= 1'b0; waiting <= 1'b0;
            h_write <= 1'b0; h_addr <= 32'd0; h_wdata <= 32'd0;
            r_data <= 32'd0; r_err <= 1'b0;
        end else begin
            req_s1 <= req_t;
            req_s2 <= req_s1;
            req_s3 <= req_s2;
            if (req_s2 != req_s3 && !waiting) begin
                h_write <= write;
                h_addr <= address;
                h_wdata <= write_data;
                h_valid <= 1'b1;
                waiting <= 1'b1;
            end
            if (waiting && h_done) begin
                r_data <= h_rdata;
                r_err <= h_error;
                ack_t <= ~ack_t;
                waiting <= 1'b0;
            end
        end
    end

    // ---- GPU -> CPU ----
    (* async_reg = "true" *) reg ack_s1, ack_s2;
    reg ack_s3;
    always @(posedge clk) begin
        done <= 1'b0;
        if (reset) begin
            ack_s1 <= 1'b0; ack_s2 <= 1'b0; ack_s3 <= 1'b0;
        end else begin
            ack_s1 <= ack_t;
            ack_s2 <= ack_s1;
            ack_s3 <= ack_s2;
            if (ack_s2 != ack_s3) done <= 1'b1;
        end
    end

    assign read_data = r_data;
    assign error = r_err;
endmodule
`default_nettype wire
