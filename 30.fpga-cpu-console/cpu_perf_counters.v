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
//   ranura 0  CYCLES       ciclos CON LA CPU EN MARCHA
//   ranura 1  RETIRED      instrucciones retiradas
//   ranura 2  IMEM_HITS    busquedas servidas por el bufer de instrucciones
//   ranura 3  IMEM_MISSES  busquedas que tuvieron que ir a la SDRAM
//   ranura 4  MEM_TX       transacciones que la CPU pide al fabric
//   ranura 5  STALL_MEM    ciclos esperando a memoria (busqueda o datos)
//   ranura 6  STALL_FETCH  de esos, los de la busqueda de instruccion
//   ranura 7  STALL_MMIO   ciclos esperando a un dispositivo MMIO
//
// Con ellos, CYCLES se reparte en calculo, memoria y MMIO sin instrumentar
// nada mas: CYCLES = calculo + STALL_MEM + STALL_MMIO, y de STALL_MEM se
// separan la busqueda (STALL_FETCH) y los datos (STALL_MEM - STALL_FETCH).
// Las definiciones exactas estan en mmio.md §13.2.
//
// POR QUE EL CONTROL VA DETRAS DE LAS 64 RANURAS y no pegado al ultimo
// contador: con el control pegado, el primer contador que se anade obliga a
// moverlo, y mover un registro es renumerar -- lo unico que §1.5 prohibe. El
// hueco no cuesta nada: reservar direcciones no implementa memoria.
//
// POR QUE ESTAN AQUI Y NO EN top.v. Eran dos registros sueltos que solo leia
// el HOST, con los comandos de monitor 0x36 y 0x37 (que ya no existen): para
// saber cuanto tardo un bucle habia que PARAR la CPU y preguntar por serie. En
// MMIO el programa se mide A SI MISMO, en marcha.
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
// LOS EVENTOS SE REGISTRAN ANTES DE CONTAR. Salen de los caminos mas cargados
// del sistema --el acierto del bufer de instrucciones y el `ready` del fabric
// eran los que mandaban en la 30-- y un contador de 32 bits colgado de ellos
// habria sido un camino critico nuevo. Con un registro de por medio cada uno
// suma UNA carga, y todo se cuenta un ciclo tarde, que en una medida de
// millones de ciclos no se nota. `MEM_TX` cuenta el FLANCO de subida de
// `valid` de cada puerto y no el handshake, por la misma razon: `ready` es la
// red crítica. Cada peticion termina siendo aceptada, asi que sale lo mismo.
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
    input wire restart,

    // Esperas de la CPU: `valid` alto y `ready` bajo. Un acceso a datos es
    // MMIO si su direccion lo es, y solo entonces cuenta como STALL_MMIO.
    input wire imem_valid,
    input wire imem_ready,
    input wire dmem_valid,
    input wire dmem_ready,
    input wire dmem_is_mmio,

    // Pulsos del bufer de instrucciones, uno por busqueda cacheable.
    input wire imem_hit,
    input wire imem_miss,

    // `valid` de los dos puertos de la CPU en el fabric (datos e instrucciones).
    input wire mem_req0,
    input wire mem_req1
);
  // Cuantas ranuras del array existen de verdad. El resto dan error.
  localparam integer NUM_COUNTERS = 8;

  localparam [5:0] SLOT_CYCLES      = 6'd0;
  localparam [5:0] SLOT_RETIRED     = 6'd1;
  localparam [5:0] SLOT_IMEM_HITS   = 6'd2;
  localparam [5:0] SLOT_IMEM_MISSES = 6'd3;
  localparam [5:0] SLOT_MEM_TX      = 6'd4;
  localparam [5:0] SLOT_STALL_MEM   = 6'd5;
  localparam [5:0] SLOT_STALL_FETCH = 6'd6;
  localparam [5:0] SLOT_STALL_MMIO  = 6'd7;

  // El mismo numero, en cinco bits, para indexar OVF0. La ranura son SEIS
  // bits porque §12.6 admite hasta 64 contadores, pero las banderas van en
  // DOS registros de 32: las ranuras 0..31 en OVF0 y las 32..63 en OVF1.
  // Indexar OVF0 con seis bits es un truncamiento --el que verilator avisa
  // como WIDTHTRUNC-- y ademas seria un alias: la ranura 32 caeria sobre la
  // 0. Con ocho contadores no puede pasar todavia, pero el dia que haya una
  // ranura >= 32 hay que escribir en OVF1, no en este bit.
  localparam [4:0] BIT_CYCLES      = SLOT_CYCLES[4:0];
  localparam [4:0] BIT_RETIRED     = SLOT_RETIRED[4:0];
  localparam [4:0] BIT_IMEM_HITS   = SLOT_IMEM_HITS[4:0];
  localparam [4:0] BIT_IMEM_MISSES = SLOT_IMEM_MISSES[4:0];
  localparam [4:0] BIT_MEM_TX      = SLOT_MEM_TX[4:0];
  localparam [4:0] BIT_STALL_MEM   = SLOT_STALL_MEM[4:0];
  localparam [4:0] BIT_STALL_FETCH = SLOT_STALL_FETCH[4:0];
  localparam [4:0] BIT_STALL_MMIO  = SLOT_STALL_MMIO[4:0];

  localparam [15:0] OFF_CTRL = 16'h0100;
  localparam [15:0] OFF_OVF0 = 16'h0104;
  localparam [15:0] OFF_OVF1 = 16'h0108;

  localparam integer CTRL_ENABLE = 0;
  localparam integer CTRL_RESET  = 1;

  reg [31:0] cycles;
  reg [31:0] retired_count;
  reg [31:0] imem_hits;
  reg [31:0] imem_misses;
  reg [31:0] mem_tx;
  reg [31:0] stall_mem;
  reg [31:0] stall_fetch;
  reg [31:0] stall_mmio;
  // Una bandera por contador, en el bit `n mod 32` de PERF_OVF[n div 32].
  // Con ocho contadores sobran 24 bits de OVF0 y OVF1 entero, y se declaran
  // igual: anadir OVF1 despues obligaria a decidir donde con el control ya
  // congelado delante (§12.6).
  reg [31:0] ovf0;
  reg        enable;

  // ---- Eventos, registrados antes de contar --------------------------------
  wire wait_access = dmem_valid && !dmem_ready;
  // Flancos de subida de `valid` de los dos puertos: una peticion por flanco.
  reg req0_prev, req1_prev;
  wire tx0 = mem_req0 && !req0_prev;
  wire tx1 = mem_req1 && !req1_prev;

  reg wait_fetch_q, wait_data_q, wait_mmio_q, hit_q, miss_q;
  // Cero, una o dos peticiones nuevas en el mismo ciclo.
  reg [1:0] tx_q;

  always @(posedge clk) begin
    if (reset || restart) begin
      req0_prev <= 1'b0;
      req1_prev <= 1'b0;
      wait_fetch_q <= 1'b0;
      wait_data_q <= 1'b0;
      wait_mmio_q <= 1'b0;
      hit_q <= 1'b0;
      miss_q <= 1'b0;
      tx_q <= 2'd0;
    end else begin
      req0_prev <= mem_req0;
      req1_prev <= mem_req1;
      wait_fetch_q <= imem_valid && !imem_ready;
      wait_data_q <= wait_access && !dmem_is_mmio;
      wait_mmio_q <= wait_access && dmem_is_mmio;
      hit_q <= imem_hit;
      miss_q <= imem_miss;
      tx_q <= {1'b0, tx0} + {1'b0, tx1};
    end
  end

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

  // MEM_TX suma hasta dos por ciclo, asi que su desbordamiento sale del
  // acarreo de una suma de 33 bits y no de mirar si estaba a tope.
  wire [32:0] mem_tx_next = {1'b0, mem_tx} + {31'd0, tx_q};

  wire stall_any = wait_fetch_q || wait_data_q;

  always @(posedge clk) begin
    if (reset || restart) begin
      cycles <= 32'd0;
      retired_count <= 32'd0;
      imem_hits <= 32'd0;
      imem_misses <= 32'd0;
      mem_tx <= 32'd0;
      stall_mem <= 32'd0;
      stall_fetch <= 32'd0;
      stall_mmio <= 32'd0;
      ovf0 <= 32'd0;
      // Tras reset los contadores CUENTAN. Arrancar congelado obligaria a
      // todo programa existente a escribir PERF_CTRL antes de medir.
      enable <= 1'b1;
    end else begin
      if (pide_reset) begin
        cycles <= 32'd0;
        retired_count <= 32'd0;
        imem_hits <= 32'd0;
        imem_misses <= 32'd0;
        mem_tx <= 32'd0;
        stall_mem <= 32'd0;
        stall_fetch <= 32'd0;
        stall_mmio <= 32'd0;
        ovf0 <= 32'd0;
      end else begin
        if (contando) begin
          cycles <= cycles + 1'b1;
          // La bandera se pone en la transicion 0xFFFFFFFF -> 0x00000000.
          if (&cycles) ovf0[BIT_CYCLES] <= 1'b1;

          // Como CYCLES, solo con el nucleo corriendo (§12.3): el volcado del
          // buffer de escrituras que sigue a un `halt` no es del programa.
          if (hit_q) begin
            imem_hits <= imem_hits + 1'b1;
            if (&imem_hits) ovf0[BIT_IMEM_HITS] <= 1'b1;
          end
          if (miss_q) begin
            imem_misses <= imem_misses + 1'b1;
            if (&imem_misses) ovf0[BIT_IMEM_MISSES] <= 1'b1;
          end
          if (tx_q != 2'd0) begin
            mem_tx <= mem_tx_next[31:0];
            if (mem_tx_next[32]) ovf0[BIT_MEM_TX] <= 1'b1;
          end
          if (stall_any) begin
            stall_mem <= stall_mem + 1'b1;
            if (&stall_mem) ovf0[BIT_STALL_MEM] <= 1'b1;
          end
          if (wait_fetch_q) begin
            stall_fetch <= stall_fetch + 1'b1;
            if (&stall_fetch) ovf0[BIT_STALL_FETCH] <= 1'b1;
          end
          if (wait_mmio_q) begin
            stall_mmio <= stall_mmio + 1'b1;
            if (&stall_mmio) ovf0[BIT_STALL_MMIO] <= 1'b1;
          end
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
        SLOT_CYCLES:      read_data = cycles;
        SLOT_RETIRED:     read_data = retired_count;
        SLOT_IMEM_HITS:   read_data = imem_hits;
        SLOT_IMEM_MISSES: read_data = imem_misses;
        SLOT_MEM_TX:      read_data = mem_tx;
        SLOT_STALL_MEM:   read_data = stall_mem;
        SLOT_STALL_FETCH: read_data = stall_fetch;
        SLOT_STALL_MMIO:  read_data = stall_mmio;
        default:          read_data = 32'd0;   // ranura sin contador: da error
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
