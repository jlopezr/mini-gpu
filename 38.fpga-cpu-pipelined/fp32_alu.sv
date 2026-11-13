// FP32 arithmetic: four elastic stages, iterative divide, RNE, DAZ/FTZ.
// Canonical NaN; no exception flags. in_op: 0 add, 1 subtract, 2 multiply, 3 divide,
// 4 FTOI (float -> int32, trunc(a * 2^in_fbits), saturating, NaN -> 0),
// 5 ITOF (int32 -> float, a / 2^in_fbits, RNE). Conversions, like the divide,
// start with the unit empty and take two steps after the accept.
module fp32_alu (
    input  logic        clk,
    input  logic        rst,
    input  logic        in_valid,
    output logic        in_ready,
    input  logic [2:0]  in_op,
    input  logic [4:0]  in_fbits,
    input  logic [31:0] in_a,
    input  logic [31:0] in_b,
    output logic        out_valid,
    input  logic        out_ready,
    output logic [31:0] out_data
);
    localparam logic [31:0] QNAN = 32'h7fc0_0000;
    localparam logic [31:0] PINF = 32'h7f80_0000;
    localparam logic [31:0] NINF = 32'hff80_0000;

    function automatic logic is_nan(input logic [31:0] value);
        is_nan = (&value[30:23]) && (|value[22:0]);
    endfunction

    function automatic logic is_inf(input logic [31:0] value);
        is_inf = (&value[30:23]) && !(|value[22:0]);
    endfunction

    function automatic logic is_zero(input logic [31:0] value);
        is_zero = value[30:23] == 0; // Includes subnormals (DAZ).
    endfunction

    function automatic logic [31:0] pack_rne(
        input logic sign, input logic signed [10:0] exponent,
        input logic [26:0] mantissa
    );
        logic [24:0] rounded;
        logic signed [10:0] e;
        begin
            rounded = {1'b0, mantissa[26:3]} +
                (mantissa[2] && (mantissa[1] || mantissa[0] || mantissa[3]));
            e = exponent;
            if (rounded[24]) begin rounded = rounded >> 1; e = e + 11'sd1; end
            // Under FTZ only rounding up to the smallest normal can survive
            // an exponent <= 0. At exponent 0 its exact halfway threshold is
            // 2^27 - 8, with the tie rounding to the even minimum normal.
            if (exponent <= 0)
                pack_rne = {sign, (exponent == 0 && mantissa >= 27'h7fffff8) ?
                            31'h00800000 : 31'd0};
            else if (e >= 255) pack_rne = {sign, 8'hff, 23'd0};
            else if (!rounded[23]) pack_rne = {sign, 31'd0};
            else pack_rne = {sign, e[7:0], rounded[22:0]};
        end
    endfunction

    // Preparation: sort operands and compute the exponent difference before
    // registering them. This keeps the CPU forwarding mux out of the barrel
    // shifter/add path. Special values travel beside the numeric datapath.
    function automatic logic [66:0] sort_add(
        input logic [31:0] a, b, input logic subtract
    );
        logic sa, sb, sl, ss;
        logic [7:0] ea, eb, el, es;
        logic [23:0] ma, mb, ml, ms;
        begin
            sa = a[31]; sb = b[31] ^ subtract;
            ea = a[30:23]; eb = b[30:23];
            ma = ea == 0 ? 24'd0 : {1'b1, a[22:0]};
            mb = eb == 0 ? 24'd0 : {1'b1, b[22:0]};
            if ({ea, ma} >= {eb, mb}) begin
                el = ea; es = eb; ml = ma; ms = mb; sl = sa; ss = sb;
            end else begin
                el = eb; es = ea; ml = mb; ms = ma; sl = sb; ss = sa;
            end
            sort_add = {sa & sb, sl, ss, el, (el - es), ml, ms};
        end
    endfunction

    // Stage 1: align and add/subtract the registered significands.
    function automatic logic [39:0] add_raw(input logic [66:0] operands);
        logic zero_sign, sl, ss;
        logic [7:0] el, shift_count;
        logic [23:0] ml, ms;
        logic [26:0] aligned_large, aligned_small;
        logic [27:0] result;
        begin
            {zero_sign, sl, ss, el, shift_count, ml, ms} = operands;
            aligned_large = {ml, 3'b0};
            if (shift_count > 26) aligned_small = (|ms) ? 27'd1 : 27'd0;
            else begin
                aligned_small = {ms, 3'b0} >> shift_count;
                if (|({ms, 3'b0} & ((27'd1 << shift_count) - 1))) aligned_small[0] = 1;
            end
            if (sl == ss) result = {1'b0, aligned_large} + {1'b0, aligned_small};
            else result = {1'b0, aligned_large} - {1'b0, aligned_small};
            add_raw = {(result == 0 ? zero_sign : sl), 3'b0, el, result};
        end
    endfunction

    // Stage 2: normalize with a five-level leading-zero tree, not 26
    // dependent shifts. The exponent uses only eleven signed bits.
    function automatic logic [38:0] normalize(
        input logic mul, sign, input logic signed [10:0] exponent,
        input logic [27:0] sum, input logic [47:0] product
    );
        logic [26:0] m;
        logic signed [10:0] e;
        logic [4:0] leading_zeros;
        begin
            leading_zeros = 0;
            e = exponent;
            if (mul) begin
                if (product[47]) begin
                    m = {product[47:24], product[23:22], |product[21:0]};
                    e = e + 11'sd1;
                end else m = {product[46:23], product[22:21], |product[20:0]};
            end else if (sum[27]) begin
                m = sum[27:1]; m[0] = m[0] | sum[0]; e = e + 11'sd1;
            end else begin
                m = sum[26:0];
                if (m != 0) begin
                    if (!(|m[26:11])) begin m = m << 16; leading_zeros = leading_zeros | 5'd16; end
                    if (!(|m[26:19])) begin m = m << 8; leading_zeros = leading_zeros | 5'd8; end
                    if (!(|m[26:23])) begin m = m << 4; leading_zeros = leading_zeros | 5'd4; end
                    if (!(|m[26:25])) begin m = m << 2; leading_zeros = leading_zeros | 5'd2; end
                    if (!m[26]) begin m = m << 1; leading_zeros = leading_zeros | 5'd1; end
                    e = exponent - $signed({6'b0, leading_zeros});
                end
            end
            normalize = {sign, e, m};
        end
    endfunction

    logic stage0_mul, stage0_sign, stage0_special;
    logic [31:0] stage0_special_data;
    logic signed [10:0] stage0_exponent;
    logic [66:0] stage0_operands;
    logic [47:0] stage0_product;
    logic stage0_valid;
    logic stage1_mul, stage1_sign, stage2_sign;
    logic signed [10:0] stage1_exponent, stage2_exponent;
    logic [27:0] stage1_sum;
    logic [47:0] stage1_product;
    logic [26:0] stage2_mantissa;
    logic stage1_special, stage2_special;
    logic [31:0] stage1_special_data, stage2_special_data, stage3_data;
    logic input_special;
    logic [31:0] input_special_data;
    logic input_b_sign;
    always_comb begin
        input_b_sign = in_b[31] ^ (in_op == 3'd1);
        input_special = 0;
        input_special_data = QNAN;
        if (is_nan(in_a) || is_nan(in_b)) input_special = 1;
        else if (in_op == 3'd2) begin
            input_special = is_inf(in_a) || is_inf(in_b) || is_zero(in_a) || is_zero(in_b);
            if ((is_inf(in_a) && is_zero(in_b)) || (is_inf(in_b) && is_zero(in_a)))
                input_special_data = QNAN;
            else if (is_inf(in_a) || is_inf(in_b))
                input_special_data = {in_a[31] ^ in_b[31], 8'hff, 23'd0};
            else input_special_data = {in_a[31] ^ in_b[31], 31'd0};
        end else begin
            input_special = is_inf(in_a) || is_inf(in_b);
            if (is_inf(in_a) && is_inf(in_b) && in_a[31] != input_b_sign)
                input_special_data = QNAN;
            else input_special_data = {is_inf(in_a) ? in_a[31] : input_b_sign, 8'hff, 23'd0};
        end
    end

    logic stage1_valid, stage2_valid, stage3_valid;
    logic divisor_busy, divisor_sign;
    logic signed [10:0] divisor_exponent;
    logic [23:0] divisor_denominator;
    logic [25:0] divisor_remainder, divisor_quotient;
    wire stage3_ready = !stage3_valid || out_ready;
    wire stage2_ready = !stage2_valid || stage3_ready;
    wire stage1_ready = !stage1_valid || stage2_ready;
    wire stage0_ready = !stage0_valid || stage1_ready;
    logic [5:0] divisor_count;
    logic [31:0] divisor_special;
    logic divisor_is_special;
    logic [26:0] shifted_remainder;
    logic [25:0] next_quotient;
    logic fast_accept, divide_accept, convert_accept;

    // Conversions. Step 1 shifts (FTOI: the significand into place; ITOF: the
    // magnitude normalized with a leading-zero tree); step 2 saturates and
    // negates, or rounds. convert_* hold the accepted operands, convert_step
    // says which step runs this cycle.
    logic convert_busy, convert_step, convert_itof, convert_sign;
    logic [31:0] convert_a;
    logic [4:0] convert_fbits;
    logic convert_nan, convert_saturate;
    logic [31:0] convert_magnitude;
    logic signed [10:0] convert_exponent;

    // FTOI step 1: |a| * 2^fbits truncated, or saturate when it is >= 2^31.
    function automatic logic [33:0] ftoi_shift(input logic [31:0] a, input logic [4:0] fbits);
        logic signed [10:0] shift;
        logic [31:0] full, magnitude;
        logic saturate;
        begin
            shift = $signed({3'b0, a[30:23]}) - 11'sd150 + $signed({6'b0, fbits});
            full = {8'b0, 1'b1, a[22:0]};
            saturate = 0;
            magnitude = 0;
            if (a[30:23] == 8'd0) magnitude = 0;             // zero or subnormal
            else if (shift >= 11'sd8) saturate = 1;           // >= 2^31, also infinity
            else if (shift >= 11'sd0) magnitude = full << shift[2:0];
            else if (shift > -11'sd32) magnitude = full >> (-shift);
            ftoi_shift = {(&a[30:23]) && (|a[22:0]), saturate, magnitude};
        end
    endfunction

    // ITOF step 1: |a| with its leading 1 at bit 31, and the exponent.
    function automatic logic [42:0] itof_normalize(input logic [31:0] magnitude, input logic [4:0] fbits);
        logic [31:0] m;
        logic [4:0] zeros;
        begin
            m = magnitude;
            zeros = 0;
            if (!(|m[31:16])) begin m = m << 16; zeros = zeros | 5'd16; end
            if (!(|m[31:24])) begin m = m << 8; zeros = zeros | 5'd8; end
            if (!(|m[31:28])) begin m = m << 4; zeros = zeros | 5'd4; end
            if (!(|m[31:30])) begin m = m << 2; zeros = zeros | 5'd2; end
            if (!m[31]) begin m = m << 1; zeros = zeros | 5'd1; end
            // value = m * 2^(31 - zeros - 31 - fbits): exponent 127 + 31 - zeros - fbits
            itof_normalize = {11'sd158 - $signed({6'b0, zeros}) - $signed({6'b0, fbits}), m};
        end
    endfunction

    assign out_valid = stage3_valid;
    assign out_data = stage3_data;
    assign fast_accept = in_valid && (in_op <= 3'd2) && in_ready;
    assign divide_accept = in_valid && (in_op == 3'd3) && in_ready;
    assign convert_accept = in_valid && in_op[2] && in_ready;
    // A division or conversion starts only with a completely empty fast path,
    // preventing a response collision while retaining one operation/cycle
    // fast-path issue.
    assign in_ready = !divisor_busy && !convert_busy && (in_op >= 3'd3 ?
        !(stage0_valid || stage1_valid || stage2_valid || stage3_valid) :
        stage0_ready);

    always_comb begin
        shifted_remainder = {divisor_remainder, 1'b0};
        next_quotient = {divisor_quotient[24:0], 1'b0};
        if (shifted_remainder >= {3'b0, divisor_denominator}) begin
            shifted_remainder = shifted_remainder - {3'b0, divisor_denominator};
            next_quotient[0] = 1'b1;
        end
    end

    always_ff @(posedge clk) begin
        if (fast_accept && in_op == 3'd2)
            stage0_product <= {1'b1, in_a[22:0]} * {1'b1, in_b[22:0]};
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            stage0_valid <= 0; stage1_valid <= 0; stage2_valid <= 0; stage3_valid <= 0;
            divisor_busy <= 0; divisor_count <= 0;
            convert_busy <= 0; convert_step <= 0;
        end else begin
            if (out_ready) stage3_valid <= 0;
            if (!divisor_busy) begin
                if (stage3_ready) begin
                    stage3_valid <= stage2_valid;
                    stage3_data <= stage2_special ? stage2_special_data :
                        pack_rne(stage2_sign, stage2_exponent, stage2_mantissa);
                end
                if (stage2_ready) begin
                    stage2_valid <= stage1_valid;
                    {stage2_sign, stage2_exponent, stage2_mantissa} <=
                        normalize(stage1_mul, stage1_sign, stage1_exponent, stage1_sum, stage1_product);
                    stage2_special <= stage1_special;
                    stage2_special_data <= stage1_special_data;
                end
                if (stage1_ready) begin
                    stage1_valid <= stage0_valid;
                    stage1_mul <= stage0_mul;
                    stage1_special <= stage0_special;
                    stage1_special_data <= stage0_special_data;
                    stage1_product <= stage0_product;
                    if (stage0_mul) begin
                        stage1_sign <= stage0_sign;
                        stage1_exponent <= stage0_exponent;
                    end else
                        {stage1_sign, stage1_exponent, stage1_sum} <= add_raw(stage0_operands);
                end
                if (stage0_ready) stage0_valid <= fast_accept;
                if (fast_accept) begin
                    stage0_mul <= in_op == 2'd2;
                    stage0_special <= input_special;
                    stage0_special_data <= input_special_data;
                    stage0_sign <= in_a[31] ^ in_b[31];
                    stage0_exponent <= $signed({3'b0, in_a[30:23]}) +
                        $signed({3'b0, in_b[30:23]}) - 11'sd127;
                    stage0_operands <= sort_add(in_a, in_b, in_op[0]);
                end
                if (convert_accept) begin
                    convert_busy <= 1;
                    convert_step <= 0;
                    convert_itof <= in_op[0];
                    convert_a <= in_a;
                    convert_fbits <= in_fbits;
                end
                if (divide_accept) begin
                    divisor_busy <= 1;
                    divisor_count <= 0;
                    divisor_sign <= in_a[31] ^ in_b[31];
                    divisor_exponent <= $signed({3'b0, in_a[30:23]}) -
                        $signed({3'b0, in_b[30:23]}) + 11'sd127 -
                        ({1'b1, in_a[22:0]} < {1'b1, in_b[22:0]});
                    divisor_denominator <= {1'b1, in_b[22:0]};
                    divisor_remainder <= ({1'b1, in_a[22:0]} >= {1'b1, in_b[22:0]}) ?
                        ({2'b0, 1'b1, in_a[22:0]} - {2'b0, 1'b1, in_b[22:0]}) :
                        ({1'b0, 1'b1, in_a[22:0], 1'b0} - {2'b0, 1'b1, in_b[22:0]});
                    divisor_quotient <= 0;
                    divisor_is_special <= is_nan(in_a) || is_nan(in_b) ||
                        is_zero(in_a) || is_zero(in_b) || is_inf(in_a) || is_inf(in_b);
                    if (is_nan(in_a) || is_nan(in_b) || (is_zero(in_a) && is_zero(in_b)) || (is_inf(in_a) && is_inf(in_b))) divisor_special <= QNAN;
                    else if (is_inf(in_a) || is_zero(in_b)) divisor_special <= (in_a[31] ^ in_b[31]) ? NINF : PINF;
                    else if (is_zero(in_a) || is_inf(in_b) || in_a[30:23] == 0 || in_b[30:23] == 0) divisor_special <= {(in_a[31] ^ in_b[31]), 31'b0};
                    else divisor_special <= 0;
                end
            end else begin
                divisor_remainder <= shifted_remainder[25:0];
                divisor_quotient <= next_quotient;
                divisor_count <= divisor_count + 1;
                if (divisor_count == 6'd25) begin
                    divisor_busy <= 0;
                    stage3_valid <= 1;
                    if (divisor_is_special) stage3_data <= divisor_special;
                    else
                        stage3_data <= pack_rne(divisor_sign, divisor_exponent,
                            {1'b1, next_quotient[25:3],
                             next_quotient[2], next_quotient[1],
                             next_quotient[0] | (|shifted_remainder)});
                end
            end
            if (convert_busy) begin
                convert_step <= 1;
                if (!convert_step) begin
                    if (convert_itof) begin
                        convert_sign <= convert_a[31];
                        convert_nan <= 0;
                        convert_saturate <= convert_a == 0; // zero: +0
                        {convert_exponent, convert_magnitude} <= itof_normalize(
                            convert_a[31] ? 32'd0 - convert_a : convert_a, convert_fbits);
                    end else begin
                        convert_sign <= convert_a[31];
                        {convert_nan, convert_saturate, convert_magnitude} <=
                            ftoi_shift(convert_a, convert_fbits);
                    end
                end else begin
                    convert_busy <= 0;
                    stage3_valid <= 1;
                    if (convert_itof)
                        stage3_data <= convert_saturate ? 32'd0 :
                            pack_rne(convert_sign, convert_exponent,
                                {convert_magnitude[31:6], |convert_magnitude[5:0]});
                    else if (convert_nan)
                        stage3_data <= 32'd0;
                    else if (convert_saturate || convert_magnitude[31])
                        stage3_data <= convert_sign ? 32'h8000_0000 : 32'h7fff_ffff;
                    else
                        stage3_data <= convert_sign ? 32'd0 - convert_magnitude : convert_magnitude;
                end
            end
        end
    end
endmodule
