`timescale 1ns/1ps
`default_nettype none

/*
 * Modelo conductual de la SDRAM W9825G6KH, para simulacion.
 *
 * Existe porque el controlador BL8 llego sin un solo banco de pruebas, y un
 * controlador de SDRAM es el peor sitio donde descubrir errores en la placa.
 * El banco de la 16 comprueba que los COMANDOS salen con la temporizacion
 * JEDEC; lo que no puede comprobar, porque no hay memoria al otro lado, es que
 * los DATOS acaben donde deben. Eso es justo lo que se rompe con rafagas.
 *
 * El modelo hace tres cosas:
 *
 *   1. guarda y devuelve datos, con la latencia CAS y la secuencia de rafaga
 *      que diga el registro de modo;
 *   2. comprueba la secuencia de arranque: nada antes del retardo de encendido,
 *      precarga general, ocho refrescos y MRS, en ese orden;
 *   3. comprueba las temporizaciones JEDEC que el controlador podria violar
 *      —tRCD, tRP, tRAS, tRC, tRFC, tMRD— y cuenta cada violacion en `errors`,
 *      que el banco lee al terminar.
 *
 * Almacenamiento: 4 bancos x ROWS filas x 512 columnas. ROWS es pequeno a
 * proposito para que quepa en simulacion, y el modelo PROTESTA si se activa una
 * fila fuera de rango en vez de aliasear en silencio, que taparia justamente un
 * error de decodificacion de fila.
 *
 * Los tiempos se llevan con `time` y `$time`, no con `real`: con el timescale
 * de 1ns/1ps de este proyecto, `$time` ya viene en nanosegundos enteros, que es
 * la granularidad de todas las constantes JEDEC de esta pieza.
 */
module sdram_model #(
    parameter integer ROWS = 32,
    parameter integer POWERUP_DELAY_NS = 200_000,
    parameter integer TRP_NS = 20,
    parameter integer TRCD_NS = 20,
    parameter integer TRAS_NS = 42,
    parameter integer TRC_NS = 63,
    parameter integer TRFC_NS = 66,
    parameter integer TMRD_CYCLES = 2,
    parameter integer TWR_CYCLES = 2,
    parameter integer CLK_PERIOD_NS = 10,
    // Ciclos de retardo de ida y vuelta del bus de datos: cuanto mas tarde la
    // FPGA en VER el dato respecto a la latencia CAS nominal. Con 0 el modelo
    // es JEDEC sobre el papel; con 1 se parece a esta placa, donde el camino de
    // salida, el pin, la pista y el de vuelta pasan de un ciclo a 100 MHz.
    parameter integer READ_DELAY_CYCLES = 0
) (
    input  wire        clk,
    input  wire        cke,
    input  wire        csn,
    input  wire        rasn,
    input  wire        casn,
    input  wire        wen,
    input  wire [12:0] a,
    input  wire [1:0]  ba,
    input  wire [1:0]  dqm,
    inout  wire [15:0] dq
);
  localparam [3:0] CMD_MRS       = 4'b0000,
                   CMD_REFRESH   = 4'b0001,
                   CMD_PRECHARGE = 4'b0010,
                   CMD_ACTIVE    = 4'b0011,
                   CMD_WRITE     = 4'b0100,
                   CMD_READ      = 4'b0101,
                   CMD_BURST_END = 4'b0110,
                   CMD_NOP       = 4'b0111;

  localparam integer CELLS = 4 * ROWS * 512;

  reg [15:0] mem[0:CELLS-1];

  // Registro de modo, tal y como lo escribe el MRS.
  reg [12:0] mode_register;
  reg mode_set;
  wire mr_interleaved = mode_register[3];
  wire [2:0] mr_cas = mode_register[6:4];
  integer burst_length;

  // Estado por banco.
  reg bank_active[0:3];
  reg [12:0] bank_row[0:3];
  time t_active[0:3];
  time t_precharge[0:3];

  time t_last_refresh;
  integer cycles_since_mrs;

  // Tuberia de salida de lectura, indexada por ciclos que faltan.
  reg [15:0] read_pipe_data[0:7];
  reg read_pipe_valid[0:7];

  // Rafaga en curso.
  reg burst_read, burst_write;
  reg [1:0] burst_bank;
  reg [8:0] burst_col;
  reg burst_autoprecharge;
  integer burst_left;
  integer burst_index;

  reg [15:0] dq_out;
  reg dq_drive;
  assign dq = dq_drive ? dq_out : 16'hzzzz;

  wire [3:0] cmd_eff = csn ? CMD_NOP : {csn, rasn, casn, wen};

  integer errors;
  integer i;
  integer refresh_count_init;
  reg precharge_all_seen;

  integer target;
  reg [15:0] scratch;
  reg [8:0] col_now;
  integer slot;

  function integer cell_index;
    input [1:0] bank;
    input [12:0] row;
    input [8:0] col;
    begin
      cell_index = ((bank * ROWS) + row) * 512 + col;
    end
  endfunction

  // Rafaga secuencial: los bits bajos cuentan y se enrollan dentro del bloque
  // del tamano de la rafaga. Con direcciones alineadas sale una cuenta lineal,
  // pero el modelo no da eso por hecho.
  function [8:0] burst_column;
    input [8:0] start;
    input integer offset;
    begin
      if (mr_interleaved) begin
        burst_column = start ^ offset[8:0];
      end else begin
        case (burst_length)
          2: burst_column = {start[8:1], start[0] + offset[0]};
          4: burst_column = {start[8:2], start[1:0] + offset[1:0]};
          8: burst_column = {start[8:3], start[2:0] + offset[2:0]};
          default: burst_column = start + offset[8:0];
        endcase
      end
    end
  endfunction

  task fail;
    input [511:0] mensaje;
    begin
      errors = errors + 1;
      $display("SDRAM %0t: %0s", $time, mensaje);
    end
  endtask

  initial begin
    errors = 0;
    mode_set = 1'b0;
    mode_register = 13'd0;
    burst_length = 1;
    burst_read = 1'b0;
    burst_write = 1'b0;
    burst_left = 0;
    burst_index = 0;
    burst_bank = 2'd0;
    burst_col = 9'd0;
    burst_autoprecharge = 1'b0;
    dq_drive = 1'b0;
    dq_out = 16'h0000;
    precharge_all_seen = 1'b0;
    refresh_count_init = 0;
    cycles_since_mrs = 0;
    t_last_refresh = 0;
    for (i = 0; i < 4; i = i + 1) begin
      bank_active[i] = 1'b0;
      bank_row[i] = 13'd0;
      t_active[i] = 0;
      t_precharge[i] = 0;
    end
    for (i = 0; i < 8; i = i + 1) begin
      read_pipe_valid[i] = 1'b0;
      read_pipe_data[i] = 16'h0000;
    end
    for (i = 0; i < CELLS; i = i + 1) mem[i] = 16'h0000;
  end

  // --------------------------------------------------------------------
  always @(posedge clk) begin
    if (cke !== 1'b1) begin
      // Este controlador deja CKE alto siempre; si algun dia deja de hacerlo,
      // el modelo tiene que enterarse antes que la placa.
      if (cmd_eff != CMD_NOP) fail("comando con CKE bajo");
    end else begin
      cycles_since_mrs = cycles_since_mrs + 1;

      // -- Secuencia de arranque ---------------------------------------
      if (!mode_set && cmd_eff != CMD_NOP) begin
        if ($time < POWERUP_DELAY_NS)
          fail("comando antes de cumplirse el retardo de encendido");
        if (!precharge_all_seen && cmd_eff != CMD_PRECHARGE)
          fail("el arranque debe empezar por PRECHARGE de todos los bancos");
      end

      case (cmd_eff)
        CMD_MRS: begin
          if (!precharge_all_seen) fail("MRS sin precarga previa");
          if (refresh_count_init < 8)
            fail("MRS antes de los ocho refrescos de arranque");
          for (i = 0; i < 4; i = i + 1)
            if (bank_active[i]) fail("MRS con un banco activo");
          if (a[6:4] != 3'b010 && a[6:4] != 3'b011)
            fail("latencia CAS invalida en el registro de modo");
          mode_register = a;
          mode_set = 1'b1;
          cycles_since_mrs = 0;
          case (a[2:0])
            3'b000: burst_length = 1;
            3'b001: burst_length = 2;
            3'b010: burst_length = 4;
            3'b011: burst_length = 8;
            3'b111: burst_length = 512;
            default: begin
              burst_length = 1;
              fail("longitud de rafaga invalida en el registro de modo");
            end
          endcase
        end

        CMD_REFRESH: begin
          for (i = 0; i < 4; i = i + 1)
            if (bank_active[i]) fail("REFRESH con un banco activo");
          if (refresh_count_init > 0 && $time - t_last_refresh < TRFC_NS)
            fail("REFRESH antes de cumplirse tRFC");
          t_last_refresh = $time;
          refresh_count_init = refresh_count_init + 1;
        end

        CMD_PRECHARGE: begin
          if (a[10]) begin
            precharge_all_seen = 1'b1;
            for (i = 0; i < 4; i = i + 1) begin
              if (bank_active[i] && $time - t_active[i] < TRAS_NS)
                fail("PRECHARGE antes de cumplirse tRAS");
              bank_active[i] = 1'b0;
              t_precharge[i] = $time;
            end
          end else begin
            if (bank_active[ba] && $time - t_active[ba] < TRAS_NS)
              fail("PRECHARGE antes de cumplirse tRAS");
            bank_active[ba] = 1'b0;
            t_precharge[ba] = $time;
          end
        end

        CMD_ACTIVE: begin
          if (!mode_set) fail("ACTIVE antes del registro de modo");
          if (cycles_since_mrs < TMRD_CYCLES) fail("ACTIVE antes de tMRD");
          if (bank_active[ba]) fail("ACTIVE sobre un banco ya activo");
          if ($time - t_precharge[ba] < TRP_NS)
            fail("ACTIVE antes de cumplirse tRP");
          if (t_active[ba] != 0 && $time - t_active[ba] < TRC_NS)
            fail("ACTIVE antes de cumplirse tRC");
          if (a >= ROWS)
            fail("fila fuera del rango que modela este banco: sube ROWS");
          bank_active[ba] = 1'b1;
          bank_row[ba] = a;
          t_active[ba] = $time;
        end

        CMD_READ, CMD_WRITE: begin
          if (!bank_active[ba]) fail("acceso a un banco sin fila activa");
          else if ($time - t_active[ba] < TRCD_NS)
            fail("READ/WRITE antes de cumplirse tRCD");
          if (burst_read || burst_write)
            fail("nuevo acceso con una rafaga todavia en curso");
          burst_bank = ba;
          burst_col = a[8:0];
          burst_autoprecharge = a[10];
          burst_left = burst_length;
          burst_index = 0;
          burst_read = (cmd_eff == CMD_READ);
          burst_write = (cmd_eff == CMD_WRITE);
        end

        CMD_BURST_END: begin
          burst_read = 1'b0;
          burst_write = 1'b0;
          burst_left = 0;
        end

        default: begin end
      endcase

      // -- Datos de la rafaga -------------------------------------------
      // Se procesan DESPUES del comando para que el propio ciclo del comando
      // cuente como primer beat, que es como funciona la SDRAM.
      if (burst_left > 0 && (burst_read || burst_write)) begin
        col_now = burst_column(burst_col, burst_index);
        target = cell_index(burst_bank, bank_row[burst_bank], col_now);

        if (burst_write) begin
          scratch = mem[target];
          if (!dqm[0]) scratch[7:0] = dq[7:0];
          if (!dqm[1]) scratch[15:8] = dq[15:8];
          mem[target] = scratch;
        end else begin
          slot = mr_cas + READ_DELAY_CYCLES;
          read_pipe_data[slot] = mem[target];
          read_pipe_valid[slot] = 1'b1;
        end

        burst_index = burst_index + 1;
        burst_left = burst_left - 1;
        if (burst_left == 0) begin
          if (burst_autoprecharge) begin
            bank_active[burst_bank] = 1'b0;
            // Con auto-precarga en escritura, la precarga interna no arranca
            // hasta cumplirse tWR desde el ultimo dato.
            t_precharge[burst_bank] =
                $time + (burst_write ? TWR_CYCLES * CLK_PERIOD_NS : 0);
          end
          burst_read = 1'b0;
          burst_write = 1'b0;
        end
      end

      // -- Tuberia de salida ---------------------------------------------
      dq_drive <= read_pipe_valid[1];
      dq_out <= read_pipe_data[1];
      for (i = 1; i < 7; i = i + 1) begin
        read_pipe_valid[i] = read_pipe_valid[i+1];
        read_pipe_data[i] = read_pipe_data[i+1];
      end
      read_pipe_valid[7] = 1'b0;
    end
  end
endmodule

`default_nettype wire
