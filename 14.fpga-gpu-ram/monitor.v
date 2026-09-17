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
 *   any other command            -> ff
 *
 * Addresses and lengths are transferred most-significant byte first. Block
 * lengths must be between 1 and 256 bytes. The memory reports invalid ranges.
 * The host must wait for the complete response before sending another command.
 *
 * READ_WORD devuelve los cuatro bytes en orden little-endian, el mismo que usa
 * la memoria, y EXIGE la direccion alineada a 4. Existe porque un registro MMIO
 * de 32 bits leido con cuatro READ_BYTE puede salir PARTIDO: entre el primero y
 * el cuarto pasa cerca de un milisegundo de serie, y hay registros que siguen
 * vivos con el nucleo parado --frame_count avanza con el scanout, que cuelga de
 * reset y no de core_reset. Una transaccion de bus ya produce la palabra
 * entera, asi que READ_WORD es atomico POR CONSTRUCCION, sin depender de que
 * nadie congele nada. Ver docs/unificacion-mmio.md fase 3.4.
 */
module monitor #(
    // Version del protocolo que contesta GET_VERSION.  El porque de cada valor
    // se explica donde se instancia: es razonamiento de cada prototipo, no de
    // este fichero, que es COPIA IDENTICA en 12, 14, 17 y 22.
    parameter [7:0] VERSION_MAJOR = 8'd1,
    parameter [7:0] VERSION_MINOR = 8'd0,

    // Primer byte que ya NO es RAM.  128 KiB de BRAM en la 12, 32 MiB de SDRAM
    // en las demas.
    parameter [32:0] RAM_END = 33'h0_0200_0000,

    // Ventanas MMIO que el monitor acepta, ademas de la RAM.  Una ranura sin
    // usar se deja en el valor por defecto: base 33'h1_ffff_ffff es inalcanzable
    // para una direccion de 32 bits, asi que no casa nunca.
    parameter [32:0] WINDOW0_BASE = 33'h0_8000_0000,  // video
    parameter [32:0] WINDOW0_END  = 33'h0_8000_001c,
    parameter [32:0] WINDOW1_BASE = 33'h0_8000_0100,  // depuracion SIMT
    parameter [32:0] WINDOW1_END  = 33'h0_8000_0118,
    parameter [32:0] WINDOW2_BASE = 33'h0_8000_0300,  // contadores
    parameter [32:0] WINDOW2_END  = 33'h0_8000_0320,
    parameter [32:0] WINDOW3_BASE = 33'h0_8000_1000,  // configuracion de warps
    parameter [32:0] WINDOW3_END  = 33'h0_8000_1080,
    parameter [32:0] WINDOW4_BASE = 33'h0_8000_0f00,  // identificacion
    parameter [32:0] WINDOW4_END  = 33'h0_8000_0f10
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
    // mem_read_data a proposito: ensanchar el puerto de byte habria truncado en
    // silencio en los dieciocho bancos que lo declaran de 8 bits --seguirian
    // compilando, cogiendo el byte 0 en vez del de la direccion. Asi el camino
    // de READ_BYTE y de los bloques no se toca.
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
  localparam [7:0] RSP_ERROR = 8'hff;

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

  reg [4:0] state;
  reg [4:0] state_after_tx;
  reg [4:0] response_done_state;
  reg block_is_write;
  reg [15:0] block_length;
  reg [15:0] block_remaining;
  reg [7:0] mem_read_data_latched;
  reg [31:0] mem_read_word_latched;
  // READ_WORD comparte los estados de direccion y de espera con READ_BYTE; esto
  // es lo unico que los distingue, igual que `block_is_write` para los bloques.
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

  /*
   * Validate the complete byte interval, not just its first address.  The GPU
   * exposes RAM plus up to five disjoint monitor-only MMIO windows.
   * Keeping this check here makes WRITE_BLOCK and READ_BLOCK agree with the
   * byte commands and with the address map implemented by gpu_system.
   *
   * Esta lista es la GEMELA de MONITOR_REGIONS en monitor.py, y las dos tienen
   * que decir lo mismo.  Anadir una ventana en gpu_system_bl8 no basta: si no
   * se anade tambien aqui, el monitor rechaza el comando antes de que llegue al
   * decodificador, y el sintoma es un NACK que parece un bitstream viejo o un
   * mapa de memoria mal escrito.  Asi se perdio un buen rato con 0x200/0x300.
   *
   * Desde que el fichero es unico las ventanas llegan por parametro, asi que la
   * gemela de monitor.py esta ahora en el top de cada prototipo.
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
    input [31:0] start_address;
    input [15:0] length;
    reg [32:0] start_extended;
    reg [32:0] end_address;
    begin
      start_extended = {1'b0, start_address};
      end_address = start_extended + {17'b0, length};
      block_range_valid =
          (start_extended < RAM_END && end_address <= RAM_END) ||
          in_window(start_extended, end_address, WINDOW0_BASE, WINDOW0_END) ||
          in_window(start_extended, end_address, WINDOW1_BASE, WINDOW1_END) ||
          in_window(start_extended, end_address, WINDOW2_BASE, WINDOW2_END) ||
          in_window(start_extended, end_address, WINDOW3_BASE, WINDOW3_END) ||
          in_window(start_extended, end_address, WINDOW4_BASE, WINDOW4_END);
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
    end else begin
      case (state)
        STATE_IDLE: begin
          if (rx_strobe) begin
            last_command <= rx_data;
            response_index <= 3'd0;

            case (rx_data)
              CMD_PING: begin
                response_byte_0 <= RSP_PONG;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              CMD_GET_VERSION: begin
                response_byte_0 <= RSP_VERSION;
                response_byte_1 <= VERSION_MAJOR;
                response_byte_2 <= VERSION_MINOR;
                response_length <= 3'd3;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
              CMD_WRITE_BYTE: state <= STATE_WRITE_ADDRESS_HIGH;
              CMD_READ_BYTE: begin
                word_access <= 1'b0;
                state <= STATE_READ_ADDRESS_HIGH;
              end
              CMD_READ_WORD: begin
                word_access <= 1'b1;
                state <= STATE_READ_ADDRESS_HIGH;
              end
              CMD_WRITE_BLOCK: begin
                block_is_write <= 1'b1;
                state <= STATE_BLOCK_ADDRESS_HIGH;
              end
              CMD_READ_BLOCK: begin
                block_is_write <= 1'b0;
                state <= STATE_BLOCK_ADDRESS_HIGH;
              end
              CMD_RUN: begin
                response_byte_0 <= (cpu_halted && !cpu_error) ? RSP_RUN : RSP_ERROR;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                if (cpu_halted && !cpu_error) cpu_run_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              CMD_HALT: begin
                response_byte_0 <= RSP_HALT;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                cpu_halt_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              CMD_STEP: begin
                response_byte_0 <= (cpu_halted && !cpu_error) ? RSP_STEP : RSP_ERROR;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                if (cpu_halted && !cpu_error) cpu_step_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              CMD_GET_STATUS: begin
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
              CMD_READ_REGISTER: state <= STATE_READ_REGISTER_ADDRESS;
              CMD_RESET_CPU: begin
                response_byte_0 <= RSP_RESET_CPU;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                cpu_reset_request <= 1'b1;
                state <= STATE_RESPOND;
              end
              default: begin
                response_byte_0 <= RSP_ERROR;
                response_length <= 3'd1;
                response_done_state <= STATE_IDLE;
                state <= STATE_RESPOND;
              end
            endcase
          end
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
            // que contiene la direccion, asi que una no alineada devolveria una
            // palabra que no es la que se pidio. Mejor rechazarla que mentir.
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
            // salen de UNA transaccion de bus, que es lo que hace atomica la
            // lectura.
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

            if ({block_length[15:8], rx_data} == 0 ||
                {block_length[15:8], rx_data} > 16'd256 ||
                !block_range_valid(mem_address,
                    {block_length[15:8], rx_data})) begin
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
        default: state <= STATE_IDLE;
      endcase
    end
  end
endmodule

`default_nettype wire
