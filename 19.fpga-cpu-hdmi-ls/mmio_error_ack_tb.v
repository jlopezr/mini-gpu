// El error de un dispositivo tiene que seguir vivo en el ciclo del `ack`.
//
// POR QUE EXISTE ESTE BANCO. El fallo que caza sólo se veía en placa, y se vio
// en la ronda de validación de MMIO v2: `shared-video-fb-desalineada` esperaba
// que la CPU parase con error 0x02 al escribir una base de framebuffer
// desalineada, y la CPU seguía como si nada. Lo desconcertante es que el
// registro SÍ rechazaba la escritura --`FB_BACK` no se movía-- así que el
// dispositivo hacía su trabajo y el aviso se perdía por el camino.
//
// La causa es de duración, no de lógica:
//
//   ciclo 1   select=1  write=1  ->  error=1, la escritura se bloquea
//   ciclo 2   select=0  write=1  ->  error=0, y AQUI es donde llega el `ack`
//
// `mmio_mux` fabrica `select` como un pulso de UN ciclo y confirma al cliente
// al siguiente; `cpu_dmem_adapter` hace `dmem_error <= mmio_error` en el ciclo
// del `ack`. El error de DIRECCION sobrevivía porque el decodificador lo saca
// de `address`/`write`, que el mux retiene; el error de DATO no, porque
// `video_registers` lo colgaba de `select`.
//
// POR QUE NO LO VEIA NINGUN BANCO. Ninguno monta la cadena entera
// mux + decodificador + dispositivo: `cpu_mmio_error_tb` instancia el
// decodificador suelto y le pone `select` a mano, así que el error y la
// comprobación caen en el mismo ciclo y el bug es invisible. Éste monta las
// tres piezas como las monta `top.v` y mira el error DONDE LO MIRA EL CLIENTE.
//
// Es la misma familia que el bug del bitmap `VIDEO_REGISTERS(64'h7f)`: algo que
// sólo existe cuando las piezas se juntan, y que por eso se cobró una placa.
`timescale 1ns/1ps
`default_nettype none

module mmio_error_ack_tb;

  reg clk = 0, reset = 1;
  always #5 clk = ~clk;

  reg         req = 0, wr_in = 0;
  reg  [3:0]  mask_in = 4'b0000;
  reg  [31:0] addr_in = 0, data_in = 0;
  wire        ack;

  wire        sel, wr;
  wire [3:0]  wmask;
  wire [31:0] addr, wdata, rdata, video_rdata;
  wire        mmio_error, video_select, video_error;
  wire        serial_select, perf_select;

  mmio_mux mux_i(
    .clk(clk), .reset(reset),
    .a_req(1'b0), .a_ack(), .a_write(1'b0), .a_write_mask(4'b0),
    .a_address(32'b0), .a_write_data(32'b0),
    .b_req(req), .b_ack(ack), .b_write(wr_in), .b_write_mask(mask_in),
    .b_address(addr_in), .b_write_data(data_in),
    .select(sel), .write(wr), .write_mask(wmask), .address(addr),
    .write_data(wdata));

  mmio_decoder #(.FOLDER(8'd19), .HAS_SERIAL(1), .VIDEO_REGISTERS(64'h3ff),
                 .ISA_PROFILE(32'h7), .DEVICES(32'h235),
                 .MEM_BASE(32'h0), .MEM_SIZE(32'h0200_0000),
                 .MONITOR_VERSION(32'h0000_0413))
  dec_i(
    .select(sel), .write(wr), .write_mask(wmask), .address(addr),
    .video_select(video_select), .video_read_data(video_rdata),
    .video_error(video_error),
    .serial_select(serial_select), .serial_read_data(32'b0),
    .perf_select(perf_select), .perf_read_data(32'b0),
    .read_data(rdata), .error(mmio_error));

  video_registers registers_i(
    .clk(clk), .reset(reset),
    .select(video_select), .write(wr), .write_mask(wmask),
    .address(addr[7:0]), .write_data(wdata), .read_data(video_rdata),
    .error(video_error),
    .running(1'b1),
    .fill_start(1'b0), .fill_first(1'b0), .fb_base(),
    .underflow_pix(1'b0), .underflow_clear(),
    .halt_request(), .video_mode(),
    .debug_front(), .debug_back());

  integer fallos = 0;

  // Una transaccion completa, y se mira `mmio_error` EN el ciclo del ack, que
  // es exactamente lo que hace `cpu_dmem_adapter` en su estado ST_MMIO.
  //
  // `visto` arranca en X y solo lo escribe el ciclo del ack, asi que un ack que
  // no llegue se distingue de un error que valga cero: la guarda corta a los 20
  // ciclos y la comprobacion ve una X, que no es igual a nada.
  reg visto;
  task automatic acceso(input [31:0] direccion, input escribe,
                        input [3:0] mascara, input [31:0] dato);
    integer guardia;
    begin
      @(posedge clk);
      addr_in <= direccion;
      data_in <= dato;
      mask_in <= mascara;
      wr_in   <= escribe;
      req     <= 1'b1;
      visto   = 1'bx;
      guardia = 0;
      while (visto === 1'bx && guardia < 20) begin
        @(posedge clk);
        if (ack) visto = mmio_error;
        guardia = guardia + 1;
      end
      req <= 1'b0;
      @(posedge clk);
    end
  endtask

  task automatic comprobar(input [8*48:1] nombre, input esperado);
    begin
      if (visto !== esperado) begin
        $display("FAIL %0s: mmio_error en el ack = %0d, esperado %0d",
                 nombre, visto, esperado);
        fallos = fallos + 1;
      end else begin
        $display("ok   %0s", nombre);
      end
    end
  endtask

  initial begin
    repeat (4) @(posedge clk);
    reset = 0;
    @(posedge clk);

    // 1. Base de FB_BACK desalineada a 16, palabra completa: ERROR (§9.2).
    //    Es el caso exacto de `shared-video-fb-desalineada`.
    acceso(32'h8020_0008, 1'b1, 4'b1111, 32'h0110_0004);
    comprobar("FB_BACK desalineada da error en el ack", 1'b1);

    // 2. La misma escritura bien alineada: sin error. Sin esta mitad, un
    //    `error` cableado a uno pasaria la comprobacion de arriba.
    acceso(32'h8020_0008, 1'b1, 4'b1111, 32'h0110_0000);
    comprobar("FB_BACK alineada no da error", 1'b0);

    // 3. FB_FRONT, que lleva la misma comprobacion por su cuenta.
    acceso(32'h8020_0004, 1'b1, 4'b1111, 32'h0110_0008);
    comprobar("FB_FRONT desalineada da error en el ack", 1'b1);

    // 4. Modo reservado en CTRL: tambien es error de dato, y por el mismo
    //    camino. Asi la prueba no depende de una sola condicion.
    acceso(32'h8020_0000, 1'b1, 4'b1111, 32'h0000_0003);
    comprobar("CTRL con modo reservado da error en el ack", 1'b1);

    // 5. Modo valido: sin error.
    acceso(32'h8020_0000, 1'b1, 4'b1111, 32'h0000_0002);
    comprobar("CTRL con modo valido no da error", 1'b0);

    // 6. Contraste con el error de DIRECCION, que nunca estuvo roto porque el
    //    decodificador lo saca de la direccion retenida. Sirve de control: si
    //    esta linea fallara, lo roto seria el banco y no el dispositivo.
    acceso(32'h8030_0000, 1'b1, 4'b1111, 32'h0000_0001);
    comprobar("bloque sin dispositivo da error en el ack", 1'b1);

    // 7. Una lectura normal no da error.
    acceso(32'h8020_0004, 1'b0, 4'b0000, 32'h0);
    comprobar("lectura de FB_FRONT no da error", 1'b0);

    $display("");
    if (fallos == 0)
      $display("mmio_error_ack_tb: OK");
    else
      $display("mmio_error_ack_tb: %0d FALLO(S)", fallos);
    $display("");
    if (fallos != 0) $stop;
    $finish;
  end

endmodule

`default_nettype wire
