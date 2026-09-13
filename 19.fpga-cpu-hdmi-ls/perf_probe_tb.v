`timescale 1ns/1ps
`default_nettype none

/*
 * Paso 0 del plan de BL8: medir antes de escribir RTL.
 *
 * La medida en placa dice ~258 ciclos por palabra de framebuffer en el bucle
 * interior de swap_demo_fast, o sea ~26 ciclos por acceso fisico de 16 bits.
 * La pregunta que decide si la rafaga merece la pena es en que se van esos
 * ciclos:
 *
 *   - los que la SDRAM pasa ejecutando comandos (ACTIVE, tRCD, CAS, tWR) son
 *     los unicos que BL8 ataca: la rafaga los reparte entre ocho palabras;
 *   - los que se van en el handshake del adaptador y en los estados de la CPU
 *     multiciclo siguen ahi con rafaga o sin ella.
 *
 * El metodo es barrer la LATENCIA del modelo de memoria: los ciclos desde que
 * acepta la peticion hasta que responde `done`. Cuatro sistemas identicos
 * (CPU + sdram_system_adapter) corren el mismo programa y solo cambia L. Eso
 * separa las dos partidas sin estimar ninguna:
 *
 *     ciclos(L) = A + N_accesos * L
 *
 * La pendiente es lo que la rafaga puede abaratar; la ordenada A es el suelo
 * de handshake y de CPU. La latencia real del sdram_controller de la 16 a
 * 100 MHz es de 8 ciclos en lectura (IDLE + ACTIVE + 2 de tRCD + READ + 2 de
 * espera + captura) y 7 en escritura, asi que L=8 es el punto que reproduce la
 * placa.
 *
 * Un quinto sistema, con L=8 pero con las busquedas de instruccion servidas en
 * un ciclo, acota el techo del punto 3 del plan (el bufer de instrucciones)
 * antes de escribir una linea de su RTL. Es la cota superior: un bufer real
 * falla al menos una vez por linea.
 *
 * Y un sexto, con L=8 y el scanout compitiendo por el bus a su ciclo de trabajo
 * real, es el unico que debe parecerse a la cifra de placa. Los cuatro del
 * barrido dejan el video en reposo a proposito, para medir el coste propio del
 * camino de la CPU sin mezclarlo con lo que el scanout le roba; comparar el
 * sexto con ellos dice cuanto es cada cosa.
 *
 * El programa es el bucle interior real de swap_demo_fast, 160 iteraciones
 * (una linea de framebuffer), en examples/perf_loop.asm:
 *     STORE R13, R6, 0 / ADDI R6,R6,4 / ADDI R3,R3,1 / BLT R3,R25,draw_word
 */

// ---------------------------------------------------------------------------
// Un sistema completo con memoria de latencia parametrizable y contadores.
// ---------------------------------------------------------------------------
module perf_system #(
    parameter integer LATENCY = 8,
    // Con IDEAL_IMEM las busquedas no pasan por el adaptador ni por la SDRAM:
    // se responden en un ciclo desde el mismo array. Modela un bufer de
    // instrucciones que nunca falla.
    parameter integer IDEAL_IMEM = 0,
    // Con WITH_VIDEO el scanout compite por la SDRAM con su ciclo de trabajo
    // real: SRC_W accesos de 16 bits por cada par de lineas de pantalla.
    parameter integer WITH_VIDEO = 0,
    parameter integer SRC_W = 320,
    parameter integer LINE_PAIR_CYCLES = 6400,
    parameter integer MEM_WORDS = 65536
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        run_request,
    output wire        halted,
    output wire        finished,
    output wire        error,
    output wire [31:0] cycles,
    output wire [31:0] instructions,
    output wire [31:0] accesses,
    output wire [31:0] mem_busy_cycles,
    output wire [31:0] adapter_cycles,
    output wire [31:0] cpu_only_cycles,
    output wire [31:0] imem_trans,
    output wire [31:0] dmem_trans,
    output wire [31:0] video_overrun_count
);
  wire [7:0] error_code;
  wire instruction_retired;
  wire imem_valid;
  wire [31:0] imem_address;
  wire dmem_valid, dmem_ready, dmem_error;
  wire [31:0] dmem_address, dmem_write_data, dmem_read_data;
  wire [3:0] dmem_write_enable;
  wire [31:0] debug_register_data, debug_pc;

  wire req_valid, req_write;
  wire [23:0] req_addr;
  wire [15:0] req_wdata;
  wire [1:0] req_wmask;
  reg req_ready, done;
  reg [15:0] rdata;

  reg [15:0] mem[0:MEM_WORDS-1];

  // -- Camino de instrucciones ----------------------------------------------
  wire [31:0] adapter_imem_read_data;
  wire adapter_imem_ready;
  reg [31:0] ideal_imem_read_data;
  reg ideal_imem_ready;

  wire [31:0] imem_read_data =
      IDEAL_IMEM ? ideal_imem_read_data : adapter_imem_read_data;
  wire imem_ready =
      IDEAL_IMEM ? ideal_imem_ready : adapter_imem_ready;


  always @(posedge clk) begin
    ideal_imem_ready <= 1'b0;
    if (!reset && imem_valid && !ideal_imem_ready) begin
      ideal_imem_read_data <= {mem[imem_address[16:1] + 1'b1],
                               mem[imem_address[16:1]]};
      ideal_imem_ready <= 1'b1;
    end
  end

  // -- Cliente de video sintetico -------------------------------------------
  // Reproduce el ciclo de trabajo de video_line_source_sdram: pide los SRC_W
  // accesos de una linea fuente uno a uno, y luego calla hasta que se cumple el
  // par de lineas de pantalla. No calcula direcciones reales porque aqui solo
  // importa la contienda por el bus.
  reg video_req;
  reg [23:0] video_addr;
  wire video_ready;
  reg [15:0] video_left;
  reg [15:0] video_clock;
  reg video_gap;
  reg [31:0] video_overruns;

  initial begin
    video_req = 1'b0;
    video_addr = 24'h008000;
    video_left = 0;
    video_clock = 0;
    video_gap = 1'b0;
    video_overruns = 0;
  end

  always @(posedge clk) begin
    if (reset) begin
      // Arrancar ya pidiendo: el barrido no espera a la CPU.
      video_req <= WITH_VIDEO ? 1'b1 : 1'b0;
      video_left <= SRC_W[15:0];
      video_clock <= 0;
      video_gap <= 1'b0;
    end else if (WITH_VIDEO) begin
      if (video_clock >= LINE_PAIR_CYCLES - 1) begin
        video_clock <= 0;
        // Solo se arranca el relleno siguiente si el anterior termino. Si no,
        // eso es exactamente un underflow: se cuenta y se sigue, en vez de
        // dejar el puerto pidiendo para siempre y colgar el banco.
        if (video_left == 0) begin
          video_left <= SRC_W[15:0];
          video_req <= 1'b1;
        end else begin
          video_overruns <= video_overruns + 1'b1;
        end
      end else begin
        video_clock <= video_clock + 1'b1;
      end
      // El lector real baja `video_req` al recibir su `ready` y lo vuelve a
      // subir un ciclo despues. No es un detalle: STATE_RELEASE del arbitro
      // espera a verlo bajo antes de volver a IDLE, asi que un nivel mantenido
      // lo deja atascado ahi para siempre.
      if (video_ready) begin
        video_addr <= video_addr + 1'b1;
        video_req <= 1'b0;
        video_gap <= 1'b1;
        video_left <= (video_left <= 1) ? 16'd0 : video_left - 1'b1;
      end else if (video_gap) begin
        video_gap <= 1'b0;
        if (video_left != 0) video_req <= 1'b1;
      end
    end
  end

  cpu cpu_i (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halt_request(1'b0), .step_request(1'b0), .halted(halted),
      .error(error), .error_code(error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid), .imem_address(imem_address),
      .imem_read_data(imem_read_data), .imem_ready(imem_ready),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data), .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(dmem_error), .debug_register_address(5'd0),
      .debug_register_data(debug_register_data), .debug_pc(debug_pc));

  sdram_system_adapter adapter_i (
      .clk(clk), .reset(reset), .init_done(1'b1),
      .monitor_address(32'd0), .monitor_write_data(8'd0),
      .monitor_write_enable(1'b0), .monitor_read_enable(1'b0),
      .monitor_read_data(), .monitor_ready(), .monitor_error(),
      .cpu_halted(halted),
      .cpu_imem_valid(IDEAL_IMEM ? 1'b0 : imem_valid),
      .cpu_imem_address(imem_address),
      .cpu_imem_read_data(adapter_imem_read_data),
      .cpu_imem_ready(adapter_imem_ready), .cpu_dmem_valid(dmem_valid),
      .cpu_dmem_address(dmem_address), .cpu_dmem_write_data(dmem_write_data),
      .cpu_dmem_write_enable(dmem_write_enable),
      .cpu_dmem_read_data(dmem_read_data), .cpu_dmem_ready(dmem_ready),
      .cpu_dmem_error(dmem_error),
      .mmio_select(), .mmio_write(), .mmio_write_mask(), .mmio_address(),
      .mmio_write_data(), .mmio_read_data(32'h0000_0000),
      .video_req(video_req), .video_addr(video_addr),
      .video_read_data(), .video_ready(video_ready),
      .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr),
      .req_wdata(req_wdata), .req_wmask(req_wmask), .req_ready(req_ready),
      .done(done), .rdata(rdata));

  // -- Modelo de memoria de latencia fija -----------------------------------
  // Acepta una peticion y la sirve LATENCY ciclos despues. Con L=0 el `done`
  // llega en el ciclo siguiente a la aceptacion: el suelo absoluto, un
  // handshake sin memoria de por medio.
  reg [31:0] wait_count;
  reg busy;
  reg [23:0] held_addr;
  reg [15:0] held_wdata;
  reg [1:0] held_wmask;
  reg held_write;
  integer k;

  initial begin
    for (k = 0; k < MEM_WORDS; k = k + 1) mem[k] = 16'h0000;
    $readmemh("perf_loop.hex", mem);
    req_ready = 1'b1;
    done = 1'b0;
    rdata = 16'h0000;
    busy = 1'b0;
    wait_count = 0;
    ideal_imem_ready = 1'b0;
    ideal_imem_read_data = 32'h0000_0000;
  end

  always @(posedge clk) begin
    done <= 1'b0;
    if (reset) begin
      busy <= 1'b0;
      req_ready <= 1'b1;
      wait_count <= 0;
    end else if (!busy) begin
      if (req_valid && req_ready) begin
        held_addr <= req_addr;
        held_wdata <= req_wdata;
        held_wmask <= req_wmask;
        held_write <= req_write;
        busy <= 1'b1;
        req_ready <= 1'b0;
        wait_count <= 0;
      end
    end else begin
      if (wait_count >= LATENCY) begin
        if (held_write) begin
          if (held_wmask[0]) mem[held_addr[15:0]][7:0] <= held_wdata[7:0];
          if (held_wmask[1]) mem[held_addr[15:0]][15:8] <= held_wdata[15:8];
        end else begin
          rdata <= mem[held_addr[15:0]];
        end
        done <= 1'b1;
        busy <= 1'b0;
        req_ready <= 1'b1;
      end else begin
        wait_count <= wait_count + 1;
      end
    end
  end

  // -- Contadores -----------------------------------------------------------
  reg [31:0] c_cycles, c_instr, c_acc, c_mem, c_adapter, c_cpu;
  reg [31:0] c_imem, c_dmem;
  // La CPU sale del reset ya en HALTED, asi que no basta con «cuenta hasta que
  // `halted` suba»: hay que ver primero que ha arrancado de verdad.
  reg started, running, done_flag;
  wire counting = started && !done_flag;
  assign finished = done_flag;

  assign cycles = c_cycles;
  assign instructions = c_instr;
  assign accesses = c_acc;
  assign mem_busy_cycles = c_mem;
  assign adapter_cycles = c_adapter;
  assign cpu_only_cycles = c_cpu;
  assign imem_trans = c_imem;
  assign dmem_trans = c_dmem;
  assign video_overrun_count = video_overruns;

  localparam [2:0] ADAPTER_IDLE = 3'd0;

  initial begin
    c_cycles = 0; c_instr = 0; c_acc = 0; c_mem = 0;
    c_adapter = 0; c_cpu = 0; c_imem = 0; c_dmem = 0;
    started = 1'b0; running = 1'b0; done_flag = 1'b0;
  end

  always @(posedge clk) begin
    if (reset) begin
      started <= 1'b0; running <= 1'b0; done_flag <= 1'b0;
    end else begin
      if (run_request) started <= 1'b1;
      if (started && !halted) running <= 1'b1;
      if (running && halted) done_flag <= 1'b1;
      if (counting && !(running && halted)) begin
        c_cycles <= c_cycles + 1;
        if (instruction_retired) c_instr <= c_instr + 1;
        if (req_valid && req_ready) c_acc <= c_acc + 1;
        // Reparto exhaustivo del ciclo entre las tres partidas.
        if (busy) c_mem <= c_mem + 1;
        else if (adapter_i.state != ADAPTER_IDLE) c_adapter <= c_adapter + 1;
        else c_cpu <= c_cpu + 1;
        if (imem_valid && imem_ready) c_imem <= c_imem + 1;
        if (dmem_valid && dmem_ready) c_dmem <= c_dmem + 1;
      end
    end
  end
endmodule

// ---------------------------------------------------------------------------
module perf_probe_tb;
  reg clk = 0;
  reg reset = 1;
  reg run_request = 0;
  integer guard;

  always #5 clk = ~clk;   // 100 MHz, el reloj de la placa

  localparam integer ITERATIONS = 160;   // una linea de framebuffer
  // 4 por iteracion mas las cuatro de preparacion. El HALT se busca pero no
  // retira, asi que hay una busqueda mas que instrucciones retiradas.
  localparam integer EXPECTED_INSTR = 4 * ITERATIONS + 4;
  localparam integer EXPECTED_FETCH = EXPECTED_INSTR + 1;

  wire [7:0] halted, finished, error;
  wire [31:0] cycles[0:7];
  wire [31:0] instructions[0:7];
  wire [31:0] accesses[0:7];
  wire [31:0] mem_busy[0:7];
  wire [31:0] adapter_busy[0:7];
  wire [31:0] cpu_only[0:7];
  wire [31:0] imem_trans[0:7];
  wire [31:0] dmem_trans[0:7];
  wire [31:0] video_overruns[0:7];

  // L=0 es el suelo sin memoria; L=8 es el sdram_controller de la 16 a
  // 100 MHz; 4 y 16 dan los puntos que confirman que la recta es recta.
  perf_system #(.LATENCY(0)) sys0 (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halted(halted[0]), .finished(finished[0]), .error(error[0]),
      .cycles(cycles[0]), .instructions(instructions[0]),
      .accesses(accesses[0]), .mem_busy_cycles(mem_busy[0]),
      .adapter_cycles(adapter_busy[0]), .cpu_only_cycles(cpu_only[0]),
      .imem_trans(imem_trans[0]), .dmem_trans(dmem_trans[0]),
      .video_overrun_count(video_overruns[0]));
  perf_system #(.LATENCY(4)) sys1 (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halted(halted[1]), .finished(finished[1]), .error(error[1]),
      .cycles(cycles[1]), .instructions(instructions[1]),
      .accesses(accesses[1]), .mem_busy_cycles(mem_busy[1]),
      .adapter_cycles(adapter_busy[1]), .cpu_only_cycles(cpu_only[1]),
      .imem_trans(imem_trans[1]), .dmem_trans(dmem_trans[1]),
      .video_overrun_count(video_overruns[1]));
  perf_system #(.LATENCY(8)) sys2 (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halted(halted[2]), .finished(finished[2]), .error(error[2]),
      .cycles(cycles[2]), .instructions(instructions[2]),
      .accesses(accesses[2]), .mem_busy_cycles(mem_busy[2]),
      .adapter_cycles(adapter_busy[2]), .cpu_only_cycles(cpu_only[2]),
      .imem_trans(imem_trans[2]), .dmem_trans(dmem_trans[2]),
      .video_overrun_count(video_overruns[2]));
  perf_system #(.LATENCY(16)) sys3 (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halted(halted[3]), .finished(finished[3]), .error(error[3]),
      .cycles(cycles[3]), .instructions(instructions[3]),
      .accesses(accesses[3]), .mem_busy_cycles(mem_busy[3]),
      .adapter_cycles(adapter_busy[3]), .cpu_only_cycles(cpu_only[3]),
      .imem_trans(imem_trans[3]), .dmem_trans(dmem_trans[3]),
      .video_overrun_count(video_overruns[3]));
  // El techo del bufer de instrucciones: misma SDRAM, cero busquedas.
  perf_system #(.LATENCY(8), .IDEAL_IMEM(1)) sys4 (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halted(halted[4]), .finished(finished[4]), .error(error[4]),
      .cycles(cycles[4]), .instructions(instructions[4]),
      .accesses(accesses[4]), .mem_busy_cycles(mem_busy[4]),
      .adapter_cycles(adapter_busy[4]), .cpu_only_cycles(cpu_only[4]),
      .imem_trans(imem_trans[4]), .dmem_trans(dmem_trans[4]),
      .video_overrun_count(video_overruns[4]));
  // El mismo sistema de la 16, pero con el scanout compitiendo por el bus.
  // Es el unico que deberia parecerse a la cifra de placa.
  perf_system #(.LATENCY(8), .WITH_VIDEO(1)) sys5 (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halted(halted[5]), .finished(finished[5]), .error(error[5]),
      .cycles(cycles[5]), .instructions(instructions[5]),
      .accesses(accesses[5]), .mem_busy_cycles(mem_busy[5]),
      .adapter_cycles(adapter_busy[5]), .cpu_only_cycles(cpu_only[5]),
      .imem_trans(imem_trans[5]), .dmem_trans(dmem_trans[5]),
      .video_overrun_count(video_overruns[5]));
  // Los dos huecos que quedan libres se atan a sistemas inertes: este banco
  // mide el camino de 16 bits de la 16, que es la LINEA BASE contra la que se
  // compara el de rafagas. Lo que cobra el bufer real sobre el camino nuevo lo
  // mide cpu_burst_system_tb.v, porque el bufer ya solo habla de 128 bits.
  perf_system #(.LATENCY(8)) sys6 (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halted(halted[6]), .finished(finished[6]), .error(error[6]),
      .cycles(cycles[6]), .instructions(instructions[6]),
      .accesses(accesses[6]), .mem_busy_cycles(mem_busy[6]),
      .adapter_cycles(adapter_busy[6]), .cpu_only_cycles(cpu_only[6]),
      .imem_trans(imem_trans[6]), .dmem_trans(dmem_trans[6]),
      .video_overrun_count(video_overruns[6]));
  perf_system #(.LATENCY(8), .WITH_VIDEO(1)) sys7 (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halted(halted[7]), .finished(finished[7]), .error(error[7]),
      .cycles(cycles[7]), .instructions(instructions[7]),
      .accesses(accesses[7]), .mem_busy_cycles(mem_busy[7]),
      .adapter_cycles(adapter_busy[7]), .cpu_only_cycles(cpu_only[7]),
      .imem_trans(imem_trans[7]), .dmem_trans(dmem_trans[7]),
      .video_overrun_count(video_overruns[7]));

  task report;
    input integer sel;
    input [127:0] etiqueta;
    begin
      $display("  %0s %7d ciclos %7.2f/palabra | sdram %6d (%2.0f%%) adaptador %6d (%2.0f%%) cpu %5d (%2.0f%%) | %4d accesos de 16 bits",
               etiqueta, cycles[sel], cycles[sel] * 1.0 / ITERATIONS,
               mem_busy[sel], mem_busy[sel] * 100.0 / cycles[sel],
               adapter_busy[sel], adapter_busy[sel] * 100.0 / cycles[sel],
               cpu_only[sel], cpu_only[sel] * 100.0 / cycles[sel],
               accesses[sel]);
    end
  endtask

  real slope;
  real intercept;

  initial begin
    repeat (4) @(negedge clk);
    reset = 0;
    @(negedge clk);
    run_request = 1;
    @(negedge clk);
    run_request = 0;

    guard = 0;
    while (finished !== 8'b11111111 && guard < 2_000_000) begin
      @(negedge clk);
      guard = guard + 1;
    end
    if (finished !== 8'b11111111)
      $fatal(1, "algun sistema no llego a HALT: halted=%b finished=%b",
             halted, finished);
    if (error !== 8'b00000000)
      $fatal(1, "algun sistema paro con error: error=%b", error);

    $display("");
    $display("Bucle interior de swap_demo_fast, %0d iteraciones, sin video.", ITERATIONS);
    $display("%0d instrucciones, %0d busquedas y %0d accesos de datos de 32 bits.",
             instructions[0], imem_trans[0], dmem_trans[0]);
    $display("");
    report(0, "L= 0       ");
    report(1, "L= 4       ");
    report(2, "L= 8 (real)");
    report(3, "L=16       ");
    $display("");
    report(4, "L= 8, imem ideal");
    $display("  (aqui la espera de busqueda es de un ciclo y cae en la columna");
    $display("   de CPU, porque ya no pasa por el adaptador ni por la SDRAM)");
    $display("");
    report(5, "L= 8, con video ");
    $display("  relleno de linea no terminado a tiempo (underflow): %0d veces", video_overruns[5]);
    $display("  medido en placa: 258 ciclos por palabra");

    slope = (cycles[3] - cycles[0]) * 1.0 / 16.0;
    intercept = cycles[0] * 1.0;
    $display("");
    $display("Ajuste: ciclos(L) = %.0f + %.0f * L, y la pendiente es exactamente",
             intercept, slope);
    $display("el numero de accesos de 16 bits. Con el controlador real (L=8):");
    $display("  comandos de SDRAM  %5.0f ciclos  %2.0f %%  <- lo unico que BL8 ataca",
             slope * 8.0, slope * 800.0 / cycles[2]);
    $display("  handshake + CPU    %5.0f ciclos  %2.0f %%  <- el suelo, intacto con rafaga",
             intercept, intercept * 100.0 / cycles[2]);
    $display("  de ese suelo, %0d ciclos son handshake del adaptador y %0d son la CPU.",
             adapter_busy[0] + mem_busy[0], cpu_only[0]);
    $display("");
    $display("Techo del bufer de instrucciones (punto 3 del plan): %.2fx,",
             cycles[2] * 1.0 / cycles[4]);
    $display("de %.1f a %.1f ciclos por palabra, sin tocar el camino de datos.",
             cycles[2] * 1.0 / ITERATIONS, cycles[4] * 1.0 / ITERATIONS);
    $display("");
    $display("Lo que cobra el bufer real sobre el camino de rafagas lo mide");
    $display("cpu_burst_system_tb.v: aqui el bufer ya no encaja, porque solo");
    $display("habla de 128 bits. Este banco es la linea base.");

    // Comprobaciones que hacen de esto un banco y no solo un informe.
    if (accesses[0] != accesses[3])
      $fatal(1, "el numero de accesos depende de la latencia: %0d vs %0d",
             accesses[0], accesses[3]);
    if (instructions[0] != EXPECTED_INSTR || instructions[4] != EXPECTED_INSTR)
      $fatal(1, "instrucciones retiradas inesperadas: %0d y %0d, esperadas %0d",
             instructions[0], instructions[4], EXPECTED_INSTR);
    if (imem_trans[0] != EXPECTED_FETCH)
      $fatal(1, "busquedas inesperadas: %0d", imem_trans[0]);
    if (dmem_trans[0] != ITERATIONS)
      $fatal(1, "accesos de datos inesperados: %0d", dmem_trans[0]);
    if (accesses[0] != 2 * (imem_trans[0] + dmem_trans[0]))
      $fatal(1, "cada transaccion de 32 bits deberia ser dos accesos de 16");
    // Con imem ideal solo quedan los accesos de datos, y siguen siendo dos por
    // palabra: es el bus de 16 bits, no el controlador.
    if (accesses[4] != 2 * ITERATIONS)
      $fatal(1, "con imem ideal deberian quedar %0d accesos, hay %0d",
             2 * ITERATIONS, accesses[4]);
    // La recta tiene que ser recta: los puntos intermedios no pueden desviarse.
    if (cycles[1] != cycles[0] + 4 * accesses[0])
      $fatal(1, "ciclos(4)=%0d, esperado %0d: el modelo no es lineal",
             cycles[1], cycles[0] + 4 * accesses[0]);
    if (cycles[2] != cycles[0] + 8 * accesses[0])
      $fatal(1, "ciclos(8)=%0d, esperado %0d: el modelo no es lineal",
             cycles[2], cycles[0] + 8 * accesses[0]);

    // El sexto sistema tiene que estar haciendo trabajo de video de verdad, o
    // no dice nada: los accesos de mas son los del scanout.
    if (accesses[5] <= accesses[2])
      $fatal(1, "el cliente de video no llego a pedir el bus: %0d accesos",
             accesses[5]);
    // Y tiene que quedarse cerca de la cifra de placa. La banda es ancha a
    // proposito: aqui no se modelan el refresco ni la latencia asimetrica de
    // escritura, asi que el modelo debe quedar algo POR DEBAJO de los 258.
    if (cycles[5] < 180 * ITERATIONS || cycles[5] > 258 * ITERATIONS)
      $fatal(1, "con video salen %.1f ciclos por palabra, fuera de [180, 258]",
             cycles[5] * 1.0 / ITERATIONS);

    // Los dos sistemas gemelos tienen que dar exactamente lo mismo que sus
    // pares: si no, es que algo depende del orden de instanciacion.
    if (cycles[6] != cycles[2] || cycles[7] != cycles[5])
      $fatal(1, "sistemas identicos con resultados distintos: %0d/%0d y %0d/%0d",
             cycles[6], cycles[2], cycles[7], cycles[5]);

    $display("");
    $display("PASS: perf_probe");
    $finish;
  end
endmodule

`default_nettype wire
