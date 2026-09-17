`default_nettype none

/*
 * Minimal UART monitor protocol.
 *
 * Requests and responses:
 *   01             (PING)        -> 81
 *   02             (GET_VERSION) -> 82 MAJOR MINOR
 *   10 A3 A2 A1 A0 DD          (WRITE_BYTE)  -> 90 (or ff)
 *   11 A3 A2 A1 A0             (READ_BYTE)   -> 91 DD (or ff)
 *   12 A3 A2 A1 A0             (READ_WORD)   -> 92 D0 D1 D2 D3 (or ff)
 *   20 A3 A2 A1 A0 LL LL DD... (WRITE_BLOCK) -> a0 (or ff)
 *   21 A3 A2 A1 A0 LL LL       (READ_BLOCK)  -> a1 DD... (or ff)
 *   30             (RUN)         -> b0 (or ff)
 *   31             (HALT)        -> b1
 *   32             (STEP)        -> b2 (or ff)
 *   33             (GET_STATUS)  -> b3 FLAGS ERROR PC3 PC2 PC1 PC0
 *   34 RR          (READ_REG)    -> b4 D3 D2 D1 D0 (or ff)
 *   35             (RESET_CPU)   -> b5
 *   38 LL DD...    (SEND_BYTES)  -> b8 NN     NN aceptados, puede ser < LL
 *   39 MM          (RECV_BYTES)  -> b9 NN DD... NN <= MM, puede ser 0
 *   any other command            -> ff
 *
 * SEND_BYTES y RECV_BYTES son el puerto serie de la CPU, y SOLO existen con
 * HAS_SERIAL = 1. Funcionan con la CPU EN MARCHA, porque no tocan la SDRAM.
 * `NN` es el control de flujo: el que devuelve SEND_BYTES dice cuantos cupieron
 * en la cola, y el resto se reenvia.
 *
 * ---------------------------------------------------------------------------
 * FICHERO UNICO. Este monitor es COPIA IDENTICA en las diez carpetas que hablan
 * el protocolo: 6, 10, 12, 14, 16, 17, 18, 19, 21 y 22. Todo lo que distingue a
 * un prototipo de otro --version, tamano de RAM, ventanas MMIO, si tiene puerto
 * serie-- entra por parametro desde su `top.v`, que es donde vive el
 * razonamiento de ese prototipo. Antes habia diez ficheros parecidos, y
 * "parecidos" es justo lo que hace que un arreglo se aplique en nueve.
 *
 * Lo comprueba `x.tests/test_monitor_port.py`: si dos copias dejan de ser
 * identicas, falla.
 *
 * DOS JUEGOS DE COMANDOS, y el mayor de la version dice cual: 1 es el juego
 * base (13 comandos) y 2 es base + serie (15). El menor es el numero de
 * carpeta. Ver docs/unificacion-mmio.md fase 5.
 * ---------------------------------------------------------------------------
 *
 * Addresses and lengths are transferred most-significant byte first. Block
 * lengths must be between 1 and 256 bytes. The memory reports invalid ranges.
 * The host must wait for the complete response before sending another command.
 *
 * READ_WORD devuelve los cuatro bytes en little-endian y EXIGE la direccion
 * alineada a 4. Existe porque un registro MMIO de 32 bits leido con cuatro
 * READ_BYTE puede salir PARTIDO: entre el primero y el cuarto pasa cerca de un
 * milisegundo de serie, y hay registros que siguen vivos con el nucleo parado
 * --frame_count avanza con el scanout. Una transaccion de bus ya produce la
 * palabra entera, asi que READ_WORD es atomico POR CONSTRUCCION.
 * Ver docs/unificacion-mmio.md fase 3.4.
 */
module monitor #(
    // Version que contesta GET_VERSION. MAYOR = juego de comandos, MENOR =
    // numero de carpeta. El porque de cada valor se explica donde se instancia:
    // es razonamiento de cada prototipo, no de este fichero.
    //
    // Los defaults son CENTINELAS, no valores plausibles: menor 0 no es ninguna
    // carpeta, asi que una placa que conteste `x.0` esta diciendo que su `top`
    // se olvido del parametro. Un default plausible convertiria ese olvido en
    // una placa que miente sobre quien es.
    parameter [7:0] VERSION_MAJOR = 8'd1,
    parameter [7:0] VERSION_MINOR = 8'd0,

    // 1 si este prototipo tiene puerto serie de CPU (SEND_BYTES/RECV_BYTES).
    // Con 0 los dos comandos contestan `ff` como cualquier otro desconocido, y
    // la sintesis se lleva por delante sus estados y sus puertos.
    parameter HAS_SERIAL = 0,

    // Primer byte que ya NO es RAM. 32 KiB en la 6, 128 KiB de BRAM en la 12,
    // 32 MiB de SDRAM en las demas.
    //
    // El default es CERO --ninguna RAM-- por la misma razon que el de la
    // version: un `top` que se olvide del parametro rechaza todos los bloques
    // en el primer comando, en vez de aceptar callado un mapa que no es el suyo.
    parameter [32:0] RAM_END = 33'h0_0000_0000,

    // Ventanas MMIO que el monitor acepta ademas de la RAM. Una ranura sin usar
    // se deja en su default: base 33'h1_ffff_ffff es inalcanzable para una
    // direccion de 32 bits, asi que no casa nunca.
    //
    // Esta lista es la GEMELA de MONITOR_REGIONS en el monitor.py de la misma
    // carpeta, y las dos tienen que decir lo mismo. Anadir una ventana en el
    // decodificador no basta: si no se anade tambien aqui, el monitor rechaza
    // el comando antes de que llegue al decodificador, y el sintoma es un NACK
    // que parece un bitstream viejo o un mapa mal escrito. Asi se perdio un
    // buen rato con 0x200/0x300.
    parameter [32:0] WINDOW0_BASE = 33'h1_ffff_ffff,
    parameter [32:0] WINDOW0_END  = 33'h1_ffff_ffff,
    parameter [32:0] WINDOW1_BASE = 33'h1_ffff_ffff,
    parameter [32:0] WINDOW1_END  = 33'h1_ffff_ffff,
    parameter [32:0] WINDOW2_BASE = 33'h1_ffff_ffff,
    parameter [32:0] WINDOW2_END  = 33'h1_ffff_ffff,
    parameter [32:0] WINDOW3_BASE = 33'h1_ffff_ffff,
    parameter [32:0] WINDOW3_END  = 33'h1_ffff_ffff,
    parameter [32:0] WINDOW4_BASE = 33'h1_ffff_ffff,
    parameter [32:0] WINDOW4_END  = 33'h1_ffff_ffff
) (
    input clk,
    input reset,
    input [7:0] rx_data,
    input rx_strobe,
    output reg [7:0] tx_data,
    output reg tx_strobe,
    input tx_ready,
    output reg [31:0] mem_address,
    output reg [7:0] mem_write_data,
    output reg mem_write_enable,
    output reg mem_read_enable,
    input [7:0] mem_read_data,
    // La MISMA lectura sin trocear, para READ_WORD. Va al lado y no en lugar de
    // mem_read_data: ensanchar el puerto de byte truncaria en silencio en los
    // bancos que lo declaran de 8 bits.
    input [31:0] mem_read_word,
    input mem_ready,
    input mem_error,

    output reg cpu_run_request,
    output reg cpu_halt_request,
    output reg cpu_step_request,
    output reg cpu_reset_request,
    input cpu_halted,
    input cpu_error,
    input [7:0] cpu_error_code,
    input [31:0] cpu_pc,
    output reg [4:0] cpu_debug_register_address,
    input [31:0] cpu_debug_register_data,

    // Puerto serie de la CPU. El monitor solo desencapsula: mete en la cola de
    // entrada lo que trae SEND_BYTES y saca de la de salida lo que pide
    // RECV_BYTES. Ni un pin ni un baudio propio; ver serial_port.v.
    //
    // Los puertos existen SIEMPRE, tambien con HAS_SERIAL = 0. Ponerlos dentro
    // de un `generate` haria que la lista de puertos dependiera de un
    // parametro, y entonces el fichero ya no seria uno: cada `top` tendria que
    // saber cual de las dos formas esta instanciando. Un `top` sin serie ata
    // las entradas a cero y deja las salidas al aire, y la sintesis se lo lleva
    // todo por delante.
    output reg serial_push,
    output reg [7:0] serial_push_data,
    input [7:0] serial_rx_free,
    output reg serial_pop,
    input [7:0] serial_tx_data,
    input [7:0] serial_tx_count,

    output reg [7:0] last_command,
    output busy
);

  localparam [7:0] CMD_PING = 8'h01;
  localparam [7:0] CMD_GET_VERSION = 8'h02;
  localparam [7:0] CMD_WRITE_BYTE = 8'h10;
  localparam [7:0] CMD_READ_BYTE = 8'h11;
  localparam [7:0] CMD_READ_WORD = 8'h12;
  localparam [7:0] CMD_WRITE_BLOCK = 8'h20;
  localparam [7:0] CMD_READ_BLOCK = 8'h21;
  localparam [7:0] CMD_RUN = 8'h30;
  localparam [7:0] CMD_HALT = 8'h31;
  localparam [7:0] CMD_STEP = 8'h32;
  localparam [7:0] CMD_GET_STATUS = 8'h33;
  localparam [7:0] CMD_READ_REGISTER = 8'h34;
  localparam [7:0] CMD_RESET_CPU = 8'h35;
  localparam [7:0] CMD_SEND_BYTES = 8'h38;
  localparam [7:0] CMD_RECV_BYTES = 8'h39;
  localparam [7:0] RSP_PONG = 8'h81;
  localparam [7:0] RSP_VERSION = 8'h82;
  localparam [7:0] RSP_WRITE_BYTE = 8'h90;
  localparam [7:0] RSP_READ_BYTE = 8'h91;
  localparam [7:0] RSP_READ_WORD = 8'h92;
  localparam [7:0] RSP_WRITE_BLOCK = 8'ha0;
  localparam [7:0] RSP_READ_BLOCK = 8'ha1;
  localparam [7:0] RSP_RUN = 8'hb0;
  localparam [7:0] RSP_HALT = 8'hb1;
  localparam [7:0] RSP_STEP = 8'hb2;
  localparam [7:0] RSP_STATUS = 8'hb3;
  localparam [7:0] RSP_READ_REGISTER = 8'hb4;
  localparam [7:0] RSP_RESET_CPU = 8'hb5;
  localparam [7:0] RSP_SEND_BYTES = 8'hb8;
  localparam [7:0] RSP_RECV_BYTES = 8'hb9;
  localparam [7:0] RSP_ERROR = 8'hff;

  localparam [5:0] STATE_IDLE = 6'd0;
  localparam [5:0] STATE_WRITE_ADDRESS_HIGH = 6'd1;
  localparam [5:0] STATE_WRITE_ADDRESS_LOW = 6'd2;
  localparam [5:0] STATE_WRITE_DATA = 6'd3;
  localparam [5:0] STATE_WAIT_WRITE = 6'd4;
  localparam [5:0] STATE_READ_ADDRESS_HIGH = 6'd5;
  localparam [5:0] STATE_READ_ADDRESS_LOW = 6'd6;
  localparam [5:0] STATE_WAIT_READ = 6'd7;
  localparam [5:0] STATE_RESPOND = 6'd8;
  localparam [5:0] STATE_WAIT_TX_ACCEPT = 6'd9;
  localparam [5:0] STATE_BLOCK_ADDRESS_HIGH = 6'd10;
  localparam [5:0] STATE_BLOCK_ADDRESS_LOW = 6'd11;
  localparam [5:0] STATE_BLOCK_LENGTH_HIGH = 6'd12;
  localparam [5:0] STATE_BLOCK_LENGTH_LOW = 6'd13;
  localparam [5:0] STATE_BLOCK_WRITE_DATA = 6'd14;
  localparam [5:0] STATE_BLOCK_WAIT_WRITE = 6'd15;
  localparam [5:0] STATE_BLOCK_READ_REQUEST = 6'd16;
  localparam [5:0] STATE_BLOCK_WAIT_READ = 6'd17;
  localparam [5:0] STATE_PREPARE_READ = 6'd18;
  localparam [5:0] STATE_BLOCK_PREPARE_READ = 6'd19;
  localparam [5:0] STATE_WRITE_ADDRESS_2 = 6'd20;
  localparam [5:0] STATE_WRITE_ADDRESS_1 = 6'd21;
  localparam [5:0] STATE_READ_ADDRESS_2 = 6'd22;
  localparam [5:0] STATE_READ_ADDRESS_1 = 6'd23;
  localparam [5:0] STATE_BLOCK_ADDRESS_2 = 6'd24;
  localparam [5:0] STATE_BLOCK_ADDRESS_1 = 6'd25;
  localparam [5:0] STATE_READ_REGISTER_ADDRESS = 6'd26;
  localparam [5:0] STATE_PREPARE_REGISTER = 6'd27;
  localparam [5:0] STATE_WAIT_REGISTER_1 = 6'd28;
  localparam [5:0] STATE_WAIT_REGISTER_2 = 6'd29;
  localparam [5:0] STATE_DECODE_COMMAND = 6'd30;
  // Block range checking is pipelined to keep rx_data off the wide adder path.
  localparam [5:0] STATE_VALIDATE_BLOCK = 6'd31;
  localparam [5:0] STATE_CALCULATE_BLOCK_END = 6'd32;
  // Puerto serie. SEND_BYTES consume SIEMPRE los LL bytes del paquete aunque la
  // cola se llene: si se cortara a medias, los que quedan en el cable se leerian
  // como comandos y el enlace se desincroniza. Lo que se devuelve es cuantos
  // entraron, y con eso el PC reenvia el resto.
  localparam [5:0] STATE_SERIAL_SEND_LENGTH = 6'd33;
  localparam [5:0] STATE_SERIAL_SEND_DATA = 6'd34;
  localparam [5:0] STATE_SERIAL_RECV_MAX = 6'd35;
  localparam [5:0] STATE_SERIAL_RECV_COUNT = 6'd36;
  localparam [5:0] STATE_SERIAL_RECV_DATA = 6'd37;

  reg [5:0] state;
  reg [5:0] state_after_tx;
  reg [5:0] response_done_state;
  reg block_is_write;
  reg [15:0] block_length;
  reg [15:0] block_remaining;
  reg [32:0] block_end_address;
  reg [7:0] mem_read_data_latched;
  reg [31:0] mem_read_word_latched;
  // READ_WORD comparte los estados de direccion y de espera con
  // READ_BYTE; esto es lo unico que los distingue.
  reg word_access;
  reg mem_error_latched;
  reg [2:0] response_index;
  reg [2:0] response_length;
  reg [7:0] response_byte_0;
  reg [7:0] response_byte_1;
  reg [7:0] response_byte_2;
  reg [7:0] response_byte_3;
  reg [7:0] response_byte_4;
  reg [7:0] response_byte_5;
  reg [7:0] response_byte_6;
  (* keep = "true" *) reg [14:0] command_decoded;

  // Bytes que faltan del paquete serie en curso, y cuantos entraron en la cola.
  reg [7:0] serial_remaining;
  reg [7:0] serial_accepted;

  /*
   * Valida el intervalo COMPLETO, no solo su primera direccion: asi
   * WRITE_BLOCK y READ_BLOCK dicen lo mismo que el mapa que implementa el
   * decodificador, y un bloque que se sale se rechaza entero en vez de
   * escribirse a medias.
   *
   * Las dos funciones son combinacionales, pero sus entradas estan
   * REGISTRADAS: `mem_address`, `block_length` y `block_end_address` llevan un
   * ciclo puestas cuando se evaluan (ver STATE_CALCULATE_BLOCK_END). Eso es lo
   * que mantiene el sumador ancho fuera del camino del byte de UART, que es lo
   * que no cumplia a 120 MHz.
   */
  function in_window;
    input [32:0] start_address;
    input [32:0] end_address;
    input [32:0] window_base;
    input [32:0] window_end;
    begin
      in_window = (start_address >= window_base) && (end_address <= window_end);
    end
  endfunction

  function block_range_valid;
    input [32:0] start_address;
    input [32:0] end_address;
    begin
      block_range_valid =
          (start_address < RAM_END && end_address <= RAM_END) ||
          in_window(start_address, end_address, WINDOW0_BASE, WINDOW0_END) ||
          in_window(start_address, end_address, WINDOW1_BASE, WINDOW1_END) ||
          in_window(start_address, end_address, WINDOW2_BASE, WINDOW2_END) ||
          in_window(start_address, end_address, WINDOW3_BASE, WINDOW3_END) ||
          in_window(start_address, end_address, WINDOW4_BASE, WINDOW4_END);
    end
  endfunction

  assign busy = (state != STATE_IDLE);

  always @(posedge clk) begin
    tx_strobe <= 1'b0;
    mem_write_enable <= 1'b0;
    mem_read_enable <= 1'b0;
    cpu_run_request <= 1'b0;
    cpu_halt_request <= 1'b0;
    cpu_step_request <= 1'b0;
    cpu_reset_request <= 1'b0;
    // Pulsos de un ciclo hacia serial_port, igual que tx_strobe.
    serial_push <= 1'b0;
    serial_pop <= 1'b0;

    if (reset) begin
      tx_data <= 8'h00;
      tx_strobe <= 1'b0;
      mem_address <= 32'h0000_0000;
      mem_write_data <= 8'h00;
      mem_write_enable <= 1'b0;
      mem_read_enable <= 1'b0;
      cpu_run_request <= 1'b0;
      cpu_halt_request <= 1'b0;
      cpu_step_request <= 1'b0;
      cpu_reset_request <= 1'b0;
      cpu_debug_register_address <= 5'd0;
      last_command <= 8'h00;
      state <= STATE_IDLE;
      state_after_tx <= STATE_IDLE;
      response_done_state <= STATE_IDLE;
      block_is_write <= 1'b0;
      block_length <= 16'd0;
      block_remaining <= 16'd0;
      block_end_address <= 33'h000000000;
      mem_read_data_latched <= 8'h00;
      mem_read_word_latched <= 32'h0000_0000;
      word_access <= 1'b0;
      mem_error_latched <= 1'b0;
      response_index <= 3'd0;
      response_length <= 3'd0;
      response_byte_0 <= 8'h00;
      response_byte_1 <= 8'h00;
      response_byte_2 <= 8'h00;
      response_byte_3 <= 8'h00;
      response_byte_4 <= 8'h00;
      response_byte_5 <= 8'h00;
      response_byte_6 <= 8'h00;
      command_decoded <= 15'h0;
      serial_push <= 1'b0;
      serial_push_data <= 8'h00;
      serial_pop <= 1'b0;
      serial_remaining <= 8'd0;
      serial_accepted <= 8'd0;
    end else begin
      case (state)
        STATE_IDLE: begin
          if (rx_strobe) begin
            last_command <= rx_data;
            response_index <= 3'd0;
            command_decoded <= {
              rx_data == CMD_READ_WORD,
              rx_data == CMD_RECV_BYTES, rx_data == CMD_SEND_BYTES,
              rx_data == CMD_RESET_CPU, rx_data == CMD_READ_REGISTER,
              rx_data == CMD_GET_STATUS, rx_data == CMD_STEP,
              rx_data == CMD_HALT, rx_data == CMD_RUN,
              rx_data == CMD_READ_BLOCK, rx_data == CMD_WRITE_BLOCK,
              rx_data == CMD_READ_BYTE, rx_data == CMD_WRITE_BYTE,
              rx_data == CMD_GET_VERSION, rx_data == CMD_PING
            };
            state <= STATE_DECODE_COMMAND;
          end
        end

        // Decode registered one-hot flags instead of putting the UART byte,
        // twelve comparisons and the complete command FSM in one 120 MHz path.
        STATE_DECODE_COMMAND: begin
            case (1'b1)
              command_decoded[0]: begin
                response_byte_0 <= RSP_PONG;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              command_decoded[1]: begin
                response_byte_0 <= RSP_VERSION;
                response_byte_1 <= VERSION_MAJOR;
                response_byte_2 <= VERSION_MINOR;
                response_length <= 3'd3;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              command_decoded[2]: state <= STATE_WRITE_ADDRESS_HIGH;
              command_decoded[3]: begin
                word_access <= 1'b0;
                state <= STATE_READ_ADDRESS_HIGH;
              end
              command_decoded[14]: begin
                word_access <= 1'b1;
                state <= STATE_READ_ADDRESS_HIGH;
              end
              command_decoded[4]: begin
                block_is_write <= 1'b1;
                state <= STATE_BLOCK_ADDRESS_HIGH;
              end
              command_decoded[5]: begin
                block_is_write <= 1'b0;
                state <= STATE_BLOCK_ADDRESS_HIGH;
              end
              // RUN y STEP exigen parado Y SIN ERROR. La familia GPU ya lo
              // hacia asi y la CPU no: arrancar sobre un error latcheado
              // contestaba `b0` y volvia a parar en el acto, asi que el host
              // veia un arranque que no arranco. Con `ff` el host sabe que
              // tiene que resetear primero, que es lo unico que lo despeja.
              command_decoded[6]: begin
                response_byte_0 <= (cpu_halted && !cpu_error) ? RSP_RUN : RSP_ERROR;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                if (cpu_halted && !cpu_error) cpu_run_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              command_decoded[7]: begin
                response_byte_0 <= RSP_HALT;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                cpu_halt_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              command_decoded[8]: begin
                response_byte_0 <= (cpu_halted && !cpu_error) ? RSP_STEP : RSP_ERROR;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                if (cpu_halted && !cpu_error) cpu_step_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              command_decoded[9]: begin
                response_byte_0 <= RSP_STATUS;
                response_byte_1 <= {6'b000000, cpu_error, cpu_halted};
                response_byte_2 <= cpu_error_code;
                response_byte_3 <= cpu_pc[31:24];
                response_byte_4 <= cpu_pc[23:16];
                response_byte_5 <= cpu_pc[15:8];
                response_byte_6 <= cpu_pc[7:0];
                response_length <= 3'd7;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              command_decoded[10]: state <= STATE_READ_REGISTER_ADDRESS;
              command_decoded[11]: begin
                response_byte_0 <= RSP_RESET_CPU;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                cpu_reset_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              // Los dos del puerto serie. Con HAS_SERIAL = 0 la condicion es
              // constante-falsa, cae al `default` --contesta `ff`, como
              // cualquier comando desconocido-- y la sintesis se lleva por
              // delante los cinco estados de abajo.
              (HAS_SERIAL != 0) && command_decoded[12]:
                  state <= STATE_SERIAL_SEND_LENGTH;
              (HAS_SERIAL != 0) && command_decoded[13]:
                  state <= STATE_SERIAL_RECV_MAX;
              default: begin
                response_byte_0 <= RSP_ERROR;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
            endcase
        end

        STATE_READ_REGISTER_ADDRESS: begin
          if (rx_strobe) begin
            if (rx_data[7:5] != 3'b000 || !cpu_halted) begin
              response_byte_0 <= RSP_ERROR;
              response_length <= 3'd1;
              response_index <= 3'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else begin
              cpu_debug_register_address <= rx_data[4:0];
              state <= STATE_WAIT_REGISTER_1;
            end
          end
        end

        STATE_WAIT_REGISTER_1: state <= STATE_WAIT_REGISTER_2;
        STATE_WAIT_REGISTER_2: state <= STATE_PREPARE_REGISTER;

        STATE_PREPARE_REGISTER: begin
          response_byte_0 <= RSP_READ_REGISTER;
          response_byte_1 <= cpu_debug_register_data[31:24];
          response_byte_2 <= cpu_debug_register_data[23:16];
          response_byte_3 <= cpu_debug_register_data[15:8];
          response_byte_4 <= cpu_debug_register_data[7:0];
          response_length <= 3'd5;
          response_index <= 3'd0;
          response_done_state <= STATE_IDLE;
          state <= STATE_RESPOND;
        end

        STATE_WRITE_ADDRESS_HIGH: begin
          if (rx_strobe) begin
            mem_address[31:24] <= rx_data;
            state <= STATE_WRITE_ADDRESS_2;
          end
        end
        STATE_WRITE_ADDRESS_2: begin
          if (rx_strobe) begin
            mem_address[23:16] <= rx_data;
            state <= STATE_WRITE_ADDRESS_1;
          end
        end
        STATE_WRITE_ADDRESS_1: begin
          if (rx_strobe) begin
            mem_address[15:8] <= rx_data;
            state <= STATE_WRITE_ADDRESS_LOW;
          end
        end
        STATE_WRITE_ADDRESS_LOW: begin
          if (rx_strobe) begin
            mem_address[7:0] <= rx_data;
            state <= STATE_WRITE_DATA;
          end
        end
        STATE_WRITE_DATA: begin
          if (rx_strobe) begin
            mem_write_data <= rx_data;
            mem_write_enable <= 1'b1;
            state <= STATE_WAIT_WRITE;
          end
        end
        STATE_WAIT_WRITE: begin
          if (mem_ready) begin
            response_byte_0 <= mem_error ? RSP_ERROR : RSP_WRITE_BYTE;
            response_length <= 3'd1;
            response_index <= 3'd0;
            response_done_state <= STATE_IDLE;
            state <= STATE_RESPOND;
          end
        end

        STATE_READ_ADDRESS_HIGH: begin
          if (rx_strobe) begin
            mem_address[31:24] <= rx_data;
            state <= STATE_READ_ADDRESS_2;
          end
        end
        STATE_READ_ADDRESS_2: begin
          if (rx_strobe) begin
            mem_address[23:16] <= rx_data;
            state <= STATE_READ_ADDRESS_1;
          end
        end
        STATE_READ_ADDRESS_1: begin
          if (rx_strobe) begin
            mem_address[15:8] <= rx_data;
            state <= STATE_READ_ADDRESS_LOW;
          end
        end
        STATE_READ_ADDRESS_LOW: begin
          if (rx_strobe) begin
            mem_address[7:0] <= rx_data;
            // READ_WORD exige alineamiento a 4: la memoria entrega la palabra
            // que CONTIENE la direccion, asi que una no alineada devolveria una
            // palabra distinta de la pedida. Mejor rechazarla que mentir.
            if (word_access && rx_data[1:0] != 2'b00) begin
              response_byte_0 <= RSP_ERROR;
              response_length <= 3'd1;
              response_index <= 3'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else begin
              mem_read_enable <= 1'b1;
              state <= STATE_WAIT_READ;
            end
          end
        end
        STATE_WAIT_READ: begin
          if (mem_ready) begin
            // Deliberate pipeline stage: register the RAM output before using it
            // to build the UART response. Without this extra cycle, the path from
            // block RAM through the response-selection logic failed timing at
            // 120 MHz. Review STATE_PREPARE_READ to understand this boundary.
            mem_read_data_latched <= mem_read_data;
            mem_read_word_latched <= mem_read_word;
            mem_error_latched <= mem_error;
            state <= STATE_PREPARE_READ;
          end
        end
        STATE_PREPARE_READ: begin
          if (mem_error_latched) begin
            response_byte_0 <= RSP_ERROR;
            response_length <= 3'd1;
          end else if (word_access) begin
            // Little-endian, el mismo orden que la memoria. Los cuatro bytes
            // salen de UNA transaccion de bus: eso es lo que la hace atomica.
            response_byte_0 <= RSP_READ_WORD;
            response_byte_1 <= mem_read_word_latched[7:0];
            response_byte_2 <= mem_read_word_latched[15:8];
            response_byte_3 <= mem_read_word_latched[23:16];
            response_byte_4 <= mem_read_word_latched[31:24];
            response_length <= 3'd5;
          end else begin
            response_byte_0 <= RSP_READ_BYTE;
            response_byte_1 <= mem_read_data_latched;
            response_length <= 3'd2;
          end
          response_index <= 3'd0;
          response_done_state <= STATE_IDLE;
          state <= STATE_RESPOND;
        end

        STATE_BLOCK_ADDRESS_HIGH: begin
          if (rx_strobe) begin
            mem_address[31:24] <= rx_data;
            state <= STATE_BLOCK_ADDRESS_2;
          end
        end
        STATE_BLOCK_ADDRESS_2: begin
          if (rx_strobe) begin
            mem_address[23:16] <= rx_data;
            state <= STATE_BLOCK_ADDRESS_1;
          end
        end
        STATE_BLOCK_ADDRESS_1: begin
          if (rx_strobe) begin
            mem_address[15:8] <= rx_data;
            state <= STATE_BLOCK_ADDRESS_LOW;
          end
        end
        STATE_BLOCK_ADDRESS_LOW: begin
          if (rx_strobe) begin
            mem_address[7:0] <= rx_data;
            state <= STATE_BLOCK_LENGTH_HIGH;
          end
        end
        STATE_BLOCK_LENGTH_HIGH: begin
          if (rx_strobe) begin
            block_length[15:8] <= rx_data;
            state <= STATE_BLOCK_LENGTH_LOW;
          end
        end
        STATE_BLOCK_LENGTH_LOW: begin
          if (rx_strobe) begin
            block_length[7:0] <= rx_data;
            block_remaining <= {block_length[15:8], rx_data};
            state <= STATE_CALCULATE_BLOCK_END;
          end
        end

        // Keep the wide address addition in its own registered stage.
        STATE_CALCULATE_BLOCK_END: begin
          block_end_address <=
              {1'b0, mem_address} + {17'd0, block_length};
          state <= STATE_VALIDATE_BLOCK;
        end

        // Validate after registering both the length and exclusive end.
        // The end address is exclusive, so a one-byte transfer at 0x01ffffff
        // is valid and ends exactly at 0x02000000.
        STATE_VALIDATE_BLOCK: begin
            if (block_length == 0 || block_length > 16'd256 ||
                !block_range_valid({1'b0, mem_address}, block_end_address)) begin
              response_byte_0 <= RSP_ERROR;
              response_length <= 3'd1;
              response_index <= 3'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else if (block_is_write) begin
              state <= STATE_BLOCK_WRITE_DATA;
            end else begin
              response_byte_0 <= RSP_READ_BLOCK;
              response_length <= 3'd1;
              response_index <= 3'd0;
              response_done_state <= STATE_BLOCK_READ_REQUEST;
              state <= STATE_RESPOND;
            end
        end
        STATE_BLOCK_WRITE_DATA: begin
          if (rx_strobe) begin
            mem_write_data <= rx_data;
            mem_write_enable <= 1'b1;
            state <= STATE_BLOCK_WAIT_WRITE;
          end
        end
        STATE_BLOCK_WAIT_WRITE: begin
          if (mem_ready) begin
            if (mem_error) begin
              response_byte_0 <= RSP_ERROR;
              response_length <= 3'd1;
              response_index <= 3'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else if (block_remaining == 1) begin
              response_byte_0 <= RSP_WRITE_BLOCK;
              response_length <= 3'd1;
              response_index <= 3'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else begin
              mem_address <= mem_address + 1'b1;
              block_remaining <= block_remaining - 1'b1;
              state <= STATE_BLOCK_WRITE_DATA;
            end
          end
        end
        STATE_BLOCK_READ_REQUEST: begin
          mem_read_enable <= 1'b1;
          state <= STATE_BLOCK_WAIT_READ;
        end
        STATE_BLOCK_WAIT_READ: begin
          if (mem_ready) begin
            // The block-read path uses the same intentional RAM-output register.
            // Review STATE_BLOCK_PREPARE_READ when studying the read pipeline.
            mem_read_data_latched <= mem_read_data;
            mem_error_latched <= mem_error;
            state <= STATE_BLOCK_PREPARE_READ;
          end
        end
        STATE_BLOCK_PREPARE_READ: begin
          response_byte_0 <= mem_error_latched ? RSP_ERROR : mem_read_data_latched;
          response_length <= 3'd1;
          response_index <= 3'd0;

          if (mem_error_latched || block_remaining == 1) begin
            response_done_state <= STATE_IDLE;
          end else begin
            mem_address <= mem_address + 1'b1;
            block_remaining <= block_remaining - 1'b1;
            response_done_state <= STATE_BLOCK_READ_REQUEST;
          end
          state <= STATE_RESPOND;
        end

        STATE_RESPOND: begin
          if (tx_ready) begin
            case (response_index)
              3'd0: tx_data <= response_byte_0;
              3'd1: tx_data <= response_byte_1;
              3'd2: tx_data <= response_byte_2;
              3'd3: tx_data <= response_byte_3;
              3'd4: tx_data <= response_byte_4;
              3'd5: tx_data <= response_byte_5;
              default: tx_data <= response_byte_6;
            endcase

            tx_strobe <= 1'b1;
            if (response_index + 1 >= response_length) begin
              state_after_tx <= response_done_state;
            end else begin
              response_index <= response_index + 1'b1;
              state_after_tx <= STATE_RESPOND;
            end
            state <= STATE_WAIT_TX_ACCEPT;
          end
        end
        STATE_WAIT_TX_ACCEPT: begin
          if (!tx_ready) begin
            state <= state_after_tx;
          end
        end

        // -------------------------------------------------------------------
        // SEND_BYTES: 38 LL <LL bytes> -> b8 NN
        //
        // NN puede ser menor que LL, y eso NO es un error: es el control de
        // flujo. Si la cola tiene veinte huecos y llegan sesenta, entran veinte
        // y el PC reenvia el resto. La alternativa --rechazar el paquete entero
        // o tragarselo y perder lo que no cabe-- deja al usuario perdiendo
        // pulsaciones solo cuando escribe rapido, que es el fallo mas caro de
        // diagnosticar que existe.
        // -------------------------------------------------------------------
        STATE_SERIAL_SEND_LENGTH: begin
          if (rx_strobe) begin
            serial_remaining <= rx_data;
            serial_accepted <= 8'd0;
            if (rx_data == 8'd0) begin
              // Longitud cero es legal y util: sirve de sondeo sin escribir.
              response_byte_0 <= RSP_SEND_BYTES;
              response_byte_1 <= 8'd0;
              response_length <= 3'd2;
              response_index <= 3'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else begin
              state <= STATE_SERIAL_SEND_DATA;
            end
          end
        end

        STATE_SERIAL_SEND_DATA: begin
          if (rx_strobe) begin
            // Se consume el byte pase lo que pase; solo se mete si cabe.
            if (serial_rx_free != 8'd0) begin
              serial_push <= 1'b1;
              serial_push_data <= rx_data;
              serial_accepted <= serial_accepted + 1'b1;
            end
            serial_remaining <= serial_remaining - 1'b1;
            if (serial_remaining == 8'd1) begin
              response_byte_0 <= RSP_SEND_BYTES;
              // `serial_accepted` todavia no se ha actualizado en este ciclo.
              response_byte_1 <= (serial_rx_free != 8'd0) ?
                                 serial_accepted + 8'd1 : serial_accepted;
              response_length <= 3'd2;
              response_index <= 3'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end
          end
        end

        // -------------------------------------------------------------------
        // RECV_BYTES: 39 MM -> b9 NN <NN bytes>
        //
        // NN = min(MM, bytes en la cola de salida), y puede ser cero: sondear
        // una cola vacia es lo normal en un terminal.
        // -------------------------------------------------------------------
        STATE_SERIAL_RECV_MAX: begin
          if (rx_strobe) begin
            serial_remaining <= (rx_data < serial_tx_count) ? rx_data
                                                            : serial_tx_count;
            response_byte_0 <= RSP_RECV_BYTES;
            response_length <= 3'd1;
            response_index <= 3'd0;
            response_done_state <= STATE_SERIAL_RECV_COUNT;
            state <= STATE_RESPOND;
          end
        end

        STATE_SERIAL_RECV_COUNT: begin
          response_byte_0 <= serial_remaining;
          response_length <= 3'd1;
          response_index <= 3'd0;
          response_done_state <= (serial_remaining == 8'd0) ?
                                 STATE_IDLE : STATE_SERIAL_RECV_DATA;
          state <= STATE_RESPOND;
        end

        STATE_SERIAL_RECV_DATA: begin
          // La cabeza de la cola es combinacional, asi que ya esta aqui; sacar
          // y transmitir van juntos.
          response_byte_0 <= serial_tx_data;
          response_length <= 3'd1;
          response_index <= 3'd0;
          serial_pop <= 1'b1;
          serial_remaining <= serial_remaining - 1'b1;
          response_done_state <= (serial_remaining == 8'd1) ?
                                 STATE_IDLE : STATE_SERIAL_RECV_DATA;
          state <= STATE_RESPOND;
        end

        default: state <= STATE_IDLE;
      endcase
    end
  end
endmodule

`default_nettype wire
