// Project F: Racing the Beam - Bounce (ULX3S)
// Copyright Will Green, open source hardware released under the MIT License
// Learn more at https://projectf.io/posts/racing-the-beam/

`default_nettype none
`timescale 1ns / 1ps

module top_bounce (
    input  wire logic clk_25mhz,     // 25 MHz clock
    input  wire logic [6:0] btn,     // buttons (btn[1] = FIRE1, active high)
    output      logic [3:0] gpdi_dp  // DVI out
    );

    // generate pixel clock
    logic clk_pix;
    logic clk_pix_5x;
    logic clk_pix_locked;
    clock2_gen #(  // 74 MHz (PLL can't do exact 74.25 MHz for 720p)
        .CLKI_DIV(5),
        .CLKFB_DIV(74),
        .CLKOP_DIV(2),
        .CLKOP_CPHASE(1),
        .CLKOS_DIV(10),
        .CLKOS_CPHASE(5)
    ) clock2_gen_inst (
       .clk_in(clk_25mhz),
       .clk_5x_out(clk_pix_5x),
       .clk_out(clk_pix),
       .clk_locked(clk_pix_locked)
    );

    // reset: on PLL lock loss, or FIRE2 pressed (synced into pixel domain)
    // (FIRE1 / btn[1] drives the colour cycling further down)
    logic btn_rst_sync_0, btn_rst_sync_1;
    always_ff @(posedge clk_pix) begin
        btn_rst_sync_0 <= btn[2];
        btn_rst_sync_1 <= btn_rst_sync_0;
    end
    logic rst_pix;
    always_comb rst_pix = !clk_pix_locked || btn_rst_sync_1;

    // display sync signals and coordinates
    localparam CORDW = 12;  // screen coordinate width in bits
    logic [CORDW-1:0] sx, sy;
    logic hsync, vsync, de;
    simple_720p display_inst (
        .clk_pix,
        .rst_pix(rst_pix),
        .sx,
        .sy,
        .hsync,
        .vsync,
        .de
    );

    // screen dimensions (must match display_inst)
    localparam H_RES = 1280;  // horizontal screen resolution
    localparam V_RES =  720;  // vertical screen resolution

    logic frame;  // high for one clock tick at the start of vertical blanking
    always_comb frame = (sy == V_RES && sx == 0);

    // frame counter lets us to slow down the action
    localparam FRAME_NUM = 1;  // slow-mo: animate every N frames
    logic [$clog2(FRAME_NUM):0] cnt_frame;  // frame counter
    always_ff @(posedge clk_pix) begin
        if (frame) cnt_frame <= (cnt_frame == FRAME_NUM-1) ? 0 : cnt_frame + 1;
    end

    // square parameters
    localparam Q_SIZE = 200;   // size in pixels
    logic [CORDW-1:0] qx, qy;  // position (origin at top left)
    logic qdx, qdy;            // direction: 0 is right/down
    logic [CORDW-1:0] qs = 2;  // speed in pixels/frame

    // update square position once per frame
    always_ff @(posedge clk_pix) begin
        if (frame && cnt_frame == 0) begin
            // horizontal position
            if (qdx == 0) begin  // moving right
                if (qx + Q_SIZE + qs >= H_RES-1) begin  // hitting right of screen?
                    qx <= H_RES - Q_SIZE - 1;  // move right as far as we can
                    qdx <= 1;  // move left next frame
                end else qx <= qx + qs;  // continue moving right
            end else begin  // moving left
                if (qx < qs) begin  // hitting left of screen?
                    qx <= 0;  // move left as far as we can
                    qdx <= 0;  // move right next frame
                end else qx <= qx - qs;  // continue moving left
            end

            // vertical position
            if (qdy == 0) begin  // moving down
                if (qy + Q_SIZE + qs >= V_RES-1) begin  // hitting bottom of screen?
                    qy <= V_RES - Q_SIZE - 1;  // move down as far as we can
                    qdy <= 1;  // move up next frame
                end else qy <= qy + qs;  // continue moving down
            end else begin  // moving up
                if (qy < qs) begin  // hitting top of screen?
                    qy <= 0;  // move up as far as we can
                    qdy <= 0;  // move down next frame
                end else qy <= qy - qs;  // continue moving up
            end
        end
    end

    // define a square with screen coordinates
    logic square;
    always_comb begin
        square = (sx >= qx) && (sx < qx + Q_SIZE) && (sy >= qy) && (sy < qy + Q_SIZE);
    end

    // FIRE1 (btn[1]) cycles the square colour: white -> red -> green -> blue
    localparam BTN_DEBOUNCE = 21'd1_500_000;  // ~20 ms at 74 MHz
    logic btn1_sync_0, btn1_sync_1;  // synchronise the async button into clk_pix
    logic btn1_stable, btn1_prev;    // debounced level, and it delayed one tick
    logic [20:0] btn1_cnt;           // how long the raw level has disagreed
    logic [1:0] colr_sel;            // wraps 0-3 on its own

    always_ff @(posedge clk_pix) begin
        btn1_sync_0 <= btn[1];
        btn1_sync_1 <= btn1_sync_0;

        // adopt a new level only once it has held steady long enough
        if (btn1_sync_1 != btn1_stable) begin
            btn1_cnt <= btn1_cnt + 1;
            if (btn1_cnt == BTN_DEBOUNCE) begin
                btn1_stable <= btn1_sync_1;
                btn1_cnt <= 0;
            end
        end else btn1_cnt <= 0;

        btn1_prev <= btn1_stable;
        if (btn1_stable && !btn1_prev) colr_sel <= colr_sel + 1;  // press

        if (rst_pix) begin
            colr_sel <= 0;
            btn1_cnt <= 0;
        end
    end

    logic [3:0] colr_r, colr_g, colr_b;
    always_comb begin
        case (colr_sel)
            2'd1:    {colr_r, colr_g, colr_b} = {4'hF, 4'h0, 4'h0};  // red
            2'd2:    {colr_r, colr_g, colr_b} = {4'h0, 4'hF, 4'h0};  // green
            2'd3:    {colr_r, colr_g, colr_b} = {4'h0, 4'h0, 4'hF};  // blue
            default: {colr_r, colr_g, colr_b} = {4'hF, 4'hF, 4'hF};  // white
        endcase
    end

    // paint colour: selected colour inside square, blue outside
    logic [3:0] paint_r, paint_g, paint_b;
    always_comb begin
        paint_r = (square) ? colr_r : 4'h1;
        paint_g = (square) ? colr_g : 4'h3;
        paint_b = (square) ? colr_b : 4'h7;
    end

    // display colour: paint colour but black in blanking interval
    logic [3:0] display_r, display_g, display_b;
    always_comb begin
        display_r = (de) ? paint_r : 4'h0;
        display_g = (de) ? paint_g : 4'h0;
        display_b = (de) ? paint_b : 4'h0;
    end

    // DVI signals (8 bits per colour channel)
    logic [7:0] dvi_r, dvi_g, dvi_b;
    logic dvi_hsync, dvi_vsync, dvi_de;
    always_ff @(posedge clk_pix) begin
        dvi_hsync <= hsync;
        dvi_vsync <= vsync;
        dvi_de <= de;
        dvi_r <= {2{display_r}};
        dvi_g <= {2{display_g}};
        dvi_b <= {2{display_b}};
    end

    // TMDS encoding and serialization
    logic tmds_ch0_serial, tmds_ch1_serial, tmds_ch2_serial, tmds_clk_serial;
    dvi_generator dvi_out (
        .clk_pix,
        .clk_pix_5x,
        .rst_pix(rst_pix),
        .de(dvi_de),
        .data_in_ch0(dvi_b),
        .data_in_ch1(dvi_g),
        .data_in_ch2(dvi_r),
        .ctrl_in_ch0({dvi_vsync, dvi_hsync}),
        .ctrl_in_ch1(2'b00),
        .ctrl_in_ch2(2'b00),
        .tmds_ch0_serial(gpdi_dp[0]),
        .tmds_ch1_serial(gpdi_dp[1]),
        .tmds_ch2_serial(gpdi_dp[2]),
        .tmds_clk_serial(gpdi_dp[3])
    );
endmodule
