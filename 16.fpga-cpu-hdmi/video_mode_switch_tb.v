`default_nettype none
`timescale 1ns/1ps
// Cambia VIDEO_CTRL A MITAD DE UN LLENADO DE LINEA y comprueba que el video
// sigue vivo despues.
//
// Por que existe
// --------------
// Es el port del banco homonimo de la MiniGPU, que nacio de un fallo REAL en
// placa: con VIDEO_CTRL=SCANOUT y FB_FRONT correcto no salia ni una peticion al
// fabric, el contador de frames seguia avanzando y no habia underflow.
// `monitor.py reset` no lo recuperaba; solo reprogramar la FPGA.
//
// La causa esta en como se elige la fuente de linea. Las dos comparten
// contrato, y si tanto el arranque como la terminacion van puerteados por el
// modo:
//
//     .fill_start(fill_start && scanout_on)     <- fuente SDRAM
//     .fill_start(fill_start && !scanout_on)    <- fuente patron
//     assign fill_done = scanout_on ? burst_done : pat_done;
//
// entonces un cambio de modo con una linea a medias deja a la fuente que estaba
// trabajando sin poder entregar su `fill_done`, y a la entrante sin haber visto
// nunca su `fill_start`. Nadie termina la linea y el video se queda ENCALLADO.
//
// La CPU no podia sufrirlo mientras no tenia VIDEO_CTRL: solo habia una fuente.
// Desde que lo tiene, puede -- y ademas el cambio PATTERN -> SCANOUT lo hara un
// programa en marcha, en un instante arbitrario, en cada arranque.
//
// Como se comprueba
// -----------------
// Los otros bancos de video instancian una sola fuente y no tienen mux, asi que
// no pueden ver esto. Aqui se replica la estructura de top.v --las dos fuentes
// y el mux REAL, no una copia de sus `assign`-- y se modela el consumidor como
// lo que es: `video_scanout` pide UNA linea y espera su `fill_done` antes de
// pedir la siguiente. Con ese modelo el encallamiento se ve solo: si se pierde
// un `fill_done`, no vuelve a salir ningun `fill_start` y las lineas dejan de
// fluir.
//
// El bus de memoria se modela con lo minimo --acepta y contesta al ciclo
// siguiente-- porque lo que se prueba es el flujo de `fill_done`, no que los
// pixeles sean los correctos: de eso ya se ocupan video_burst_tb y
// cpu_video_tb.
module video_mode_switch_tb;
  reg clk = 0;
  always #5 clk = ~clk;
  reg reset = 1;

  localparam [1:0] MODE_PATTERN = 2'd1;
  localparam [1:0] MODE_SCANOUT = 2'd2;

  // ---------------------------------------------------------------- registros
  reg select = 0, write = 0;
  reg [3:0] write_mask = 4'h0;
  reg [7:0] address = 8'h00;
  reg [31:0] write_data = 32'h0;
  wire [31:0] read_data;
  wire [1:0] video_mode;
  wire [23:0] fb_base;

  video_registers registers_i(
      .clk(clk), .reset(reset),
      .select(select), .write(write), .write_mask(write_mask),
      .address(address), .write_data(write_data), .read_data(read_data),
      .fill_start(1'b0), .fill_first(1'b0), .fb_base(fb_base),
      .underflow_pix(1'b0),
      .video_mode(video_mode),
      .debug_front(), .debug_back());

  // ------------------------------------------------------ consumidor modelado
  //
  // `fill_start` NO corre libre: sale cuando toca por tiempo Y no hay ninguna
  // linea a medias. Asi, perder un `fill_done` deja `fill_busy` clavado a uno
  // para siempre y el fallo se manifiesta como ausencia de lineas, que es
  // exactamente lo que se veia en la placa.
  reg [15:0] line_tick = 0;
  reg fill_start = 0;
  reg fill_busy = 0;
  reg [7:0] fill_line = 0;
  integer lines_done = 0;

  // Reset local de fuentes, mux y consumidor. Modela lo unico que sacaba a la
  // placa del encallamiento: reprogramar la FPGA. Sin esto, el primer caso que
  // encalla deja muertos a los siguientes y no se puede probar la otra
  // direccion del cambio.
  reg src_reset_pulse = 0;
  wire src_reset = reset | src_reset_pulse;

  wire burst_we, burst_done, pat_we, pat_done;
  wire [8:0] burst_addr, pat_addr;
  wire [15:0] burst_data, pat_data;
  wire fill_we, fill_done;
  wire [8:0] fill_addr;
  wire [15:0] fill_data;
  wire start_sdram, start_pattern;

  video_line_source_mux source_mux_i(
      .clk(clk), .reset(src_reset),
      .video_mode(video_mode), .fill_start(fill_start),
      .start_sdram(start_sdram), .start_pattern(start_pattern),
      .burst_we(burst_we), .burst_addr(burst_addr),
      .burst_data(burst_data), .burst_done(burst_done),
      .pat_we(pat_we), .pat_addr(pat_addr),
      .pat_data(pat_data), .pat_done(pat_done),
      .fill_we(fill_we), .fill_addr(fill_addr),
      .fill_data(fill_data), .fill_done(fill_done));

  always @(posedge clk) begin
    fill_start <= 1'b0;
    if (src_reset) begin
      line_tick <= 0; fill_busy <= 0; fill_line <= 0;
    end else begin
      if (fill_done && fill_busy) begin
        fill_busy <= 1'b0;
        lines_done = lines_done + 1;
      end
      if (line_tick >= 16'd1587) begin
        if (!fill_busy) begin
          line_tick <= 0; fill_start <= 1'b1; fill_busy <= 1'b1;
          fill_line <= (fill_line == 8'd239) ? 8'd0 : fill_line + 8'd1;
        end
      end else line_tick <= line_tick + 1'b1;
    end
  end

  // ------------------------------------------------------- memoria de juguete
  //
  // La fuente de esta carpeta habla palabra a palabra con un `video_req` /
  // `video_ready`, no por el fabric de rafagas. El modelo contesta al ciclo
  // siguiente: lo que se prueba es el flujo de `fill_done`, no que los pixeles
  // sean los correctos -- de eso ya se ocupa cpu_video_tb.
  wire video_req;
  wire [23:0] video_addr;
  reg video_ready = 0;

  video_line_source_sdram source_sdram_i(
      .clk(clk), .reset(src_reset), .fb_base(fb_base),
      .fill_start(start_sdram), .fill_line(fill_line),
      .fill_we(burst_we), .fill_addr(burst_addr), .fill_data(burst_data),
      .fill_done(burst_done),
      .video_req(video_req), .video_addr(video_addr),
      .video_read_data(16'h1234), .video_ready(video_ready));

  always @(posedge clk) video_ready <= video_req && !video_ready;

  video_line_source_pattern source_pat_i(
      .clk(clk), .reset(src_reset),
      .fill_start(start_pattern), .fill_line(fill_line),
      .fill_we(pat_we), .fill_addr(pat_addr), .fill_data(pat_data),
      .fill_done(pat_done));

  // ------------------------------------------------------------------- pruebas
  integer antes;
  integer errores = 0;

  task escribir_ctrl;
    input [1:0] modo;
    begin
      @(posedge clk);
      select <= 1'b1; write <= 1'b1; write_mask <= 4'b1111;
      address <= 8'h18; write_data <= {30'd0, modo};
      @(posedge clk);
      select <= 1'b0; write <= 1'b0; write_mask <= 4'b0000;
    end
  endtask

  // Espera a que el consumidor complete N lineas mas, o se rinde: rendirse ES
  // el fallo que se busca.
  task exigir_lineas;
    input integer cuantas;
    // Ancha a proposito: con 128 bits la etiqueta se truncaba por la izquierda
    // y el mensaje de fallo decia "UT a media linea", que no identifica nada.
    input [319:0] etiqueta;
    integer limite;
    begin
      antes = lines_done;
      limite = 0;
      while (lines_done < antes + cuantas && limite < 400000) begin
        @(posedge clk);
        limite = limite + 1;
      end
      if (lines_done < antes + cuantas) begin
        $display("FAIL: %0s -- el video se encallo (%0d lineas en vez de %0d)",
                 etiqueta, lines_done - antes, cuantas);
        errores = errores + 1;
      end
    end
  endtask

  initial begin
    repeat (4) @(posedge clk);
    reset <= 1'b0;

    // Tras el reset el modo es PATTERN, no SCANOUT. Comprobarlo aqui es barato
    // y es la mitad de la decision: arrancar sin leer memoria es lo que permite
    // que las bases de framebuffer dejen de venir cableadas.
    @(posedge clk);
    if (video_mode !== MODE_PATTERN) begin
      $display("FAIL: tras el reset VIDEO_CTRL deberia ser PATTERN (%0d)",
               video_mode);
      errores = errores + 1;
    end

    exigir_lineas(3, "arranque en PATTERN");

    // --- el caso que colgaba la placa: cambiar A MEDIA LINEA ---
    @(posedge fill_start);
    repeat (40) @(posedge clk);       // con la linea a medias
    escribir_ctrl(MODE_SCANOUT);
    exigir_lineas(3, "PATTERN -> SCANOUT a media linea");

    // Y la direccion contraria, que es la que un caso de prueba hace al
    // terminar para dejar la placa como se la encontro.
    @(posedge fill_start);
    repeat (40) @(posedge clk);
    escribir_ctrl(MODE_PATTERN);
    exigir_lineas(3, "SCANOUT -> PATTERN a media linea");

    if (errores == 0)
      $display("PASS: el cambio de modo a media linea no encalla el video");
    else
      $fatal(1, "%0d fallos", errores);
    $finish;
  end

  initial begin
    #40_000_000;
    $fatal(1, "timeout global");
  end
endmodule

`default_nettype wire
