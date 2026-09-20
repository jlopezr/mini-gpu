`timescale 1ns/1ps
`default_nettype none

/*
 * Un framebuffer de 320x240 DE VERDAD, dibujado por la CPU real sobre el
 * camino de memoria real, y volcado a fichero.
 *
 * Es la prueba mas cercana a la placa que se puede hacer sin placa. A
 * diferencia de video_frame_tb.v, que trabaja a 32x16 para que un frame quepa
 * en 960 ciclos, aqui la resolucion es la de verdad y lo que se ejercita es:
 *
 *   - la CPU ejecutando un programa real desde la SDRAM, con su bufer de
 *     instrucciones;
 *   - el bufer de combinacion de escrituras, incluido el vaciado forzado al
 *     escribir SWAP, que es la parte mas delicada del camino de datos;
 *   - el controlador BL8 y el arbitro con dos clientes de verdad compitiendo;
 *   - el registro HALT_AT, que hasta ahora solo se probaba aislado en
 *     video_registers_tb.v.
 *
 * Lo que NO se comprueba pixel a pixel es la salida del scanout: renderizar un
 * frame de 640x480 son 420 000 ciclos de pixel y aqui ya cuesta bastante. El
 * scanout corre igualmente --hace falta para que ocurran los intercambios y
 * para vigilar el underflow-- pero la comparacion pixel a pixel de su salida
 * la hace video_frame_tb.v a resolucion reducida, donde es barata.
 *
 * Lo que se vuelca es el FRAMEBUFFER, que ademas es exactamente lo que
 * devuelve `monitor.py read-block` desde la placa: asi el mismo fichero
 * esperado sirve para los dos sitios.
 *
 * Ficheros de salida, en el directorio de trabajo:
 *
 *   frame_full.hex   medias palabras de 16 bits, una por linea
 *   frame_full.bin   RGB565 crudo, lo que come tools/compare-frames.py
 *
 * Para verlo:
 *
 *   ..\.venv\Scripts\python.exe ..\tools\frame-to-image.py frame_full.bin salida.jpg
 *
 * Direcciones
 * -----------
 *
 * Los framebuffers NO estan en 0x01000000 como en la placa, sino en 0x00010000
 * y 0x00035800. El modelo de SDRAM guarda 4 bancos x ROWS filas x 512 columnas,
 * y la fila sale de los bits [23:11] de la direccion de palabra: 0x01000000
 * pediria la fila 4096 y no hay memoria de simulacion para tanto. Con las bases
 * bajas, los dos buffers caben en 128 filas. Es lo unico que difiere de la
 * placa, y no toca ningun camino logico.
 *
 * Por eso el programa es `fullframe_tb.asm` y NO `examples/fullframe.asm`:
 * son el mismo programa salvo esas dos constantes. Durante anos la cabecera
 * decia lo segundo y el .hex venia de lo primero, y al regenerarlo "como
 * ponia aqui" el banco empezo a contar 60 000 violaciones JEDEC --que son en
 * realidad 60 000 accesos a una fila que no existe--.
 *
 *   python ..\1.isa\miniisa_asm.py fullframe_tb.asm --hex fullframe.hex \
 *       -I ..\x.tests\inc
 *
 * `x.tests/test_fullframe_fixture.py` comprueba que el .hex sale de ahi.
 */
module video_fullframe_tb;
  localparam integer SRC_W = 320;
  localparam integer SRC_H = 240;
  localparam integer CLK_HZ = 80_000_000;
  localparam integer POWERUP_US = 2;

  // Donde paramos. Cada intercambio necesita un frame de video entero
  // (420 000 ciclos de pixel), asi que esto domina el tiempo de simulacion.
  // Antes eran INTERCAMBIOS; con MMIO v2 `HALT_AT` cuenta FRAMES (§9.6). No es
  // lo mismo aqui: mientras la CPU dibuja el frame entero pasan varios frames
  // de scanout sin que haya ningun intercambio, asi que la alarma llega mucho
  // antes en terminos del programa. Con 2 paraba a la CPU a media rafaga.
  localparam integer FRAMES_TO_STOP = 6;

  localparam [31:0] FB0 = 32'h0001_0000;
  localparam [31:0] FB1 = 32'h0003_5800;   // FB0 + 320*240*2

  reg clk_sys = 1'b0;
  reg clk_pix = 1'b0;
  reg reset = 1'b1;
  always #6.25 clk_sys = ~clk_sys;   // 80 MHz
  always #20.0 clk_pix = ~clk_pix;   // 25 MHz

  integer guard;
  integer i;

  // ---- barrido de 640x480 completo ---------------------------------------
  // El reset del dominio de pixel se sincroniza, como en top.v.
  reg rst_pix = 1'b1;
  always @(posedge clk_pix) rst_pix <= reset;

  wire [11:0] sx, sy;
  wire hsync, vsync, de;
  simple_480p display_i(
      .clk_pix(clk_pix), .rst_pix(rst_pix), .sx(sx), .sy(sy),
      .hsync(hsync), .vsync(vsync), .de(de));

  // ---- CPU ----------------------------------------------------------------
  reg run_request = 0;
  wire halted, cpu_error, instruction_retired;
  wire [7:0] cpu_error_code;
  wire imem_valid, imem_ready;
  wire [31:0] imem_address, imem_read_data;
  wire dmem_valid, dmem_ready, dmem_error;
  wire [31:0] dmem_address, dmem_write_data, dmem_read_data;
  wire [3:0] dmem_write_enable;
  wire [31:0] debug_pc;
  wire video_halt_request, video_underflow_clear;

  cpu cpu_i (
      .clk(clk_sys), .reset(reset), .run_request(run_request),
      .halt_request(video_halt_request), .step_request(1'b0), .halted(halted),
      .error(cpu_error), .error_code(cpu_error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid), .imem_address(imem_address),
      .imem_read_data(imem_read_data), .imem_ready(imem_ready),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data), .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(dmem_error), .debug_register_address(5'd0),
      .debug_register_data(), .debug_pc(debug_pc));

  // ---- puertos del arbitro ------------------------------------------------
  wire p0_valid, p0_ready, p0_write, p0_rsp_valid, p0_rsp_ready, p0_rsp_error;
  wire [31:0] p0_addr;
  wire [127:0] p0_wdata, p0_rsp_rdata;
  wire [15:0] p0_wmask;

  wire p1_valid, p1_ready, p1_write, p1_rsp_valid, p1_rsp_ready, p1_rsp_error;
  wire [31:0] p1_addr;
  wire [127:0] p1_wdata, p1_rsp_rdata;
  wire [15:0] p1_wmask;

  wire p2_valid, p2_ready, p2_write, p2_urgent, p2_rsp_valid, p2_rsp_error;
  wire [31:0] p2_addr;
  wire [127:0] p2_wdata, p2_rsp_rdata;
  wire [15:0] p2_wmask;
  wire video_rsp_ready;

  // ---- MMIO ---------------------------------------------------------------
  wire cpu_mmio_req, cpu_mmio_ack, cpu_mmio_write;
  wire [3:0] cpu_mmio_mask;
  // 32 bits, no 5. Con cinco, cualquier offset por encima de +0x1F se
  // truncaba en silencio: es el fallo que dejo la 18 muda, dentro de un banco.
  wire [31:0] cpu_mmio_addr;
  wire [31:0] cpu_mmio_wdata;
  wire mmio_select, mmio_write;
  wire [3:0] mmio_write_mask;
  wire [31:0] mmio_address;
  wire [31:0] mmio_write_data, mmio_read_data;
  wire wb_dirty;

  // ---- video --------------------------------------------------------------
  wire fill_start, fill_first, fill_we, fill_done;
  wire [7:0] fill_line;
  wire [8:0] fill_addr;
  wire [15:0] fill_data;
  wire [23:0] fb_base;
  wire underflow;
  wire [7:0] pix_r, pix_g, pix_b;
  wire pix_de;

  // ---- SDRAM --------------------------------------------------------------
  wire s_req_valid, s_req_ready, s_req_write, s_done;
  wire [23:0] s_req_addr;
  wire [127:0] s_req_wdata, s_rdata;
  wire [15:0] s_req_wmask;
  wire init_done, ctrl_busy, fabric_busy, sdram_clk_unused;
  wire cke, csn, rasn, casn, wen;
  wire [12:0] sdram_a;
  wire [1:0] sdram_ba, sdram_dqm;
  wire [15:0] sdram_dq;

  cpu_dmem_adapter dmem_adapter_i (
      .clk(clk_sys), .reset(reset), .init_done(init_done),
      .cpu_halted(halted),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data),
      .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(dmem_error), .wb_dirty(wb_dirty),
      .merge_count(), .flush_count(),
      .mmio_req(cpu_mmio_req), .mmio_ack(cpu_mmio_ack),
      .mmio_write(cpu_mmio_write), .mmio_write_mask(cpu_mmio_mask),
      .mmio_address(cpu_mmio_addr), .mmio_write_data(cpu_mmio_wdata),
      .mmio_read_data(mmio_read_data), .mmio_error(1'b0),
      .req_valid(p0_valid), .req_ready(p0_ready), .req_write(p0_write),
      .req_addr(p0_addr), .req_wdata(p0_wdata), .req_wmask(p0_wmask),
      .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
      .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));

  instruction_buffer #(.LINES(4), .INDEX_BITS(2)) ibuf_i (
      .clk(clk_sys), .reset(reset), .init_done(init_done),
      .cpu_halted(halted),
      .cpu_imem_valid(imem_valid), .cpu_imem_address(imem_address),
      .cpu_imem_read_data(imem_read_data), .cpu_imem_ready(imem_ready),
      .req_valid(p1_valid), .req_ready(p1_ready), .req_write(p1_write),
      .req_addr(p1_addr), .req_wdata(p1_wdata), .req_wmask(p1_wmask),
      .rsp_valid(p1_rsp_valid), .rsp_ready(p1_rsp_ready),
      .rsp_rdata(p1_rsp_rdata), .rsp_error(p1_rsp_error),
      .hit_count(), .miss_count());

  // El monitor no se monta: aqui no hay UART. Su lado del mux se ata a cero.
  mmio_mux mmio_mux_i (
      .clk(clk_sys), .reset(reset),
      .a_req(1'b0), .a_ack(), .a_write(1'b0), .a_write_mask(4'd0),
      .a_address(5'd0), .a_write_data(32'd0),
      .b_req(cpu_mmio_req), .b_ack(cpu_mmio_ack), .b_write(cpu_mmio_write),
      .b_write_mask(cpu_mmio_mask), .b_address(cpu_mmio_addr),
      .b_write_data(cpu_mmio_wdata),
      .select(mmio_select), .write(mmio_write),
      .write_mask(mmio_write_mask), .address(mmio_address),
      .write_data(mmio_write_data));

  video_registers #(.FB_FRONT_RESET(FB0), .FB_BACK_RESET(FB1)) registers_i (
      .clk(clk_sys), .reset(reset),
      .select(mmio_select), .write(mmio_write), .write_mask(mmio_write_mask),
      // La rebanada es EXPLICITA: el dispositivo solo ve el offset dentro de
      // su bloque, y escribirlo asi lo convierte en una decision en vez de un
      // truncamiento accidental. Es lo que hace `top.v`.
      .address(mmio_address[7:0]), .write_data(mmio_write_data),
      .read_data(mmio_read_data),
      .fill_start(fill_start), .fill_first(fill_first), .fb_base(fb_base),
      .underflow_pix(underflow), .underflow_clear(video_underflow_clear),
      .halt_request(video_halt_request),
      .debug_front(), .debug_back());

  video_line_source_burst #(.SRC_W(SRC_W)) reader_i (
      .clk(clk_sys), .reset(reset), .fb_base(fb_base),
      .fill_start(fill_start), .fill_line(fill_line),
      .fill_we(fill_we), .fill_addr(fill_addr), .fill_data(fill_data),
      .fill_done(fill_done),
      .req_valid(p2_valid), .req_ready(p2_ready), .req_write(p2_write),
      .req_addr(p2_addr), .req_wdata(p2_wdata), .req_wmask(p2_wmask),
      .urgent(p2_urgent),
      .rsp_valid(p2_rsp_valid), .rsp_ready(video_rsp_ready),
      .rsp_rdata(p2_rsp_rdata), .rsp_error(p2_rsp_error));

  video_scanout #(.SRC_W(SRC_W), .SRC_H(SRC_H)) scanout_i (
      .clk_pix(clk_pix), .rst_pix(rst_pix), .sx(sx), .sy(sy),
      .de_in(de), .hsync_in(hsync), .vsync_in(vsync),
      .r(pix_r), .g(pix_g), .b(pix_b),
      .de_out(pix_de), .hsync_out(), .vsync_out(),
      .underflow(underflow),
      .clk_sys(clk_sys), .rst_sys(reset),
      .underflow_clear(video_underflow_clear),
      .fill_start(fill_start), .fill_line(fill_line), .fill_first(fill_first),
      .fill_we(fill_we), .fill_addr(fill_addr), .fill_data(fill_data),
      .fill_done(fill_done));

  memory_fabric_4 fabric_i (
      .clk(clk_sys), .reset(reset),
      .p0_req_valid(p0_valid), .p0_req_ready(p0_ready),
      .p0_req_write(p0_write), .p0_req_addr(p0_addr),
      .p0_req_wdata(p0_wdata), .p0_req_wmask(p0_wmask),
      .p0_rsp_valid(p0_rsp_valid), .p0_rsp_ready(p0_rsp_ready),
      .p0_rsp_rdata(p0_rsp_rdata), .p0_rsp_error(p0_rsp_error),

      .p1_req_valid(p1_valid), .p1_req_ready(p1_ready),
      .p1_req_write(p1_write), .p1_req_addr(p1_addr),
      .p1_req_wdata(p1_wdata), .p1_req_wmask(p1_wmask),
      .p1_rsp_valid(p1_rsp_valid), .p1_rsp_ready(p1_rsp_ready),
      .p1_rsp_rdata(p1_rsp_rdata), .p1_rsp_error(p1_rsp_error),

      .p2_req_valid(p2_valid), .p2_req_ready(p2_ready),
      .p2_req_write(p2_write), .p2_req_addr(p2_addr),
      .p2_req_wdata(p2_wdata), .p2_req_wmask(p2_wmask),
      .p2_urgent(p2_urgent),
      .p2_rsp_valid(p2_rsp_valid), .p2_rsp_ready(video_rsp_ready),
      .p2_rsp_rdata(p2_rsp_rdata), .p2_rsp_error(p2_rsp_error),

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
      .clk(clk_sys), .reset(reset),
      .req_valid(s_req_valid), .req_write(s_req_write), .req_addr(s_req_addr),
      .req_wdata(s_req_wdata), .req_wmask(s_req_wmask),
      .req_ready(s_req_ready), .done(s_done), .rdata(s_rdata),
      .init_done(init_done), .busy(ctrl_busy),
      .sdram_clk(sdram_clk_unused), .sdram_cke(cke), .sdram_csn(csn),
      .sdram_rasn(rasn), .sdram_casn(casn), .sdram_wen(wen),
      .sdram_a(sdram_a), .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm),
      .sdram_d(sdram_dq));

  // 128 filas: los dos framebuffers de 320x240 ocupan hasta la fila 91.
  sdram_model #(
      .ROWS(128), .POWERUP_DELAY_NS(POWERUP_US * 1000),
      .READ_DELAY_CYCLES(1), .CLK_PERIOD_NS(12)
  ) mem (
      .clk(clk_sys), .cke(cke), .csn(csn), .rasn(rasn), .casn(casn), .wen(wen),
      .a(sdram_a), .ba(sdram_ba), .dqm(sdram_dqm), .dq(sdram_dq));

  // -------------------------------------------------------------------------
  // Acceso directo al modelo para cargar el programa y volcar el frame. Es
  // legitimo: el modelo ES la memoria, y pasar por el bus para 76 800 palabras
  // multiplicaria el tiempo de simulacion sin probar nada nuevo.
  // -------------------------------------------------------------------------
  function integer celda;
    input [23:0] word_address;
    begin
      celda = ((word_address[10:9] * 128) + word_address[23:11]) * 512
              + word_address[8:0];
    end
  endfunction

  // PALABRAS de 32 bits, no medias palabras. El fichero lo escribe el
  // ensamblador con `--hex` y nadie lo convierte por el camino: hasta MMIO v2
  // el .hex se generaba a mano en medias palabras, y regenerarlo con la
  // herramienta --que emite palabras-- cargaba un programa que no era el
  // programa, con un sintoma que no se parecia a la causa. Un formato, una
  // orden, y la orden esta en la cabecera del fichero.
  reg [31:0] programa[0:255];

  task cargar_programa;
    integer n;
    begin
      for (n = 0; n < 256; n = n + 1) programa[n] = 32'h0000_0000;
      $readmemh("fullframe.hex", programa);
      // La SDRAM es de 16 bits: cada palabra ocupa dos celdas, la baja primero.
      for (n = 0; n < 256; n = n + 1) begin
        mem.mem[celda(2*n)]     = programa[n][15:0];
        mem.mem[celda(2*n + 1)] = programa[n][31:16];
      end
    end
  endtask

  integer fd_hex, fd_bin;
  reg [23:0] base_palabra;
  reg [15:0] pixel;
  integer x, y;

  task volcar;
    input [31:0] base_byte;
    begin
      base_palabra = base_byte[24:1];
      fd_hex = $fopen("frame_full.hex", "w");
      fd_bin = $fopen("frame_full.bin", "wb");
      $fwrite(fd_hex, "// Framebuffer de %0dx%0d en RGB565, una media palabra por linea.\n",
              SRC_W, SRC_H);
      $fwrite(fd_hex, "// Volcado por video_fullframe_tb.v desde 0x%08x.\n", base_byte);
      for (y = 0; y < SRC_H; y = y + 1)
        for (x = 0; x < SRC_W; x = x + 1) begin
          pixel = mem.mem[celda(base_palabra + y * SRC_W + x)];
          $fwrite(fd_hex, "%04x\n", pixel);
          // Little-endian, igual que lo devuelve `monitor.py read-block`.
          $fwrite(fd_bin, "%c%c", pixel[7:0], pixel[15:8]);
        end
      $fclose(fd_hex);
      $fclose(fd_bin);
    end
  endtask

  // -------------------------------------------------------------------------
  integer ciclos;
  always @(posedge clk_sys) if (!reset && !halted) ciclos = ciclos + 1;

  initial begin
    ciclos = 0;
    repeat (4) @(negedge clk_sys);
    reset = 1'b0;

    guard = 0;
    while (!init_done && guard < 200_000) begin
      @(negedge clk_sys);
      guard = guard + 1;
    end
    if (!init_done) $fatal(1, "la inicializacion de la SDRAM no termino");

    cargar_programa;

    // Armar la parada ANTES de arrancar, escribiendo HALT_AT por el mismo
    // camino que usaria el monitor. Es la unica prueba que ejercita ese
    // registro dentro del sistema completo.
    // HALT_TARGET va PRIMERO: en MMIO v2 la alarma dice a quien para (§9.6) y
    // tras reset no para a nadie. Sin esta escritura la CPU no se detiene y el
    // banco se agota esperando, que es un sintoma que no se parece a la causa.
    escribir_mmio(8'h20, 32'h0000_0001);        // HALT_TARGET = CPU
    escribir_mmio(8'h1C, FRAMES_TO_STOP);         // HALT_AT, ahora en +0x1C

    @(negedge clk_sys); run_request = 1'b1;
    @(negedge clk_sys); run_request = 1'b0;

    // Cada intercambio cuesta un frame de video entero: 800*525 ciclos de
    // pixel, o sea 1,34 M de ciclos de sistema. Es lo que domina el reloj de
    // pared de este banco.
    guard = 0;
    while (!halted && guard < 20_000_000) begin
      @(negedge clk_sys);
      guard = guard + 1;
    end
    if (!halted)
      $fatal(1, "la CPU no paro en el intercambio %0d", FRAMES_TO_STOP);
    if (cpu_error)
      $fatal(1, "la CPU paro con error %02x en pc=%08x", cpu_error_code, debug_pc);

    // El buffer que se acaba de terminar es el FRONTAL.
    volcar(leer_mmio(5'h00));

    $display("");
    $display("Parada en el intercambio %0d tras %0d ciclos de CPU",
             FRAMES_TO_STOP, ciclos);
    $display("  SWAP_COUNT = %0d", leer_mmio(5'h10));
    $display("  underflow  = %0d", leer_mmio(5'h0c) & 1);
    $display("  FB_FRONT   = 0x%08x", leer_mmio(5'h00));
    $display("  frame_full.hex y frame_full.bin volcados");

    if ((leer_mmio(5'h0c) & 1) !== 0)
      $fatal(1, "underflow: el scanout no llego a tiempo a resolucion completa");
    if (leer_mmio(5'h10) !== FRAMES_TO_STOP)
      $fatal(1, "SWAP_COUNT vale %0d, esperado %0d",
             leer_mmio(5'h10), FRAMES_TO_STOP);
    if (mem.errors != 0)
      $fatal(1, "el modelo de SDRAM conto %0d violaciones JEDEC", mem.errors);

    comprobar_imagen;

    $display("");
    $display("PASS: video_fullframe");
    $finish;
  end

  // -- acceso a los registros de video desde el banco ------------------------
  // Se pinchan directamente en el bloque de registros, no por el bus: el bus
  // lo tiene ocupado la CPU y aqui solo hace falta leer el resultado.
  function [31:0] leer_mmio;
    input [4:0] offset;
    begin
      case (offset[4:2])
        3'd0: leer_mmio = registers_i.fb_front;
        3'd1: leer_mmio = registers_i.fb_back;
        3'd3: leer_mmio = {16'd0, 14'd0, registers_i.swap_pending,
                           registers_i.underflow_sync_1};
        3'd4: leer_mmio = registers_i.swap_count;
        default: leer_mmio = 32'd0;
      endcase
    end
  endfunction

  task escribir_mmio;
    // OCHO bits, no cinco. Con cinco, `HALT_TARGET` en +0x20 se truncaba a
    // +0x00 --o sea a CTRL-- sin que Verilog dijera nada: el mismo fallo de
    // ancho que este banco existe para cazar, cometido dentro del banco.
    input [7:0] offset;
    input [31:0] value;
    begin
      @(negedge clk_sys);
      force mmio_select = 1'b1;
      force mmio_write = 1'b1;
      force mmio_write_mask = 4'b1111;
      force mmio_address = offset;
      force mmio_write_data = value;
      @(negedge clk_sys);
      release mmio_select;
      release mmio_write;
      release mmio_write_mask;
      release mmio_address;
      release mmio_write_data;
    end
  endtask

  // -- comprobacion de la imagen --------------------------------------------
  // El programa pinta la linea de arriba, la columna de la izquierda y un
  // cuadrado blanco de 32x32 en (64,48). Todo lo demas se queda a cero.
  integer malos;
  reg [15:0] esperado;

  task comprobar_imagen;
    begin
      malos = 0;
      for (y = 0; y < SRC_H; y = y + 1)
        for (x = 0; x < SRC_W; x = x + 1) begin
          if (y == 0 || x < 2)
            esperado = 16'h001F;                       // la L azul
          else if (x >= 64 && x < 96 && y >= 48 && y < 80)
            esperado = 16'hFFFF;                       // el cuadrado
          else
            esperado = 16'h0000;                       // negro
          pixel = mem.mem[celda(base_palabra + y * SRC_W + x)];
          if (pixel !== esperado) begin
            malos = malos + 1;
            if (malos <= 8)
              $display("FALLO en (%0d,%0d): %04x, esperado %04x",
                       x, y, pixel, esperado);
          end
        end
      if (malos != 0)
        $fatal(1, "%0d pixeles incorrectos de %0d", malos, SRC_W * SRC_H);
      $display("  %0d pixeles comprobados, todos correctos", SRC_W * SRC_H);
    end
  endtask
endmodule

`default_nettype wire
