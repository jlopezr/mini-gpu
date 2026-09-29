`default_nettype none

/*
 * Puerto serie visto por la CPU como un dispositivo MMIO.
 *
 * No habla con ningun pin. Los bytes entran y salen encapsulados en paquetes
 * del protocolo del monitor --SEND_BYTES y RECV_BYTES-- y este bloque es solo
 * las dos colas que hay en medio:
 *
 *     PC  --SEND_BYTES-->  [ cola RX ]  --LOAD DATA-->   CPU
 *     PC  <--RECV_BYTES--  [ cola TX ]  <--STORE DATA--  CPU
 *
 * Por que paquetes y no `write-byte` sobre esta misma ventana, que ya
 * funcionaria: porque el monitor lee palabras BYTE A BYTE, cuatro comandos por
 * palabra. Si leer DATA sacara de la cola, una lectura del PC se comeria cuatro
 * caracteres. Con paquetes, el unico que lee DATA es la CPU, con un LOAD que es
 * un acceso unico, y sacar-al-leer vuelve a ser seguro.
 *
 * Registros, en la ventana del dispositivo:
 *
 *   +0x00  DATA    lectura: saca un byte de RX (cero si esta vacia)
 *                  escritura: mete el byte bajo en TX (se pierde si esta llena)
 *   +0x04  STATUS  [7:0] bytes en RX, [15:8] huecos en TX, bit 16 overrun.
 *                  Escribir un uno en el bit 16 borra el overrun; lo demas es
 *                  de solo lectura, igual que en video_registers.
 *   +0x08  PEEK    la cabeza de RX SIN sacarla. Existe para poder mirar la cola
 *                  desde el PC con `read-byte` sin destruirla: sin esto,
 *                  depurar el dispositivo lo rompe.
 *
 * Reglas que no se pueden romper:
 *
 *   1. NINGUN acceso bloquea. Leer DATA con la cola vacia devuelve cero
 *      inmediatamente y `STATUS` dice la verdad. Los dos adaptadores de memoria
 *      dan por hecho que un acceso MMIO se resuelve en un ciclo; un dispositivo
 *      que espere cuelga el `ack` y con el a la CPU.
 *   2. El control de flujo lo hace el PC con `host_rx_free`, que va en la
 *      respuesta de SEND_BYTES. `rx_overrun` no deberia levantarse nunca: si
 *      pasa, es que el PC ignoro la cuenta de huecos, y entonces conviene
 *      enterarse en vez de perder pulsaciones en silencio.
 */

module byte_fifo #(
    parameter integer DEPTH = 64,
    parameter integer ABITS = 6
) (
    input  wire       clk,
    input  wire       reset,
    input  wire       push,
    input  wire [7:0] push_data,
    input  wire       pop,
    output wire [7:0] head,
    output reg  [ABITS:0] count
);
  /*
   * `ABITS` tiene que ser exactamente log2(DEPTH), y son dos parametros
   * distintos porque Verilog-2001 no tiene $clog2. Si no cuadran, los punteros
   * dan la vuelta donde no toca y la cola se corrompe en silencio --el peor
   * fallo posible en un sitio como este--.
   *
   * Instanciar un modulo inexistente convierte el descuido en un error de
   * elaboracion, en iverilog y en yosys. El nombre del modulo es el mensaje.
   * Es el mismo truco que usa `uart.v` con su divisor.
   */
  generate
    if ((1 << ABITS) != DEPTH) begin : g_depth_check
      DEPTH_must_be_two_to_the_ABITS guard ();
    end
  endgenerate

  reg [7:0] store[0:DEPTH-1];
  reg [ABITS-1:0] read_ptr, write_ptr;

  wire full  = (count == DEPTH[ABITS:0]);
  wire empty = (count == 0);
  wire do_push = push && !full;
  wire do_pop  = pop && !empty;

  // Lectura asincrona de la cabeza: en el ECP5 son LUT RAM, y asi `head` esta
  // listo en el mismo ciclo que el `select` del bus, que es lo que exige el
  // contrato de un ciclo.
  assign head = store[read_ptr];

  always @(posedge clk) begin
    if (reset) begin
      read_ptr <= 0;
      write_ptr <= 0;
      count <= 0;
    end else begin
      if (do_push) begin
        store[write_ptr] <= push_data;
        write_ptr <= write_ptr + 1'b1;
      end
      if (do_pop) read_ptr <= read_ptr + 1'b1;
      // Meter y sacar el mismo ciclo es normal --la CPU lee mientras el PC
      // escribe-- y entonces la cuenta no cambia.
      case ({do_push, do_pop})
        2'b10: count <= count + 1'b1;
        2'b01: count <= count - 1'b1;
        default: ;
      endcase
    end
  end
endmodule


module serial_port #(
    parameter integer DEPTH = 64,
    parameter integer ABITS = 6
) (
    input  wire        clk,
    input  wire        reset,

    // Bus MMIO. Mismo contrato que video_registers: `select` dura un ciclo y
    // la lectura es combinacional respecto a `address`.
    input  wire        select,
    input  wire        write,
    input  wire [3:0]  write_mask,
    input  wire [7:0]  address,       // byte dentro de la ventana; [7:2] elige
    input  wire [31:0] write_data,
    output reg  [31:0] read_data,

    // Lado del monitor: el desempaquetado de SEND_BYTES y RECV_BYTES.
    input  wire        host_push,       // un byte de SEND_BYTES
    input  wire [7:0]  host_push_data,
    output wire [7:0]  host_rx_free,    // huecos: es el control de flujo
    input  wire        host_pop,        // un byte hacia RECV_BYTES
    output wire [7:0]  host_tx_data,
    output wire [7:0]  host_tx_count
);
  localparam [5:0] REG_DATA   = 6'd0;
  localparam [5:0] REG_STATUS = 6'd1;
  localparam [5:0] REG_PEEK   = 6'd2;

  wire [5:0] selected = address[7:2];
  wire bus_write = select && write;
  wire bus_read  = select && !write;

  wire [ABITS:0] rx_count, tx_count;
  wire [7:0] rx_head, tx_head;

  /*
   * Sacar de RX en la lectura de DATA, y solo ahi. PEEK deja la cola quieta.
   *
   * Pero UN CICLO DESPUES de `select`, y esto es lo mas delicado del modulo.
   *
   * El contrato del bus dice que `read_data` es valido en el mismo ciclo que el
   * `ack`, y el `ack` llega un ciclo despues del `select`. Para `video_registers`
   * da igual: sus registros no cambian por leerlos, asi que el dato es el mismo
   * en los dos ciclos. Una cola SI cambia. Si se saca en el ciclo de `select`,
   * el puntero ya ha avanzado cuando el cliente mira, y lo que se lleva es el
   * byte SIGUIENTE.
   *
   * Eso es exactamente lo que hacia: `A B C` entraba y salia `B C <vacio>`.
   * Retrasando el `pop` un ciclo, la cabeza sigue siendo la buena durante el
   * ciclo del `ack` y avanza justo despues.
   *
   * Cualquier dispositivo MMIO nuevo con lectura destructiva tiene el mismo
   * problema. Lo caza `cpu_serial_tb.v`.
   */
  reg rx_pop;
  always @(posedge clk) begin
    if (reset) rx_pop <= 1'b0;
    else rx_pop <= bus_read && (selected == REG_DATA);
  end
  wire tx_push = bus_write && (selected == REG_DATA) && write_mask[0];

  reg rx_overrun;

  byte_fifo #(.DEPTH(DEPTH), .ABITS(ABITS)) rx_fifo (
      .clk(clk), .reset(reset),
      .push(host_push), .push_data(host_push_data),
      .pop(rx_pop), .head(rx_head), .count(rx_count));

  byte_fifo #(.DEPTH(DEPTH), .ABITS(ABITS)) tx_fifo (
      .clk(clk), .reset(reset),
      .push(tx_push), .push_data(write_data[7:0]),
      .pop(host_pop), .head(tx_head), .count(tx_count));

  assign host_rx_free  = DEPTH[7:0] - {{(8 - ABITS - 1){1'b0}}, rx_count};
  assign host_tx_data  = tx_head;
  assign host_tx_count = {{(8 - ABITS - 1){1'b0}}, tx_count};

  wire [7:0] tx_free = DEPTH[7:0] - {{(8 - ABITS - 1){1'b0}}, tx_count};

  always @(posedge clk) begin
    if (reset) begin
      rx_overrun <= 1'b0;
    end else begin
      // El PC empujando en una cola llena: no deberia pasar nunca, porque
      // `host_rx_free` viaja en cada respuesta de SEND_BYTES.
      if (host_push && rx_count == DEPTH[ABITS:0]) rx_overrun <= 1'b1;
      if (bus_write && selected == REG_STATUS && write_mask[2] && write_data[16])
        rx_overrun <= 1'b0;
    end
  end

  always @* begin
    case (selected)
      // Cero con la cola vacia, no el ultimo byte otra vez: un programa que
      // lea sin mirar STATUS ve ceros, no basura repetida.
      REG_DATA:   read_data = (rx_count == 0) ? 32'd0 : {24'd0, rx_head};
      REG_STATUS: read_data = {15'd0, rx_overrun, tx_free,
                               {{(8 - ABITS - 1){1'b0}}, rx_count}};
      REG_PEEK:   read_data = (rx_count == 0) ? 32'd0 : {24'd0, rx_head};
      default:    read_data = 32'd0;
    endcase
  end
endmodule

`default_nettype wire
