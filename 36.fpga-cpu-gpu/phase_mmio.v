`default_nettype none

/*
 * MMIO local/experimental de la fase SDRAM, dominio clk de CPU/monitor.
 *
 * +0x00 PHASE_CTRL   WO: bit0 START, bit1 DIR (debe ser 0), bits13:8 STEPS
 * +0x04 PHASE_STATUS RO: bit0 BUSY, bit1 ERR, bit2 LOCKED, bit3 INIT_DONE,
 *                       bits13:8 POS (0..47)
 *
 * req_steps es un bus agrupado con el toggle: se mantiene estable hasta el
 * ack. phase_pos cruza codificado en Gray y el resto son bits independientes
 * con dos registros de sincronizacion; no hay un bus binario cambiante CDC.
 */
module phase_mmio (
    input  wire        clk,
    input  wire        reset,
    input  wire        select,
    input  wire        write,
    input  wire [3:0]  write_mask,
    input  wire [15:0] address,
    input  wire [31:0] write_data,
    output reg  [31:0] read_data,
    output reg         error,

    output reg         req_toggle,
    output reg  [5:0]  req_steps,
    input  wire        ack_toggle_async,
    input  wire        phase_busy_async,
    input  wire        phase_err_async,
    input  wire [5:0]  phase_pos_gray_async,
    input  wire        pll_locked_async,
    input  wire        init_done_async,
    // Diagnostico (clk_mem), solo lectura: [3:0] estado del FSM de fase,
    // [4] traffic_block, [5] fabric_busy, [6] sdram_busy, [7] fab_req_valid,
    // [13:8] req_empty de los seis puertos. Se lee en PHASE_STATUS.
    input  wire [13:0] diag_async,
    // +0x08 = bits 31:0, +0x0C = bits 35:32. Seis bits por puerto, puerto i en
    // [6i+5:6i]: {puntero de lectura Gray, puntero de escritura Gray} de su FIFO
    // de peticion. En reposo deben ser iguales; si no, hay una entrada fantasma.
    input  wire [35:0] diag2_async,
    // +0x10: [15:0] dbg del fabric (ver memory_fabric_fifo_6.v), [16] p2_valid,
    // [17] p2_ready, [19:18] video_mode, [20] p2_rsp_valid, [21] video_rsp_ready.
    input  wire [31:0] diag3_async,
    // +0x14: [19:0] dbg2 del fabric (ver memory_fabric_fifo_6.v), [20] el reset
    // del fabric se ha visto alguna vez en un flanco de clk_mem, [21] ya se ha
    // soltado, [29:22] ciclos que duro ese primer reset (satura en 255).
    input  wire [31:0] diag4_async,
    // +0x18: [23:0] por puerto i, en [4i+3:4i]: {rsp_full, rsp_empty,
    // rsp_hold_valid, rsp_read_pending} del bridge; [29:24] route_port del fabric.
    input  wire [31:0] diag5_async,
    // +0x1C: {done[15:0], aceptadas[15:0]} del controlador; +0x20: racha maxima
    // de `done` a 1 en [3:0].
    input  wire [31:0] diag6_async,
    input  wire [31:0] diag7_async,
    // +0x24: ver top.v (phase_diag8).
    input  wire [31:0] diag8_async,
    // Traza del fabric (ver memory_fabric_fifo_6.v). +0x28 TRACE_IDX (R/W, 0..31),
    // +0x2C TRACE_LO = entrada[31:0], +0x30 TRACE_HI = {n[5:0] en [13:8],
    // entrada[37:32] en [5:0]}. La traza se congela al llenarse, asi que el
    // indice (que cruza a clk_mem sin sincronizar) solo importa mientras se lee.
    input  wire [37:0] trace_data_async,
    input  wire [5:0]  trace_n_async,
    output reg  [4:0]  trace_idx,
    // +0x34 FABRIC_RESET (WO, cualquier escritura de palabra completa): cambia
    // este toggle; top.v lo cruza a clk_mem y da un pulso de reset al fabric.
    output reg         fabric_rst_toggle,
    output wire        quiesce
);
    reg [37:0] trace_meta, trace_sync;
    reg [5:0]  trace_n_meta, trace_n_sync;
    reg [31:0] diag8_meta, diag8_sync;
    reg [31:0] diag6_meta, diag6_sync, diag7_meta, diag7_sync;
    reg [31:0] diag5_meta, diag5_sync;
    reg [31:0] diag4_meta, diag4_sync;
    reg [31:0] diag3_meta, diag3_sync;
    reg [35:0] diag2_meta, diag2_sync;
    reg [13:0] diag_meta, diag_sync;
    reg ack_meta, ack_sync;
    reg busy_meta, busy_sync;
    reg err_meta, err_sync;
    reg lock_meta, lock_sync;
    reg init_meta, init_sync;
    reg [5:0] pos_gray_meta, pos_gray_sync;
    reg pending;
    reg local_err;
    integer i;
    reg [5:0] pos_binary;

    assign quiesce = pending || busy_sync;

    always @* begin
        pos_binary[5] = pos_gray_sync[5];
        for (i = 4; i >= 0; i = i - 1)
            pos_binary[i] = pos_binary[i + 1] ^ pos_gray_sync[i];
    end

    always @(posedge clk) begin
        ack_meta <= ack_toggle_async;
        ack_sync <= ack_meta;
        busy_meta <= phase_busy_async;
        busy_sync <= busy_meta;
        err_meta <= phase_err_async;
        err_sync <= err_meta;
        lock_meta <= pll_locked_async;
        lock_sync <= lock_meta;
        init_meta <= init_done_async;
        init_sync <= init_meta;
        pos_gray_meta <= phase_pos_gray_async;
        pos_gray_sync <= pos_gray_meta;
        // Valores de depuracion que cambian solos: pueden llegar a medias de
        // un cambio. Sirven para ver cual se queda a 1, no para decidir nada.
        diag_meta <= diag_async;
        diag_sync <= diag_meta;
        diag2_meta <= diag2_async;
        diag2_sync <= diag2_meta;
        diag3_meta <= diag3_async;
        diag3_sync <= diag3_meta;
        diag4_meta <= diag4_async;
        diag4_sync <= diag4_meta;
        diag5_meta <= diag5_async;
        diag5_sync <= diag5_meta;
        diag6_meta <= diag6_async;
        diag6_sync <= diag6_meta;
        diag7_meta <= diag7_async;
        diag7_sync <= diag7_meta;
        diag8_meta <= diag8_async;
        diag8_sync <= diag8_meta;
        trace_meta <= trace_data_async;
        trace_sync <= trace_meta;
        trace_n_meta <= trace_n_async;
        trace_n_sync <= trace_n_meta;

        error <= 1'b0;
        if (reset) begin
            req_toggle <= 1'b0;
            req_steps <= 6'd0;
            pending <= 1'b0;
            local_err <= 1'b0;
            read_data <= 32'd0;
            error <= 1'b0;
            ack_meta <= 1'b0;
            ack_sync <= 1'b0;
            busy_meta <= 1'b0;
            busy_sync <= 1'b0;
            err_meta <= 1'b0;
            err_sync <= 1'b0;
            lock_meta <= 1'b0;
            lock_sync <= 1'b0;
            init_meta <= 1'b0;
            init_sync <= 1'b0;
            pos_gray_meta <= 6'd0;
            pos_gray_sync <= 6'd0;
            trace_idx <= 5'd0;
            fabric_rst_toggle <= 1'b0;
        end else begin
            if (pending && ack_sync == req_toggle)
                pending <= 1'b0;

            if (select) begin
                if (address == 16'h0000) begin
                    if (!write || write_mask != 4'b1111 || !write_data[0]
                        || write_data[1] || (|write_data[31:14])
                        || (|write_data[7:2])
                        || write_data[13:8] == 0
                        || write_data[13:8] > 6'd48
                        || pending || busy_sync) begin
                        error <= 1'b1;
                        local_err <= 1'b1;
                    end else begin
                        req_steps <= write_data[13:8];
                        req_toggle <= ~req_toggle;
                        pending <= 1'b1;
                        local_err <= 1'b0;
                    end
                    read_data <= 32'd0;
                end else if (address == 16'h0004) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= {8'd0, diag_sync[13:8], diag_sync[7:4],
                                  pos_binary, diag_sync[3:0],
                                  init_sync, lock_sync,
                                  (local_err || err_sync),
                                  (pending || busy_sync)};
                end else if (address == 16'h0008) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= diag2_sync[31:0];
                end else if (address == 16'h000c) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= {28'd0, diag2_sync[35:32]};
                end else if (address == 16'h0010) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= diag3_sync;
                end else if (address == 16'h0014) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= diag4_sync;
                end else if (address == 16'h0018) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= diag5_sync;
                end else if (address == 16'h001c) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= diag6_sync;
                end else if (address == 16'h0020) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= diag7_sync;
                end else if (address == 16'h0024) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= diag8_sync;
                end else if (address == 16'h0028) begin
                    if (write) begin
                        if (write_mask != 4'b1111 || (|write_data[31:5]))
                            error <= 1'b1;
                        else
                            trace_idx <= write_data[4:0];
                    end
                    read_data <= {27'd0, trace_idx};
                end else if (address == 16'h002c) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= trace_sync[31:0];
                end else if (address == 16'h0030) begin
                    if (write)
                        error <= 1'b1;
                    read_data <= {18'd0, trace_n_sync, 2'b00, trace_sync[37:32]};
                end else if (address == 16'h0034) begin
                    if (!write || write_mask != 4'b1111)
                        error <= 1'b1;
                    else
                        fabric_rst_toggle <= ~fabric_rst_toggle;
                    read_data <= 32'd0;
                end else begin
                    error <= 1'b1;
                    read_data <= 32'd0;
                end
            end
        end
    end
endmodule

`default_nettype wire
