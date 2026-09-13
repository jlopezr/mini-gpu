`default_nettype none

/*
 * Minimal UART monitor protocol.
 *
 * Requests and responses:
 *   01             (PING)        -> 81
 *   02             (GET_VERSION) -> 82 01 0e
 *   10 A3 A2 A1 A0 DD          (WRITE_BYTE)  -> 90 (or ff)
 *   11 A3 A2 A1 A0             (READ_BYTE)   -> 91 DD (or ff)
 *   20 A3 A2 A1 A0 LL LL DD... (WRITE_BLOCK) -> a0 (or ff)
 *   21 A3 A2 A1 A0 LL LL       (READ_BLOCK)  -> a1 DD... (or ff)
 *   30             (RUN)         -> b0 (or ff)
 *   31             (HALT)        -> b1
 *   32             (STEP)        -> b2 (or ff)
 *   33             (GET_STATUS)  -> b3 FLAGS ERROR PC3 PC2 PC1 PC0
 *   34 RR          (READ_REG)    -> b4 D3 D2 D1 D0 (or ff)
 *   35             (RESET_CPU)   -> b5
 *   36             (GET_CYCLES)  -> b6 C3 C2 C1 C0
 *   37             (GET_INSTR)   -> b7 I3 I2 I1 I0
 *   38 LL DD...    (SEND_BYTES)  -> b8 NN     NN aceptados, puede ser < LL
 *   39 MM          (RECV_BYTES)  -> b9 NN DD... NN <= MM, puede ser 0
 *   any other command            -> ff
 *
 * SEND_BYTES y RECV_BYTES son el puerto serie de la CPU. Funcionan con la CPU
 * EN MARCHA, porque no tocan la SDRAM. `NN` es el control de flujo: el que
 * devuelve SEND_BYTES dice cuantos cupieron en la cola, y el resto se reenvia.
 *
 * Addresses and lengths are transferred most-significant byte first. Block
 * lengths must be between 1 and 256 bytes. The memory reports invalid ranges.
 * The host must wait for the complete response before sending another command.
 */
module monitor (
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
    // Contadores de rendimiento de UNA ejecucion. Los lleva top.v, que es
    // quien ve `instruction_retired` y el reloj.
    input [31:0] cpu_cycles,
    input [31:0] cpu_instructions,
    output reg [4:0] cpu_debug_register_address,
    input [31:0] cpu_debug_register_data,

    // Puerto serie de la CPU. El monitor solo desencapsula: mete en la cola de
    // entrada lo que trae SEND_BYTES y saca de la de salida lo que pide
    // RECV_BYTES. Ni un pin ni un baudio propio; ver serial_port.v.
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
  localparam [7:0] CMD_WRITE_BLOCK = 8'h20;
  localparam [7:0] CMD_READ_BLOCK = 8'h21;
  localparam [7:0] CMD_RUN = 8'h30;
  localparam [7:0] CMD_HALT = 8'h31;
  localparam [7:0] CMD_STEP = 8'h32;
  localparam [7:0] CMD_GET_STATUS = 8'h33;
  localparam [7:0] CMD_READ_REGISTER = 8'h34;
  localparam [7:0] CMD_RESET_CPU = 8'h35;
  // Contadores de rendimiento. Son DOS comandos y no uno porque la respuesta
  // maxima de este monitor son siete bytes: dos contadores de 32 bits mas la
  // cabecera serian nueve. Leerlos por separado no es problema, porque solo
  // tienen sentido con la CPU parada, y entonces no cambian.
  localparam [7:0] CMD_GET_CYCLES = 8'h36;
  localparam [7:0] CMD_GET_INSTRUCTIONS = 8'h37;
  localparam [7:0] CMD_SEND_BYTES = 8'h38;
  localparam [7:0] CMD_RECV_BYTES = 8'h39;
  localparam [7:0] RSP_PONG = 8'h81;
  localparam [7:0] RSP_VERSION = 8'h82;
  localparam [7:0] RSP_WRITE_BYTE = 8'h90;
  localparam [7:0] RSP_READ_BYTE = 8'h91;
  localparam [7:0] RSP_WRITE_BLOCK = 8'ha0;
  localparam [7:0] RSP_READ_BLOCK = 8'ha1;
  localparam [7:0] RSP_RUN = 8'hb0;
  localparam [7:0] RSP_HALT = 8'hb1;
  localparam [7:0] RSP_STEP = 8'hb2;
  localparam [7:0] RSP_STATUS = 8'hb3;
  localparam [7:0] RSP_READ_REGISTER = 8'hb4;
  localparam [7:0] RSP_RESET_CPU = 8'hb5;
  localparam [7:0] RSP_CYCLES = 8'hb6;
  localparam [7:0] RSP_INSTRUCTIONS = 8'hb7;
  localparam [7:0] RSP_SEND_BYTES = 8'hb8;
  localparam [7:0] RSP_RECV_BYTES = 8'hb9;
  localparam [7:0] RSP_ERROR = 8'hff;
  localparam [7:0] VERSION_MAJOR = 8'h01;
  // 1.5 fue el mapa unificado sobre SDRAM de 10.fpga-cpu-ram. Esta rama sube
  // la version cada vez que cambia algo que el PC no puede negociar:
  //   1.7  se anade el subsistema de video
  //   1.8  el reloj baja a 100 MHz y el monitor a 2 Mbaud
  //   1.9  el baudio se corrige a 1 Mbaud (2 Mbaud daba un divisor no
  //        multiplo de 4 y la recepcion fallaba la mitad de las veces)
  //   1.10 el arbitro engancha el pulso del monitor; hasta 1.9 se perdia si
  //        coincidia con el video y la placa se quedaba muda hasta el reset
  //   1.11 camino de memoria de rafagas BL8: controlador de 128 bits, arbitro
  //        de cuatro puertos y un adaptador por cliente. El reloj baja a
  //        80 MHz porque a 100 no cumple ninguna semilla. El baudio NO cambia:
  //        divisor 80 sigue dando 1 Mbaud exacto, y por eso se eligio 80 MHz.
  //   1.12 contadores de ciclos e instrucciones, con GET_CYCLES (0x36) y
  //        GET_INSTRUCTIONS (0x37). Sin ellos no hay forma de medir CPI en la
  //        placa: `instruction_retired` estaba cableado en top.v y no iba a
  //        ninguna parte.
  //   1.13 la CPU gana los accesos de 8 y 16 bits (0x18..0x1D) y las llamadas
  //        JAL/JALR/JR (0x2C..0x2E). El PROTOCOLO no cambia: ni un comando
  //        nuevo, ni un campo distinto. Sube igual porque la version es lo
  //        unico que el PC puede preguntar antes de cargar un programa, y un
  //        programa que use esas instrucciones no corre en un bitstream 1.12:
  //        para con ERROR_INVALID_OPCODE a la primera. Sin este numero,
  //        x.cpu-tests no puede distinguir la 18 de la 19 y cargaria la que no
  //        es, o peor, no cargaria nada y culparia al programa.
  //   1.14 puerto serie: SEND_BYTES (0x38) y RECV_BYTES (0x39). Aqui si cambia
  //        el protocolo, y ademas son los dos primeros comandos que mueven
  //        datos con la CPU EN MARCHA: no tocan la SDRAM, asi que no pasan por
  //        la condicion `cpu_halted` del adaptador.
  // BACKPORT DE R0 CABLEADO A CERO. `R0` paso a valer siempre cero y a
  // descartar las escrituras, que es un cambio INCOMPATIBLE con lo que hacia
  // esta carpeta antes: un programa que use `R0` como registro general no para
  // con error, da otro resultado en silencio. Por eso sube la version aunque el
  // protocolo no cambie ni un byte, y por eso cada core tiene un numero propio
  // en vez de compartirlo. Ver 1.isa/isa.md seccion 1.
  localparam [7:0] VERSION_MINOR = 8'h14;

  localparam [4:0] STATE_IDLE = 5'd0;
  localparam [4:0] STATE_WRITE_ADDRESS_HIGH = 5'd1;
  localparam [4:0] STATE_WRITE_ADDRESS_LOW = 5'd2;
  localparam [4:0] STATE_WRITE_DATA = 5'd3;
  localparam [4:0] STATE_WAIT_WRITE = 5'd4;
  localparam [4:0] STATE_READ_ADDRESS_HIGH = 5'd5;
  localparam [4:0] STATE_READ_ADDRESS_LOW = 5'd6;
  localparam [4:0] STATE_WAIT_READ = 5'd7;
  localparam [4:0] STATE_RESPOND = 5'd8;
  localparam [4:0] STATE_WAIT_TX_ACCEPT = 5'd9;
  localparam [4:0] STATE_BLOCK_ADDRESS_HIGH = 5'd10;
  localparam [4:0] STATE_BLOCK_ADDRESS_LOW = 5'd11;
  localparam [4:0] STATE_BLOCK_LENGTH_HIGH = 5'd12;
  localparam [4:0] STATE_BLOCK_LENGTH_LOW = 5'd13;
  localparam [4:0] STATE_BLOCK_WRITE_DATA = 5'd14;
  localparam [4:0] STATE_BLOCK_WAIT_WRITE = 5'd15;
  localparam [4:0] STATE_BLOCK_READ_REQUEST = 5'd16;
  localparam [4:0] STATE_BLOCK_WAIT_READ = 5'd17;
  localparam [4:0] STATE_PREPARE_READ = 5'd18;
  localparam [4:0] STATE_BLOCK_PREPARE_READ = 5'd19;
  localparam [4:0] STATE_WRITE_ADDRESS_2 = 5'd20;
  localparam [4:0] STATE_WRITE_ADDRESS_1 = 5'd21;
  localparam [4:0] STATE_READ_ADDRESS_2 = 5'd22;
  localparam [4:0] STATE_READ_ADDRESS_1 = 5'd23;
  localparam [4:0] STATE_BLOCK_ADDRESS_2 = 5'd24;
  localparam [4:0] STATE_BLOCK_ADDRESS_1 = 5'd25;
  localparam [4:0] STATE_READ_REGISTER_ADDRESS = 5'd26;
  localparam [4:0] STATE_PREPARE_REGISTER = 5'd27;
  localparam [4:0] STATE_WAIT_REGISTER_1 = 5'd28;
  localparam [4:0] STATE_WAIT_REGISTER_2 = 5'd29;
  localparam [4:0] STATE_DECODE_COMMAND = 5'd30;
  // Block range checking is pipelined to keep rx_data off the wide adder path.
  localparam [4:0] STATE_VALIDATE_BLOCK = 5'd31;
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
  (* keep = "true" *) reg [15:0] command_decoded;

  // Bytes que faltan del paquete serie en curso, y cuantos entraron en la cola.
  reg [7:0] serial_remaining;
  reg [7:0] serial_accepted;

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
      mem_error_latched <= 1'b0;
      response_index <= 2'd0;
      response_length <= 2'd0;
      response_byte_0 <= 8'h00;
      response_byte_1 <= 8'h00;
      response_byte_2 <= 8'h00;
      response_byte_3 <= 8'h00;
      response_byte_4 <= 8'h00;
      response_byte_5 <= 8'h00;
      response_byte_6 <= 8'h00;
      command_decoded <= 16'h0000;
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
            response_index <= 2'd0;
            command_decoded <= {
              rx_data == CMD_RECV_BYTES, rx_data == CMD_SEND_BYTES,
              rx_data == CMD_GET_INSTRUCTIONS, rx_data == CMD_GET_CYCLES,
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
                response_length <= 2'd1;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              command_decoded[1]: begin
                response_byte_0 <= RSP_VERSION;
                response_byte_1 <= VERSION_MAJOR;
                response_byte_2 <= VERSION_MINOR;
                response_length <= 2'd3;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              command_decoded[2]: state <= STATE_WRITE_ADDRESS_HIGH;
              command_decoded[3]: state <= STATE_READ_ADDRESS_HIGH;
              command_decoded[4]: begin
                block_is_write <= 1'b1;
                state <= STATE_BLOCK_ADDRESS_HIGH;
              end
              command_decoded[5]: begin
                block_is_write <= 1'b0;
                state <= STATE_BLOCK_ADDRESS_HIGH;
              end
              command_decoded[6]: begin
                response_byte_0 <= cpu_halted ? RSP_RUN : RSP_ERROR;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                if (cpu_halted) cpu_run_request <= 1'b1;
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
                response_byte_0 <= cpu_halted ? RSP_STEP : RSP_ERROR;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                if (cpu_halted) cpu_step_request <= 1'b1;
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
              // Los dos contadores. Miden UNA ejecucion: se ponen a cero al
              // arrancar la CPU, no al resetearla, para que `run` / `halt` /
              // `run` den tres medidas y no una acumulada.
              command_decoded[12]: begin
                response_byte_0 <= RSP_CYCLES;
                response_byte_1 <= cpu_cycles[31:24];
                response_byte_2 <= cpu_cycles[23:16];
                response_byte_3 <= cpu_cycles[15:8];
                response_byte_4 <= cpu_cycles[7:0];
                response_length <= 3'd5;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              command_decoded[13]: begin
                response_byte_0 <= RSP_INSTRUCTIONS;
                response_byte_1 <= cpu_instructions[31:24];
                response_byte_2 <= cpu_instructions[23:16];
                response_byte_3 <= cpu_instructions[15:8];
                response_byte_4 <= cpu_instructions[7:0];
                response_length <= 3'd5;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              command_decoded[14]: state <= STATE_SERIAL_SEND_LENGTH;
              command_decoded[15]: state <= STATE_SERIAL_RECV_MAX;
              default: begin
                response_byte_0 <= RSP_ERROR;
                response_length <= 2'd1;
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
            response_length <= 2'd1;
            response_index <= 2'd0;
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
            mem_read_enable <= 1'b1;
            state <= STATE_WAIT_READ;
          end
        end
        STATE_WAIT_READ: begin
          if (mem_ready) begin
            // Deliberate pipeline stage: register the RAM output before using it
            // to build the UART response. Without this extra cycle, the path from
            // block RAM through the response-selection logic failed timing at
            // 120 MHz. Review STATE_PREPARE_READ to understand this boundary.
            mem_read_data_latched <= mem_read_data;
            mem_error_latched <= mem_error;
            state <= STATE_PREPARE_READ;
          end
        end
        STATE_PREPARE_READ: begin
          response_byte_0 <= mem_error_latched ? RSP_ERROR : RSP_READ_BYTE;
          response_byte_1 <= mem_read_data_latched;
          response_length <= mem_error_latched ? 2'd1 : 2'd2;
          response_index <= 2'd0;
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
                mem_address[31:25] != 0 ||
                block_end_address > 33'h02000000) begin
              response_byte_0 <= RSP_ERROR;
              response_length <= 2'd1;
              response_index <= 2'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else if (block_is_write) begin
              state <= STATE_BLOCK_WRITE_DATA;
            end else begin
              response_byte_0 <= RSP_READ_BLOCK;
              response_length <= 2'd1;
              response_index <= 2'd0;
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
              response_length <= 2'd1;
              response_index <= 2'd0;
              response_done_state <= STATE_IDLE;
              state <= STATE_RESPOND;
            end else if (block_remaining == 1) begin
              response_byte_0 <= RSP_WRITE_BLOCK;
              response_length <= 2'd1;
              response_index <= 2'd0;
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
          response_length <= 2'd1;
          response_index <= 2'd0;

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
              2'd0: tx_data <= response_byte_0;
              2'd1: tx_data <= response_byte_1;
              2'd2: tx_data <= response_byte_2;
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
