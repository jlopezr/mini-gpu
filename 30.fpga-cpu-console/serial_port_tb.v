`timescale 1ns/1ps
`default_nettype none

/*
 * Banco del puerto serie. Prueba el dispositivo solo, sin CPU ni monitor.
 *
 * Aqui van los casos de borde de las colas, que son baratos de provocar en
 * aislamiento y carisimos de reproducir a traves de un programa: cola llena,
 * cola vacia, vuelta del puntero circular, meter y sacar el mismo ciclo, y el
 * overrun.
 *
 * Lo que NO se prueba aqui es que el dispositivo este bien enganchado al bus:
 * eso es cpu_serial_tb.v.
 */
module serial_port_tb;
  localparam integer DEPTH = 64;

  localparam [7:0] REG_DATA   = 8'h00;
  localparam [7:0] REG_STATUS = 8'h04;
  localparam [7:0] REG_PEEK   = 8'h08;

  reg clk = 0;
  reg reset = 1;
  always #5 clk = ~clk;

  reg select = 0, write = 0;
  reg [3:0] write_mask = 4'b1111;
  reg [7:0] address = 0;
  reg [31:0] write_data = 0;
  wire [31:0] read_data;

  reg host_push = 0;
  reg [7:0] host_push_data = 0;
  wire [7:0] host_rx_free;
  reg host_pop = 0;
  wire [7:0] host_tx_data, host_tx_count;

  integer errors = 0;
  integer i;
  reg [31:0] leido;

  serial_port #(.DEPTH(DEPTH), .ABITS(6)) dut (
      .clk(clk), .reset(reset),
      .select(select), .write(write), .write_mask(write_mask),
      .address(address), .write_data(write_data), .read_data(read_data),
      .host_push(host_push), .host_push_data(host_push_data),
      .host_rx_free(host_rx_free),
      .host_pop(host_pop), .host_tx_data(host_tx_data),
      .host_tx_count(host_tx_count));

  // Un acceso del bus dura un ciclo, como lo entrega mmio_mux.
  task bus_read;
    input [7:0] addr;
    begin
      @(negedge clk);
      address = addr; select = 1; write = 0;
      #1 leido = read_data;   // combinacional, valida en el mismo ciclo
      @(negedge clk);
      select = 0;
    end
  endtask

  task bus_write;
    input [7:0] addr;
    input [31:0] value;
    begin
      @(negedge clk);
      address = addr; select = 1; write = 1; write_data = value;
      @(negedge clk);
      select = 0; write = 0;
    end
  endtask

  task push_host;
    input [7:0] value;
    begin
      @(negedge clk);
      host_push = 1; host_push_data = value;
      @(negedge clk);
      host_push = 0;
    end
  endtask

  task pop_host;
    begin
      @(negedge clk);
      host_pop = 1;
      @(negedge clk);
      host_pop = 0;
    end
  endtask

  task check;
    input [31:0] got;
    input [31:0] want;
    input [255:0] what;
    begin
      if (got !== want) begin
        $display("FALLO %0s: %08x, esperado %08x", what, got, want);
        errors = errors + 1;
      end
    end
  endtask

  initial begin
    $dumpvars(0, serial_port_tb);
    repeat (2) @(negedge clk);
    reset = 0;
    @(negedge clk);

    // -- 1. Al arrancar: nada que leer, todo el hueco disponible ------------
    bus_read(REG_STATUS);
    check(leido[7:0], 8'd0, "rx_count inicial");
    check(leido[15:8], DEPTH, "tx_free inicial");
    check({31'd0, leido[16]}, 32'd0, "overrun inicial");
    check({24'd0, host_rx_free}, DEPTH, "host_rx_free inicial");

    // Leer DATA con la cola vacia da cero y no cuelga.
    bus_read(REG_DATA);
    check(leido, 32'd0, "DATA con RX vacia");

    // -- 2. Camino PC -> CPU -----------------------------------------------
    push_host(8'h41);
    push_host(8'h42);
    bus_read(REG_STATUS);
    check(leido[7:0], 8'd2, "rx_count tras dos push");
    check({24'd0, host_rx_free}, DEPTH - 2, "host_rx_free tras dos push");

    // PEEK no saca: dos lecturas seguidas dan lo mismo.
    bus_read(REG_PEEK);
    check(leido, 32'h41, "PEEK");
    bus_read(REG_PEEK);
    check(leido, 32'h41, "PEEK otra vez, sin sacar");
    bus_read(REG_STATUS);
    check(leido[7:0], 8'd2, "PEEK no cambio rx_count");

    // DATA si saca, y en orden.
    bus_read(REG_DATA);
    check(leido, 32'h41, "primer DATA");
    bus_read(REG_DATA);
    check(leido, 32'h42, "segundo DATA");
    bus_read(REG_STATUS);
    check(leido[7:0], 8'd0, "rx_count tras vaciar");

    // -- 3. Camino CPU -> PC -----------------------------------------------
    bus_write(REG_DATA, 32'h0000_0037);
    bus_write(REG_DATA, 32'hFFFF_FF38);   // solo el byte bajo cuenta
    bus_read(REG_STATUS);
    check(leido[15:8], DEPTH - 2, "tx_free tras dos escrituras");
    check({24'd0, host_tx_count}, 32'd2, "host_tx_count");
    check({24'd0, host_tx_data}, 32'h37, "cabeza de TX");
    pop_host();
    check({24'd0, host_tx_data}, 32'h38, "cabeza de TX tras sacar");
    pop_host();
    bus_read(REG_STATUS);
    check(leido[15:8], DEPTH, "tx_free tras vaciar");

    // -- 4. Cola llena y vuelta del puntero circular ------------------------
    // Se llena, se vacia y se vuelve a llenar: asi los punteros dan la vuelta
    // y se ve si el modulo confunde llena con vacia.
    for (i = 0; i < DEPTH; i = i + 1) push_host(i[7:0]);
    bus_read(REG_STATUS);
    check(leido[7:0], DEPTH, "rx_count con la cola llena");
    check({24'd0, host_rx_free}, 32'd0, "sin huecos con la cola llena");
    check({31'd0, leido[16]}, 32'd0, "llenar exacto no es overrun");

    // Un byte mas con la cola llena: se descarta y se marca.
    push_host(8'hFF);
    bus_read(REG_STATUS);
    check(leido[7:0], DEPTH, "la cola llena no crece");
    check({31'd0, leido[16]}, 32'd1, "overrun marcado");

    // Se vacia entera y sale en orden.
    for (i = 0; i < DEPTH; i = i + 1) begin
      bus_read(REG_DATA);
      if (leido !== i) begin
        $display("FALLO: byte %0d salio %02x", i, leido[7:0]);
        errors = errors + 1;
        i = DEPTH;  // no llenar la salida de fallos iguales
      end
    end
    bus_read(REG_STATUS);
    check(leido[7:0], 8'd0, "vacia tras sacarlo todo");

    // El overrun es pegajoso hasta que se borra a mano.
    bus_read(REG_STATUS);
    check({31'd0, leido[16]}, 32'd1, "el overrun sigue ahi");
    bus_write(REG_STATUS, 32'h0001_0000);
    bus_read(REG_STATUS);
    check({31'd0, leido[16]}, 32'd0, "overrun borrado");

    // Y despues de la vuelta, la cola sigue funcionando.
    push_host(8'h5A);
    bus_read(REG_DATA);
    check(leido, 32'h5A, "tras la vuelta del puntero");

    // -- 5. Meter y sacar el mismo ciclo ------------------------------------
    // Es lo normal en marcha: el PC empuja mientras la CPU lee. La cuenta no
    // debe cambiar, y ni el byte que entra ni el que sale se pueden perder.
    push_host(8'h11);
    push_host(8'h22);
    @(negedge clk);
    address = REG_DATA; select = 1; write = 0;
    host_push = 1; host_push_data = 8'h33;
    #1 leido = read_data;
    @(negedge clk);
    select = 0; host_push = 0;
    check(leido, 32'h11, "el byte que salia en un ciclo con push");
    bus_read(REG_STATUS);
    check(leido[7:0], 8'd2, "la cuenta no cambia si entra y sale a la vez");
    bus_read(REG_DATA);
    check(leido, 32'h22, "el orden se conserva");
    bus_read(REG_DATA);
    check(leido, 32'h33, "el byte empujado en el mismo ciclo no se perdio");

    // -- 6. Escribir en TX con la cola llena no rompe nada ------------------
    for (i = 0; i < DEPTH; i = i + 1) bus_write(REG_DATA, i[7:0]);
    bus_read(REG_STATUS);
    check(leido[15:8], 8'd0, "TX llena");
    bus_write(REG_DATA, 32'h99);
    bus_read(REG_STATUS);
    check(leido[15:8], 8'd0, "TX llena no crece");
    check({24'd0, host_tx_data}, 32'd0, "la cabeza de TX sigue siendo la buena");

    if (errors != 0) $fatal(1, "%0d comprobaciones fallaron", errors);
    $display("PASS: serial_port");
    $finish;
  end

  initial begin
    #500_000;
    $fatal(1, "timeout");
  end
endmodule

`default_nettype wire
