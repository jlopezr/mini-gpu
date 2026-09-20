`default_nettype none
// Contadores de rendimiento de la MiniCPU. Bloque CPU PERFORMANCE de MMIO v2,
// en 0x81010000. Contrato: 1.isa/mmio.md §12 y §13.2.
//
// DISPOSICION (§12.6). El array empieza en el offset 0 y el control va DETRAS
// de su extension maxima, nunca intercalado:
//
//   +0x000 .. +0x0FC   array de hasta 64 contadores; el contador n en +4n
//                      las ranuras sin contador dan error
//   +0x100             PERF_CTRL   RW
//   +0x104             PERF_OVF0   W1C   contadores  0-31
//   +0x108             PERF_OVF1   W1C   contadores 32-63
//
//   ranura 0  CYCLES      ciclos CON LA CPU EN MARCHA
//   ranura 1  RETIRED     instrucciones retiradas
//
// POR QUE EL CONTROL VA DETRAS DE LAS 64 RANURAS y no pegado al ultimo
// contador: con el control pegado, el primer contador que se anade obliga a
// moverlo, y mover un registro es renumerar -- lo unico que §1.5 prohibe. El
// hueco no cuesta nada: reservar direcciones no implementa memoria.
//
// POR QUE ESTAN AQUI Y NO EN top.v. Eran dos registros sueltos que solo leia
// el HOST, con los comandos de monitor 0x36 y 0x37: para saber cuanto tardo un
// bucle habia que PARAR la CPU y preguntar por serie. En MMIO el programa se
// mide A SI MISMO, en marcha.
//
// DAN LA VUELTA, no saturan (§12.2). A 80 MHz 2^32 ciclos son 53 segundos: un
// programa de un minuto saturaria y dejaria de medir NADA, mientras que dando
// la vuelta las DIFERENCIAS siguen siendo correctas, que es como se usan --la
// aritmetica modular de 32 bits lo arregla sola--. Lo que se anade en v2 es la
// bandera: asi la resta sigue valiendo Y ademas se sabe si es de fiar.
//
// SE REINICIAN EN CADA `run`, a diferencia de la GPU, que solo lo hace con el
// reset del nucleo. Se conserva la semantica de la CPU a proposito: asi
// `run`/`halt`/`run` da tres medidas independientes en vez de una suma que
// crece sin sentido.
//
// AVISO DE MEDIDA. Leer CYCLES con un LOAD cuesta ciclos y retira una
// instruccion, y en la 21 ademas drena el bufer de escrituras: el programa
// perturba su propia medida. Se mide por deltas y se asume el sesgo.
module cpu_perf_counters (
    input wire clk,
    input wire reset,

    // Ahora SI hace falta `select`: PERF_CTRL y PERF_OVF se escriben. Cuando
    // el bloque era de solo lectura no habia escritura que filtrar.
    input wire select,
    input wire write,
    input wire [3:0] write_mask,
    // Offset dentro del bloque. Son DIECISEIS bits, no ocho: el control vive
    // en +0x100, o sea fuera de lo que alcanzan ocho.
    input wire [15:0] address,
    input wire [31:0] write_data,
    output reg [31:0] read_data,

    // Alto mientras la CPU NO esta parada. Incluye lo que espera a memoria,
    // que es justo lo que interesa medir: la diferencia entre 9 ciclos por
    // instruccion ejecutando desde EBR y los 35 de la 21 es toda espera.
    input wire running,
    input wire retired,
    // Un pulso al arrancar: cada `run` empieza una medida nueva.
    input wire restart
);
  // Cuantas ranuras del array existen de verdad. El resto dan error.
  localparam integer NUM_COUNTERS = 2;

  localparam [5:0] SLOT_CYCLES  = 6'd0;
  localparam [5:0] SLOT_RETIRED = 6'd1;

  // El mismo numero, en cinco bits, para indexar OVF0. La ranura son SEIS
  // bits porque §12.6 admite hasta 64 contadores, pero las banderas van en
  // DOS registros de 32: las ranuras 0..31 en OVF0 y las 32..63 en OVF1.
  // Indexar OVF0 con seis bits es un truncamiento --el que verilator avisa
  // como WIDTHTRUNC-- y ademas seria un alias: la ranura 32 caeria sobre la
  // 0. Con solo dos contadores no puede pasar todavia, pero el dia que haya
  // una ranura >= 32 hay que escribir en OVF1, no en este bit.
  localparam [4:0] BIT_CYCLES  = SLOT_CYCLES[4:0];
  localparam [4:0] BIT_RETIRED = SLOT_RETIRED[4:0];

  localparam [15:0] OFF_CTRL = 16'h0100;
  localparam [15:0] OFF_OVF0 = 16'h0104;
  localparam [15:0] OFF_OVF1 = 16'h0108;

  localparam integer CTRL_ENABLE = 0;
  localparam integer CTRL_RESET  = 1;

  reg [31:0] cycles;
  reg [31:0] retired_count;
  // Una bandera por contador, en el bit `n mod 32` de PERF_OVF[n div 32].
  // Con dos contadores sobran 30 bits de OVF0 y OVF1 entero, y se declaran
  // igual: anadir OVF1 despues obligaria a decidir donde con el control ya
  // congelado delante (§12.6).
  reg [31:0] ovf0;
  reg        enable;

  wire es_array = (address < 16'h0100);
  wire [5:0] slot = address[7:2];

  // §12.5: un solo bit para parar y arrancar TODOS los contadores del bloque
  // a la vez. Sin el, leer seis contadores son seis instantes distintos con
  // el programa corriendo entre medias, y el CPI que sale es de una mezcla.
  wire contando = running && enable;

  wire bus_write = select && write;
  wire escribe_ctrl = bus_write && (address == OFF_CTRL) && write_mask[0];
  wire escribe_ovf0 = bus_write && (address == OFF_OVF0);
  // `RESET_COUNTERS` limpia tambien PERF_OVF: si no lo hiciera, resetear para
  // medir limpio dejaria un aviso de la medida anterior, que es el falso
  // positivo que la bandera existe para evitar (§12.4).
  wire pide_reset = escribe_ctrl && write_data[CTRL_RESET];

  always @(posedge clk) begin
    if (reset || restart) begin
      cycles <= 32'd0;
      retired_count <= 32'd0;
      ovf0 <= 32'd0;
      // Tras reset los contadores CUENTAN. Arrancar congelado obligaria a
      // todo programa existente a escribir PERF_CTRL antes de medir.
      enable <= 1'b1;
    end else begin
      if (pide_reset) begin
        cycles <= 32'd0;
        retired_count <= 32'd0;
        ovf0 <= 32'd0;
      end else begin
        if (contando) begin
          cycles <= cycles + 1'b1;
          // La bandera se pone en la transicion 0xFFFFFFFF -> 0x00000000.
          if (&cycles) ovf0[BIT_CYCLES] <= 1'b1;
        end
        // RETIRED no se condiciona a `running`, y esa es la diferencia entre
        // contar bien y contar una de menos SIEMPRE: el HALT retira en el
        // mismo ciclo en que la CPU se para, asi que con el filtro puesto se
        // perdia justo esa. Lo delato el contraste con el simulador en
        // `--measure`: 11 contra 12 en todos los programas a la vez, que es
        // un off-by-one de definicion y no dos CPUs distintas.
        //
        // Si lleva `enable` porque congelar tiene que congelar el bloque
        // ENTERO: leer CYCLES congelado y RETIRED corriendo daria un CPI de
        // dos instantes distintos, que es justo lo que el bit evita.
        if (retired && enable) begin
          retired_count <= retired_count + 1'b1;
          if (&retired_count) ovf0[BIT_RETIRED] <= 1'b1;
        end
        // W1C: escribir un uno limpia ese bit. Se aplica DESPUES de las
        // subidas de arriba, asi que un desbordamiento en el mismo ciclo que
        // el borrado no se pierde.
        if (escribe_ovf0) begin
          if (write_mask[0]) ovf0[7:0]   <= ovf0[7:0]   & ~write_data[7:0];
          if (write_mask[1]) ovf0[15:8]  <= ovf0[15:8]  & ~write_data[15:8];
          if (write_mask[2]) ovf0[23:16] <= ovf0[23:16] & ~write_data[23:16];
          if (write_mask[3]) ovf0[31:24] <= ovf0[31:24] & ~write_data[31:24];
        end
      end
      if (escribe_ctrl) enable <= write_data[CTRL_ENABLE];
    end
  end

  always @* begin
    if (es_array) begin
      case (slot)
        SLOT_CYCLES:  read_data = cycles;
        SLOT_RETIRED: read_data = retired_count;
        default:      read_data = 32'd0;   // ranura sin contador: da error
      endcase
    end else begin
      case (address)
        OFF_CTRL: read_data = {30'd0, 1'b0, enable};
        OFF_OVF0: read_data = ovf0;
        // PERF_OVF1 lee cero y existe desde ahora aunque no tenga
        // contadores detras (§12.6).
        OFF_OVF1: read_data = 32'd0;
        default:  read_data = 32'd0;
      endcase
    end
  end

  // Solo para que el linter no avise de un parametro sin usar: NUM_COUNTERS
  // documenta cuantas ranuras existen y lo usa el decodificador.
  /* verilator lint_off UNUSEDPARAM */
  localparam integer NUM_COUNTERS_UNUSED = NUM_COUNTERS;
  /* verilator lint_on UNUSEDPARAM */
endmodule

`default_nettype wire
