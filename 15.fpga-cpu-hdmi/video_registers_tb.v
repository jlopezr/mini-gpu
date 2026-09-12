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
//   5. Las direcciones se alinean a cuatro bytes y STATUS es de solo lectura.

module video_registers_tb;
  localparam [31:0] FRONT_RESET = 32'h0100_0000;
  localparam [31:0] BACK_RESET  = 32'h0102_5800;

  reg clk = 1'b0;
  reg reset = 1'b1;
  always #4.1667 clk = ~clk;

  reg select = 1'b0;
  reg write = 1'b0;
  reg [3:0] write_mask = 4'b0000;
  reg [3:0] address = 4'h0;
  reg [31:0] write_data = 32'h0;
  wire [31:0] read_data;

  reg fill_start = 1'b0;
  reg fill_first = 1'b0;
  wire [23:0] fb_base;
  reg underflow_pix = 1'b0;
  wire [31:0] debug_front, debug_back;

  video_registers #(
      .FB_FRONT_RESET(FRONT_RESET), .FB_BACK_RESET(BACK_RESET)
  ) dut(
      .clk(clk), .reset(reset),
      .select(select), .write(write), .write_mask(write_mask),
      .address(address), .write_data(write_data), .read_data(read_data),
      .fill_start(fill_start), .fill_first(fill_first), .fb_base(fb_base),
      .underflow_pix(underflow_pix),
      .debug_front(debug_front), .debug_back(debug_back));

  task bus_write_word(input [3:0] offset, input [31:0] value);
    begin
      @(negedge clk);
      select = 1'b1; write = 1'b1; write_mask = 4'b1111;
      address = offset; write_data = value;
      @(negedge clk);
      select = 1'b0; write = 1'b0; write_mask = 4'b0000;
    end
  endtask

  task bus_write_byte(input [3:0] offset, input [7:0] value);
    begin
      @(negedge clk);
      select = 1'b1; write = 1'b1;
      write_mask = 4'b0001 << offset[1:0];
      address = offset; write_data = {4{value}};
      @(negedge clk);
      select = 1'b0; write = 1'b0; write_mask = 4'b0000;
    end
  endtask

  task bus_read(input [3:0] offset, output [31:0] value);
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
  integer frames_before, frames_after;

  initial begin
    $dumpvars(0, video_registers_tb);

    repeat (3) @(negedge clk);
    reset = 1'b0;
    @(negedge clk);

    // --- valores de reset -------------------------------------------------
    bus_read(4'h0, value);
    if (value !== FRONT_RESET) $fatal(1, "FB_FRONT tras reset: %08x", value);
    bus_read(4'h4, value);
    if (value !== BACK_RESET) $fatal(1, "FB_BACK tras reset: %08x", value);

    // --- sin swap pedido, el frame entero sale del mismo buffer -----------
    line_request(1'b1, base_seen);
    if (base_seen !== FRONT_RESET[24:1])
      $fatal(1, "sin swap, linea 0 salio de %06x", base_seen);
    line_request(1'b0, base_seen);
    if (base_seen !== FRONT_RESET[24:1])
      $fatal(1, "sin swap, linea 1 salio de %06x", base_seen);

    // --- swap: pedido a mitad de frame, aplicado al empezar el siguiente ---
    bus_write_word(4'h8, 32'h1);            // SWAP
    bus_read(4'h8, value);
    if (value[0] !== 1'b1) $fatal(1, "SWAP no quedo pendiente");

    // Una linea que NO es la primera del frame no debe intercambiar nada.
    line_request(1'b0, base_seen);
    if (base_seen !== FRONT_RESET[24:1])
      $fatal(1, "el swap se aplico a mitad de frame: %06x", base_seen);
    bus_read(4'h8, value);
    if (value[0] !== 1'b1) $fatal(1, "SWAP dejo de estar pendiente antes de tiempo");

    // La primera linea del frame siguiente ya tiene que salir del otro buffer.
    line_request(1'b1, base_seen);
    if (base_seen !== BACK_RESET[24:1])
      $fatal(1, "la linea 0 tras el swap salio de %06x, esperado %06x",
             base_seen, BACK_RESET[24:1]);

    bus_read(4'h0, value);
    if (value !== BACK_RESET) $fatal(1, "FB_FRONT tras swap: %08x", value);
    bus_read(4'h4, value);
    if (value !== FRONT_RESET) $fatal(1, "FB_BACK tras swap: %08x", value);
    bus_read(4'h8, value);
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
    bus_write_word(4'h8, 32'h1);
    @(negedge clk);
    fill_start = 1'b1; fill_first = 1'b1;
    select = 1'b1; write = 1'b1; write_mask = 4'b1111;
    address = 4'h8; write_data = 32'h1;
    @(negedge clk);
    fill_start = 1'b0; fill_first = 1'b0;
    select = 1'b0; write = 1'b0; write_mask = 4'b0000;

    bus_read(4'h0, value);
    if (value !== FRONT_RESET)
      $fatal(1, "el swap simultaneo no se aplico: FB_FRONT=%08x", value);
    bus_read(4'h8, value);
    if (value[0] !== 1'b1)
      $fatal(1, "se perdio la peticion de swap que coincidio con otro swap");

    // Y ese segundo swap se aplica en el frame siguiente, no antes.
    line_request(1'b1, base_seen);
    if (base_seen !== BACK_RESET[24:1])
      $fatal(1, "el segundo swap no se aplico: base %06x", base_seen);

    // --- contador de frames ------------------------------------------------
    bus_read(4'hc, value);
    frames_before = value[31:16];
    line_request(1'b1, base_seen);
    line_request(1'b0, base_seen);
    bus_read(4'hc, value);
    frames_after = value[31:16];
    if (frames_after != frames_before + 1)
      $fatal(1, "el contador de frames paso de %0d a %0d",
             frames_before, frames_after);

    // --- escritura byte a byte, como la hace el monitor --------------------
    bus_write_byte(4'h4, 8'h11);
    bus_write_byte(4'h5, 8'h22);
    bus_write_byte(4'h6, 8'h33);
    bus_write_byte(4'h7, 8'h44);
    bus_read(4'h4, value);
    if (value !== 32'h4433_2210)
      $fatal(1, "escritura por bytes dio %08x, esperado 44332210 (alineado)",
             value);

    // --- alineamiento y solo lectura ---------------------------------------
    bus_write_word(4'h0, 32'h0100_0003);
    bus_read(4'h0, value);
    if (value !== 32'h0100_0000)
      $fatal(1, "FB_FRONT no se alineo a cuatro bytes: %08x", value);

    underflow_pix = 1'b1;
    repeat (3) @(negedge clk);
    bus_read(4'hc, value);
    if (value[0] !== 1'b1) $fatal(1, "STATUS no refleja el underflow");
    bus_write_word(4'hc, 32'hffff_ffff);
    bus_read(4'hc, value);
    if (value[15:2] !== 0) $fatal(1, "STATUS acepto una escritura: %08x", value);

    $display("OK: swap en la primera linea del frame, contador y acceso por bytes");
    $finish;
  end

  initial begin
    #200_000;
    $fatal(1, "timeout");
  end
endmodule

`default_nettype wire
