// Project F Library - DVI Generator (ECP5)
// Copyright Will Green, Open Source Hardware released under the MIT License
// Learn more at https://projectf.io

`default_nettype none
`timescale 1ns / 1ps

module dvi_generator (
    input  wire logic clk_pix,
    input  wire logic clk_pix_5x,
    input  wire logic rst_pix,
    input  wire logic de,                 // data enable (high when drawing)
    input  wire logic [7:0] data_in_ch0,  // channel 0 - data
    input  wire logic [7:0] data_in_ch1,  // channel 1 - data
    input  wire logic [7:0] data_in_ch2,  // channel 2 - data
    input  wire logic [1:0] ctrl_in_ch0,  // channel 0 - control
    input  wire logic [1:0] ctrl_in_ch1,  // channel 1 - control
    input  wire logic [1:0] ctrl_in_ch2,  // channel 2 - control
    output logic tmds_ch0_serial,         // channel 0 - serial TMDS
    output logic tmds_ch1_serial,         // channel 1 - serial TMDS
    output logic tmds_ch2_serial,         // channel 2 - serial TMDS
    output logic tmds_clk_serial          // clock - serial TMDS
    );

    logic [9:0] tmds_ch0, tmds_ch1, tmds_ch2;

    tmds_encoder_dvi encode_ch0 (
        .clk_pix,
        .rst_pix,
        .data_in(data_in_ch0),
        .ctrl_in(ctrl_in_ch0),
        .de,
        .tmds(tmds_ch0)
    );

    tmds_encoder_dvi encode_ch1 (
        .clk_pix,
        .rst_pix,
        .data_in(data_in_ch1),
        .ctrl_in(ctrl_in_ch1),
        .de,
        .tmds(tmds_ch1)
    );

    tmds_encoder_dvi encode_ch2 (
        .clk_pix,
        .rst_pix,
        .data_in(data_in_ch2),
        .ctrl_in(ctrl_in_ch2),
        .de,
        .tmds(tmds_ch2)
    );

    logic [9:0] tmds_ch0_shift, tmds_ch1_shift, tmds_ch2_shift;
    logic [4:0] shift5 = 1;  // 5-bit circular shift buffer
    always_ff @(posedge clk_pix_5x) begin
        shift5 <= {shift5[3:0], shift5[4]};
        tmds_ch0_shift <= shift5[4] ? tmds_ch0 : tmds_ch0_shift >> 2;  // shift two bits for DDR
        tmds_ch1_shift <= shift5[4] ? tmds_ch1 : tmds_ch1_shift >> 2;
        tmds_ch2_shift <= shift5[4] ? tmds_ch2 : tmds_ch2_shift >> 2;
    end

    // Register stage feeding the output DDR registers. Its only load is the
    // ODDRX1F, so the placer can put it right next to the pad instead of
    // routing the wide shift register across the die. Same trick as
    // daveshah1/prjtrellis-dvi ("register stage to improve timing").
    logic [1:0] tmds_ch0_out, tmds_ch1_out, tmds_ch2_out;
    always_ff @(posedge clk_pix_5x) begin
        tmds_ch0_out <= tmds_ch0_shift[1:0];
        tmds_ch1_out <= tmds_ch1_shift[1:0];
        tmds_ch2_out <= tmds_ch2_shift[1:0];
    end

    // Los `cells_sim.v` de ECP5 que Apio pasa a iverilog no traen ODDRX1F, y
    // iverilog compila todas las fuentes del proyecto para cada testbench. Sin
    // esta guarda ningun banco de la CPU podria elaborar. Misma convencion que
    // `pll_120` y `clock2_gen`: fuera de sintesis se emite solo D0, que no
    // reproduce la serializacion DDR pero deja la jerarquia elaborable.
`ifdef SYNTHESIZE
    ODDRX1F serialize_ch0 (.D0(tmds_ch0_out[0]), .D1(tmds_ch0_out[1]), .Q(tmds_ch0_serial), .SCLK(clk_pix_5x), .RST(1'b0));
    ODDRX1F serialize_ch1 (.D0(tmds_ch1_out[0]), .D1(tmds_ch1_out[1]), .Q(tmds_ch1_serial), .SCLK(clk_pix_5x), .RST(1'b0));
    ODDRX1F serialize_ch2 (.D0(tmds_ch2_out[0]), .D1(tmds_ch2_out[1]), .Q(tmds_ch2_serial), .SCLK(clk_pix_5x), .RST(1'b0));
`else
    always_comb begin
        tmds_ch0_serial = tmds_ch0_out[0];
        tmds_ch1_serial = tmds_ch1_out[0];
        tmds_ch2_serial = tmds_ch2_out[0];
    end
`endif

    always_comb tmds_clk_serial = clk_pix;  // clock isn't following same path as other channels
endmodule