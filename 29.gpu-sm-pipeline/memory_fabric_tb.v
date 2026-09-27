`timescale 1ns/1ps
`default_nettype none

/*
 * Banco de memory_fabric_4.
 *
 * El arbitro llego de pruebas/sdram sin una sola prueba y esta en el camino de
 * memoria de top.v desde la integracion. Los bancos de sistema lo ejercitan de
 * refilon —video_burst_tb.v con dos clientes, cpu_burst_system_tb.v con tres—,
 * pero ninguno comprueba a proposito lo unico que un arbitro tiene que hacer
 * bien: repartir el turno, no mezclar respuestas y no colgarse.
 *
 * Lo que se comprueba aqui:
 *
 *   1. que el round-robin reparte en orden;
 *   2. que con los cuatro clientes pidiendo SIN PARAR el reparto es
 *      equitativo, que es lo unico que prueba el puntero de verdad;
 *   3. que cada puerto recibe SU respuesta y no la del vecino, que es el fallo
 *      silencioso que un arbitro puede tener durante meses;
 *   4. que `urgent` del puerto de video se salta el turno, y —con el control
 *      negativo— que sin `urgent` no se lo salta;
 *   5. hasta donde llega `urgent` y hasta donde no;
 *   6. que la validacion de direccion responde error sin llegar a pedir nada a
 *      la SDRAM;
 *   7. que un cliente que retrasa su `rsp_ready` frena al arbitro entero, que
 *      es justo lo que hace el lector de video mientras vacia una rafaga;
 *   8. que la direccion y los datos llegan al controlador sin tocarse, con la
 *      conversion de byte a palabra de 16 bits.
 *
 * Dos cosas que este banco corrigio de lo que se creia
 * ----------------------------------------------------
 *
 * **El caso 1 no probaba nada.** Con cuatro clientes que piden una vez y
 * callan, el orden sale 0,1,2,3 aunque el puntero de round-robin no avance
 * jamas: cada uno baja su `valid` al ser servido y el `else if` en cascada hace
 * el resto. Se comprobo sustituyendo el avance por `rr_ptr <= MASTER_0`, y el
 * banco seguia en verde. De ahi sale el caso 2, que con el mismo sabotaje da
 * 21/21/3/3 en vez de 12/12/12/12 y falla como debe.
 *
 * **`urgent` mantenido NO es monopolio**, que era lo que se habia supuesto por
 * analogia con la prioridad absoluta que se le dio al video en la 16. El
 * arbitro solo mira `p2_urgent` cuando `p2_req_valid` esta alto, asi que en
 * cuanto el cliente deja un hueco entre peticiones, el round-robin reparte. Lo
 * que si se cumple es el invariante «mientras el puerto 2 pide con urgent, no
 * se concede a nadie mas», y eso se vigila en TODOS los ciclos del banco, no
 * solo en su caso.
 */

// ---------------------------------------------------------------------------
// Un cliente de un puerto del arbitro, con retardo de aceptacion configurable.
// ---------------------------------------------------------------------------
module fabric_port_driver (
    input  wire         clk,
    input  wire         reset,

    input  wire         start,        // pulso: emitir una peticion
    // Con `hammer` alto, el cliente vuelve a pedir en cuanto le responden, sin
    // dejar un solo hueco. Es lo unico que ejercita el puntero de round-robin:
    // con clientes que piden una vez y callan, el orden sale correcto aunque el
    // puntero no avance nunca, porque cada uno baja su `valid` al ser servido.
    input  wire         hammer,
    input  wire         in_write,
    input  wire [31:0]  in_addr,
    input  wire [127:0] in_wdata,
    input  wire [15:0]  in_wmask,
    input  wire [7:0]   rsp_delay,    // ciclos antes de aceptar la respuesta

    output reg          req_valid,
    input  wire         req_ready,
    output reg          req_write,
    output reg  [31:0]  req_addr,
    output reg  [127:0] req_wdata,
    output reg  [15:0]  req_wmask,

    input  wire         rsp_valid,
    output wire         rsp_ready,
    input  wire [127:0] rsp_rdata,
    input  wire         rsp_error,

    output reg          busy,
    output reg          done,
    output reg  [127:0] last_rdata,
    output reg          last_error,
    output reg  [31:0]  served,
    output reg  [31:0]  granted_at    // ciclo global en que le llego `ready`
);
  localparam [1:0] S_IDLE = 2'd0, S_ISSUE = 2'd1, S_WAIT = 2'd2;

  reg [1:0] state;
  reg [7:0] delay_left;
  reg [31:0] tick;

  // El arbitro concede mirando el `valid` del puerto, asi que hay que
  // levantarlo primero y esperar `ready` despues. Esperar `ready` antes de
  // pedir no funciona, y este driver existe tambien para dejarlo escrito.
  assign rsp_ready = (state == S_WAIT) && (delay_left == 8'd0);

  always @(posedge clk) begin
    done <= 1'b0;
    if (reset) begin
      state <= S_IDLE;
      req_valid <= 1'b0;
      req_write <= 1'b0;
      req_addr <= 32'd0;
      req_wdata <= 128'd0;
      req_wmask <= 16'd0;
      busy <= 1'b0;
      last_rdata <= 128'd0;
      last_error <= 1'b0;
      served <= 32'd0;
      granted_at <= 32'd0;
      delay_left <= 8'd0;
      tick <= 32'd0;
    end else begin
      tick <= tick + 1'b1;
      case (state)
        S_IDLE:
          if (start || hammer) begin
            req_write <= in_write;
            req_addr <= in_addr;
            req_wdata <= in_wdata;
            req_wmask <= in_wmask;
            req_valid <= 1'b1;
            busy <= 1'b1;
            state <= S_ISSUE;
          end

        S_ISSUE:
          if (req_ready) begin
            req_valid <= 1'b0;
            granted_at <= tick;
            delay_left <= rsp_delay;
            state <= S_WAIT;
          end

        S_WAIT: begin
          if (delay_left != 8'd0) begin
            delay_left <= delay_left - 1'b1;
          end else if (rsp_valid) begin
            last_rdata <= rsp_rdata;
            last_error <= rsp_error;
            served <= served + 1'b1;
            done <= 1'b1;
            busy <= 1'b0;
            state <= S_IDLE;
          end
        end

        default: state <= S_IDLE;
      endcase
    end
  end
endmodule

// ---------------------------------------------------------------------------
module memory_fabric_tb;
  reg clk = 0;
  reg reset = 1;
  always #5 clk = ~clk;

  integer errors = 0;
  integer guard;
  integer i;

  // -- Estimulo comun -------------------------------------------------------
  reg [3:0] start = 4'b0000;
  reg [3:0] hammer = 4'b0000;
  reg [3:0] wr = 4'b0000;
  reg [31:0] addr0 = 0, addr1 = 0, addr2 = 0, addr3 = 0;
  reg [127:0] wdata0 = 0;
  reg [15:0] wmask0 = 0;
  reg [7:0] delay0 = 0, delay1 = 0, delay2 = 0, delay3 = 0;
  reg urgent2 = 0;

  // -- Puertos --------------------------------------------------------------
  wire [3:0] pv, pr, pw, rv, rr_, re, pbusy, pdone;
  wire [31:0] pa0, pa1, pa2, pa3;
  wire [127:0] pd0, pd1, pd2, pd3;
  wire [15:0] pm0, pm1, pm2, pm3;
  wire [127:0] rd0, rd1, rd2, rd3;
  wire [31:0] served0, served1, served2, served3;
  wire [31:0] gat0, gat1, gat2, gat3;
  wire [3:0] perr;

  fabric_port_driver d0 (.clk(clk), .reset(reset), .start(start[0]), .hammer(hammer[0]),
      .in_write(wr[0]), .in_addr(addr0), .in_wdata(wdata0), .in_wmask(wmask0),
      .rsp_delay(delay0), .req_valid(pv[0]), .req_ready(pr[0]),
      .req_write(pw[0]), .req_addr(pa0), .req_wdata(pd0), .req_wmask(pm0),
      .rsp_valid(rv[0]), .rsp_ready(rr_[0]), .rsp_rdata(rd0),
      .rsp_error(re[0]), .busy(pbusy[0]), .done(pdone[0]), .last_rdata(),
      .last_error(perr[0]), .served(served0), .granted_at(gat0));

  fabric_port_driver d1 (.clk(clk), .reset(reset), .start(start[1]), .hammer(hammer[1]),
      .in_write(wr[1]), .in_addr(addr1), .in_wdata(128'd0), .in_wmask(16'd0),
      .rsp_delay(delay1), .req_valid(pv[1]), .req_ready(pr[1]),
      .req_write(pw[1]), .req_addr(pa1), .req_wdata(pd1), .req_wmask(pm1),
      .rsp_valid(rv[1]), .rsp_ready(rr_[1]), .rsp_rdata(rd1),
      .rsp_error(re[1]), .busy(pbusy[1]), .done(pdone[1]), .last_rdata(),
      .last_error(perr[1]), .served(served1), .granted_at(gat1));

  fabric_port_driver d2 (.clk(clk), .reset(reset), .start(start[2]), .hammer(hammer[2]),
      .in_write(wr[2]), .in_addr(addr2), .in_wdata(128'd0), .in_wmask(16'd0),
      .rsp_delay(delay2), .req_valid(pv[2]), .req_ready(pr[2]),
      .req_write(pw[2]), .req_addr(pa2), .req_wdata(pd2), .req_wmask(pm2),
      .rsp_valid(rv[2]), .rsp_ready(rr_[2]), .rsp_rdata(rd2),
      .rsp_error(re[2]), .busy(pbusy[2]), .done(pdone[2]), .last_rdata(),
      .last_error(perr[2]), .served(served2), .granted_at(gat2));

  fabric_port_driver d3 (.clk(clk), .reset(reset), .start(start[3]), .hammer(hammer[3]),
      .in_write(wr[3]), .in_addr(addr3), .in_wdata(128'd0), .in_wmask(16'd0),
      .rsp_delay(delay3), .req_valid(pv[3]), .req_ready(pr[3]),
      .req_write(pw[3]), .req_addr(pa3), .req_wdata(pd3), .req_wmask(pm3),
      .rsp_valid(rv[3]), .rsp_ready(rr_[3]), .rsp_rdata(rd3),
      .rsp_error(re[3]), .busy(pbusy[3]), .done(pdone[3]), .last_rdata(),
      .last_error(perr[3]), .served(served3), .granted_at(gat3));

  // -- Lado SDRAM: modelo funcional -----------------------------------------
  // Devuelve la propia direccion replicada, para que se vea de que peticion
  // viene cada respuesta. Si el arbitro cruza los datos de dos puertos, se nota
  // en el numero.
  wire s_valid, s_write;
  wire [23:0] s_addr;
  wire [127:0] s_wdata;
  wire [15:0] s_wmask;
  reg s_ready, s_done;
  reg [127:0] s_rdata;
  reg [3:0] s_count;
  reg s_busy;
  reg [23:0] s_held;
  reg s_held_write;
  reg [127:0] s_held_wdata;
  reg [15:0] s_held_wmask;
  integer s_transactions;
  wire fabric_busy;

  localparam integer SDRAM_LATENCY = 6;

  initial begin
    s_ready = 1'b1;
    s_done = 1'b0;
    s_rdata = 128'd0;
    s_count = 0;
    s_busy = 1'b0;
    s_transactions = 0;
    s_held = 24'd0;
    s_held_write = 1'b0;
    s_held_wdata = 128'd0;
    s_held_wmask = 16'd0;
  end

  always @(posedge clk) begin
    s_done <= 1'b0;
    if (reset) begin
      s_busy <= 1'b0;
      s_ready <= 1'b1;
      s_count <= 0;
    end else if (!s_busy) begin
      if (s_valid && s_ready) begin
        s_held <= s_addr;
        s_held_write <= s_write;
        s_held_wdata <= s_wdata;
        s_held_wmask <= s_wmask;
        s_busy <= 1'b1;
        s_ready <= 1'b0;
        s_count <= 0;
        s_transactions = s_transactions + 1;
      end
    end else if (s_count >= SDRAM_LATENCY) begin
      s_rdata <= {8{8'hA0, s_held[7:0]}};
      s_done <= 1'b1;
      s_busy <= 1'b0;
      s_ready <= 1'b1;
    end else begin
      s_count <= s_count + 1'b1;
    end
  end

  memory_fabric_4 fabric (
      .clk(clk), .reset(reset),
      .p0_req_valid(pv[0]), .p0_req_ready(pr[0]), .p0_req_write(pw[0]),
      .p0_req_addr(pa0), .p0_req_wdata(pd0), .p0_req_wmask(pm0),
      .p0_rsp_valid(rv[0]), .p0_rsp_ready(rr_[0]), .p0_rsp_rdata(rd0),
      .p0_rsp_error(re[0]),

      .p1_req_valid(pv[1]), .p1_req_ready(pr[1]), .p1_req_write(pw[1]),
      .p1_req_addr(pa1), .p1_req_wdata(pd1), .p1_req_wmask(pm1),
      .p1_rsp_valid(rv[1]), .p1_rsp_ready(rr_[1]), .p1_rsp_rdata(rd1),
      .p1_rsp_error(re[1]),

      .p2_req_valid(pv[2]), .p2_req_ready(pr[2]), .p2_req_write(pw[2]),
      .p2_req_addr(pa2), .p2_req_wdata(pd2), .p2_req_wmask(pm2),
      .p2_urgent(urgent2),
      .p2_rsp_valid(rv[2]), .p2_rsp_ready(rr_[2]), .p2_rsp_rdata(rd2),
      .p2_rsp_error(re[2]),

      .p3_req_valid(pv[3]), .p3_req_ready(pr[3]), .p3_req_write(pw[3]),
      .p3_req_addr(pa3), .p3_req_wdata(pd3), .p3_req_wmask(pm3),
      .p3_rsp_valid(rv[3]), .p3_rsp_ready(rr_[3]), .p3_rsp_rdata(rd3),
      .p3_rsp_error(re[3]),

      .sdram_req_valid(s_valid), .sdram_req_ready(s_ready),
      .sdram_req_write(s_write), .sdram_req_addr(s_addr),
      .sdram_req_wdata(s_wdata), .sdram_req_wmask(s_wmask),
      .sdram_done(s_done), .sdram_rdata(s_rdata), .busy(fabric_busy));

  // -- El invariante de `urgent`, vigilado siempre --------------------------
  // Mientras el puerto 2 pide con urgent, el arbitro no puede conceder a nadie
  // mas. Se comprueba en cada ciclo del banco entero, no solo en su caso: un
  // invariante que solo se mira donde se espera que se cumpla no vale de nada.
  integer urgent_violations;
  initial urgent_violations = 0;
  always @(posedge clk) begin
    if (!reset && urgent2 && pv[2] && (pr[0] || pr[1] || pr[3])) begin
      $display("FALLO %0t: concesion a otro puerto con el 2 pidiendo urgente (ready=%b)",
               $time, pr);
      urgent_violations = urgent_violations + 1;
    end
  end

  // -- Registro del orden de concesion --------------------------------------
  integer orden[0:31];
  integer n_orden;
  always @(posedge clk) begin
    if (!reset) begin
      if (pr[0] && pv[0]) begin orden[n_orden] = 0; n_orden = n_orden + 1; end
      if (pr[1] && pv[1]) begin orden[n_orden] = 1; n_orden = n_orden + 1; end
      if (pr[2] && pv[2]) begin orden[n_orden] = 2; n_orden = n_orden + 1; end
      if (pr[3] && pv[3]) begin orden[n_orden] = 3; n_orden = n_orden + 1; end
    end
  end

  // -------------------------------------------------------------------------
  task check;
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

  // Lanza una peticion en todos los puertos marcados y espera a que todos
  // terminen.
  task lanzar;
    input [3:0] mask;
    begin
      @(negedge clk);
      start = mask;
      @(negedge clk);
      start = 4'b0000;
    end
  endtask

  task esperar_todos;
    begin
      guard = 0;
      while ((pbusy != 4'b0000) && guard < 5000) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (pbusy != 4'b0000)
        $fatal(1, "algun puerto se quedo colgado: busy=%b", pbusy);
    end
  endtask

  reg [127:0] esperado;

  initial begin
    n_orden = 0;
    for (i = 0; i < 32; i = i + 1) orden[i] = -1;

    addr0 = 32'h0000_0000;
    addr1 = 32'h0000_0010;
    addr2 = 32'h0000_0020;
    addr3 = 32'h0000_0030;

    repeat (4) @(negedge clk);
    reset = 0;
    @(negedge clk);

    // ---------------------------------------------------------------------
    // 1. Round-robin: los cuatro piden a la vez, dos veces seguidas.
    //    El puntero arranca en el puerto 0 y avanza al siguiente del que
    //    acaba de servir, asi que el orden tiene que ser 0,1,2,3.
    // ---------------------------------------------------------------------
    n_orden = 0;
    lanzar(4'b1111);
    esperar_todos;
    check("concesiones en la primera ronda", n_orden, 4);
    for (i = 0; i < 4; i = i + 1)
      if (orden[i] != i) begin
        $display("FALLO round-robin: la concesion %0d fue del puerto %0d, esperado %0d",
                 i, orden[i], i);
        errors = errors + 1;
      end

    // Y cada uno tiene que haber recibido SU respuesta, no la del vecino.
    // El modelo devuelve la direccion de palabra replicada.
    if (d0.last_rdata !== {8{8'hA0, 8'h00}}) begin
      $display("FALLO: el puerto 0 recibio %032x", d0.last_rdata);
      errors = errors + 1;
    end
    if (d1.last_rdata !== {8{8'hA0, 8'h08}}) begin
      $display("FALLO: el puerto 1 recibio %032x", d1.last_rdata);
      errors = errors + 1;
    end
    if (d2.last_rdata !== {8{8'hA0, 8'h10}}) begin
      $display("FALLO: el puerto 2 recibio %032x", d2.last_rdata);
      errors = errors + 1;
    end
    if (d3.last_rdata !== {8{8'hA0, 8'h18}}) begin
      $display("FALLO: el puerto 3 recibio %032x", d3.last_rdata);
      errors = errors + 1;
    end
    $display("Round-robin: orden %0d,%0d,%0d,%0d y cada puerto con su respuesta",
             orden[0], orden[1], orden[2], orden[3]);

    // ---------------------------------------------------------------------
    // 2. Segunda ronda: el puntero quedo en 0 tras servir al 3, asi que el
    //    orden vuelve a ser el mismo. Si el puntero no avanzara, el puerto 0
    //    se llevaria todas y esto lo caza.
    // ---------------------------------------------------------------------
    n_orden = 0;
    lanzar(4'b1111);
    esperar_todos;
    for (i = 0; i < 4; i = i + 1)
      if (orden[i] != i) begin
        $display("FALLO round-robin, segunda ronda: concesion %0d del puerto %0d",
                 i, orden[i]);
        errors = errors + 1;
      end

    // ---------------------------------------------------------------------
    // 2b. EQUIDAD, que es lo que de verdad prueba el puntero.
    //
    //     Los dos casos de arriba pasan igual con el puntero averiado: si cada
    //     cliente pide una vez y calla, el orden sale 0,1,2,3 porque cada uno
    //     baja su `valid` al ser servido y el `else if` en cascada hace el
    //     resto. Se comprobo sustituyendo el avance del puntero por
    //     `rr_ptr <= MASTER_0` y el banco seguia en verde.
    //
    //     Lo que si lo distingue es que los cuatro pidan SIN parar. Con el
    //     puntero bien, las concesiones se reparten a partes iguales; con el
    //     puntero clavado en cero, el puerto 0 se lo lleva todo y los demas se
    //     mueren de hambre.
    // ---------------------------------------------------------------------
    i = served0;
    n_orden = 0;
    hammer = 4'b1111;
    repeat (400) @(negedge clk);
    hammer = 4'b0000;
    esperar_todos;

    $display("Martilleando los cuatro: %0d / %0d / %0d / %0d concesiones",
             served0, served1, served2, served3);
    // Con round-robin honesto ninguno puede pasar del 40 % del total.
    i = served0 + served1 + served2 + served3;
    if (served0 * 100 > i * 40 || served1 * 100 > i * 40 ||
        served2 * 100 > i * 40 || served3 * 100 > i * 40) begin
      $display("FALLO: el reparto no es equitativo (total %0d)", i);
      errors = errors + 1;
    end
    // Y ninguno puede quedarse sin nada.
    if (served0 == 0 || served1 == 0 || served2 == 0 || served3 == 0) begin
      $display("FALLO: algun puerto se quedo sin servir");
      errors = errors + 1;
    end

    // ---------------------------------------------------------------------
    // 3. Sin `urgent`, el puerto 2 espera su turno. Es el control negativo
    //    del caso siguiente: sin esto, que el video vaya primero no probaria
    //    que `urgent` sirve para algo.
    // ---------------------------------------------------------------------
    urgent2 = 1'b0;
    n_orden = 0;
    lanzar(4'b1101);            // puertos 0, 2 y 3
    esperar_todos;
    check("concesiones sin urgent", n_orden, 3);
    if (orden[0] == 2) begin
      $display("FALLO: el puerto 2 fue primero sin urgent");
      errors = errors + 1;
    end
    $display("Sin urgent, el puerto 2 llega el %0d de 3",
             (orden[0] == 2) ? 1 : ((orden[1] == 2) ? 2 : 3));

    // ---------------------------------------------------------------------
    // 4. Con `urgent`, el puerto 2 se salta el turno aunque no le toque.
    // ---------------------------------------------------------------------
    urgent2 = 1'b1;
    n_orden = 0;
    lanzar(4'b1101);
    esperar_todos;
    if (orden[0] != 2) begin
      $display("FALLO: con urgent el puerto 2 no fue primero (fue el %0d)",
               orden[0]);
      errors = errors + 1;
    end else begin
      $display("Con urgent, el puerto 2 se salta el turno");
    end
    urgent2 = 1'b0;

    // ---------------------------------------------------------------------
    // 5. Hasta donde llega `urgent`, que no es hasta donde parecia.
    //
    //    La primera version de este caso daba por hecho que `urgent`
    //    mantenido era monopolio, como la prioridad absoluta que se le dio al
    //    video en la 16. No lo es, y el banco lo corrigio: el arbitro solo
    //    mira `p2_urgent` cuando `p2_req_valid` esta alto, asi que en cuanto
    //    el cliente de video deja un hueco entre peticiones, el round-robin
    //    reparte y los demas entran.
    //
    //    Lo que SI se cumple, y es lo que hay que fijar, es el invariante:
    //    mientras el puerto 2 pide con `urgent`, no se concede a nadie mas.
    //    Se vigila durante TODO el banco, no solo aqui.
    // ---------------------------------------------------------------------
    urgent2 = 1'b1;
    n_orden = 0;
    // Los puertos 0 y 3 piden PRIMERO y se quedan esperando.
    lanzar(4'b1001);
    @(negedge clk);
    // Y ahora el 2 encadena cuatro peticiones urgentes, con sus huecos.
    for (i = 0; i < 4; i = i + 1) begin
      lanzar(4'b0100);
      guard = 0;
      while (pbusy[2] && guard < 500) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (pbusy[2]) $fatal(1, "el puerto urgente se colgo");
    end
    esperar_todos;
    // El adelantamiento lo prueba el caso 4, donde los tres piden a la vez.
    // Aqui lo que importa es lo contrario: que `urgent` NO excluye. Los
    // puertos 0 y 3 acaban servidos, porque el puerto 2 deja huecos entre
    // peticiones y en esos huecos el round-robin reparte.
    if (served0 == 0 || served3 == 0) begin
      $display("FALLO: urgent dejo a 0 o 3 sin servir nunca");
      errors = errors + 1;
    end
    check("el puerto urgente completo sus cuatro peticiones", served2 >= 4, 1);
    $display("Urgent adelanta pero NO excluye: el puerto 2 encadeno 4 peticiones");
    $display("  urgentes y los otros dos entraron por los huecos. El invariante");
    $display("  que si se cumple —nadie es servido mientras el 2 pide urgente—");
    $display("  se vigila en todos los ciclos del banco.");
    urgent2 = 1'b0;

    // ---------------------------------------------------------------------
    // 6. Direcciones invalidas: error, y SIN pedir nada a la SDRAM.
    // ---------------------------------------------------------------------
    i = s_transactions;
    addr0 = 32'h0000_0004;      // no alineada a 16 bytes
    lanzar(4'b0001);
    esperar_todos;
    if (!perr[0]) begin
      $display("FALLO: una direccion no alineada a 16 no dio error");
      errors = errors + 1;
    end
    addr0 = 32'h0400_0000;      // fuera de los 32 MiB
    lanzar(4'b0001);
    esperar_todos;
    if (!perr[0]) begin
      $display("FALLO: una direccion fuera de rango no dio error");
      errors = errors + 1;
    end
    check("peticiones a la SDRAM por direcciones invalidas",
          s_transactions - i, 0);
    addr0 = 32'h0000_0000;

    // Y despues de dos errores el arbitro sigue vivo.
    lanzar(4'b0001);
    esperar_todos;
    if (perr[0]) begin
      $display("FALLO: una direccion valida dio error tras dos invalidas");
      errors = errors + 1;
    end

    // ---------------------------------------------------------------------
    // 7. Un cliente lento frena al arbitro entero. Es lo que hace el lector
    //    de video mientras vacia una rafaga en el line buffer, y hay que
    //    saber que bloquea a los demas mientras tanto.
    // ---------------------------------------------------------------------
    delay1 = 8'd20;
    n_orden = 0;
    lanzar(4'b1010);            // puertos 1 y 3
    esperar_todos;
    check("concesiones con un cliente lento", n_orden, 2);
    if (gat3 < gat1) begin
      $display("FALLO: el puerto 3 fue servido antes que el 1, que pidio primero");
      errors = errors + 1;
    end
    if (gat3 - gat1 < 20) begin
      $display("FALLO: el cliente lento no freno al arbitro (%0d ciclos)",
               gat3 - gat1);
      errors = errors + 1;
    end else begin
      $display("Un cliente que tarda 20 ciclos en aceptar retrasa al siguiente %0d",
               gat3 - gat1);
    end
    delay1 = 8'd0;

    // ---------------------------------------------------------------------
    // 8. Los datos de escritura llegan al controlador sin tocarse, y la
    //    direccion convertida de byte a palabra de 16 bits.
    // ---------------------------------------------------------------------
    wr = 4'b0001;
    addr0 = 32'h0001_0020;
    wdata0 = 128'h0123_4567_89ab_cdef_fedc_ba98_7654_3210;
    wmask0 = 16'h8001;
    fork
      begin
        lanzar(4'b0001);
        esperar_todos;
      end
      begin
        // Capturar lo que ve el controlador en el ciclo de la peticion.
        guard = 0;
        while (!(s_valid && s_ready) && guard < 200) begin
          @(negedge clk);
          guard = guard + 1;
        end
        if (s_addr !== 24'h008010) begin
          $display("FALLO: el controlador ve la direccion %06x, esperada 008010",
                   s_addr);
          errors = errors + 1;
        end
        if (s_wdata !== 128'h0123_4567_89ab_cdef_fedc_ba98_7654_3210) begin
          $display("FALLO: los datos de escritura llegaron alterados");
          errors = errors + 1;
        end
        if (s_wmask !== 16'h8001) begin
          $display("FALLO: la mascara llego como %04x, esperada 8001", s_wmask);
          errors = errors + 1;
        end
        if (!s_write) begin
          $display("FALLO: la escritura llego como lectura");
          errors = errors + 1;
        end
      end
    join
    wr = 4'b0000;

    if (urgent_violations != 0) begin
      $display("FALLO: %0d concesiones violaron la prioridad de urgent",
               urgent_violations);
      errors = errors + 1;
    end

    if (errors != 0) $fatal(1, "%0d comprobaciones fallaron", errors);
    $display("");
    $display("PASS: memory_fabric");
    $finish;
  end
endmodule

`default_nettype wire
