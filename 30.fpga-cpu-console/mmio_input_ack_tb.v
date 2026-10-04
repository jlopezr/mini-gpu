// Los accesos invalidos a INPUT dan error EN el ciclo del `ack`, y no tienen
// efecto.
//
// Es la cadena entera --mmio_mux + mmio_decoder + input_registers-- como la
// monta top.v, por la misma razon que mmio_error_ack_tb.v: el error de
// DIRECCION (registro reservado, escribir uno de solo lectura, leer EVENT_CTRL,
// acceso no alineado, mas alla de +0x30) lo pone el decodificador, el de DATO
// (bits reservados de EVENT_CTRL, mascara parcial) lo pone el dispositivo, y lo
// que importa es que ambos valgan cuando el cliente los mira. input_registers_tb
// prueba el dispositivo solo; aqui se prueba que el filtro de `select` del
// decodificador impide que un acceso rechazado se ejecute.
//
// Cada acceso malo va seguido de un STATUS que demuestra que NO paso nada: la
// FIFO sigue con sus tres eventos y OVERFLOW sin tocar.
`timescale 1ns/1ps
`default_nettype none

module mmio_input_ack_tb;

  reg clk = 0, reset = 1;
  always #5 clk = ~clk;

  reg         req = 0, wr_in = 0;
  reg  [3:0]  mask_in = 4'b0000;
  reg  [31:0] addr_in = 0, data_in = 0;
  wire        ack;

  wire        sel, wr;
  wire [3:0]  wmask;
  wire [31:0] addr, wdata, rdata;
  wire        mmio_error;
  wire        input_select, input_error;
  wire [31:0] input_rdata;

  reg         event_valid = 0;
  reg  [31:0] event_word = 0;
  wire [4:0]  free_slots;

  mmio_mux mux_i(
    .clk(clk), .reset(reset),
    .a_req(1'b0), .a_ack(), .a_write(1'b0), .a_write_mask(4'b0),
    .a_address(32'b0), .a_write_data(32'b0),
    .b_req(req), .b_ack(ack), .b_write(wr_in), .b_write_mask(mask_in),
    .b_address(addr_in), .b_write_data(data_in),
    .select(sel), .write(wr), .write_mask(wmask), .address(addr),
    .write_data(wdata));

  mmio_decoder #(.FOLDER(8'd30), .HAS_SERIAL(0), .HAS_INPUT(1),
                 .ISA_PROFILE(32'h7), .DEVICES(32'hA37),
                 .MEM_BASE(32'h0), .MEM_SIZE(32'h0200_0000),
                 .MONITOR_VERSION(32'h0000_051E))
  dec_i(
    .clk(clk),
    .select(sel), .write(wr), .write_mask(wmask), .address(addr),
    .video_select(), .video_read_data(32'b0), .video_error(1'b0),
    .serial_select(), .serial_read_data(32'b0),
    .input_select(input_select), .input_read_data(input_rdata),
    .input_error(input_error),
    .perf_select(), .perf_read_data(32'b0),
    .read_data(rdata), .error(mmio_error));

  input_registers input_i(
    .clk(clk), .reset(reset),
    .select(input_select), .write(wr), .write_mask(wmask),
    .address(addr[7:0]), .write_data(wdata), .read_data(input_rdata),
    .input_error(input_error),
    .event_valid(event_valid), .event_word(event_word),
    .presence_write(1'b0), .presence_keyboard(1'b0), .presence_mouse(1'b0),
    .free_slots(free_slots));

  integer fallos = 0;

  // Una transaccion completa. `visto` y `dato` se toman EN el ciclo del ack. El
  // valor `x` inicial distingue un ack que no llega de un error que vale cero.
  reg        visto;
  reg [31:0] dato;
  task automatic acceso(input [31:0] direccion, input escribe,
                        input [3:0] mascara, input [31:0] valor);
    integer guardia;
    begin
      @(posedge clk);
      addr_in <= direccion;
      data_in <= valor;
      mask_in <= mascara;
      wr_in   <= escribe;
      req     <= 1'b1;
      visto   = 1'bx;
      guardia = 0;
      while (visto === 1'bx && guardia < 20) begin
        @(posedge clk);
        if (ack) begin visto = mmio_error; dato = rdata; end
        guardia = guardia + 1;
      end
      req <= 1'b0;
      repeat (2) @(posedge clk);
    end
  endtask

  task automatic evento(input [31:0] palabra);
    begin
      @(posedge clk);
      event_valid <= 1'b1; event_word <= palabra;
      @(posedge clk);
      event_valid <= 1'b0;
      @(posedge clk);
    end
  endtask

  task automatic comprobar(input [8*56:1] nombre, input esperado);
    begin
      if (visto !== esperado) begin
        $display("FAIL %0s: error en el ack = %0d, esperado %0d",
                 nombre, visto, esperado);
        fallos = fallos + 1;
      end else begin
        $display("ok   %0s", nombre);
      end
    end
  endtask

  task automatic comprobar_dato(input [8*56:1] nombre, input [31:0] esperado);
    begin
      if (dato !== esperado) begin
        $display("FAIL %0s: dato = %08h, esperado %08h", nombre, dato, esperado);
        fallos = fallos + 1;
      end else begin
        $display("ok   %0s", nombre);
      end
    end
  endtask

  // Intenta un acceso malo y demuestra que no tuvo efecto: STATUS sigue igual.
  task automatic malo(input [8*56:1] nombre, input [31:0] direccion,
                      input escribe, input [3:0] mascara, input [31:0] valor);
    begin
      acceso(direccion, escribe, mascara, valor);
      comprobar(nombre, 1'b1);
      acceso(32'h8060_0004, 1'b0, 4'b0000, 32'h0);
      if (visto !== 1'b0 || dato !== 32'h0000_0003) begin
        $display("FAIL %0s: tuvo efecto (STATUS = %08h)", nombre, dato);
        fallos = fallos + 1;
      end
    end
  endtask

  integer r;

  initial begin
    repeat (4) @(posedge clk);
    reset = 0;
    @(posedge clk);

    // Tres eventos en la FIFO, para que un FLUSH indebido se note.
    evento(32'h0000_0104);                      // A down
    evento(32'h0200_1001);                      // mover
    evento(32'h0100_0100);                      // boton 0 down

    // ---- lo legal ----
    acceso(32'h8060_0004, 1'b0, 4'b0000, 32'h0);
    comprobar("lectura de STATUS no da error", 1'b0);
    comprobar_dato("STATUS = tres eventos", 32'h0000_0003);
    for (r = 0; r < 8; r = r + 1) begin
      acceso(32'h8060_0010 + 4 * r, 1'b0, 4'b0000, 32'h0);
      comprobar("lectura de KEY_STATE no da error", 1'b0);
    end
    acceso(32'h8060_0010, 1'b0, 4'b0000, 32'h0);
    comprobar_dato("KEY_STATE0 tiene la A", 32'h0000_0010);
    acceso(32'h8060_0030, 1'b0, 4'b0000, 32'h0);
    comprobar("lectura de MOUSE_BUTTONS no da error", 1'b0);
    comprobar_dato("MOUSE_BUTTONS tiene el boton 0", 32'h0000_0001);
    acceso(32'h8060_0008, 1'b1, 4'b1111, 32'h0000_0000);
    comprobar("escribir cero en EVENT_CTRL no da error", 1'b0);
    acceso(32'h8060_0008, 1'b1, 4'b1111, 32'h0000_0002);
    comprobar("CLEAR_OVERFLOW no da error", 1'b0);

    // ---- errores de DIRECCION (decodificador) ----
    malo("leer EVENT_CTRL (solo escritura)", 32'h8060_0008, 1'b0, 4'b0000, 32'h0);
    malo("registro reservado +0x0C", 32'h8060_000C, 1'b0, 4'b0000, 32'h0);
    malo("registro reservado +0x34", 32'h8060_0034, 1'b0, 4'b0000, 32'h0);
    malo("registro reservado +0x100", 32'h8060_0100, 1'b0, 4'b0000, 32'h0);
    malo("lectura no alineada +0x05", 32'h8060_0005, 1'b0, 4'b0000, 32'h0);
    malo("escribir STATUS (solo lectura)", 32'h8060_0004, 1'b1, 4'b1111, 32'h1);
    malo("escribir EVENT_DATA (solo lectura)", 32'h8060_0000, 1'b1, 4'b1111, 32'h1);
    malo("escribir KEY_STATE0 (solo lectura)", 32'h8060_0010, 1'b1, 4'b1111, 32'h1);
    malo("escribir MOUSE_BUTTONS (solo lectura)", 32'h8060_0030, 1'b1, 4'b1111, 32'h1);
    malo("escribir un registro reservado", 32'h8060_000C, 1'b1, 4'b1111, 32'h1);
    malo("escritura no alineada de EVENT_CTRL", 32'h8060_0009, 1'b1, 4'b1111, 32'h1);
    malo("mas alla del bloque (0x80610000)", 32'h8061_0000, 1'b0, 4'b0000, 32'h0);

    // ---- errores de DATO y de forma (decodificador y dispositivo) ----
    malo("EVENT_CTRL con bit reservado 2", 32'h8060_0008, 1'b1, 4'b1111, 32'h0000_0004);
    malo("EVENT_CTRL con bit reservado 31", 32'h8060_0008, 1'b1, 4'b1111, 32'h8000_0001);
    malo("FLUSH con mascara parcial", 32'h8060_0008, 1'b1, 4'b0111, 32'h0000_0001);
    malo("FLUSH con mascara de un byte", 32'h8060_0008, 1'b1, 4'b0001, 32'h0000_0001);

    // ---- y un FLUSH legal si surte efecto ----
    acceso(32'h8060_0008, 1'b1, 4'b1111, 32'h0000_0001);
    comprobar("FLUSH legal no da error", 1'b0);
    acceso(32'h8060_0004, 1'b0, 4'b0000, 32'h0);
    comprobar_dato("tras FLUSH la FIFO esta vacia", 32'h0000_0000);

    // ---- la lectura destructiva entrega el evento, no el siguiente ----
    evento(32'h0200_0001);
    evento(32'h0200_0002);
    acceso(32'h8060_0000, 1'b0, 4'b0000, 32'h0);
    comprobar_dato("EVENT_DATA entrega el mas antiguo", 32'h0200_0001);
    acceso(32'h8060_0000, 1'b0, 4'b0000, 32'h0);
    comprobar_dato("y despues el siguiente", 32'h0200_0002);
    acceso(32'h8060_0000, 1'b0, 4'b0000, 32'h0);
    comprobar_dato("FIFO vacia: cero", 32'h0000_0000);

    $display("");
    if (fallos == 0)
      $display("mmio_input_ack_tb: OK");
    else
      $display("mmio_input_ack_tb: %0d FALLO(S)", fallos);
    $display("");
    if (fallos != 0) $stop;
    $finish;
  end

endmodule

`default_nettype wire
