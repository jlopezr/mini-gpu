`default_nettype none

// Consola de texto de la propuesta 2D v0.4.
//
// Una celda ocupa 16 bits en EBR y una palabra en MMIO:
//   [7:0] caracter, [11:8] foreground, [15:12] background.
// Los bits [31:16] son reservados. Color cero significa transparencia.
module text_console #(
    parameter FONT_FILE = "fonts/font8x16_cpc464.hex"
) (
    input wire clk_sys,
    input wire reset_sys,
    input wire select,
    input wire write,
    input wire [3:0] write_mask,
    input wire [15:0] address,
    input wire [31:0] write_data,
    output reg [31:0] read_data,
    output reg error,

    input wire clk_pix,
    input wire reset_pix,
    input wire enable,
    input wire [11:0] sx,
    input wire [11:0] sy,
    input wire [7:0] r_in,
    input wire [7:0] g_in,
    input wire [7:0] b_in,
    input wire de_in,
    input wire hsync_in,
    input wire vsync_in,
    output reg [7:0] r_out,
    output reg [7:0] g_out,
    output reg [7:0] b_out,
    output reg de_out,
    output reg hsync_out,
    output reg vsync_out
);
  localparam [15:0] FONT_COUNT = 16'h0080;
  localparam [15:0] FONT_GLYPH = 16'h0084;
  localparam [15:0] FONT_DATA0 = 16'h0088;
  localparam [15:0] FONT_DATA1 = 16'h008c;
  localparam [15:0] FONT_DATA2 = 16'h0090;
  localparam [15:0] FONT_DATA3 = 16'h0094;
  localparam [15:0] PALETTE_LO = 16'h1000;
  localparam [15:0] PALETTE_HI = 16'h13fc;
  localparam [15:0] TEXT_LO    = 16'h6000;
  localparam [15:0] TEXT_HI    = 16'h857c;

  (* ram_style = "block" *) reg [15:0] text_ram [0:2399];
  (* ram_style = "block" *) reg [127:0] font_ram [0:255];
  (* ram_style = "block" *) reg [23:0] palette_ram [0:255];
  reg [23:0] text_palette [0:15];

  reg [8:0] loader_count;
  reg [7:0] loader_glyph;
  reg [31:0] font_data0, font_data1, font_data2;
  reg write_error;
  reg [15:0] text_read_q;
  reg [23:0] palette_read_q;

  wire is_palette = (address >= PALETTE_LO) && (address <= PALETTE_HI)
                    && (address[1:0] == 2'b00);
  wire is_text = (address >= TEXT_LO) && (address <= TEXT_HI)
                 && (address[1:0] == 2'b00);
  wire is_font_reg = (address >= FONT_COUNT) && (address <= FONT_DATA3)
                     && (address[1:0] == 2'b00);
  wire [7:0] palette_index = address[9:2];
  wire [13:0] text_word_offset = address[15:2] - 14'h1800;
  wire [11:0] text_index = text_word_offset[11:0];
  wire full_word = write_mask == 4'b1111;
  wire loader_range_valid = (write_data[8:0] != 0)
      && ({1'b0, loader_glyph} + write_data[8:0] <= 9'd256)
      && (write_data[31:9] == 0);

  initial begin
    $readmemh(FONT_FILE, font_ram);
  end

  reg validation_error;
  always @* begin
    validation_error = 1'b0;
    if (write && (is_font_reg || is_palette || is_text)) begin
      if (!full_word)
        validation_error = 1'b1;
      else if (address == FONT_COUNT)
        validation_error = !loader_range_valid;
      else if (address == FONT_DATA3)
        validation_error = loader_count == 0;
      else if (is_palette)
        validation_error = |write_data[31:24];
      else if (is_text)
        validation_error = |write_data[31:16];
    end
  end

  // El cliente consume el error en el ciclo posterior al pulso de select.
  // Se registra para que FONT_DATA3 no se convierta falsamente en invalido
  // después de que su propia escritura haya decrementado FONT_COUNT.
  always @* error = write ? write_error : 1'b0;

  always @(posedge clk_sys) begin
    if (reset_sys) begin
      loader_count <= 0;
      loader_glyph <= 0;
      font_data0 <= 0;
      font_data1 <= 0;
      font_data2 <= 0;
      write_error <= 1'b0;
    end else begin
      if (select && !write && is_text)
        text_read_q <= text_ram[text_index];
      if (select && !write && is_palette)
        palette_read_q <= palette_ram[palette_index];
      if (select && write) write_error <= validation_error;
      if (select && write && !validation_error) begin
      case (address)
        FONT_COUNT: loader_count <= write_data[8:0];
        FONT_GLYPH: loader_glyph <= write_data[7:0];
        FONT_DATA0: font_data0 <= write_data;
        FONT_DATA1: font_data1 <= write_data;
        FONT_DATA2: font_data2 <= write_data;
        FONT_DATA3: begin
          font_ram[loader_glyph] <= {write_data, font_data2,
                                     font_data1, font_data0};
          loader_count <= loader_count - 1'b1;
          if (loader_glyph != 8'hff) loader_glyph <= loader_glyph + 1'b1;
        end
        default: begin
          if (is_palette) begin
            palette_ram[palette_index] <= write_data[23:0];
            if (palette_index != 0 && palette_index < 16)
              text_palette[palette_index[3:0]] <= write_data[23:0];
          end else if (is_text) begin
            text_ram[text_index] <= write_data[15:0];
          end
        end
      endcase
      end
    end
  end

  always @* begin
    read_data = 0;
    case (address)
      FONT_COUNT: read_data = {23'd0, loader_count};
      FONT_GLYPH: read_data = {24'd0, loader_glyph};
      FONT_DATA0: read_data = font_data0;
      FONT_DATA1: read_data = font_data1;
      FONT_DATA2: read_data = font_data2;
      default: begin
        if (is_palette)
          read_data = {8'd0, palette_read_q};
        else if (is_text)
          read_data = {16'd0, text_read_q};
      end
    endcase
  end

  // Dos lecturas EBR registradas: celda y, después, glifo completo.
  reg [15:0] cell_q;
  reg [127:0] glyph_q;
  reg [3:0] glyph_y_q;
  reg [2:0] glyph_x_q;
  reg [3:0] glyph_y_d;
  reg [2:0] glyph_x_d;
  reg [3:0] fg_q, bg_q;
  reg [7:0] r_d0, g_d0, b_d0, r_d1, g_d1, b_d1;
  reg de_d0, hs_d0, vs_d0, de_d1, hs_d1, vs_d1;
  reg enable_sync0, enable_sync1;
  reg [11:0] sx_aligned, sy_aligned;
  wire [11:0] cell_address = (sy_aligned[8:4] * 12'd80)
                             + {5'd0, sx_aligned[9:3]};
  wire [7:0] glyph_row = glyph_q[glyph_y_q * 8 +: 8];
  wire glyph_pixel = glyph_row[7 - glyph_x_q];
  wire [3:0] color_index = glyph_pixel ? fg_q : bg_q;
  wire [23:0] text_color = text_palette[color_index];

  always @(posedge clk_pix) begin
    enable_sync0 <= enable;
    enable_sync1 <= enable_sync0;
    sx_aligned <= sx;
    sy_aligned <= sy;
    cell_q <= text_ram[cell_address];
    glyph_q <= font_ram[cell_q[7:0]];
    glyph_x_d <= sx_aligned[2:0];
    glyph_y_d <= sy_aligned[3:0];
    glyph_x_q <= glyph_x_d;
    glyph_y_q <= glyph_y_d;
    fg_q <= cell_q[11:8];
    bg_q <= cell_q[15:12];

    r_d0 <= r_in; g_d0 <= g_in; b_d0 <= b_in;
    r_d1 <= r_d0; g_d1 <= g_d0; b_d1 <= b_d0;
    de_d0 <= de_in; hs_d0 <= hsync_in; vs_d0 <= vsync_in;
    de_d1 <= de_d0; hs_d1 <= hs_d0; vs_d1 <= vs_d0;

    if (reset_pix) begin
      r_out <= 0; g_out <= 0; b_out <= 0;
      de_out <= 0; hsync_out <= 0; vsync_out <= 0;
      enable_sync0 <= 0; enable_sync1 <= 0;
    end else begin
      de_out <= de_d1;
      hsync_out <= hs_d1;
      vsync_out <= vs_d1;
      if (enable_sync1 && de_d1 && color_index != 0) begin
        r_out <= text_color[23:16];
        g_out <= text_color[15:8];
        b_out <= text_color[7:0];
      end else begin
        r_out <= r_d1; g_out <= g_d1; b_out <= b_d1;
      end
    end
  end
endmodule

`default_nettype wire
