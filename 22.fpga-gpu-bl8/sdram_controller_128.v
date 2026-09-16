`default_nettype none

module sdram_controller_128 #(
    parameter integer CLK_FREQ_HZ = 25_000_000,
    parameter integer POWERUP_DELAY_US = 200,
    parameter integer REFRESH_RATE_HZ = 128_000,

    // Debe cubrir holgadamente una transacción completa BL8.
    parameter integer MAX_ACCESS_CYCLES = 32,

    parameter integer TRP_NS = 20,
    parameter integer TRCD_NS = 20,
    parameter integer TRFC_NS = 66,

    parameter integer TMRD_CYCLES = 2,
    parameter integer CAS_LATENCY_CYCLES = 2,
    parameter integer TWR_CYCLES = 2,

    // Ciclos que hay que esperar POR ENCIMA de la latencia CAS antes de
    // muestrear DQ. No es margen de sobra: entre que la FPGA emite el comando y
    // ve el dato de vuelta estan el camino de salida, el pin, la pista, el pin
    // de vuelta y el camino de entrada, y a 100 MHz eso pasa de un ciclo.
    //
    // ESTE PARAMETRO ES CALIBRACION DE PLACA. Un banco de pruebas no puede
    // fijarlo: el modelo tiene el mismo parametro, asi que controlador y modelo
    // se ponen de acuerdo en el valor que sea y la simulacion pasa igual. Lo
    // unico que decide es el hardware.
    //
    // Nacio valiendo 1 por analogia con el sdram_controller BL1 de la 16, que
    // muestrea en ST_READ + dos esperas + ST_READ_CAPTURE. La analogia era
    // mala: la 16 corre a 100 MHz y esta a 80. El retardo de ida y vuelta es
    // fisico y no cambia con el reloj, asi que a 10 ns se sale del ciclo y a
    // 12,5 ns cabe dentro.
    //
    // Cuenta flancos de SUBIDA, pero DQ se muestrea en la BAJADA anterior
    // (ver `dq_negedge` mas abajo), asi que el instante real de captura es
    // medio ciclo antes de lo que sugiere este numero. Con la captura
    // centrada en el ojo, el valor correcto para esta placa vuelve a ser 1.
    //
    // POR ESO SE DERIVA DEL RELOJ Y NO SE FIJA A UN NUMERO. Si el retardo es
    // fisico y constante, los ciclos que hay que esperar NO lo son: dependen de
    // cuanto dure un ciclo. Dejarlo en 1 fijo es correcto a 80 MHz (21) y
    // ROMPE a 25 MHz (22), donde hace muestrear un ciclo tarde y el dato
    // vuelve desplazado una palabra de 16 bits.
    //
    // ROUND_TRIP_PS esta calibrado con DOS puntos medidos en placa:
    //
    //   80 MHz -> 1   (21.fpga-cpu-hdmi-alu, en produccion)
    //   25 MHz -> 0   (22, confirmado: con 1 la primera instruccion daba
    //                  ERROR_INVALID_ENCODING y con 0 el programa corre)
    //
    // Los dos juntos acotan el retardo real entre 12,5 y 25 ns; se toma 18 ns,
    // a mitad del intervalo. Lo que la formula predice para OTROS relojes
    // (1 hasta 111 MHz, 2 hasta 166 MHz) sigue siendo inferencia: cada reloj
    // nuevo hay que confirmarlo en placa.
    parameter integer ROUND_TRIP_PS = 18_000,
    // Division entera = suelo. Se calcula en MHz x ps para no desbordar el
    // entero de 32 bits, que CLK_FREQ_HZ * ROUND_TRIP_PS si haria.
    parameter integer READ_DELAY_CYCLES =
        (CLK_FREQ_HZ / 1_000_000) * ROUND_TRIP_PS / 1_000_000
) (
    input wire clk,
    input wire reset,

    // ------------------------------------------------------------
    // Interfaz lógica
    //
    // Cada request transfiere 128 bits = 16 bytes.
    //
    // req_addr sigue direccionando palabras SDRAM de 16 bits.
    // Debe cumplir req_addr[2:0] == 3'b000.
    //
    // Beat 0 -> bits [15:0]
    // Beat 1 -> bits [31:16]
    // ...
    // Beat 7 -> bits [127:112]
    // ------------------------------------------------------------

    input wire req_valid,
    input wire req_write,

    input wire [23:0] req_addr,

    input wire [127:0] req_wdata,

    // Byte enable.
    //
    // bit 0 -> byte bajo beat 0
    // bit 1 -> byte alto beat 0
    // ...
    // bit 15 -> byte alto beat 7
    //
    // 1 = escribir byte
    // 0 = preservar byte
    input wire [15:0] req_wmask,

    output wire req_ready,

    output reg done,
    output reg [127:0] rdata,

    output reg init_done,
    output wire busy,

    // ------------------------------------------------------------
    // SDRAM
    // ------------------------------------------------------------

    output wire sdram_clk,

    output reg sdram_cke,
    output reg sdram_csn,
    output reg sdram_rasn,
    output reg sdram_casn,
    output reg sdram_wen,

    output reg [12:0] sdram_a,
    output reg [1:0] sdram_ba,
    output reg [1:0] sdram_dqm,

    inout wire [15:0] sdram_d
);

    // ------------------------------------------------------------
    // SDRAM commands
    // {CS#, RAS#, CAS#, WE#}
    // ------------------------------------------------------------

    localparam [3:0]
        CMD_MRS       = 4'b0000,
        CMD_REFRESH   = 4'b0001,
        CMD_PRECHARGE = 4'b0010,
        CMD_ACTIVE    = 4'b0011,
        CMD_WRITE     = 4'b0100,
        CMD_READ      = 4'b0101,
        CMD_NOP       = 4'b0111;

    // ------------------------------------------------------------
    // State machine
    // ------------------------------------------------------------

    localparam [4:0]
        ST_INIT_WAIT       = 5'd0,
        ST_INIT_PRE        = 5'd1,
        ST_INIT_PRE_WAIT   = 5'd2,
        ST_INIT_REF        = 5'd3,
        ST_INIT_REF_WAIT   = 5'd4,
        ST_INIT_MRS        = 5'd5,
        ST_INIT_MRS_WAIT   = 5'd6,

        ST_IDLE            = 5'd7,

        ST_ACTIVE          = 5'd8,
        ST_TRCD_WAIT       = 5'd9,

        ST_READ_CMD        = 5'd10,
        ST_READ_LATENCY    = 5'd11,
        ST_READ_BURST      = 5'd12,
        ST_READ_TRP        = 5'd13,

        ST_WRITE_CMD       = 5'd14,
        ST_WRITE_BURST     = 5'd15,
        ST_WRITE_RECOVERY  = 5'd16,
        ST_WRITE_TRP       = 5'd17,

        ST_REFRESH         = 5'd18,
        ST_REFRESH_WAIT    = 5'd19;

    // ------------------------------------------------------------
    // Timing conversion
    // ------------------------------------------------------------

    function integer ns_to_cycles;
        input integer delay_ns;
        integer result;
        begin
            result =
                (((CLK_FREQ_HZ / 1000) * delay_ns) + 999_999)
                / 1_000_000;

            ns_to_cycles = (result < 1) ? 1 : result;
        end
    endfunction

    localparam integer POWERUP_DELAY_CYCLES =
        (((CLK_FREQ_HZ / 1000) * POWERUP_DELAY_US) + 999)
        / 1000;

    localparam integer REFRESH_PERIOD_CYCLES =
        CLK_FREQ_HZ / REFRESH_RATE_HZ;

    localparam integer REFRESH_TRIGGER_CYCLES =
        (REFRESH_PERIOD_CYCLES > MAX_ACCESS_CYCLES)
            ? (REFRESH_PERIOD_CYCLES - MAX_ACCESS_CYCLES)
            : 1;

    localparam integer TRP_CYCLES  = ns_to_cycles(TRP_NS);
    localparam integer TRCD_CYCLES = ns_to_cycles(TRCD_NS);
    localparam integer TRFC_CYCLES = ns_to_cycles(TRFC_NS);

    // ------------------------------------------------------------
    // Registers
    // ------------------------------------------------------------

    reg [4:0] state;

    reg [31:0] init_count;
    reg [3:0] init_refreshes;

    reg [31:0] refresh_count;
    reg [15:0] timing_count;

    reg [2:0] beat_count;

    reg [23:0] saved_addr;
    reg [127:0] saved_wdata;
    reg [15:0] saved_wmask;
    reg saved_write;

    // ------------------------------------------------------------
    // Address decode
    //
    // 13 row
    // 2 bank
    // 9 column
    //
    // = 24-bit word address
    // ------------------------------------------------------------

    wire [12:0] saved_row =
        saved_addr[23:11];

    wire [1:0] saved_bank =
        saved_addr[10:9];

    wire [8:0] saved_col =
        saved_addr[8:0];

    // ------------------------------------------------------------
    // Write burst datapath
    // ------------------------------------------------------------

    wire write_phase =
        (state == ST_WRITE_CMD) ||
        (state == ST_WRITE_BURST);

    wire [2:0] write_beat =
        (state == ST_WRITE_CMD)
            ? 3'd0
            : beat_count;

    wire [15:0] write_word =
        saved_wdata[write_beat * 16 +: 16];

    wire [1:0] write_mask =
        saved_wmask[write_beat * 2 +: 2];

    // ------------------------------------------------------------
    // External status
    // ------------------------------------------------------------

    assign req_ready =
        (state == ST_IDLE) &&
        (refresh_count < REFRESH_TRIGGER_CYCLES);

    assign busy =
        (state != ST_IDLE);

    assign sdram_clk =
        clk;

    // ------------------------------------------------------------
    // Captura de DQ en el flanco de BAJADA
    // ------------------------------------------------------------
    //
    // La SDRAM recibe nuestro mismo reloj, asi que sus datos de lectura salen
    // alineados con el flanco de subida, viajan por el pin, la pista y el pin
    // de vuelta, y llegan CERCA del flanco siguiente. Muestrear ahi es
    // muestrear en el borde del ojo.
    //
    // Lo enseno la placa y no la simulacion. Con captura en subida:
    //
    //   - un ciclo antes (READ_DELAY_CYCLES=0) la rafaga sale casi bien, con
    //     unos pocos bits sueltos mal: fallaban los beats 3 y 7 en DQ4 y DQ5, y
    //     al recompilar con otra semilla los bits malos CAMBIABAN a DQ4 y DQ6.
    //     Un fallo que se mueve con la colocacion es margen, no logica;
    //   - un ciclo despues (=1) la rafaga sale entera corrida un beat.
    //
    // O sea que el limite del beat cae entre los dos flancos, y el centro del
    // ojo esta a mitad de camino. Este registro muestrea justo ahi: medio
    // ciclo, 6,25 ns a 80 MHz, de margen por los dos lados en vez de cero.
    //
    // Con esto, READ_DELAY_CYCLES vuelve a ser 1: el beat 0 se captura en la
    // bajada de T+2 y se guarda en la subida de T+3.
    reg [15:0] dq_negedge;
    always @(negedge clk) begin
        dq_negedge <= sdram_d;
    end

    // SDRAM DQ is only driven during WRITE burst.
    assign sdram_d =
        write_phase
            ? write_word
            : 16'hzzzz;

    // ------------------------------------------------------------
    // SDRAM combinational command generation
    // ------------------------------------------------------------

    always @* begin

        {
            sdram_csn,
            sdram_rasn,
            sdram_casn,
            sdram_wen
        } = CMD_NOP;

        sdram_a   = 13'd0;
        sdram_ba  = 2'd0;
        sdram_dqm = 2'b00;

        case (state)

            // ----------------------------------------------------
            // Initialization
            // ----------------------------------------------------

            ST_INIT_WAIT: begin
                sdram_dqm = 2'b11;
            end

            ST_INIT_PRE: begin
                {
                    sdram_csn,
                    sdram_rasn,
                    sdram_casn,
                    sdram_wen
                } = CMD_PRECHARGE;

                // A10=1 -> all banks
                sdram_a[10] = 1'b1;
            end

            ST_INIT_REF: begin
                {
                    sdram_csn,
                    sdram_rasn,
                    sdram_casn,
                    sdram_wen
                } = CMD_REFRESH;
            end

            ST_INIT_MRS: begin
                {
                    sdram_csn,
                    sdram_rasn,
                    sdram_casn,
                    sdram_wen
                } = CMD_MRS;

                // Mode register:
                //
                // A2:A0 = 011 -> burst length 8
                // A3    = 0   -> sequential
                // A6:A4 = 010 -> CAS latency 2
                // A9    = 0   -> programmed write burst
                //
                // 0x023 = CL2 + BL8
                sdram_a = 13'h023;
            end

            // ----------------------------------------------------
            // Row activate
            // ----------------------------------------------------

            ST_ACTIVE: begin

                {
                    sdram_csn,
                    sdram_rasn,
                    sdram_casn,
                    sdram_wen
                } = CMD_ACTIVE;

                sdram_a  = saved_row;
                sdram_ba = saved_bank;
            end

            // ----------------------------------------------------
            // READ
            // ----------------------------------------------------

            ST_READ_CMD: begin

                {
                    sdram_csn,
                    sdram_rasn,
                    sdram_casn,
                    sdram_wen
                } = CMD_READ;

                // A10 = 1 -> auto-precharge.
                //
                // A9 = 0.
                //
                // A8:A0 = starting column.
                sdram_a = {
                    2'b00,
                    1'b1,
                    1'b0,
                    saved_col
                };

                sdram_ba = saved_bank;
            end

            // ----------------------------------------------------
            // WRITE
            // ----------------------------------------------------

            ST_WRITE_CMD: begin

                {
                    sdram_csn,
                    sdram_rasn,
                    sdram_casn,
                    sdram_wen
                } = CMD_WRITE;

                // A10 = 1 -> auto-precharge.
                sdram_a = {
                    2'b00,
                    1'b1,
                    1'b0,
                    saved_col
                };

                sdram_ba = saved_bank;

                // DQM:
                //
                // SDRAM DQM = 1 -> mask byte
                // Nuestro mask = 1 -> escribir byte
                //
                // Por eso invertimos.
                sdram_dqm =
                    ~write_mask;
            end

            ST_WRITE_BURST: begin

                // Durante los beats 1..7 ya no se emite WRITE.
                // La SDRAM continúa el burst internamente.

                sdram_dqm =
                    ~write_mask;
            end

            // ----------------------------------------------------
            // Refresh
            // ----------------------------------------------------

            ST_REFRESH: begin

                {
                    sdram_csn,
                    sdram_rasn,
                    sdram_casn,
                    sdram_wen
                } = CMD_REFRESH;
            end

            default: begin
            end

        endcase
    end

    // ------------------------------------------------------------
    // Main FSM
    // ------------------------------------------------------------

    always @(posedge clk) begin

        if (reset) begin

            state <= ST_INIT_WAIT;

            init_count <= 0;
            init_refreshes <= 0;

            refresh_count <= 0;
            timing_count <= 0;

            beat_count <= 0;

            saved_addr <= 0;
            saved_wdata <= 0;
            saved_wmask <= 0;
            saved_write <= 0;

            done <= 0;
            rdata <= 0;

            init_done <= 0;

            sdram_cke <= 1'b1;

        end else begin

            done <= 1'b0;

            // ----------------------------------------------------
            // Refresh timer
            // ----------------------------------------------------

            if (
                init_done &&
                refresh_count < REFRESH_PERIOD_CYCLES
            ) begin
                refresh_count <=
                    refresh_count + 1'b1;
            end

            case (state)

                // =================================================
                // INITIALIZATION
                // =================================================

                ST_INIT_WAIT: begin

                    if (
                        init_count + 1 >=
                        POWERUP_DELAY_CYCLES
                    ) begin

                        init_count <= 0;
                        state <= ST_INIT_PRE;

                    end else begin

                        init_count <=
                            init_count + 1'b1;
                    end
                end

                // -------------------------------------------------

                ST_INIT_PRE: begin

                    timing_count <= 0;

                    state <=
                        ST_INIT_PRE_WAIT;
                end

                // -------------------------------------------------

                ST_INIT_PRE_WAIT: begin

                    if (
                        timing_count + 16'd1 >=
                        TRP_CYCLES[15:0]
                    ) begin

                        timing_count <= 0;
                        state <= ST_INIT_REF;

                    end else begin

                        timing_count <=
                            timing_count + 1'b1;
                    end
                end

                // -------------------------------------------------

                ST_INIT_REF: begin

                    timing_count <= 0;

                    state <=
                        ST_INIT_REF_WAIT;
                end

                // -------------------------------------------------

                ST_INIT_REF_WAIT: begin

                    if (
                        timing_count + 16'd1 >=
                        TRFC_CYCLES[15:0]
                    ) begin

                        timing_count <= 0;

                        if (
                            init_refreshes == 4'd7
                        ) begin

                            init_refreshes <= 0;

                            state <=
                                ST_INIT_MRS;

                        end else begin

                            init_refreshes <=
                                init_refreshes + 1'b1;

                            state <=
                                ST_INIT_REF;
                        end

                    end else begin

                        timing_count <=
                            timing_count + 1'b1;
                    end
                end

                // -------------------------------------------------

                ST_INIT_MRS: begin

                    timing_count <= 0;

                    state <=
                        ST_INIT_MRS_WAIT;
                end

                // -------------------------------------------------

                ST_INIT_MRS_WAIT: begin

                    if (
                        timing_count + 16'd1 >=
                        TMRD_CYCLES[15:0]
                    ) begin

                        timing_count <= 0;

                        init_done <= 1'b1;
                        refresh_count <= 0;

                        state <= ST_IDLE;

                    end else begin

                        timing_count <=
                            timing_count + 1'b1;
                    end
                end

                // =================================================
                // IDLE
                // =================================================

                ST_IDLE: begin

                    if (
                        refresh_count >=
                        REFRESH_TRIGGER_CYCLES
                    ) begin

                        refresh_count <= 0;

                        state <= ST_REFRESH;

                    end else if (req_valid) begin

                        saved_addr <=
                            req_addr;

                        saved_wdata <=
                            req_wdata;

                        saved_wmask <=
                            req_wmask;

                        saved_write <=
                            req_write;

                        state <=
                            ST_ACTIVE;
                    end
                end

                // =================================================
                // ACTIVATE
                // =================================================

                ST_ACTIVE: begin

                    timing_count <= 0;

                    state <=
                        ST_TRCD_WAIT;
                end

                // -------------------------------------------------

                ST_TRCD_WAIT: begin

                    if (
                        timing_count + 16'd1 >=
                        TRCD_CYCLES[15:0]
                    ) begin

                        timing_count <= 0;

                        if (saved_write) begin

                            // beat 0 sale junto con WRITE command.
                            beat_count <= 3'd1;

                            state <=
                                ST_WRITE_CMD;

                        end else begin

                            state <=
                                ST_READ_CMD;
                        end

                    end else begin

                        timing_count <=
                            timing_count + 1'b1;
                    end
                end

                // =================================================
                // READ BL8
                // =================================================

                ST_READ_CMD: begin

                    timing_count <= 0;

                    state <=
                        ST_READ_LATENCY;
                end

                // -------------------------------------------------

                ST_READ_LATENCY: begin

                    // Con CL2:
                    //
                    // READ command
                    //   ↓
                    // wait
                    //   ↓
                    // D0
                    //
                    // Después los 8 beats son consecutivos.

                    if (
                        timing_count + 16'd1 >=
                        CAS_LATENCY_CYCLES[15:0] - 16'd1 + READ_DELAY_CYCLES[15:0]
                    ) begin

                        timing_count <= 0;
                        beat_count <= 0;

                        state <=
                            ST_READ_BURST;

                    end else begin

                        timing_count <=
                            timing_count + 1'b1;
                    end
                end

                // -------------------------------------------------

                ST_READ_BURST: begin

                    // Del registro de flanco de bajada, no de DQ directamente.
                    // Ver `dq_negedge` arriba.
                    rdata[
                        beat_count * 16 +: 16
                    ] <= dq_negedge;

                    if (
                        beat_count == 3'd7
                    ) begin

                        beat_count <= 0;
                        timing_count <= 0;

                        state <=
                            ST_READ_TRP;

                    end else begin

                        beat_count <=
                            beat_count + 1'b1;
                    end
                end

                // -------------------------------------------------

                ST_READ_TRP: begin

                    // Dejamos terminar el auto-precharge antes
                    // de permitir otra operación.

                    if (
                        timing_count + 16'd1 >=
                        TRP_CYCLES[15:0]
                    ) begin

                        timing_count <= 0;

                        done <= 1'b1;

                        state <= ST_IDLE;

                    end else begin

                        timing_count <=
                            timing_count + 1'b1;
                    end
                end

                // =================================================
                // WRITE BL8
                // =================================================

                ST_WRITE_CMD: begin

                    // Beat 0 se está presentando en DQ en este
                    // mismo ciclo.

                    state <=
                        ST_WRITE_BURST;
                end

                // -------------------------------------------------

                ST_WRITE_BURST: begin

                    // beat_count comienza en 1.
                    //
                    // El datapath combinacional presenta:
                    //
                    // saved_wdata[beat_count*16 +: 16]

                    if (
                        beat_count == 3'd7
                    ) begin

                        beat_count <= 0;
                        timing_count <= 0;

                        state <=
                            ST_WRITE_RECOVERY;

                    end else begin

                        beat_count <=
                            beat_count + 1'b1;
                    end
                end

                // -------------------------------------------------

                ST_WRITE_RECOVERY: begin

                    if (
                        timing_count + 16'd1 >=
                        TWR_CYCLES[15:0]
                    ) begin

                        timing_count <= 0;

                        state <=
                            ST_WRITE_TRP;

                    end else begin

                        timing_count <=
                            timing_count + 1'b1;
                    end
                end

                // -------------------------------------------------

                ST_WRITE_TRP: begin

                    if (
                        timing_count + 16'd1 >=
                        TRP_CYCLES[15:0]
                    ) begin

                        timing_count <= 0;

                        done <= 1'b1;

                        state <= ST_IDLE;

                    end else begin

                        timing_count <=
                            timing_count + 1'b1;
                    end
                end

                // =================================================
                // REFRESH
                // =================================================

                ST_REFRESH: begin

                    timing_count <= 0;

                    state <=
                        ST_REFRESH_WAIT;
                end

                // -------------------------------------------------

                ST_REFRESH_WAIT: begin

                    if (
                        timing_count + 16'd1 >=
                        TRFC_CYCLES[15:0]
                    ) begin

                        timing_count <= 0;

                        state <= ST_IDLE;

                    end else begin

                        timing_count <=
                            timing_count + 1'b1;
                    end
                end

                // =================================================

                default: begin

                    state <=
                        ST_INIT_WAIT;
                end

            endcase
        end
    end

    // ------------------------------------------------------------
    // Simulation checks
    // ------------------------------------------------------------

`ifndef SYNTHESIS

    always @(posedge clk) begin

        if (
            !reset &&
            req_valid &&
            req_ready &&
            req_addr[2:0] != 3'b000
        ) begin

            // Dos literales pegados no son Verilog, aunque lo parezcan: asi
            // escrito, este fichero ni siquiera elaboraba.
            $error("sdram_controller_128: req_addr debe estar alineado a 8 palabras de SDRAM / 16 bytes");
        end
    end

`endif

endmodule

`default_nettype wire