`default_nettype none
// MiniGPU ROP core, prototype v0.4-area1: sequential one-pixel SPAN/FRAGMENT datapath.
// One active command, multiple outstanding writes, one in-flight read.
// In-order responses are REQUIRED (as in dma_engine_v2).
// FILL/COPY/GEN keep v0.1 alignment rules. SPAN/FRAGMENT support partial words.
//
// Todavia NO esta instanciado en top.v: falta el frontal MMIO con cola de
// comandos. De las variantes del experimento (v0.4, v0.4-area1, area1_debug;
// los originales en ROP.zip) queda esta, con un cambio: GENERATE2D ya no
// encadena ocho sumas `v = v + dx`, sino que suma cur_z + dx_mult[k] por
// carril (dx_mult = k*dx, cargado al aceptar el comando).
//
// Fuera de contexto (Yosys + nextpnr, 85F, 50 MHz), 15 de noviembre:
//   v0.4                 11.347 COMB, 2.289 FF, 2 DSP, 32 MHz
//   area1                 6.584 COMB, 2.323 FF, 0 DSP, 44-45 MHz
//   area1 + GEN           7.462 COMB, 2.432 FF, 5 DSP, 60-61 MHz
//   esta (+ FRAC/SAT, grupos de 8, sin barrera, Z registrada)
//                         8.054 COMB, 2.475 FF, 5 DSP, 60-63 MHz
// Banco: rop_core_tb.sv y rop_core_stress_tb.sv.
//
// Modo de SPAN/FRAGMENT (cmd_mode en los explicitos; el modo de render de
// CONFIG, p8[15:0], en los compactos, con el bit 12 a cero):
//   [2:0] comparacion (0 ALWAYS, 1 EQ, 2 NE, 3 LT, 4 LE, 5 GT, 6 GE)
//   [3] color de 32 bits  [4] Z de 32 bits  [5] escribe Z  [6] escribe color
//   [7] comparacion con signo
//   [11:8] FRAC: la Z de cada pixel es el acumulador desplazado
//          aritmeticamente FRAC bits (z >>> FRAC); el acumulador sigue siendo
//          de 32 bits y modular, asi que la fraccion no se pierde entre pixeles.
//          En los compactos [11:8] son los overrides y FRAC sale de CONFIG.
//   [12] compacto (solo en cmd_mode)
//   [13] SAT: con Z16, el valor desplazado se satura a 0..65535 en vez de
//          quedarse con sus 16 bits bajos. Es lo que hace mini-gl
//          (FRAC = 8, MGR_DEPTH_FRAC). Solo con Z16 y comparacion sin signo.
//   [15:14] reservados, a cero.
//
// Los grupos de SPAN/FRAGMENT son de hasta 8 pixeles (lo que cabe en la
// palabra de 128 bits de Z y de color) y NO esperan a que terminen las
// escrituras del grupo anterior: las escrituras llevan mascara de bytes y dos
// grupos que comparten palabra tocan pixeles distintos. Las filas de un SPAN
// no deben solaparse.
module rop_core #(
    parameter integer TAG_DEPTH = 8
)(
    input wire clk,
    input wire reset,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [2:0] cmd_op,       // 0 FILL, 1 COPY, 2 GENERATE2D, 3 SPAN, 4 FRAGMENT, 5 CONFIG
    input wire [15:0] cmd_mode,    // meaning depends on cmd_op (see header)
    input wire [319:0] cmd_params, // p0 = bits 31:0, ..., p9 = 319:288
    input wire [255:0] cmd_frag_colors, // lane i color at [32*i +: 32]
    input wire [255:0] cmd_frag_z,      // lane i Z at [32*i +: 32]
    output reg done_valid,         // single-cycle completion pulse
    output reg done_error,         // meaningful when done_valid
    output wire busy,
    output wire req_valid,
    input wire req_ready,
    output wire req_write,
    output wire [31:0] req_addr,
    output wire [127:0] req_wdata,
    output wire [15:0] req_wmask,
    input wire rsp_valid,
    output wire rsp_ready,
    input wire [127:0] rsp_rdata,
    input wire rsp_error
);
    localparam [2:0] OP_FILL=3'd0, OP_COPY=3'd1, OP_GEN=3'd2, OP_SPAN=3'd3, OP_FRAGMENT=3'd4, OP_CONFIG=3'd5;
    localparam [3:0] S_IDLE=0, S_PREP=1, S_READ_REQ=2,
       S_READ_WAIT=3, S_WRITE_REQ=4, S_ADV=5, S_DRAIN=6,
       S_SP_PREP=7, S_SP_READ_REQ=8, S_SP_READ_WAIT=9,
       S_SP_Z_REQ=10, S_SP_COLOR_REQ=11, S_SP_ADV=12,
       S_SP_PIXEL=14;   // 13 era S_SP_SYNC, la barrera que se quito
    localparam integer PTR_W = (TAG_DEPTH <= 2) ? 1 : $clog2(TAG_DEPTH);
    // Ordered persistent configuration. No MMIO; CONFIG is another command.
    // CONFIG mode[4:0] selects fields to update (see README v0.4).
    reg [31:0] cfg_color_base, cfg_z_base;
    reg [31:0] cfg_color_stride, cfg_z_stride;
    reg [31:0] cfg_color, cfg_z0, cfg_dx, cfg_dy;
    reg [15:0] cfg_render_mode;
    reg [4:0] cfg_written;
    reg [3:0] state;
    reg [2:0] op;
    reg [15:0] mode;
    reg [31:0] row_src, row_dst, cur_src, cur_dst;
    reg [31:0] rows_left, blocks_left, blocks_per_row;
    reg [31:0] src_stride, dst_stride, pattern, dx, dy;
    // k*dx para k = 0..7, cargados al aceptar el comando (GENERATE2D). Cada
    // carril de gen_word suma cur_z + k*dx en paralelo: antes era una cadena de
    // ocho sumas (v = v + dx) seguida de la comparacion, el camino critico
    // (44 MHz fuera de contexto).
    reg [31:0] dx_mult [0:7];
    integer dk;
    reg [31:0] row_z, cur_z;
    // SPAN owns explicit independent color/depth pointers and strides.
    reg [31:0] sp_color_row, sp_z_row, sp_color_cur, sp_z_cur;
    reg [31:0] sp_color_stride, sp_z_stride;
    reg [31:0] sp_width, sp_remaining, sp_rows, sp_row_initial, sp_cur_z;
    reg [31:0] sp_dx, sp_dy, sp_color;
    reg [3:0] sp_step;
    reg [2:0] sp_pixel_index;
    reg [31:0] sp_pixel_z;
    reg [3:0] frag_index;   // index of first fragment in current group (0..7)
    reg [7:0] frag_coverage;
    reg [255:0] frag_colors, frag_depths;
    reg [127:0] sp_z_data, sp_color_data;
    reg [15:0] sp_z_mask, sp_color_mask;
    reg [127:0] read_buffer;
    reg [127:0] generated;
    reg [15:0] write_mask;
    reg failed;
    reg [PTR_W-1:0] tag_wr, tag_rd;
    reg [PTR_W:0] tag_count;
    reg tag_is_read [0:TAG_DEPTH-1];
    wire tags_full = (tag_count == TAG_DEPTH);
    wire tags_empty = (tag_count == 0);
    wire [31:0] p0=cmd_params[31:0];
    wire [31:0] p1=cmd_params[63:32];
    wire [31:0] p2=cmd_params[95:64];
    wire [31:0] p3=cmd_params[127:96];
    wire [31:0] p4=cmd_params[159:128];
    wire [31:0] p5=cmd_params[191:160];
    wire [31:0] p6=cmd_params[223:192];
    wire [31:0] p7=cmd_params[255:224];
    wire [31:0] p8=cmd_params[287:256];
    wire [31:0] p9=cmd_params[319:288];
    wire compact_graphics = cmd_mode[12];
    wire [31:0] compact_color_address = cfg_color_base + p0;
    wire [31:0] compact_z_address = cfg_z_base + p1;
    // Compact SPAN overrides: bit 8 color, bit 9 initial Z,
    // bit 10 dX, bit 11 dY. FRAGMENT must not set overrides.
    wire [31:0] effective_color = cmd_mode[8] ? p4 : cfg_color;
    wire [31:0] effective_z0 = cmd_mode[9] ? p5 : cfg_z0;
    wire [31:0] effective_dx = cmd_mode[10] ? p6 : cfg_dx;
    wire [31:0] effective_dy = cmd_mode[11] ? p7 : cfg_dy;
    wire width32 = mode[3];
    wire sp_color32 = mode[3];
    wire sp_z32 = mode[4];
    wire sp_write_z = mode[5];
    wire sp_write_color = mode[6];
    wire sp_signed = mode[7];
    wire [3:0] sp_frac = mode[11:8];
    wire sp_sat = mode[13];
    wire [2:0] sp_cmp = mode[2:0];
    wire [31:0] sp_z_offset = {28'd0, sp_z_cur[3:0]};
    wire [31:0] sp_color_offset = {28'd0, sp_color_cur[3:0]};
    wire [31:0] sp_z_room = (32'd16 - sp_z_offset) >> (sp_z32 ? 2 : 1);
    wire [31:0] sp_color_room = (32'd16 - sp_color_offset) >> (sp_color32 ? 2 : 1);
    wire [31:0] sp_step_w = (sp_remaining < 32'd8 ? sp_remaining : 32'd8) < sp_z_room ?
        (sp_remaining < 32'd8 ? sp_remaining : 32'd8) : sp_z_room;
    wire [31:0] sp_step_calc = sp_step_w < sp_color_room ? sp_step_w : sp_color_room;
    wire [31:0] value_step = width32 ? (dx << 2) : (dx << 3);
    wire response = rsp_valid && rsp_ready;
    
    // We need no read for unconditional FILL and GENERATE2D.
    wire needs_read = (op == OP_COPY) ||
                      ((op == OP_GEN) && (mode[2:0] != 3'd0));
    assign cmd_ready = (state == S_IDLE) && !reset;
    assign busy = (state != S_IDLE);
    assign req_valid = !reset && !tags_full && !(response && rsp_error) &&
                       (state == S_READ_REQ ||
                       (state == S_WRITE_REQ && write_mask != 16'h0000) ||
                       state == S_SP_READ_REQ ||
                       (state == S_SP_Z_REQ && sp_z_mask != 0) ||
                       (state == S_SP_COLOR_REQ && sp_color_mask != 0));
    assign req_write = (state == S_WRITE_REQ || state == S_SP_Z_REQ ||
                        state == S_SP_COLOR_REQ);
    assign req_addr = (state == S_SP_READ_REQ || state == S_SP_Z_REQ) ?
                          {sp_z_cur[31:4], 4'b0} :
                      (state == S_SP_COLOR_REQ) ?
                          {sp_color_cur[31:4], 4'b0} :
                      (state == S_READ_REQ) ?
                          ((op == OP_COPY) ? cur_src : cur_dst) : cur_dst;
    assign req_wdata = (state == S_SP_Z_REQ) ? sp_z_data :
                       (state == S_SP_COLOR_REQ) ? sp_color_data :
                       (op == OP_FILL) ? {4{pattern}} :
                       ((op == OP_COPY) ? read_buffer : generated);
    assign req_wmask = (state == S_SP_Z_REQ) ? sp_z_mask :
                       (state == S_SP_COLOR_REQ) ? sp_color_mask :
                       (state == S_WRITE_REQ) ? write_mask : 16'h0000;
    wire issue = req_valid && req_ready;
    assign rsp_ready = !reset && !tags_empty;    
    wire read_response = response && tag_is_read[tag_rd];
    wire [2:0] cmp = mode[2:0];
    wire signed_cmp = mode[4];

    // Parallel candidate generation. May be replaced by a multicycle generator
    // if the timing/area results suggest sharing the adder.
    reg [127:0] gen_word;
    reg [15:0] cmp_mask;
    reg [31:0] v;
    reg passed;
    reg [31:0] new_value, old_value;
    integer k;
    always @* begin
        gen_word = 128'd0;
        cmp_mask = 16'd0;
        v = cur_z;
        passed = 1'b0;
        new_value = 32'd0;
        old_value = 32'd0;
        for (k=0; k<8; k=k+1) begin
            v = cur_z + dx_mult[k];
            if ((width32 && k<4) || !width32) begin
                if (width32) begin
                    new_value = v;
                    old_value = rsp_rdata[k*32 +: 32];
                    gen_word[k*32 +: 32] = v;
                end else begin
                    new_value = {16'd0,v[15:0]};
                    old_value = {16'd0,rsp_rdata[k*16 +: 16]};
                    gen_word[k*16 +: 16] = v[15:0];
                end
                case (cmp)
                    3'd0: passed = 1'b1;
                    3'd1: passed = (new_value == old_value);
                    3'd2: passed = (new_value != old_value);
                    3'd3: passed = signed_cmp ?
                        (width32 ? ($signed(new_value) < $signed(old_value)) :
                                   ($signed(new_value[15:0]) < $signed(old_value[15:0]))) :
                        (new_value < old_value);
                    3'd4: passed = signed_cmp ?
                        (width32 ? ($signed(new_value) <= $signed(old_value)) :
                                   ($signed(new_value[15:0]) <= $signed(old_value[15:0]))) :
                        (new_value <= old_value);
                    3'd5: passed = signed_cmp ?
                        (width32 ? ($signed(new_value) > $signed(old_value)) :
                                   ($signed(new_value[15:0]) > $signed(old_value[15:0]))) :
                        (new_value > old_value);
                    3'd6: passed = signed_cmp ?
                        (width32 ? ($signed(new_value) >= $signed(old_value)) :
                                   ($signed(new_value[15:0]) >= $signed(old_value[15:0]))) :
                        (new_value >= old_value);
                    default: passed = 1'b0;
                endcase
                if (passed) begin
                    if (width32) cmp_mask[k*4 +: 4] = 4'hf;
                    else cmp_mask[k*2 +: 2] = 2'b11;
                end
            end
        end
    end

    // One pixel per cycle. The read response is latched into read_buffer,
    // and four parallel Z compares and variable 128-bit shifts are replaced
    // by a single pixel extractor, comparator and byte-lane writer.
    // Pixel addresses are always aligned within the current 128-bit word.
    wire [3:0] sp_lane_index = frag_index + {1'b0, sp_pixel_index};
    wire [31:0] sp_pixel_color = (op == OP_FRAGMENT) ?
        frag_colors[sp_lane_index*32 +: 32] : sp_color;
    wire [4:0] sp_pixel_z_byte = {1'b0,sp_z_cur[3:0]} +
        (sp_z32 ? {sp_pixel_index,2'b00} : {1'b0,sp_pixel_index,1'b0});
    wire [4:0] sp_pixel_color_byte = {1'b0,sp_color_cur[3:0]} +
        (sp_color32 ? {sp_pixel_index,2'b00} : {1'b0,sp_pixel_index,1'b0});
    wire [6:0] sp_pixel_z_bit = {sp_pixel_z_byte[3:0],3'b000};
    wire [6:0] sp_pixel_color_bit = {sp_pixel_color_byte[3:0],3'b000};
    wire [31:0] sp_pixel_old = sp_z32 ?
        read_buffer[sp_pixel_z_bit +: 32] :
        {16'd0,read_buffer[sp_pixel_z_bit +: 16]};
    // Formato de la Z: desplazamiento aritmetico FRAC y, con SAT, saturacion
    // a 16 bits sin signo. Se calcula UN CICLO ANTES y se registra en
    // sp_new_q: en S_SP_PREP el del primer pixel del grupo, y en cada ciclo de
    // S_SP_PIXEL el del siguiente. Asi el mux del carril, el desplazamiento y
    // la saturacion no van en serie con la comparacion y las mascaras (sin
    // registrar, 45-46 MHz fuera de contexto).
    wire [3:0] sp_next_lane = (sp_lane_index + 4'd1) & 4'd7;
    wire [31:0] sp_fmt_in = (state == S_SP_PIXEL) ?
        ((op == OP_FRAGMENT) ? frag_depths[sp_next_lane*32 +: 32] : sp_pixel_z + sp_dx) :
        ((op == OP_FRAGMENT) ? frag_depths[frag_index[2:0]*32 +: 32] : sp_cur_z);
    wire signed [31:0] sp_fmt_shifted = $signed(sp_fmt_in) >>> sp_frac;
    wire [15:0] sp_fmt_z16 = !sp_sat ? sp_fmt_shifted[15:0] :
        sp_fmt_shifted[31] ? 16'd0 :
        (|sp_fmt_shifted[30:16]) ? 16'hffff : sp_fmt_shifted[15:0];
    wire [31:0] sp_fmt_out = sp_z32 ? sp_fmt_shifted : {16'd0,sp_fmt_z16};
    reg [31:0] sp_new_q;
    wire [31:0] sp_pixel_new = sp_new_q;
    wire sp_eq = (sp_pixel_new == sp_pixel_old);
    // Flip the sign bit for a single unsigned comparison circuit in both
    // signed and unsigned modes. Z16 is compared in the low 16 bits.
    wire [31:0] sp_order_new = sp_signed ?
        (sp_z32 ? (sp_pixel_new ^ 32'h80000000) :
                  (sp_pixel_new ^ 32'h00008000)) : sp_pixel_new;
    wire [31:0] sp_order_old = sp_signed ?
        (sp_z32 ? (sp_pixel_old ^ 32'h80000000) :
                  (sp_pixel_old ^ 32'h00008000)) : sp_pixel_old;
    wire sp_lt = sp_order_new < sp_order_old;
    reg sp_pixel_pass;
    always @* begin
        case (sp_cmp)
            3'd0: sp_pixel_pass = 1'b1;
            3'd1: sp_pixel_pass = sp_eq;
            3'd2: sp_pixel_pass = !sp_eq;
            3'd3: sp_pixel_pass = sp_lt;
            3'd4: sp_pixel_pass = sp_lt || sp_eq;
            3'd5: sp_pixel_pass = !sp_lt && !sp_eq;
            3'd6: sp_pixel_pass = !sp_lt;
            default: sp_pixel_pass = 1'b0;
        endcase
        if (op == OP_FRAGMENT && !frag_coverage[sp_lane_index])
            sp_pixel_pass = 1'b0;
    end

    // Pointers do not need power-of-two depth (only TAG_DEPTH >=2).
    wire [PTR_W-1:0] wr_next = (tag_wr == TAG_DEPTH-1) ? 0 : tag_wr + 1'b1;
    wire [PTR_W-1:0] rd_next = (tag_rd == TAG_DEPTH-1) ? 0 : tag_rd + 1'b1;
    // SAT solo tiene sentido con Z16 y comparacion sin signo.
    function z_format_ok(input [15:0] m);
        z_format_ok = !m[13] || (!m[4] && !m[7]);
    endfunction
    reg valid_command;
    always @* begin
        valid_command = 1'b0;
        case (cmd_op)
            OP_FILL: valid_command = p1 != 0 && p2 != 0 &&
                p0[3:0] == 0 && p1[3:0] == 0 && p3[3:0] == 0;
            OP_COPY: valid_command = p2 != 0 && p3 != 0 &&
                p0[3:0] == 0 && p1[3:0] == 0 && p2[3:0] == 0 &&
                p4[3:0] == 0 && p5[3:0] == 0;
            OP_GEN: valid_command = p1 != 0 && p2 != 0 &&
                p0[3:0] == 0 && p3[3:0] == 0 &&
                (cmd_mode[3] ? (p1[1:0] == 0) : (p1[2:0] == 0)) &&
                cmd_mode[2:0] != 3'd7 && cmd_mode[15:5] == 0;
            OP_SPAN: begin
                if (!compact_graphics) begin
                    valid_command = p2 != 0 && p3 != 0 &&
                        cmd_mode[2:0] != 3'd7 && cmd_mode[12] == 0 &&
                        cmd_mode[15:14] == 0 && z_format_ok(cmd_mode) &&
                        (cmd_mode[5] || cmd_mode[6]) &&
                        p0[0] == 0 && p1[0] == 0 &&
                        (!cmd_mode[3] || (p0[1:0] == 0 && p4[1:0] == 0)) &&
                        (!cmd_mode[4] || (p1[1:0] == 0 && p5[1:0] == 0)) &&
                        (cmd_mode[3] || !p4[0]) &&
                        (cmd_mode[4] || !p5[0]);
                end else begin
                    valid_command = (cfg_written == 5'b11111) &&
                        p2 != 0 && p3 != 0 && cmd_mode[7:0] == 0 &&
                        cmd_mode[15:13] == 0 &&
                        p8 == 0 && p9 == 0 &&
                        cfg_render_mode[2:0] != 3'd7 &&
                        (cfg_render_mode[5] || cfg_render_mode[6]) &&
                        compact_color_address[0] == 0 && compact_z_address[0] == 0 &&
                        (!cfg_render_mode[3] || (compact_color_address[1:0] == 0 && cfg_color_stride[1:0] == 0)) &&
                        (!cfg_render_mode[4] || (compact_z_address[1:0] == 0 && cfg_z_stride[1:0] == 0)) &&
                        (cfg_render_mode[3] || !cfg_color_stride[0]) &&
                        (cfg_render_mode[4] || !cfg_z_stride[0]);
                end
            end
            OP_FRAGMENT: begin
                if (!compact_graphics) begin
                    valid_command = p2 >= 1 && p2 <= 8 &&
                        cmd_mode[2:0] != 3'd7 && cmd_mode[12] == 0 &&
                        cmd_mode[15:14] == 0 && z_format_ok(cmd_mode) &&
                        (cmd_mode[5] || cmd_mode[6]) &&
                        p0[0] == 0 && p1[0] == 0 &&
                        (!cmd_mode[3] || p0[1:0] == 0) &&
                        (!cmd_mode[4] || p1[1:0] == 0) &&
                        p3[31:8] == 0 && (p3[7:0] >> p2) == 0 &&
                        p4 == 0 && p5 == 0 && p6 == 0 && p7 == 0 &&
                        p8 == 0 && p9 == 0;
                end else begin
                    valid_command = cfg_written[4:0] == 5'b11111 &&
                        cmd_mode[11:0] == 0 && cmd_mode[15:13] == 0 &&
                        p2 >= 1 && p2 <= 8 &&
                        cfg_render_mode[2:0] != 3'd7 &&
                        (cfg_render_mode[5] || cfg_render_mode[6]) &&
                        compact_color_address[0] == 0 && compact_z_address[0] == 0 &&
                        (!cfg_render_mode[3] || compact_color_address[1:0] == 0) &&
                        (!cfg_render_mode[4] || compact_z_address[1:0] == 0) &&
                        p3[31:8] == 0 && (p3[7:0] >> p2) == 0 &&
                        p4 == 0 && p5 == 0 && p6 == 0 && p7 == 0 &&
                        p8 == 0 && p9 == 0;
                end
            end
            OP_CONFIG: valid_command = cmd_mode[15:5] == 0 &&
                cmd_mode[4:0] != 0 &&
                p9 == 0 &&
                (!cmd_mode[4] || (p8[31:16] == 0 && p8[2:0] != 3'd7 &&
                    p8[12] == 0 && p8[15:14] == 0 && z_format_ok(p8[15:0]) &&
                    (p8[5] || p8[6])));
            default: valid_command = 1'b0;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= S_IDLE;
            cfg_color_base <= 0; cfg_z_base <= 0;
            cfg_color_stride <= 0; cfg_z_stride <= 0;
            cfg_color <= 0; cfg_z0 <= 0; cfg_dx <= 0; cfg_dy <= 0;
            cfg_render_mode <= 0; cfg_written <= 0;
            done_valid <= 0;
            done_error <= 0;
            op <= 0; mode <= 0;
            row_src <= 0; row_dst <= 0; cur_src <= 0; cur_dst <= 0;
            rows_left <= 0; blocks_left <= 0; blocks_per_row <= 0;
            src_stride <= 0; dst_stride <= 0; pattern <= 0;
            dx <= 0; dy <= 0; row_z <= 0; cur_z <= 0;
            read_buffer <= 0; generated <= 0; write_mask <= 0;
            failed <= 0; tag_wr <= 0; tag_rd <= 0; tag_count <= 0;
            sp_color_row <= 0; sp_z_row <= 0; sp_color_cur <= 0; sp_z_cur <= 0;
            sp_color_stride <= 0; sp_z_stride <= 0;
            sp_width <= 0; sp_remaining <= 0; sp_rows <= 0;
            sp_row_initial <= 0; sp_cur_z <= 0; sp_dx <= 0; sp_dy <= 0;
            sp_color <= 0; sp_step <= 0; sp_pixel_index <= 0; sp_pixel_z <= 0;
            sp_new_q <= 0;
            sp_z_data <= 0; sp_color_data <= 0;
            frag_index <= 0; frag_coverage <= 0; frag_colors <= 0; frag_depths <= 0;
            sp_z_mask <= 0; sp_color_mask <= 0;
        end else begin
            done_valid <= 1'b0;
            if (issue) begin
                tag_is_read[tag_wr] <= !req_write;
                tag_wr <= wr_next;
            end
            if (response) tag_rd <= rd_next;
            case ({issue,response})
                2'b10: tag_count <= tag_count + 1'b1;
                2'b01: tag_count <= tag_count - 1'b1;
                default: ;
            endcase
            if (response && rsp_error) failed <= 1'b1;
            if (read_response && !rsp_error) begin
                read_buffer <= rsp_rdata;
                if (op == OP_GEN) begin
                    // cmp_mask/gen_word use rsp_rdata combinationally.
                    generated <= gen_word;
                    write_mask <= cmp_mask;
                end else begin
                    write_mask <= 16'hffff;
                end
            end
            // A response error overrides normal state progression, so that
            // no further memory request is generated for this command.
            if (response && rsp_error && state != S_IDLE) begin
                state <= S_DRAIN;
            end else case (state)
                S_IDLE: if (cmd_valid) begin
                    if (!valid_command) begin
                        done_valid <= 1'b1;
                        done_error <= 1'b1;
                    end else if (cmd_op == OP_CONFIG) begin
                        if (cmd_mode[0]) begin
                            cfg_color_base <= p0;
                            cfg_z_base <= p1;
                        end
                        if (cmd_mode[1]) begin
                            cfg_color_stride <= p2;
                            cfg_z_stride <= p3;
                        end
                        if (cmd_mode[2]) cfg_color <= p4;
                        if (cmd_mode[3]) begin
                            cfg_z0 <= p5;
                            cfg_dx <= p6;
                            cfg_dy <= p7;
                        end
                        if (cmd_mode[4]) cfg_render_mode <= p8[15:0];
                        cfg_written <= cfg_written | cmd_mode[4:0];
                        done_valid <= 1'b1;
                        done_error <= 1'b0;
                    end else begin
                        op <= cmd_op;
                        mode <= ((cmd_op == OP_SPAN || cmd_op == OP_FRAGMENT) && compact_graphics) ?
                                cfg_render_mode : cmd_mode;
                        failed <= 1'b0;
                        if (cmd_op == OP_FILL) begin
                            row_dst <= p0; cur_dst <= p0;
                            rows_left <= p2;
                            blocks_per_row <= p1 >> 4;
                            blocks_left <= p1 >> 4;
                            dst_stride <= p3;
                            pattern <= p4;
                        end else if (cmd_op == OP_COPY) begin
                            row_src <= p0; cur_src <= p0;
                            row_dst <= p1; cur_dst <= p1;
                            rows_left <= p3;
                            blocks_per_row <= p2 >> 4;
                            blocks_left <= p2 >> 4;
                            src_stride <= p4; dst_stride <= p5;
                        end else if (cmd_op == OP_SPAN || cmd_op == OP_FRAGMENT) begin
                            sp_color_row <= compact_graphics ? compact_color_address : p0;
                            sp_z_row <= compact_graphics ? compact_z_address : p1;
                            sp_color_cur <= compact_graphics ? compact_color_address : p0;
                            sp_z_cur <= compact_graphics ? compact_z_address : p1;
                            sp_width <= p2;
                            sp_remaining <= p2;
                            sp_rows <= p3;
                            sp_color_stride <= compact_graphics ? cfg_color_stride : p4;
                            sp_z_stride <= compact_graphics ? cfg_z_stride : p5;
                            sp_color <= compact_graphics ? effective_color : p6;
                            sp_row_initial <= compact_graphics ? effective_z0 : p7;
                            sp_cur_z <= compact_graphics ? effective_z0 : p7;
                            sp_dx <= compact_graphics ? effective_dx : p8;
                            sp_dy <= compact_graphics ? effective_dy : p9;
                            if (cmd_op == OP_FRAGMENT) begin
                                sp_width <= p2;
                                sp_remaining <= p2;
                                sp_rows <= 1;
                                sp_color_stride <= 0;
                                sp_z_stride <= 0;
                                frag_index <= 0;
                                frag_coverage <= p3[7:0];
                                frag_colors <= cmd_frag_colors;
                                frag_depths <= cmd_frag_z;
                            end
                        end else begin
                            row_dst <= p0; cur_dst <= p0;
                            rows_left <= p2;
                            blocks_per_row <= cmd_mode[3] ? (p1 >> 2) : (p1 >> 3);
                            blocks_left <= cmd_mode[3] ? (p1 >> 2) : (p1 >> 3);
                            dst_stride <= p3;
                            row_z <= p4; cur_z <= p4;
                            dx <= p5; dy <= p6;
                            for (dk = 0; dk < 8; dk = dk + 1)
                                dx_mult[dk] <= p5 * dk;
                        end
                        state <= (cmd_op == OP_SPAN || cmd_op == OP_FRAGMENT) ? S_SP_PREP : S_PREP;
                    end
                end
                S_PREP: begin
                    if (needs_read) state <= S_READ_REQ;
                    else begin
                        write_mask <= 16'hffff;
                        if (op == OP_GEN) generated <= gen_word;
                        state <= S_WRITE_REQ;
                    end
                end
                S_READ_REQ: if (issue) state <= S_READ_WAIT;
                S_READ_WAIT: if (read_response) state <= S_WRITE_REQ;
                S_WRITE_REQ: if (write_mask == 0 || issue) state <= S_ADV;
                S_ADV: begin
                    if (blocks_left == 1) begin
                        if (rows_left == 1) begin
                            state <= S_DRAIN;
                        end else begin
                            rows_left <= rows_left - 1'b1;
                            blocks_left <= blocks_per_row;
                            row_src <= row_src + src_stride;
                            cur_src <= row_src + src_stride;
                            row_dst <= row_dst + dst_stride;
                            cur_dst <= row_dst + dst_stride;
                            row_z <= row_z + dy;
                            cur_z <= row_z + dy;
                            state <= S_PREP;
                        end
                    end else begin
                        blocks_left <= blocks_left - 1'b1;
                        cur_src <= cur_src + 32'd16;
                        cur_dst <= cur_dst + 32'd16;
                        cur_z <= cur_z + value_step;
                        state <= S_PREP;
                    end
                end
                // Compute one group with independent aligned word boundaries.
                // A conditional Z test reads the old word once, then processes
                // the group's pixels over successive clock cycles.
                S_SP_PREP: begin
                    sp_new_q <= sp_fmt_out;
                    sp_step <= sp_step_calc[3:0];
                    sp_pixel_index <= 0;
                    sp_pixel_z <= sp_cur_z;
                    sp_z_data <= 0;
                    sp_color_data <= 0;
                    sp_z_mask <= 0;
                    sp_color_mask <= 0;
                    if (sp_cmp == 3'd0)
                        state <= S_SP_PIXEL;
                    else
                        state <= S_SP_READ_REQ;
                end
                S_SP_READ_REQ: if (issue) state <= S_SP_READ_WAIT;
                S_SP_READ_WAIT: if (read_response) state <= S_SP_PIXEL;
                S_SP_PIXEL: begin
                    // The Z value is assembled even when comparison fails;
                    // only byte masks determine what gets written to RAM.
                    if (sp_z32)
                        sp_z_data[sp_pixel_z_bit +: 32] <= sp_pixel_new;
                    else
                        sp_z_data[sp_pixel_z_bit +: 16] <= sp_pixel_new[15:0];
                    if (sp_pixel_pass) begin
                        if (sp_write_z) begin
                            if (sp_z32)
                                sp_z_mask[sp_pixel_z_byte[3:0] +: 4] <= 4'hf;
                            else
                                sp_z_mask[sp_pixel_z_byte[3:0] +: 2] <= 2'b11;
                        end
                        if (sp_write_color) begin
                            if (sp_color32) begin
                                sp_color_mask[sp_pixel_color_byte[3:0] +: 4] <= 4'hf;
                                sp_color_data[sp_pixel_color_bit +: 32] <= sp_pixel_color;
                            end else begin
                                sp_color_mask[sp_pixel_color_byte[3:0] +: 2] <= 2'b11;
                                sp_color_data[sp_pixel_color_bit +: 16] <= sp_pixel_color[15:0];
                            end
                        end
                    end
                    if (op != OP_FRAGMENT) sp_pixel_z <= sp_pixel_z + sp_dx;
                    sp_new_q <= sp_fmt_out;
                    if ({1'b0, sp_pixel_index} + 4'd1 == sp_step)
                        state <= S_SP_Z_REQ;
                    else
                        sp_pixel_index <= sp_pixel_index + 3'd1;
                end
                S_SP_Z_REQ: begin
                    if (sp_z_mask == 0 || issue)
                        state <= S_SP_COLOR_REQ;
                end
                // Sin barrera: el grupo siguiente puede leer su palabra de Z
                // con escrituras de este aun pendientes. Si comparten palabra,
                // son pixeles distintos y las mascaras de bytes no se pisan.
                S_SP_COLOR_REQ: begin
                    if (sp_color_mask == 0 || issue)
                        state <= S_SP_ADV;
                end
                S_SP_ADV: begin
                    if (sp_remaining == {28'd0,sp_step}) begin
                        if (sp_rows == 1) begin
                            state <= S_DRAIN;
                        end else begin
                            sp_rows <= sp_rows - 1'b1;
                            sp_color_row <= sp_color_row + sp_color_stride;
                            sp_z_row <= sp_z_row + sp_z_stride;
                            sp_color_cur <= sp_color_row + sp_color_stride;
                            sp_z_cur <= sp_z_row + sp_z_stride;
                            sp_row_initial <= sp_row_initial + sp_dy;
                            sp_cur_z <= sp_row_initial + sp_dy;
                            sp_remaining <= sp_width;
                            state <= S_SP_PREP;
                        end
                    end else begin
                        sp_remaining <= sp_remaining - sp_step;
                        sp_color_cur <= sp_color_cur + (sp_color32 ? ({28'd0,sp_step} << 2) : ({28'd0,sp_step} << 1));
                        sp_z_cur <= sp_z_cur + (sp_z32 ? ({28'd0,sp_step} << 2) : ({28'd0,sp_step} << 1));
                        sp_cur_z <= sp_pixel_z;
                        if (op == OP_FRAGMENT) frag_index <= frag_index + sp_step;
                        state <= S_SP_PREP;
                    end
                end
                S_DRAIN: if (tag_count == 0) begin
                    done_valid <= 1'b1;
                    done_error <= failed;
                    state <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
