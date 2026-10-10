`default_nettype none

/*
 * INPUT (teclado y raton normalizados, 1.isa/mmio.md §25) visto por la CPU como
 * un dispositivo MMIO en 0x8060_0000.
 *
 * Este bloque SOLO GUARDA. No compara estados, no ordena eventos y no parte
 * movimientos: recibe EVENTOS YA FORMADOS, con el mismo formato que la CPU leera
 * por EVENT_DATA (§25.5-§25.8), y mantiene dos cosas:
 *
 *   STATE        KEY_STATE0..7 (256 bits) y MOUSE_BUTTONS (32 bits)
 *   EVENT FIFO   16 palabras de 32 bits, drop-new, con OVERFLOW pegajoso
 *
 * Quien calcula los eventos es el ADAPTADOR que va delante (Apendice A de
 * mmio.md). Hoy es el software del PC, a traves del monitor (`INPUT_EVENTS`,
 * `INPUT_PRESENCE`): ya tiene esa logica escrita y probada en
 * `InputDevice.keyboard_events` / `mouse_events`. Con un host USB el adaptador
 * seria una FSM, pero produciria igualmente eventos, asi que este bloque no
 * cambia. Por eso la interfaz del lado del adaptador es neutral.
 *
 * Que hace con cada palabra, SIEMPRE y en el mismo ciclo, haya sitio o no:
 *
 *   TYPE_KEY, KEY != 0     pone o quita el bit KEY de KEY_STATE segun DOWN
 *   TYPE_KEY, KEY == 0     cambio de modificadores: bits 0xE0..0xE7 := MODIFIERS
 *   TYPE_MOUSE_BUTTON      pone o quita el bit del boton en MOUSE_BUTTONS
 *   TYPE_MOUSE_MOVE        no toca STATE
 *
 * y despues intenta meterla en la FIFO. STATE se actualiza aunque el evento se
 * pierda (§25.5): tras un overflow, STATE es lo que permite recuperar el estado.
 *
 * Decisiones sobre lo que el contrato no cierra, tomadas para que coincida
 * EXACTAMENTE con el oraculo `InputDevice.apply_event`:
 *
 *   - Evento de un dispositivo NO presente: se aplica igual. Que el dispositivo
 *     este presente es responsabilidad del adaptador, que manda la presencia
 *     antes de los eventos de la conexion y las liberaciones antes de quitarla.
 *   - KEY dentro de 0xE0..0xE7 (con KEY != 0): se trata como cualquier otro
 *     Usage ID y pone ese bit. El adaptador nunca lo genera --los modificadores
 *     viajan en el evento KEY=0--, pero filtrarlo aqui costaria logica en un
 *     camino que no la necesita.
 *   - TYPE reservado (0x03..0xFF): no toca STATE y se encola tal cual.
 *   - Boton >= 32: no hay bit en MOUSE_BUTTONS; solo se encola.
 *   - Presencia a cero: pone a cero el STATE de ese dispositivo (invariante de
 *     §25.4). Presencia a uno solo marca PRESENT. Presencia y evento no llegan
 *     nunca en el mismo ciclo (los serializa el monitor); si lo hicieran, ganaria
 *     la presencia.
 *
 * Lado MMIO. Un acceso invalido no se resuelve aqui sino en `mmio_decoder`
 * (registro reservado, escribir uno de solo lectura, leer EVENT_CTRL, acceso no
 * alineado). Aqui solo queda lo que depende del DATO: una escritura de
 * EVENT_CTRL con bits reservados o con mascara parcial da `input_error` y no
 * ejecuta nada.
 *
 * Reglas que no se pueden romper (las mismas que en serial_port.v):
 *
 *   1. NINGUN acceso bloquea. Leer EVENT_DATA con la FIFO vacia devuelve cero
 *      de inmediato.
 *   2. La lectura destructiva retrasa el pop UN CICLO tras el `select`: el
 *      contrato del bus dice que `read_data` vale en el ciclo del `ack`, que es
 *      un ciclo despues, y si se sacara en el ciclo del `select` el cliente se
 *      llevaria el evento SIGUIENTE. Ver serial_port.v para la historia.
 *   3. `read_data` sale registrado, todos los ciclos, por la misma razon de
 *      timing que en serial_port.v.
 */
module input_registers (
    input  wire        clk,
    input  wire        reset,

    // Bus MMIO. `select` dura un ciclo; address, write, write_mask y write_data
    // llegan retenidos por mmio_mux durante toda la transaccion.
    input  wire        select,
    input  wire        write,
    input  wire [3:0]  write_mask,
    input  wire [7:0]  address,       // byte dentro de la ventana; [7:2] elige
    input  wire [31:0] write_data,
    output reg  [31:0] read_data,
    // Error de DATO (bits reservados de EVENT_CTRL, mascara parcial). Como
    // `video_error`: no depende de `select`, y el decodificador solo lo mira
    // cuando el bloque es INPUT.
    output wire        input_error,

    // Lado del adaptador (hoy el monitor). Un evento por ciclo.
    input  wire        event_valid,
    input  wire [31:0] event_word,
    // Presencia de los dos dispositivos: con `presence_write` ambos niveles se
    // cargan a la vez (un byte de INPUT_PRESENCE los trae los dos).
    input  wire        presence_write,
    input  wire        presence_keyboard,
    input  wire        presence_mouse,
    // Huecos libres de la FIFO, 0..16: es el control de flujo del adaptador.
    output wire [4:0]  free_slots
);
  localparam integer DEPTH = 16;

  localparam [5:0] REG_EVENT_DATA    = 6'd0;   // +0x00
  localparam [5:0] REG_STATUS        = 6'd1;   // +0x04
  localparam [5:0] REG_EVENT_CTRL    = 6'd2;   // +0x08
  localparam [5:0] REG_KEY_STATE0    = 6'd4;   // +0x10 .. +0x2C
  localparam [5:0] REG_MOUSE_BUTTONS = 6'd12;  // +0x30

  localparam [7:0] TYPE_KEY          = 8'h00;
  localparam [7:0] TYPE_MOUSE_BUTTON = 8'h01;

  wire [5:0] selected = address[7:2];
  wire bus_write = select && write;
  wire bus_read  = select && !write;

  // ---- EVENT_CTRL -----------------------------------------------------------
  // Con bits reservados o mascara parcial: error y ninguna operacion (§25.9).
  assign input_error = write && (selected == REG_EVENT_CTRL)
                       && (|write_data[31:2] || (write_mask != 4'b1111));
  wire ctrl_write = bus_write && (selected == REG_EVENT_CTRL) && !input_error;
  wire ctrl_flush = ctrl_write && write_data[0];
  wire ctrl_clear = ctrl_write && write_data[1];

  // ---- STATE ----------------------------------------------------------------
  reg [255:0] keys;
  reg [31:0]  buttons;
  reg         keyboard_present, mouse_present;

  wire [7:0] ev_type  = event_word[31:24];
  wire [7:0] ev_usage = event_word[7:0];     // KEY o boton, segun el tipo
  wire       ev_down  = event_word[8];
  wire [7:0] ev_mods  = event_word[23:16];

  always @(posedge clk) begin
    if (reset) begin
      keys <= 256'd0;
      buttons <= 32'd0;
      keyboard_present <= 1'b0;
      mouse_present <= 1'b0;
    end else begin
      if (event_valid && ev_type == TYPE_KEY) begin
        if (ev_usage != 8'd0) keys[ev_usage] <= ev_down;
        else                  keys[231:224] <= ev_mods;   // Usage IDs 0xE0..0xE7
      end
      if (event_valid && ev_type == TYPE_MOUSE_BUTTON && ev_usage[7:5] == 3'd0)
        buttons[ev_usage[4:0]] <= ev_down;

      // La presencia va despues: si coincidiera con un evento, gana (ver arriba).
      if (presence_write) begin
        keyboard_present <= presence_keyboard;
        mouse_present <= presence_mouse;
        if (!presence_keyboard) keys <= 256'd0;
        if (!presence_mouse) buttons <= 32'd0;
      end
    end
  end

  // ---- EVENT FIFO -----------------------------------------------------------
  // 16 palabras. Lectura asincrona de la cabeza (LUT RAM en el ECP5): `head`
  // esta listo en el mismo ciclo que el `select`, como en serial_port.v.
  reg [31:0] store [0:DEPTH-1];
  reg [3:0]  read_ptr, write_ptr;
  reg [4:0]  count;
  reg        overflow;
  wire [31:0] head = store[read_ptr];

  // Pop un ciclo despues del `select` de EVENT_DATA (regla 2).
  reg pop_q;
  always @(posedge clk) begin
    if (reset) pop_q <= 1'b0;
    else pop_q <= bus_read && (selected == REG_EVENT_DATA);
  end

  wire full   = (count == DEPTH[4:0]);
  wire empty  = (count == 5'd0);
  wire do_pop = pop_q && !empty;
  // FLUSH gana al PUSH (§25.9): la FIFO termina vacia y el evento se descarta,
  // aunque STATE ya lo haya recogido. Y FLUSH no produce overflow.
  wire do_push = event_valid && !ctrl_flush && (!full || do_pop);
  // Perdida: evento valido, sin FLUSH, FIFO llena y sin pop que libere hueco.
  wire lost = event_valid && !ctrl_flush && full && !do_pop;

  assign free_slots = DEPTH[4:0] - count;

  always @(posedge clk) begin
    if (reset) begin
      read_ptr <= 4'd0;
      write_ptr <= 4'd0;
      count <= 5'd0;
      overflow <= 1'b0;
    end else begin
      if (ctrl_flush) begin
        read_ptr <= 4'd0;
        write_ptr <= 4'd0;
        count <= 5'd0;
      end else begin
        if (do_push) begin
          store[write_ptr] <= event_word;
          write_ptr <= write_ptr + 1'b1;
        end
        if (do_pop) read_ptr <= read_ptr + 1'b1;
        // Pop y push el mismo ciclo, tambien con la FIFO llena: la cuenta no
        // cambia y no hay overflow (§25.5).
        case ({do_push, do_pop})
          2'b10: count <= count + 1'b1;
          2'b01: count <= count - 1'b1;
          default: ;
        endcase
      end
      // CLEAR_OVERFLOW pierde contra una perdida simultanea (§25.9).
      if (ctrl_clear) overflow <= 1'b0;
      if (lost) overflow <= 1'b1;
    end
  end

  // ---- lectura --------------------------------------------------------------
  // Registrada todos los ciclos (regla 3). Con la FIFO vacia EVENT_DATA da cero,
  // no el ultimo evento otra vez.
  wire [31:0] status = {13'd0, mouse_present, keyboard_present, overflow,
                        11'd0, count};
  wire [2:0] key_word = selected[2:0] - REG_KEY_STATE0[2:0];

  always @(posedge clk) begin
    if (selected == REG_EVENT_DATA)
      read_data <= empty ? 32'd0 : head;
    else if (selected == REG_STATUS)
      read_data <= status;
    else if (selected >= REG_KEY_STATE0 && selected < REG_MOUSE_BUTTONS)
      read_data <= keys[{key_word, 5'd0} +: 32];
    else if (selected == REG_MOUSE_BUTTONS)
      read_data <= buttons;
    else
      read_data <= 32'd0;
  end
endmodule

`default_nettype wire
