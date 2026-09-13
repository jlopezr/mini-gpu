`timescale 1ns/1ps
`default_nettype none

/*
 * Banco del lector de lineas en rafagas.
 *
 * Monta la cadena entera: video_line_source_burst -> memory_fabric_4 ->
 * sdram_controller_128 -> sdram_model. El puerto 0 del arbitro lo usa el propio
 * banco para dejar el framebuffer escrito, asi que el arbitro queda ejercitado
 * con dos clientes de verdad y no solo con uno.
 *
 * Lo que se comprueba:
 *
 *   1. que la linea que sale al line buffer es pixel a pixel la que estaba en
 *      memoria, y en el orden correcto;
 *   2. que son 40 peticiones por linea y no 320, que es el punto de todo esto;
 *   3. que sigue saliendo bien con la base del framebuffer DESALINEADA, que es
 *      legal porque video_registers solo obliga a alinear a cuatro bytes;
 *   4. que el relleno cabe en el presupuesto de un par de lineas de pantalla.
 *
 * El patron guardado es la propia direccion de palabra. Asi cada pixel dice de
 * donde vino, y un desplazamiento de un beat —el fallo que ya aparecio en el
 * controlador— se lee directamente en el numero.
 */
module video_burst_tb;
  localparam integer SRC_W = 320;
  localparam integer CLK_HZ = 100_000_000;
  localparam integer POWERUP_US = 2;
  // Presupuesto real: dos lineas de pantalla de 800 pixeles a 25 MHz, en
  // ciclos de 100 MHz.
  localparam integer LINE_PAIR_CYCLES = 6400;

  reg clk = 0;
  reg reset = 1;
  always #5 clk = ~clk;

  integer errors = 0;
  integer guard;
  integer i;

  // -- Puerto 0: el escritor del banco --------------------------------------
  reg p0_req_valid = 0;
  reg [31:0] p0_req_addr = 0;
  reg [127:0] p0_req_wdata = 0;
  wire p0_req_ready, p0_rsp_valid, p0_rsp_error;
  wire [127:0] p0_rsp_rdata;

  // -- Puerto 2: el lector de video -----------------------------------------
  wire v_req_valid, v_req_ready, v_req_write, v_urgent;
  wire [31:0] v_req_addr;
  wire [127:0] v_req_wdata;
  wire [15:0] v_req_wmask;
  wire v_rsp_valid, v_rsp_ready, v_rsp_error;
  wire [127:0] v_rsp_rdata;

  reg [23:0] fb_base = 24'd0;
  reg fill_start = 0;
  reg [7:0] fill_line = 0;
  wire fill_we, fill_done;
  wire [8:0] fill_addr;
  wire [15:0] fill_data;

  // -- SDRAM ----------------------------------------------------------------
  wire s_req_valid, s_req_ready, s_req_write, s_done;
  wire [23:0] s_req_addr;
  wire [127:0] s_req_wdata, s_rdata;
  wire [15:0] s_req_wmask;
  wire fabric_busy, ctrl_busy, init_done, sdram_clk_unused;
  wire cke, csn, rasn, casn, wen;
  wire [12:0] sdram_a;
  wire [1:0] sdram_ba, sdram_dqm;
  wire [15:0] sdram_dq;

  video_line_source_burst #(.SRC_W(SRC_W)) reader (
      .clk(clk), .reset(reset), .fb_base(fb_base),
      .fill_start(fill_start), .fill_line(fill_line),
      .fill_we(fill_we), .fill_addr(fill_addr), .fill_data(fill_data),
      .fill_done(fill_done),
      .req_valid(v_req_valid), .req_ready(v_req_ready),
      .req_write(v_req_write), .req_addr(v_req_addr),
      .req_wdata(v_req_wdata), .req_wmask(v_req_wmask), .urgent(v_urgent),
      .rsp_valid(v_rsp_valid), .rsp_ready(v_rsp_ready),
      .rsp_rdata(v_rsp_rdata), .rsp_error(v_rsp_error));

  memory_fabric_4 fabric (
      .clk(clk), .reset(reset),
      .p0_req_valid(p0_req_valid), .p0_req_ready(p0_req_ready),
      .p0_req_write(1'b1), .p0_req_addr(p0_req_addr),
      .p0_req_wdata(p0_req_wdata), .p0_req_wmask(16'hffff),
      .p0_rsp_valid(p0_rsp_valid), .p0_rsp_ready(1'b1),
      .p0_rsp_rdata(p0_rsp_rdata), .p0_rsp_error(p0_rsp_error),

      .p1_req_valid(1'b0), .p1_req_ready(), .p1_req_write(1'b0),
      .p1_req_addr(32'd0), .p1_req_wdata(128'd0), .p1_req_wmask(16'd0),
      .p1_rsp_valid(), .p1_rsp_ready(1'b1), .p1_rsp_rdata(), .p1_rsp_error(),

      .p2_req_valid(v_req_valid), .p2_req_ready(v_req_ready),
      .p2_req_write(v_req_write), .p2_req_addr(v_req_addr),
      .p2_req_wdata(v_req_wdata), .p2_req_wmask(v_req_wmask),
      .p2_urgent(v_urgent),
      .p2_rsp_valid(v_rsp_valid), .p2_rsp_ready(v_rsp_ready),
      .p2_rsp_rdata(v_rsp_rdata), .p2_rsp_error(v_rsp_error),

      .p3_req_valid(1'b0), .p3_req_ready(), .p3_req_write(1'b0),
      .p3_req_addr(32'd0), .p3_req_wdata(128'd0), .p3_req_wmask(16'd0),
      .p3_rsp_valid(), .p3_rsp_ready(1'b1), .p3_rsp_rdata(), .p3_rsp_error(),

      .sdram_req_valid(s_req_valid), .sdram_req_ready(s_req_ready),
      .sdram_req_write(s_req_write), .sdram_req_addr(s_req_addr),
      .sdram_req_wdata(s_req_wdata), .sdram_req_wmask(s_req_wmask),
      .sdram_done(s_done), .sdram_rdata(s_rdata), .busy(fabric_busy));

  sdram_controller_128 #(
      .CLK_FREQ_HZ(CLK_HZ), .POWERUP_DELAY_US(POWERUP_US)
  ) ctrl (
      .clk(clk), .reset(reset),
      .req_valid(s_req_valid), .req_write(s_req_write), .req_addr(s_req_addr),
      .req_wdata(s_req_wdata), .req_wmask(s_req_wmask),
      .req_ready(s_req_ready), .done(s_done), .rdata(s_rdata),
      .init_done(init_done), .busy(ctrl_busy),
      .sdram_clk(sdram_clk_unused), .sdram_cke(cke), .sdram_csn(csn),
      .sdram_rasn(rasn), .sdram_casn(casn), .sdram_wen(wen),
      .sdram_a(sdram_a), .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm),
      .sdram_d(sdram_dq));

  sdram_model #(
      .POWERUP_DELAY_NS(POWERUP_US * 1000), .READ_DELAY_CYCLES(1)
  ) mem (
      .clk(clk), .cke(cke), .csn(csn), .rasn(rasn), .casn(casn), .wen(wen),
      .a(sdram_a), .ba(sdram_ba), .dqm(sdram_dqm), .dq(sdram_dq));

  // -- Captura de lo que sale al line buffer --------------------------------
  reg [15:0] linea[0:SRC_W-1];
  reg escrito[0:SRC_W-1];
  integer escrituras;

  always @(posedge clk) begin
    if (!reset && fill_we) begin
      linea[fill_addr] <= fill_data;
      escrito[fill_addr] <= 1'b1;
      escrituras <= escrituras + 1;
    end
  end

  // -- Cuenta de peticiones de video ----------------------------------------
  integer peticiones;
  always @(posedge clk) begin
    if (!reset && v_req_valid && v_req_ready) peticiones <= peticiones + 1;
  end

  // -------------------------------------------------------------------------
  task escribir_rafaga;
    input [23:0] word_address;   // alineada a 8 palabras
    begin
      @(negedge clk);
      // OJO: en memory_fabric_4, `req_ready` depende COMBINACIONALMENTE de
      // `req_valid` —el grant mira el valid del propio puerto—, asi que hay que
      // levantar valid PRIMERO y esperar ready despues. Esperar ready antes de
      // levantar valid se cuelga para siempre, y es la primera piedra con la
      // que tropieza cualquiera que escriba un cliente para este arbitro.
      p0_req_valid = 1'b1;
      p0_req_addr = {word_address, 1'b0};   // direccion de byte
      // Cada palabra guarda su propia direccion.
      p0_req_wdata = {word_address[15:0] + 16'd7, word_address[15:0] + 16'd6,
                      word_address[15:0] + 16'd5, word_address[15:0] + 16'd4,
                      word_address[15:0] + 16'd3, word_address[15:0] + 16'd2,
                      word_address[15:0] + 16'd1, word_address[15:0]};
      guard = 0;
      while (!p0_req_ready && guard < 500) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (!p0_req_ready)
        $fatal(1, "el arbitro no acepto la escritura de %06x", word_address);
      @(negedge clk);
      p0_req_valid = 1'b0;
      guard = 0;
      while (!p0_rsp_valid && guard < 500) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (!p0_rsp_valid) $fatal(1, "el arbitro no respondio al escribir %06x",
                                word_address);
      if (p0_rsp_error) $fatal(1, "error del arbitro al escribir %06x",
                               word_address);
      @(negedge clk);
    end
  endtask

  // Rellena `palabras` palabras desde `desde`, en rafagas alineadas.
  task preparar;
    input [23:0] desde;
    input integer palabras;
    integer w;
    begin
      for (w = 0; w < palabras; w = w + 8)
        escribir_rafaga((desde & 24'hfffff8) + w);
    end
  endtask

  integer ciclos;
  integer x;
  reg [15:0] esperado;

  task pedir_linea;
    input [7:0 ] l;
    begin
      for (x = 0; x < SRC_W; x = x + 1) begin
        linea[x] = 16'hdead;
        escrito[x] = 1'b0;
      end
      escrituras = 0;
      peticiones = 0;
      @(negedge clk);
      fill_line = l;
      fill_start = 1'b1;
      @(negedge clk);
      fill_start = 1'b0;
      ciclos = 0;
      while (!fill_done && ciclos < 100_000) begin
        @(negedge clk);
        ciclos = ciclos + 1;
      end
      if (!fill_done) $fatal(1, "el relleno de la linea %0d no termino", l);
      // `fill_done` se levanta en el MISMO ciclo que el ultimo `fill_we`, igual
      // que en el lector sin rafagas, asi que la captura del ultimo pixel
      // todavia no ha ocurrido cuando se ve el pulso. Un par de ciclos mas.
      repeat (2) @(negedge clk);
    end
  endtask

  task comprobar_linea;
    input [255:0] etiqueta;
    input [7:0] l;
    begin
      for (x = 0; x < SRC_W; x = x + 1) begin
        esperado = (fb_base + l * SRC_W + x) & 16'hffff;
        if (!escrito[x]) begin
          $display("FALLO %0s: el pixel %0d no se escribio", etiqueta, x);
          errors = errors + 1;
          x = SRC_W;
        end else if (linea[x] !== esperado) begin
          $display("FALLO %0s: pixel %0d = %04x, esperado %04x",
                   etiqueta, x, linea[x], esperado);
          errors = errors + 1;
          x = SRC_W;
        end
      end
      if (escrituras != SRC_W) begin
        $display("FALLO %0s: %0d escrituras al line buffer, esperadas %0d",
                 etiqueta, escrituras, SRC_W);
        errors = errors + 1;
      end
    end
  endtask

  initial begin
    escrituras = 0;
    peticiones = 0;
    for (i = 0; i < SRC_W; i = i + 1) begin
      linea[i] = 16'h0000;
      escrito[i] = 1'b0;
    end

    repeat (4) @(negedge clk);
    reset = 0;
    guard = 0;
    while (!init_done && guard < 200_000) begin
      @(negedge clk);
      guard = guard + 1;
    end
    if (!init_done) $fatal(1, "la inicializacion no termino");

    // Tres lineas de framebuffer escritas, mas una rafaga de margen por si la
    // version desalineada se sale por el final.
    preparar(24'd0, 3 * SRC_W + 8);

    // -------------------------------------------------------------------
    // 1. Base alineada. 320 palabras = 40 rafagas exactas.
    // -------------------------------------------------------------------
    fb_base = 24'd0;
    pedir_linea(8'd0);
    comprobar_linea("linea 0, base alineada", 8'd0);
    if (peticiones != SRC_W / 8) begin
      $display("FALLO: %0d peticiones para la linea 0, esperadas %0d",
               peticiones, SRC_W / 8);
      errors = errors + 1;
    end
    $display("Linea alineada: %0d peticiones (antes eran %0d accesos), %0d ciclos",
             peticiones, SRC_W, ciclos);
    if (ciclos >= LINE_PAIR_CYCLES) begin
      $display("FALLO: el relleno tarda %0d ciclos y el presupuesto es %0d",
               ciclos, LINE_PAIR_CYCLES);
      errors = errors + 1;
    end

    // -------------------------------------------------------------------
    // 2. Otra linea, para que el producto linea x SRC_W entre en juego.
    // -------------------------------------------------------------------
    pedir_linea(8'd2);
    comprobar_linea("linea 2, base alineada", 8'd2);

    // -------------------------------------------------------------------
    // 3. Base DESALINEADA. video_registers solo obliga a alinear a cuatro
    //    bytes, o sea a dos palabras, asi que esto es legal y tiene que
    //    salir bien. Cuesta una rafaga mas.
    // -------------------------------------------------------------------
    fb_base = 24'd2;            // 4 bytes: lo minimo que permiten los registros
    pedir_linea(8'd0);
    comprobar_linea("linea 0, base desalineada", 8'd0);
    if (peticiones != SRC_W / 8 + 1) begin
      $display("FALLO: %0d peticiones con base desalineada, esperadas %0d",
               peticiones, SRC_W / 8 + 1);
      errors = errors + 1;
    end
    $display("Linea desalineada: %0d peticiones, %0d ciclos", peticiones, ciclos);

    // -------------------------------------------------------------------
    // 4. Y de vuelta a la alineada, para descartar que el desalineado deje
    //    estado pegado.
    // -------------------------------------------------------------------
    fb_base = 24'd0;
    pedir_linea(8'd1);
    comprobar_linea("linea 1, otra vez alineada", 8'd1);

    if (mem.errors != 0) begin
      $display("FALLO: el modelo de SDRAM conto %0d violaciones JEDEC",
               mem.errors);
      errors = errors + 1;
    end

    if (errors != 0) $fatal(1, "%0d comprobaciones fallaron", errors);
    $display("PASS: video_burst");
    $finish;
  end
endmodule

`default_nettype wire
