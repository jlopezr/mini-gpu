`default_nettype none

/*
 * MMIO local/experimental de la fase SDRAM, dominio clk (80 MHz).
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
    output wire        quiesce
);
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
                    read_data <= {18'd0, pos_binary, 4'd0,
                                  init_sync, lock_sync,
                                  (local_err || err_sync),
                                  (pending || busy_sync)};
                end else begin
                    error <= 1'b1;
                    read_data <= 32'd0;
                end
            end
        end
    end
endmodule

`default_nettype wire
