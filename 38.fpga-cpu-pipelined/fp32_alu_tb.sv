`timescale 1ns/1ps
module fp32_alu_tb;
    logic clk = 0, rst = 1, in_valid = 0, in_ready, out_valid, out_ready = 1;
    logic [2:0] in_op = 0;
    logic [4:0] in_fbits = 0;
    logic [31:0] in_a = 0, in_b = 0, out_data;
    fp32_alu dut (.*);
    always #5 clk = ~clk;
    integer seed = 32'h27182818, i, op;
    reg [31:0] a, b, expected;
    localparam integer CONVERT_VECTORS = 3152;
    reg [31:0] vectors [0:4 * CONVERT_VECTORS - 1];

    task automatic issue(input logic [2:0] op, input logic [31:0] a, b);
        begin
            @(negedge clk); in_valid = 1; in_op = op; in_a = a; in_b = b;
            do @(posedge clk); while (!in_ready);
            @(negedge clk); in_valid = 0;
        end
    endtask
    task automatic await_result(input logic [31:0] expected);
        begin
            do @(posedge clk); while (!out_valid);
            if (out_data !== expected)
                $fatal(1, "op=%d a=%h b=%h expected=%h got=%h", in_op, in_a, in_b, expected, out_data);
        end
    endtask
    task automatic check(input [2:0] op, input [31:0] a, b, expected);
        begin issue(op, a, b); await_result(expected); end
    endtask

    // Independent binary64 reference for random finite normals. Each FP32
    // significand converts exactly; binary64 preserves ample guard bits.
    function automatic real value(input [31:0] x);
        value = (x[31] ? -1.0 : 1.0) * (8388608.0 + x[22:0]) *
                (2.0 ** ($signed({1'b0, x[30:23]}) - 150));
    endfunction
    function automatic [31:0] rounded(input real x);
        reg [63:0] bits, mant, q, rembits, half;
        integer e, shift;
        begin
            bits = $realtobits(x);
            e = bits[62:52] - 1023 + 127;
            mant = {1'b1, bits[51:0]};
            shift = 29 + (e <= 0 ? 1 - e : 0);
            if (shift >= 63 || bits[62:0] == 0) rounded = {bits[63], 31'd0};
            else begin
                q = mant >> shift;
                rembits = mant & ((64'd1 << shift) - 1);
                half = 64'd1 << (shift - 1);
                if (rembits > half || (rembits == half && q[0])) q = q + 1;
                if (e <= 0) e = 1;
                if (q[24]) begin q = q >> 1; e = e + 1; end
                if (e >= 255) rounded = {bits[63], 8'hff, 23'd0};
                else if (!q[23]) rounded = {bits[63], 31'd0};
                else rounded = {bits[63], e[7:0], q[22:0]};
            end
        end
    endfunction

    initial begin #5000000; $fatal(1, "FP32 timeout"); end
    initial begin
        repeat (3) @(negedge clk); rst = 0;
        check(0, 'h3fc00000, 'h40100000, 'h40700000);
        check(1, 'h40800000, 'h3f800000, 'h40400000);
        check(2, 'h3fc00000, 'h40200000, 'h40700000);
        check(3, 'h40c00000, 'h40000000, 'h40400000);
        check(3, 'h3f800000, 'h40400000, 'h3eaaaaab); // 1/3
        check(3, 'h3fc00000, 'h40000000, 'h3f400000); // normalized quotient < 1
        check(0, 'h7f800000, 'hff800000, 'h7fc00000);
        check(0, 0, 0, 0);
        check(0, 'h80000000, 'h80000000, 'h80000000);
        check(1, 'h3f800000, 'h3f800000, 0);
        check(0, 'h3f800000, 'h33800000, 'h3f800000); // tie, even
        check(0, 'h3f800001, 'h33800000, 'h3f800002); // tie, odd
        check(2, 1, 'h3f800000, 0); // DAZ
        check(2, 'h7f800000, 1, 'h7fc00000); // inf * DAZ
        check(3, 'h3f800000, 1, 'h7f800000); // DAZ divisor
        check(3, 'h80000000, 0, 'h7fc00000);
        check(3, 'h3f800000, 'h80000000, 'hff800000);
        check(3, 'h7f800000, 'h7f800000, 'h7fc00000);
        check(3, 'h3f800000, 'hff800000, 'h80000000);
        check(3, 'h7f7fffff, 'h00800000, 'h7f800000); // exponent overflow
        check(3, 'h00800000, 'h7f7fffff, 0); // underflow, no wrap
        check(2, 'h00800000, 'h3f7fffff, 'h00800000); // rounds to min normal
        check(2, 'h00800000, 'h3f000000, 0); // FTZ
        for (op = 0; op < 4; op = op + 1) begin
            for (i = 0; i < 1000; i = i + 1) begin
                a = $random(seed); b = $random(seed);
                // Random normals, with the entire exponent range.
                if (a[30:23] == 0 || a[30:23] == 255) a[30:23] = 127;
                if (b[30:23] == 0 || b[30:23] == 255) b[30:23] = 127;
                case (op)
                    0: expected = rounded(value(a) + value(b));
                    1: expected = rounded(value(a) - value(b));
                    2: expected = rounded(value(a) * value(b));
                    3: expected = rounded(value(a) / value(b));
                endcase
                check(op, a, b, expected);
            end
        end
        // A full fast-path pipeline, held by output backpressure, followed
        // by division: no loss, reordering or overwrite of the stalled head.
        @(negedge clk); out_ready = 0;
        issue(0, 'h3f800000, 'h40000000);
        issue(1, 'h40a00000, 'h3f800000); // 4
        issue(2, 'h3fc00000, 'h40800000); // 6
        issue(0, 'h40800000, 'h40400000); // 7, fills all four stages
        wait(out_valid);
        repeat (6) begin
            @(negedge clk);
            if (!out_valid || out_data !== 32'h40400000) $fatal(1, "unstable output");
            in_op = 0;
            #1;
            if (in_ready) $fatal(1, "fast path accepted while full");
            in_op = 3;
            #1;
            if (in_ready) $fatal(1, "divide accepted before draining fast path");
        end
        out_ready = 1;
        for (i = 0; i < 4; i = i + 1) begin
            @(posedge clk);
            case (i)
                0: expected = 32'h40400000;
                1: expected = 32'h40800000;
                2: expected = 32'h40c00000;
                3: expected = 32'h40e00000;
            endcase
            if (!out_valid || out_data !== expected) $fatal(1, "lost/reordered queued result %d", i);
        end
        check(3, 'h40800000, 'h40000000, 'h40000000);
        issue(3, 'h40c00000, 'h40000000);
        @(negedge clk); rst = 1;
        @(negedge clk); rst = 0;
        repeat (35) begin
            @(negedge clk);
            if (out_valid) $fatal(1, "stale result after reset");
        end
        check(0, 'h3f800000, 'h3f800000, 'h40000000);
        // FTOI/ITOF against tools/fp32.py (tools/gen_fp32_convert_vectors.py).
        $readmemh("fp32_convert_vectors.hex", vectors);
        for (i = 0; i < CONVERT_VECTORS; i = i + 1) begin
            in_fbits = vectors[4 * i + 1][4:0];
            check(vectors[4 * i][2:0], vectors[4 * i + 2], 32'd0, vectors[4 * i + 3]);
        end
        // A conversion waits for the fast path to drain, and back to back.
        in_fbits = 16;
        issue(2, 'h3fc00000, 'h40800000); // 6, in the fast path
        in_valid = 1; in_op = 4; in_a = 'h3fc00000;
        #1;
        if (in_ready) $fatal(1, "conversion accepted before draining fast path");
        in_valid = 0;
        await_result('h40c00000);
        check(4, 'h3fc00000, 0, 'h00018000); // 1.5 in Q16.16
        issue(4, 'h3fc00000, 0);
        @(negedge clk);
        if (in_ready) $fatal(1, "accepted while converting");
        await_result('h00018000);
        in_fbits = 0;
        issue(5, 'hfffffffd, 0);
        await_result('hc0400000);
        check(0, 'h3f800000, 'h3f800000, 'h40000000);
        $display("PASS: fp32_alu (4000 random operations, %0d conversions, edge cases and handshake)",
                 CONVERT_VECTORS);
        $finish;
    end
endmodule
