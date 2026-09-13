`timescale 1ns/1ps
`default_nettype none

/*
 * Banco del bufer de instrucciones.
 *
 * Lo que hay que demostrar no es solo que devuelve la instruccion correcta: un
 * bufer que fallara siempre tambien la devolveria bien, y no serviria de nada.
 * Asi que cada caso comprueba ADEMAS cuantos aciertos y cuantos fallos hubo,
 * con numeros exactos.
 *
 * Y el dimensionado tiene su propio control negativo. Se instancian dos
 * bufers, de cuatro lineas y de dos, alimentados con la misma secuencia. El
 * caso del bucle de 48 bytes existe para que el de dos lineas FALLE: sin ese
 * caso, cuatro lineas serian una eleccion sin justificar.
 */

// ---------------------------------------------------------------------------
// Memoria falsa con la latencia del camino real. No guarda nada: devuelve la
// propia direccion mas un sesgo, asi que cada palabra es identificable y
// cambiar el sesgo equivale a que el monitor reescriba el programa.
// ---------------------------------------------------------------------------
module fake_imem #(
    parameter integer LATENCY = 20
) (
    input  wire        clk,
    input  wire        reset,
    input  wire [31:0] bias,
    input  wire        req_valid,
    input  wire [31:0] req_addr,
    output reg  [127:0] read_data,
    output reg         ready,
    output reg  [31:0] transactions
);
  reg [31:0] count;
  reg busy;
  reg [31:0] held;

  initial begin
    read_data = 128'd0;
    ready = 1'b0;
    transactions = 32'd0;
    count = 0;
    busy = 1'b0;
    held = 32'h0000_0000;
  end

  always @(posedge clk) begin
    ready <= 1'b0;
    if (reset) begin
      busy <= 1'b0;
      count <= 0;
      transactions <= 32'd0;
    end else if (!busy) begin
      if (req_valid && !ready) begin
        held <= req_addr;
        busy <= 1'b1;
        count <= 0;
      end
    end else if (count >= LATENCY) begin
      // Una rafaga son cuatro palabras de 32 bits consecutivas, y cada una
      // vale su propia direccion mas el sesgo. Asi cada instruccion dice de
      // donde vino y un desplazamiento dentro de la linea se lee en el numero.
      read_data <= {held + bias + 32'd12, held + bias + 32'd8,
                    held + bias + 32'd4, held + bias};
      ready <= 1'b1;
      busy <= 1'b0;
      transactions <= transactions + 1'b1;
    end else begin
      count <= count + 1;
    end
  end
endmodule

// ---------------------------------------------------------------------------
module instruction_buffer_tb;
  reg clk = 0;
  reg reset = 1;
  reg init_done = 1;
  reg cpu_halted = 0;
  reg [31:0] bias = 32'h0000_0000;

  always #5 clk = ~clk;

  // Lado CPU, uno por bufer: cada uno baja su `valid` cuando le responden.
  reg v4 = 0, v2 = 0;
  reg [31:0] addr4 = 0, addr2 = 0;
  reg [31:0] data4 = 0, data2 = 0;
  wire [31:0] rdata4, rdata2;
  wire ready4, ready2;

  wire mv4, mv2;
  wire [31:0] maddr4, maddr2;
  wire [127:0] mdata4, mdata2;
  wire mready4, mready2;
  wire [31:0] hits4, misses4, hits2, misses2;
  wire [31:0] trans4, trans2;

  instruction_buffer #(.LINES(4), .INDEX_BITS(2)) buf4 (
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(cpu_halted),
      .cpu_imem_valid(v4), .cpu_imem_address(addr4),
      .cpu_imem_read_data(rdata4), .cpu_imem_ready(ready4),
      .req_valid(mv4), .req_ready(mv4), .req_write(), .req_addr(maddr4),
      .req_wdata(), .req_wmask(),
      .rsp_valid(mready4), .rsp_ready(), .rsp_rdata(mdata4),
      .rsp_error(1'b0),
      .hit_count(hits4), .miss_count(misses4));

  instruction_buffer #(.LINES(2), .INDEX_BITS(1)) buf2 (
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(cpu_halted),
      .cpu_imem_valid(v2), .cpu_imem_address(addr2),
      .cpu_imem_read_data(rdata2), .cpu_imem_ready(ready2),
      .req_valid(mv2), .req_ready(mv2), .req_write(), .req_addr(maddr2),
      .req_wdata(), .req_wmask(),
      .rsp_valid(mready2), .rsp_ready(), .rsp_rdata(mdata2),
      .rsp_error(1'b0),
      .hit_count(hits2), .miss_count(misses2));

  fake_imem mem4 (.clk(clk), .reset(reset), .bias(bias), .req_valid(mv4),
      .req_addr(maddr4), .read_data(mdata4), .ready(mready4),
      .transactions(trans4));
  fake_imem mem2 (.clk(clk), .reset(reset), .bias(bias), .req_valid(mv2),
      .req_addr(maddr2), .read_data(mdata2), .ready(mready2),
      .transactions(trans2));

  integer errors = 0;
  integer guard;
  integer i, pass;
  reg [31:0] base;
  reg [31:0] h4, m4, h2, m2;

  task check;
    input [255:0] etiqueta;
    input [31:0] got;
    input [31:0] want;
    begin
      if (got !== want) begin
        $display("FALLO %0s: leido %08x, esperado %08x", etiqueta, got, want);
        errors = errors + 1;
      end
    end
  endtask

  task check_count;
    input [255:0] etiqueta;
    input integer got;
    input integer want;
    begin
      if (got != want) begin
        $display("FALLO %0s: %0d, esperado %0d", etiqueta, got, want);
        errors = errors + 1;
      end
    end
  endtask

  // Busca la misma direccion en los dos bufers a la vez. Cada uno baja su
  // `valid` en cuanto le responden, como hace la CPU real: mantenerlo alto un
  // ciclo de mas haria que la misma busqueda se sirviera dos veces.
  task fetch;
    input [31:0] a;
    begin
      @(negedge clk);
      addr4 = a; addr2 = a; v4 = 1'b1; v2 = 1'b1;
      guard = 0;
      while ((v4 || v2) && guard < 2000) begin
        @(negedge clk);
        guard = guard + 1;
        if (v4 && ready4) begin data4 = rdata4; v4 = 1'b0; end
        if (v2 && ready2) begin data2 = rdata2; v2 = 1'b0; end
      end
      if (v4 || v2) begin
        $display("FALLO: busqueda de %08x sin respuesta (v4=%b v2=%b)",
                 a, v4, v2);
        errors = errors + 1;
        v4 = 1'b0; v2 = 1'b0;
      end
    end
  endtask

  // Recorre un bucle de `bytes` bytes desde `from`, `passes` veces.
  task run_loop;
    input [31:0] from;
    input integer bytes;
    input integer passes;
    begin
      for (pass = 0; pass < passes; pass = pass + 1)
        for (i = 0; i < bytes; i = i + 4) begin
          fetch(from + i);
          check("dato de 4 lineas", data4, from + i + bias);
          check("dato de 2 lineas", data2, from + i + bias);
        end
    end
  endtask

  task snapshot;
    begin
      h4 = hits4; m4 = misses4; h2 = hits2; m2 = misses2;
    end
  endtask

  initial begin
    repeat (3) @(negedge clk);
    reset = 0;
    @(negedge clk);

    // ---------------------------------------------------------------------
    // 1. Bucle de 16 bytes alineado: una linea, y a partir de la segunda
    //    vuelta no se vuelve a la memoria.
    // ---------------------------------------------------------------------
    snapshot;
    run_loop(32'h0000_0000, 16, 5);
    check_count("fallos de 4 lineas, bucle alineado", misses4 - m4, 1);
    check_count("aciertos de 4 lineas, bucle alineado", hits4 - h4, 19);
    check_count("fallos de 2 lineas, bucle alineado", misses2 - m2, 1);
    // Y aqui esta el punto de las rafagas: un fallo trae la linea entera en
    // UNA peticion. Antes eran cuatro transacciones de 32 bits, y en la 16
    // ocho accesos de 16 bits.
    check_count("transacciones a memoria", trans4, 1);

    // ---------------------------------------------------------------------
    // 2. Bucle de 16 bytes a caballo entre dos lineas. Es el punto debil que
    //    el plan senala: con una sola linea se fallaria en cada iteracion.
    // ---------------------------------------------------------------------
    snapshot;
    run_loop(32'h0000_0108, 16, 5);
    check_count("fallos de 4 lineas, bucle a caballo", misses4 - m4, 2);
    check_count("aciertos de 4 lineas, bucle a caballo", hits4 - h4, 18);
    check_count("fallos de 2 lineas, bucle a caballo", misses2 - m2, 2);

    // ---------------------------------------------------------------------
    // 3. Bucle de 48 bytes: tres lineas. Aqui es donde el bufer de dos
    //    lineas tiene que fallar, porque las lineas 0 y 2 comparten indice y
    //    se echan la una a la otra en cada vuelta. Sin este caso, elegir
    //    cuatro lineas seria una decision sin respaldo.
    // ---------------------------------------------------------------------
    snapshot;
    run_loop(32'h0000_0200, 48, 5);
    check_count("fallos de 4 lineas, bucle de 48 bytes", misses4 - m4, 3);
    check_count("aciertos de 4 lineas, bucle de 48 bytes", hits4 - h4, 57);
    // El de dos lineas falla mas de una vez por vuelta, no tres veces en total.
    if (misses2 - m2 <= 3) begin
      $display("FALLO: el bufer de dos lineas deberia degradarse con 48 bytes, y solo fallo %0d veces", misses2 - m2);
      errors = errors + 1;
    end
    $display("  bucle de 48 bytes: 4 lineas %0d fallos, 2 lineas %0d fallos",
             misses4 - m4, misses2 - m2);

    // ---------------------------------------------------------------------
    // 4. Vaciado al parar la CPU. El monitor reescribe el programa mientras
    //    esta parada, asi que lo guardado tiene que desaparecer. Se simula
    //    cambiando el sesgo de la memoria: si el bufer no se vaciara, seguiria
    //    devolviendo el programa viejo.
    // ---------------------------------------------------------------------
    // El bucle de 48 bytes acaba de desalojar la linea 0, asi que hay que
    // volver a traerla antes de poder comprobar que se queda.
    fetch(32'h0000_0000);
    snapshot;
    fetch(32'h0000_0000);
    check("guardado antes de parar", data4, 32'h0000_0000);
    check_count("acierto antes de parar", hits4 - h4, 1);

    cpu_halted = 1;
    bias = 32'h1000_0000;          // el monitor reescribe el programa
    repeat (4) @(negedge clk);
    cpu_halted = 0;
    @(negedge clk);

    snapshot;
    fetch(32'h0000_0000);
    check("programa nuevo tras arrancar", data4, 32'h1000_0000);
    check("programa nuevo tras arrancar, 2 lineas", data2, 32'h1000_0000);
    check_count("fallo forzado por el vaciado", misses4 - m4, 1);
    check_count("aciertos tras el vaciado", hits4 - h4, 0);
    bias = 32'h0000_0000;

    // ---------------------------------------------------------------------
    // 5. Fuera de la SDRAM: el adaptador responde con un opcode invalido y eso
    //    NO se guarda. Guardarlo lo haria permanente.
    // ---------------------------------------------------------------------
    snapshot;
    fetch(32'h8000_0000);
    check("respuesta fuera de rango", data4, 32'hf800_0000);
    check_count("una respuesta fuera de rango no se guarda", hits4 - h4, 0);
    check_count("y tampoco cuenta como fallo de linea", misses4 - m4, 0);
    snapshot;
    fetch(32'h8000_0000);
    check_count("la segunda tampoco acierta", hits4 - h4, 0);

    // ---------------------------------------------------------------------
    // 6. Antes de init_done tampoco se guarda nada.
    // ---------------------------------------------------------------------
    init_done = 0;
    snapshot;
    fetch(32'h0000_0400);
    check_count("sin init_done no se guarda", misses4 - m4, 0);
    init_done = 1;
    snapshot;
    fetch(32'h0000_0400);
    check_count("con init_done ya se guarda", misses4 - m4, 1);

    if (errors != 0) $fatal(1, "%0d comprobaciones fallaron", errors);
    $display("PASS: instruction_buffer");
    $finish;
  end
endmodule

`default_nettype wire
