`ifndef _uart_v_
`define _uart_v_
`default_nettype none

/*
 * UART block derived from the reusable UART supplied by the user.
 *
 * Copyright (C) 2009 Micah Dowty
 * Copyright (C) 2018 Trammell Hudson
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

// Reusable UART block based on the user's existing interface.
// DIVISOR = clk_hz / baud. For the wrapper, DIVISOR must be divisible by 4.

module uart_tx #(
    parameter integer DIVISOR = 216
)(
    input  wire       clk,
    input  wire       reset,
    output wire       serial,
    output reg        ready,
    input  wire [7:0] data,
    input  wire       data_strobe
);
    wire baud_x1;

    divide_by_n #(.N(DIVISOR)) baud_x1_div (
        .clk   (clk),
        .reset (reset),
        .out   (baud_x1)
    );

    reg [9:0] shiftreg;
    reg       serial_r;

    assign serial = !serial_r;

    always @(posedge clk) begin
        if (reset) begin
            shiftreg <= 10'b0;
            serial_r <= 1'b0;
            ready    <= 1'b1;
        end else if (data_strobe && ready) begin
            shiftreg <= {1'b1, data, 1'b0}; // stop, data[7:0], start
            ready    <= 1'b0;
        end else if (baud_x1) begin
            if (shiftreg == 0) begin
                serial_r <= 1'b0; // idle high after inversion
                ready    <= 1'b1;
            end else begin
                serial_r <= !shiftreg[0];
            end
            shiftreg <= {1'b0, shiftreg[9:1]};
        end else begin
            ready <= (shiftreg == 0);
        end
    end
endmodule

module uart_rx #(
    parameter integer DIVISOR = 54
)(
    input  wire       clk,
    input  wire       reset,
    input  wire       serial,
    output wire [7:0] data,
    output reg        data_strobe
);
    wire baud_x4;

    divide_by_n #(.N(DIVISOR)) baud_x4_div (
        .clk   (clk),
        .reset (reset),
        .out   (baud_x4)
    );

    reg [1:0] serial_buf;
    wire serial_sync = serial_buf[1];

    always @(posedge clk) begin
        if (reset)
            serial_buf <= 2'b11;
        else
            serial_buf <= {serial_buf[0], serial};
    end

    reg  [8:0] shiftreg;
    reg  [5:0] state;
    wire [3:0] bit_count = state[5:2];
    wire [1:0] bit_phase = state[1:0];
    wire       sampling_phase = (bit_phase == 2'd1);
    wire       start_bit = (bit_count == 0 && sampling_phase);
    wire       stop_bit  = (bit_count == 9 && sampling_phase);
    wire       waiting_for_start = (state == 0 && serial_sync == 1'b1);
    wire       error = ((start_bit && serial_sync == 1'b1) ||
                        (stop_bit  && serial_sync == 1'b0));

    assign data = shiftreg[7:0];

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            shiftreg   <= 9'b0;
            state      <= 6'b0;
            data_strobe <= 1'b0;
        end else if (baud_x4) begin
            if (waiting_for_start || error || stop_bit)
                state <= 0;
            else
                state <= state + 1'b1;

            if (bit_phase == 2'd1)
                shiftreg <= {serial_sync, shiftreg[8:1]};

            data_strobe <= stop_bit && !error;
        end else begin
            data_strobe <= 1'b0;
        end
    end
endmodule

module uart #(
    parameter integer DIVISOR = 216
)(
    input  wire       clk,
    input  wire       reset,
    input  wire       serial_rxd,
    output wire       serial_txd,
    output wire [7:0] rxd,
    output wire       rxd_strobe,
    input  wire [7:0] txd,
    input  wire       txd_strobe,
    output wire       txd_ready
);
    // DIVISOR must be divisible by four because RX samples at 4x baud.
    generate
        if (DIVISOR % 4 != 0) begin : g_divisor_check
            DIVISOR_must_be_divisible_by_4 guard (); // deliberate elaboration error
        end
    endgenerate

    uart_rx #(.DIVISOR(DIVISOR / 4)) rx (
        .clk         (clk),
        .reset       (reset),
        .serial      (serial_rxd),
        .data        (rxd),
        .data_strobe (rxd_strobe)
    );

    uart_tx #(.DIVISOR(DIVISOR)) tx (
        .clk         (clk),
        .reset       (reset),
        .serial      (serial_txd),
        .data        (txd),
        .data_strobe (txd_strobe),
        .ready       (txd_ready)
    );
endmodule

`default_nettype wire
`endif
