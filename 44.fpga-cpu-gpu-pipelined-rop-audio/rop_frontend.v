`default_nettype none
// Frontend de CPU del ROP: microoperaciones ya decodificadas por cpu.v (familia
// 0x37 de 1.isa/isa.md §7.5) -> cola ordenada de descriptores -> rop_core.
//
// Mantiene staging de parámetros con instantánea al enviar, contadores
// submitted/completed para la espera y error pegajoso. Para la ISA:
//   - PMODE de 16 bits (el cmd_mode de rop_core, con FRAC/SAT).
//   - Cada microoperacion escribe hasta DOS parametros (pA <- da, pB <- db),
//     y SUBMIT los aplica ANTES de la instantanea: un span que solo cambia dos
//     parametros es una instruccion.
//   - La cola es de QUEUE_DEPTH entradas en RAM distribuida (16 cuestan lo
//     mismo que 4) y su salida va por un registro: rop_core recibe el
//     descriptor desde FF, no desde el mux de la RAM.
//   - Dos errores distintos: `cpu_bad_value` (escribir PMODE con [31:16] != 0,
//     preciso: ERROR_INVALID_ENCODING en la instruccion) y `cpu_rop_error`
//     (el pegajoso, que cpu.v convierte en ERROR_ROP al hacer WAIT).
//
// Handshake: cpu.v sostiene cpu_valid y los operandos desde MEM hasta ver
// cpu_ready; el efecto ocurre en ese flanco. cpu_rdata y los errores son
// combinacionales y validos en el mismo ciclo.
//
// Microoperaciones (cpu_uop, el `sub` de la instruccion):
//   0 SET     pA <- da, pB <- db
//   1 SUBMIT  pA <- da, pB <- db; instantanea de P0-P9/PMODE + op a la cola.
//             Espera si la cola esta llena.
//   2 WAIT    espera a que submitted == completed (todos terminados).
//   3 STATUS  cpu_rdata; con cpu_clear, borra el error pegajoso.
// Indices: 0-9 P0-P9, 10 PMODE, 15 ninguno. 11-14 los rechaza cpu.v al
// decodificar; aqui cuentan como ninguno.
module rop_frontend #(
    parameter integer QUEUE_DEPTH = 16
)(
    input  wire         clk,
    input  wire         reset,

    input  wire         cpu_valid,
    output wire         cpu_ready,
    input  wire [1:0]   cpu_uop,
    input  wire [3:0]   cpu_ia,
    input  wire [3:0]   cpu_ib,
    input  wire [31:0]  cpu_da,
    input  wire [31:0]  cpu_db,
    input  wire [2:0]   cpu_op,
    input  wire         cpu_clear,
    output wire [31:0]  cpu_rdata,
    output wire         cpu_bad_value,
    output wire         cpu_rop_error,
    output wire         cpu_busy,

    output wire         rop_cmd_valid,
    input  wire         rop_cmd_ready,
    output wire [2:0]   rop_cmd_op,
    output wire [15:0]  rop_cmd_mode,
    output wire [319:0] rop_cmd_params,
    input  wire         rop_done_valid,
    input  wire         rop_done_error
);
    localparam [1:0] U_SET = 2'd0, U_SUBMIT = 2'd1, U_WAIT = 2'd2, U_STATUS = 2'd3;
    localparam integer PW = (QUEUE_DEPTH <= 2) ? 1 : $clog2(QUEUE_DEPTH);
    localparam integer CW = $clog2(QUEUE_DEPTH + 1);
    localparam integer EW = 3 + 16 + 320;

    reg [319:0] staging_params;
    reg [15:0]  staging_mode;
    reg [31:0]  submitted, completed;
    reg         sticky_error;

    // Los parametros con las escrituras de esta microoperacion ya aplicadas:
    // es lo que se guarda en staging y, en SUBMIT, lo que va a la cola.
    reg [319:0] next_params;
    reg [15:0]  next_mode;
    integer k;
    always @* begin
        next_params = staging_params;
        next_mode = staging_mode;
        for (k = 0; k < 10; k = k + 1) begin
            if (cpu_ia == k) next_params[k*32 +: 32] = cpu_da;
            if (cpu_ib == k) next_params[k*32 +: 32] = cpu_db;
        end
        if (cpu_ia == 4'd10) next_mode = cpu_da[15:0];
        if (cpu_ib == 4'd10) next_mode = cpu_db[15:0];
    end

    // ---- Cola: RAM distribuida + registro de salida -----------------------
    (* ram_style = "distributed", syn_ramstyle = "distributed" *) reg [EW-1:0] fifo [0:QUEUE_DEPTH-1];
    reg [PW-1:0] wr_ptr, rd_ptr;
    reg [CW-1:0] count;                 // entradas en la RAM
    reg          out_valid;
    reg [EW-1:0] out_entry;

    wire full  = (count == QUEUE_DEPTH);
    wire [PW-1:0] wr_next = (wr_ptr == QUEUE_DEPTH-1) ? {PW{1'b0}} : wr_ptr + 1'b1;
    wire [PW-1:0] rd_next = (rd_ptr == QUEUE_DEPTH-1) ? {PW{1'b0}} : rd_ptr + 1'b1;

    wire is_write_uop = (cpu_uop == U_SET) || (cpu_uop == U_SUBMIT);
    assign cpu_bad_value = is_write_uop &&
        ((cpu_ia == 4'd10 && |cpu_da[31:16]) || (cpu_ib == 4'd10 && |cpu_db[31:16]));
    wire all_done = (submitted == completed);
    assign cpu_ready = !reset &&
        ((cpu_uop == U_SUBMIT) ? (cpu_bad_value || !full) :
         (cpu_uop == U_WAIT)   ? all_done : 1'b1);
    wire cpu_fire = cpu_valid && cpu_ready;
    wire enqueue = cpu_fire && cpu_uop == U_SUBMIT && !cpu_bad_value;
    assign cpu_rop_error = sticky_error;
    assign cpu_busy = !all_done;

    // STATUS: bit 0 pendientes, bit 1 cola llena, bit 2 error pegajoso,
    // [15:8] huecos libres (orientativo).
    wire [7:0] free_slots = QUEUE_DEPTH - count;
    assign cpu_rdata = {16'd0, free_slots, 5'd0, sticky_error, full, !all_done};

    assign rop_cmd_valid = !reset && out_valid;
    assign rop_cmd_op = out_entry[EW-1 -: 3];
    assign rop_cmd_mode = out_entry[335:320];
    assign rop_cmd_params = out_entry[319:0];
    wire out_take = rop_cmd_valid && rop_cmd_ready;
    // El registro de salida se recarga cuando esta vacio o se entrega.
    wire load_out = (count != 0) && (!out_valid || out_take);

    always @(posedge clk) begin
        if (enqueue) fifo[wr_ptr] <= {cpu_op, next_mode, next_params};
    end

    always @(posedge clk) begin
        if (reset) begin
            staging_params <= 0;
            staging_mode <= 0;
            wr_ptr <= 0;
            rd_ptr <= 0;
            count <= 0;
            out_valid <= 1'b0;
            out_entry <= 0;
            submitted <= 0;
            completed <= 0;
            sticky_error <= 1'b0;
        end else begin
            if (cpu_fire && is_write_uop && !cpu_bad_value) begin
                staging_params <= next_params;
                staging_mode <= next_mode;
            end
            if (cpu_fire && cpu_uop == U_STATUS && cpu_clear) sticky_error <= 1'b0;
            if (enqueue) begin
                wr_ptr <= wr_next;
                submitted <= submitted + 1'b1;
            end
            if (load_out) begin
                out_entry <= fifo[rd_ptr];
                out_valid <= 1'b1;
                rd_ptr <= rd_next;
            end else if (out_take) begin
                out_valid <= 1'b0;
            end
            case ({enqueue, load_out})
                2'b10: count <= count + 1'b1;
                2'b01: count <= count - 1'b1;
                default: ;
            endcase
            if (rop_done_valid) begin
                completed <= completed + 1'b1;
                if (rop_done_error) sticky_error <= 1'b1;
            end
        end
    end
endmodule
`default_nettype wire
