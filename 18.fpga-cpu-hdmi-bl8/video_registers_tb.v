`timescale 1ns/1ps
`default_nettype none

// Banco de pruebas del hito D: registros de video y doble framebuffer.
//
// Lo que se comprueba, en orden de lo que costaria mas caro equivocarse:
//
//   1. El swap ocurre EXACTAMENTE en la primera peticion de linea del frame, y
//      `fb_base` ya vale el buffer nuevo en ese mismo ciclo. Si `fb_base`
//      fuera un registro, la linea 0 saldria del buffer viejo y el resto del
//      nuevo: un desgarro de una linea. Esta es la prueba que justifica que
//      `fb_base` sea combinacional.
//   2. Sin peticion de swap, el frame entero sale del mismo buffer.
//   3. Una peticion de swap que cae en el mismo ciclo que un swap en curso
//      queda pendiente para el frame siguiente y no se pierde.
//   4. Escritura byte a byte (lo que hace el monitor) sin destruir los otros
//      tres bytes del registro.
//   5. Una base desalineada es ERROR y STATUS es de solo lectura.
//
// Los offsets son los de MMIO v2 (mmio.md §9): CTRL volvio al +0x00 y empujo
// una palabra todo lo demas. Se nombran como localparam en vez de escribirse
// a pelo porque este banco tenia los diez repartidos por 350 lineas y
// migrarlos a mano era justo la clase de trabajo donde se cuela uno.

module video_registers_tb;
  localparam [31:0] FRONT_RESET = 32'h0100_0000;
  localparam [31:0] BACK_RESET  = 32'h0102_5800;

  localparam [7:0] CTRL        = 8'h00;
  localparam [7:0] FB_FRONT    = 8'h04;
  localparam [7:0] FB_BACK     = 8'h08;
  localparam [7:0] SWAP        = 8'h0C;
  localparam [7:0] STATUS      = 8'h10;
  localparam [7:0] FRAME_COUNT = 8'h14;
  localparam [7:0] SWAP_COUNT  = 8'h18;
  localparam [7:0] HALT_AT     = 8'h1C;
  localparam [7:0] HALT_TARGET = 8'h20;
  localparam [7:0] VIDEO_TX    = 8'h24;

  localparam [31:0] TARGET_CPU = 32'h0000_0001;

  reg clk = 1'b0;
  reg reset = 1'b1;
  always #4.1667 clk = ~clk;

  reg select = 1'b0;
  reg write = 1'b0;
  reg [3:0] write_mask = 4'b0000;
  reg [7:0] address = 8'h00;
  wire underflow_clear, halt_request;
  reg [31:0] write_data = 32'h0;
  wire [31:0] read_data;

  reg fill_start = 1'b0;
  reg fill_first = 1'b0;
  wire [23:0] fb_base;
  reg underflow_pix = 1'b0;
  wire [31:0] debug_front, debug_back;
  wire error;
  wire [1:0] video_mode;
  // El nucleo se da por corriendo: `video_tx` solo avanza mientras corre, y un
  // banco que lo dejara a cero no veria nunca ese contador moverse.
  reg running = 1'b1;

  video_registers #(
      .FB_FRONT_RESET(FRONT_RESET), .FB_BACK_RESET(BACK_RESET)
  ) dut(
      .clk(clk), .reset(reset),
      .select(select), .write(write), .write_mask(write_mask),
      .address(address), .write_data(write_data), .read_data(read_data),
      .error(error), .running(running),
      .fill_start(fill_start), .fill_first(fill_first), .fb_base(fb_base),
      .underflow_pix(underflow_pix), .underflow_clear(underflow_clear),
      .halt_request(halt_request), .video_mode(video_mode),
      .debug_front(debug_front), .debug_back(debug_back));

  task bus_write_word(input [7:0] offset, input [31:0] value);
    begin
      @(negedge clk);
      select = 1'b1; write = 1'b1; write_mask = 4'b1111;
      address = offset; write_data = value;
      @(negedge clk);
      select = 1'b0; write = 1'b0; write_mask = 4'b0000;
    end
  endtask

  task bus_write_byte(input [7:0] offset, input [7:0] value);
    begin
      @(negedge clk);
      select = 1'b1; write = 1'b1;
      write_mask = 4'b0001 << offset[1:0];
      address = offset; write_data = {4{value}};
      @(negedge clk);
      select = 1'b0; write = 1'b0; write_mask = 4'b0000;
    end
  endtask

  task bus_read(input [7:0] offset, output [31:0] value);
    begin
      @(negedge clk);
      select = 1'b1; write = 1'b0; address = offset;
      #1;
      value = read_data;
      @(negedge clk);
      select = 1'b0;
    end
  endtask

  // Una peticion de linea. `first` marca la primera del frame, que es el unico
  // instante en el que el hardware puede intercambiar los buffers.
  //
  // `fb_base` se muestrea con #1 tras el flanco de bajada, es decir mientras
  // `fill_start` sigue alto: es exactamente lo que ve el lector de lineas en el
  // flanco de subida que captura su direccion base.
  task line_request(input first, output [23:0] observed);
    begin
      @(negedge clk);
      fill_start = 1'b1; fill_first = first;
      #1;
      observed = fb_base;
      @(negedge clk);
      fill_start = 1'b0; fill_first = 1'b0;
    end
  endtask

  reg [23:0] base_seen;
  reg [31:0] value;
  reg [31:0] swaps_before;
  integer frames_before, frames_after;

  // `underflow_clear` y `halt_request` son pulsos de un ciclo, asi que hay que
  // engancharlos: comprobarlos con un `if` suelto no los veria.
  //
  // Se cuentan en vez de marcarse con un booleano que la secuencia de prueba
  // pusiera a cero: eso serian DOS procesos escribiendo el mismo registro, y
  // el orden entre ellos no esta definido. Aqui solo escribe el `always`, y la
  // prueba compara antes y despues.
  integer clear_count, halt_count, mark, error_count;
  initial begin
    clear_count = 0;
    halt_count = 0;
    error_count = 0;
    mark = 0;
  end
  always @(posedge clk) begin
    if (underflow_clear) clear_count = clear_count + 1;
    if (halt_request) halt_count = halt_count + 1;
    // `error` solo tiene sentido mientras hay un acceso: fuera de `select` es
    // el valor de una comparacion sobre datos que nadie esta presentando.
    if (select && error) error_count = error_count + 1;
  end

  initial begin
    $dumpvars(0, video_registers_tb);

    repeat (3) @(negedge clk);
    reset = 1'b0;
    @(negedge clk);

    // --- valores de reset -------------------------------------------------
    bus_read(FB_FRONT, value);
    if (value !== FRONT_RESET) $fatal(1, "FB_FRONT tras reset: %08x", value);
    bus_read(FB_BACK, value);
    if (value !== BACK_RESET) $fatal(1, "FB_BACK tras reset: %08x", value);

    // --- sin swap pedido, el frame entero sale del mismo buffer -----------
    line_request(1'b1, base_seen);
    if (base_seen !== FRONT_RESET[24:1])
      $fatal(1, "sin swap, linea 0 salio de %06x", base_seen);
    line_request(1'b0, base_seen);
    if (base_seen !== FRONT_RESET[24:1])
      $fatal(1, "sin swap, linea 1 salio de %06x", base_seen);

    // --- swap: pedido a mitad de frame, aplicado al empezar el siguiente ---
    bus_write_word(SWAP, 32'h1);            // SWAP
    bus_read(SWAP, value);
    if (value[0] !== 1'b1) $fatal(1, "SWAP no quedo pendiente");

    // Una linea que NO es la primera del frame no debe intercambiar nada.
    line_request(1'b0, base_seen);
    if (base_seen !== FRONT_RESET[24:1])
      $fatal(1, "el swap se aplico a mitad de frame: %06x", base_seen);
    bus_read(SWAP, value);
    if (value[0] !== 1'b1) $fatal(1, "SWAP dejo de estar pendiente antes de tiempo");

    // La primera linea del frame siguiente ya tiene que salir del otro buffer.
    line_request(1'b1, base_seen);
    if (base_seen !== BACK_RESET[24:1])
      $fatal(1, "la linea 0 tras el swap salio de %06x, esperado %06x",
             base_seen, BACK_RESET[24:1]);

    bus_read(FB_FRONT, value);
    if (value !== BACK_RESET) $fatal(1, "FB_FRONT tras swap: %08x", value);
    bus_read(FB_BACK, value);
    if (value !== FRONT_RESET) $fatal(1, "FB_BACK tras swap: %08x", value);
    bus_read(SWAP, value);
    if (value[0] !== 1'b0) $fatal(1, "SWAP sigue pendiente tras aplicarse");

    // El resto del frame sigue saliendo del buffer ya intercambiado.
    line_request(1'b0, base_seen);
    if (base_seen !== BACK_RESET[24:1])
      $fatal(1, "la linea 1 tras el swap salio de %06x", base_seen);

    // --- swap pedido en el MISMO ciclo en que se aplica otro ---------------
    //
    // El software que dibuja a toda velocidad puede pedir un swap justo en el
    // flanco en que el hardware esta aplicando el anterior. La peticion nueva
    // tiene que sobrevivir para el frame siguiente: perderla dejaria al
    // programa esperando un intercambio que nunca llega.
    bus_write_word(SWAP, 32'h1);
    @(negedge clk);
    fill_start = 1'b1; fill_first = 1'b1;
    select = 1'b1; write = 1'b1; write_mask = 4'b1111;
    address = SWAP; write_data = 32'h1;
    @(negedge clk);
    fill_start = 1'b0; fill_first = 1'b0;
    select = 1'b0; write = 1'b0; write_mask = 4'b0000;

    bus_read(FB_FRONT, value);
    if (value !== FRONT_RESET)
      $fatal(1, "el swap simultaneo no se aplico: FB_FRONT=%08x", value);
    bus_read(SWAP, value);
    if (value[0] !== 1'b1)
      $fatal(1, "se perdio la peticion de swap que coincidio con otro swap");

    // Y ese segundo swap se aplica en el frame siguiente, no antes.
    line_request(1'b1, base_seen);
    if (base_seen !== BACK_RESET[24:1])
      $fatal(1, "el segundo swap no se aplico: base %06x", base_seen);

    // --- contador de frames ------------------------------------------------
    // En v1 vivia en STATUS[31:16] y daban la vuelta a los 65536 frames, unos
    // 18 minutos de video. v2 le da registro propio y los 32 bits (§9.5).
    bus_read(FRAME_COUNT, value);
    frames_before = value;
    line_request(1'b1, base_seen);
    line_request(1'b0, base_seen);
    bus_read(FRAME_COUNT, value);
    frames_after = value;
    if (frames_after != frames_before + 1)
      $fatal(1, "el contador de frames paso de %0d a %0d",
             frames_before, frames_after);

    // --- escritura byte a byte, como la hace el monitor --------------------
    //
    // DEUDA CONOCIDA, fijada aqui a proposito. §4.1 dice que MMIO solo admite
    // palabras alineadas, y §16.2 que el monitor debe usar WRITE_WORD. Este
    // modulo ya recibe `write_mask` y la comprobacion de alineamiento se salta
    // cuando la escritura es parcial, asi que los cuatro bytes entran y el
    // valor queda DESALINEADO --acabado en 0x11-- sin que nadie proteste.
    // Rechazarlas es una linea, pero el host y varios bancos escriben byte a
    // byte y tienen que pasar a WRITE_WORD a la vez; hasta entonces esto
    // documenta lo que el hardware hace hoy, no lo que deberia hacer.
    bus_write_byte(FB_BACK + 0, 8'h11);
    bus_write_byte(FB_BACK + 1, 8'h22);
    bus_write_byte(FB_BACK + 2, 8'h33);
    bus_write_byte(FB_BACK + 3, 8'h44);
    bus_read(FB_BACK, value);
    if (value !== 32'h4433_2211)
      $fatal(1, "escritura por bytes dio %08x, esperado 44332211", value);
    // Se deja alineado otra vez: lo de arriba es una prueba, no un estado del
    // que el resto del banco pueda depender.
    bus_write_word(FB_BACK, BACK_RESET);

    // --- desalinear es ERROR, no se trunca (§9.2) --------------------------
    // En v1 los dos bits bajos se ignoraban, y el truncamiento no era el mismo
    // en las dos familias --cuatro bytes en la CPU, dieciseis en la GPU-- asi
    // que el mismo programa dibujaba bien en una placa y torcido en la otra.
    // Contra el valor que haya AHORA, no contra FRONT_RESET: a estas alturas
    // los buffers se han intercambiado un numero de veces que depende de los
    // bloques anteriores, y fijar aqui una constante hace que este test falle
    // cuando alguien anade un swap cien lineas mas arriba.
    bus_read(FB_FRONT, swaps_before);
    mark = error_count;
    bus_write_word(FB_FRONT, 32'h0100_0004);   // alineado a 4, no a 16
    if (error_count == mark)
      $fatal(1, "una base desalineada no levanto error");
    bus_read(FB_FRONT, value);
    if (value !== swaps_before)
      $fatal(1, "la base desalineada se escribio igual: %08x", value);

    // Y una alineada de verdad si entra: el test de arriba tiene que fallar
    // por el alineamiento, no porque el registro haya dejado de aceptar nada.
    bus_write_word(FB_FRONT, 32'h0100_0010);
    bus_read(FB_FRONT, value);
    if (value !== 32'h0100_0010)
      $fatal(1, "una base alineada a 16 fue rechazada: %08x", value);
    bus_write_word(FB_FRONT, swaps_before);

    underflow_pix = 1'b1;
    repeat (3) @(negedge clk);
    bus_read(STATUS, value);
    if (value[0] !== 1'b1) $fatal(1, "STATUS no refleja el underflow");

    // --- borrado del underflow --------------------------------------------
    // El latch vive en el dominio de pixel, asi que desde aqui solo se puede
    // comprobar que sale el pulso; que el latch se entera lo cubre
    // video_scanout_tb.v, que tiene los dos dominios.
    //
    // Escribir CUALQUIER cosa no vale: solo un uno en el bit 0. Asi una
    // escritura descuidada de STATUS no borra un underflow que alguien estaba
    // a punto de leer.
    mark = clear_count;
    bus_write_word(STATUS, 32'hffff_fffe);      // bit 0 a cero
    repeat (2) @(negedge clk);
    if (clear_count != mark)
      $fatal(1, "STATUS borro el underflow sin el bit 0");

    mark = clear_count;
    bus_write_word(STATUS, 32'h0000_0001);
    repeat (2) @(negedge clk);
    if (clear_count == mark)
      $fatal(1, "escribir 1 en STATUS bit 0 no borro el underflow");

    // Y el resto de STATUS sigue siendo de solo lectura.
    bus_read(STATUS, value);
    if (value[15:2] !== 0) $fatal(1, "STATUS acepto una escritura: %08x", value);

    // --- SWAP_COUNT cuenta intercambios, no frames de video ----------------
    bus_read(SWAP_COUNT, swaps_before);
    // Un frame SIN intercambio pedido: el contador no debe moverse.
    line_request(1'b1, base_seen);
    bus_read(SWAP_COUNT, value);
    if (value !== swaps_before)
      $fatal(1, "SWAP_COUNT avanzo sin intercambio: %0d -> %0d",
             swaps_before, value);
    // Y ahora uno con intercambio.
    bus_write_word(SWAP, 32'h1);
    line_request(1'b1, base_seen);
    bus_read(SWAP_COUNT, value);
    if (value !== swaps_before + 1)
      $fatal(1, "SWAP_COUNT no conto el intercambio: %0d -> %0d",
             swaps_before, value);

    // --- HALT_AT para la CPU en el FRAME N ---------------------------------
    // En v1 contaba INTERCAMBIOS. En v2 cuenta frames (§9.7), y no es lo
    // mismo: mientras un programa dibuja un frame entero pasan varios frames
    // de barrido sin ningun intercambio, asi que la alarma llega mucho antes
    // en terminos del programa. Todo lo que sigue son `line_request(1)`, que
    // es un frame, y ya no hace falta pedir swap para que la cuenta avance.
    bus_read(HALT_AT, value);
    if (value !== 32'd0) $fatal(1, "HALT_AT no arranca a cero: %08x", value);

    // El pulso lo engancha el muestreador en el flanco SIGUIENTE al del
    // frame, asi que hay que dejar pasar un par de ciclos antes de mirar el
    // contador. Comprobar nada mas volver de `line_request` daria «no paro»
    // siempre, incluso con el hardware correcto.
    mark = halt_count;
    line_request(1'b1, base_seen);
    repeat (2) @(negedge clk);
    if (halt_count != mark) $fatal(1, "HALT_AT a cero paro la CPU");

    // --- HALT_TARGET: la alarma dice A QUIEN para (§9.6) -------------------
    // Tras reset no para a nadie, asi que armar solo HALT_AT --que era todo
    // lo que hacia falta en v1-- no detiene nada. Es la trampa numero uno al
    // portar un programa, y por eso se comprueba antes de armar de verdad.
    bus_read(HALT_TARGET, value);
    if (value !== 32'd0)
      $fatal(1, "HALT_TARGET no arranca a cero: %08x", value);
    bus_write_word(HALT_AT, 32'd1);
    mark = halt_count;
    line_request(1'b1, base_seen);
    repeat (2) @(negedge clk);
    if (halt_count != mark)
      $fatal(1, "paro sin HALT_TARGET: la alarma no mira a quien para");

    bus_write_word(HALT_TARGET, TARGET_CPU);

    // Armar: la cuenta es RELATIVA a este momento, asi que se pide 2 y no «el
    // que haga dos mas». Armar tambien pone FRAME_COUNT a cero --en v1 ponia
    // SWAP_COUNT, que es el otro contador--.
    bus_write_word(HALT_AT, 32'd2);
    bus_read(FRAME_COUNT, value);
    if (value !== 32'd0)
      $fatal(1, "armar HALT_AT no puso FRAME_COUNT a cero: %0d", value);

    // El frame de en medio no debe parar nada.
    mark = halt_count;
    line_request(1'b1, base_seen);
    repeat (2) @(negedge clk);
    if (halt_count != mark)
      $fatal(1, "HALT_AT paro en el frame equivocado");
    // Y el siguiente si.
    line_request(1'b1, base_seen);
    repeat (2) @(negedge clk);
    if (halt_count == mark)
      $fatal(1, "HALT_AT no paro a los dos frames");

    // --- Y se puede volver a armar -----------------------------------------
    // Este es el fallo que encontro la placa y que la simulacion no veia: con
    // `==` contra un contador que solo el reset pone a cero, la segunda vez
    // que un programa arma la alarma no para NUNCA, porque el contador ya
    // paso de largo. El caso `bounce` pasaba la primera vez y fallaba siempre
    // despues.
    //
    // Control negativo: sin el arreglo, este bloque se queda en «no paro».
    bus_write_word(HALT_AT, 32'd1);
    mark = halt_count;
    line_request(1'b1, base_seen);
    repeat (2) @(negedge clk);
    if (halt_count == mark)
      $fatal(1, "HALT_AT no volvio a armarse");

    // Y es de UN disparo: consumida, los frames siguientes no paran.
    mark = halt_count;
    line_request(1'b1, base_seen);
    repeat (2) @(negedge clk);
    if (halt_count != mark)
      $fatal(1, "HALT_AT siguio disparando despues de consumirse");

    // --- VIDEO_TX cuenta frames emitidos mientras el nucleo corre ----------
    bus_read(VIDEO_TX, swaps_before);
    line_request(1'b1, base_seen);
    bus_read(VIDEO_TX, value);
    if (value !== swaps_before + 1)
      $fatal(1, "VIDEO_TX no conto el frame: %0d -> %0d", swaps_before, value);

    $display("OK: swap, contadores, borrado de underflow y parada en el frame N");
    $finish;
  end

  initial begin
    #200_000;
    $fatal(1, "timeout");
  end
endmodule

`default_nettype wire
