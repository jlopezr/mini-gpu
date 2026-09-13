`default_nettype none

/*
 * Puerto del monitor UART sobre el bus de 128 bits.
 *
 * Parte del monitor_mem_adapter.v de pruebas/sdram, que traduce accesos byte a
 * byte a peticiones de 16 bytes con mascara. Aquel dice explicitamente que los
 * MMIO «deben seguir siendo decodificados fuera de este modulo» y no sabe nada
 * de la CPU; aqui van las dos cosas que faltaban, porque las dos son reglas del
 * sistema y no del bus:
 *
 *   - la ventana de registros de video en 0x80000000, que el monitor usa para
 *     mover el framebuffer y pedir swaps desde el PC sin escribir un programa;
 *   - «el monitor posee la memoria solo con la CPU parada». Los registros de
 *     video son la excepcion deliberada: responden tambien con la CPU en
 *     marcha, porque no hay coherencia que romper y el contador de frames solo
 *     sirve si se puede leer mientras un programa dibuja.
 *
 * EL PULSO. El monitor pide memoria con un pulso de UN ciclo, no con un nivel
 * mantenido hasta `ready` como la CPU y el video. Esto ya costo una vez que la
 * placa se quedara muda, con el sintoma desconcertante de que `ping` funcionaba
 * y cualquier lectura de memoria colgaba. Aqui no se pierde porque este
 * adaptador es suyo y solo suyo: en ST_IDLE esta siempre mirando, y el monitor
 * no puede emitir otra peticion hasta recibir respuesta. Lo que NO vale es
 * colgar el monitor directamente del arbitro, que solo concede cuando le toca.
 */
module monitor_mem_adapter_128 #(
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000,
    parameter [19:0] MMIO_PREFIX = 20'h80000
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        init_done,
    input  wire        cpu_halted,
    // Alto mientras el bufer de combinacion de escrituras del camino de datos
    // tenga algo sin volcar. Hay que esperarlo: la CPU para, el PC lee
    // inmediatamente y sin esto veria la memoria de antes del ultimo frame.
    input  wire        wb_dirty,

    // Lado monitor: identico al que ya usaba monitor.v.
    input  wire [31:0] mem_address,
    input  wire [7:0]  mem_write_data,
    input  wire        mem_write_enable,
    input  wire        mem_read_enable,
    output reg  [7:0]  mem_read_data,
    output reg         mem_ready,
    output reg         mem_error,

    // Ventana de registros de video.
    output reg         mmio_req,
    input  wire        mmio_ack,
    output reg         mmio_write,
    output reg  [3:0]  mmio_write_mask,
    output reg  [11:0] mmio_address,
    output reg  [31:0] mmio_write_data,
    input  wire [31:0] mmio_read_data,

    // Puerto de 128 bits hacia el arbitro.
    output wire         req_valid,
    input  wire         req_ready,
    output reg          req_write,
    output reg  [31:0]  req_addr,
    output reg  [127:0] req_wdata,
    output reg  [15:0]  req_wmask,

    input  wire         rsp_valid,
    output wire         rsp_ready,
    input  wire [127:0] rsp_rdata,
    input  wire         rsp_error
);
  localparam [2:0] ST_IDLE = 3'd0, ST_ISSUE = 3'd1, ST_WAIT = 3'd2,
                   ST_MMIO = 3'd3, ST_WAIT_FLUSH = 3'd4;

  reg [2:0] state;
  reg [3:0] byte_offset;
  reg [1:0] mmio_byte;
  reg saved_write;

  assign req_valid = (state == ST_ISSUE);
  assign rsp_ready = (state == ST_WAIT);

  // Bits altos en vez de comparador de magnitud, por lo mismo que en los otros
  // adaptadores: el rango es potencia de dos y la resta de 32 bits sale cara.
  localparam [31:0] ADDR_RANGE_MASK = ~(SDRAM_SIZE_BYTES - 32'd1);
  wire address_in_sdram = ((mem_address & ADDR_RANGE_MASK) == 32'd0);

  wire strobe = mem_write_enable || mem_read_enable;
  // El monitor accede byte a byte, asi que no exige alineamiento.
  wire is_mmio = (mem_address[31:12] == MMIO_PREFIX);

  always @(posedge clk) begin
    mem_ready <= 1'b0;
    mem_error <= 1'b0;

    if (reset) begin
      state <= ST_IDLE;
      mem_read_data <= 8'h00;
      req_write <= 1'b0;
      req_addr <= 32'h0000_0000;
      req_wdata <= 128'd0;
      req_wmask <= 16'd0;
      byte_offset <= 4'd0;
      mmio_byte <= 2'd0;
      saved_write <= 1'b0;
      mmio_req <= 1'b0;
      mmio_write <= 1'b0;
      mmio_write_mask <= 4'b0000;
      mmio_address <= 12'h000;
      mmio_write_data <= 32'h0000_0000;
    end else begin
      case (state)
        ST_IDLE: begin
          if (strobe) begin
            saved_write <= mem_write_enable;
            if (mem_write_enable && mem_read_enable) begin
              // Peticion contradictoria: se rechaza, como antes.
              mem_ready <= 1'b1;
              mem_error <= 1'b1;
            end else if (is_mmio) begin
              mmio_byte <= mem_address[1:0];
              mmio_req <= 1'b1;
              mmio_write <= mem_write_enable;
              mmio_write_mask <= 4'b0001 << mem_address[1:0];
              mmio_address <= mem_address[11:0];
              mmio_write_data <= {4{mem_write_data}};
              state <= ST_MMIO;
            end else if (!cpu_halted || !init_done || !address_in_sdram) begin
              mem_ready <= 1'b1;
              mem_error <= 1'b1;
            end else begin
              byte_offset <= mem_address[3:0];
              req_addr <= {mem_address[31:4], 4'b0000};
              req_write <= mem_write_enable;
              // Un byte en su carril, y la mascara deja intactos los otros
              // quince. Sin esto habria que leer la linea antes de escribir.
              req_wdata <= {120'd0, mem_write_data} << {mem_address[3:0], 3'b000};
              req_wmask <= 16'h0001 << mem_address[3:0];
              // La peticion ya esta capturada; si el bufer de escrituras
              // todavia tiene algo, se espera a que lo vuelque antes de tocar
              // la SDRAM.
              state <= wb_dirty ? ST_WAIT_FLUSH : ST_ISSUE;
            end
          end
        end

        ST_WAIT_FLUSH:
          if (!wb_dirty) state <= ST_ISSUE;

        ST_ISSUE:
          if (req_ready) state <= ST_WAIT;

        ST_WAIT:
          if (rsp_valid) begin
            if (!saved_write && !rsp_error)
              mem_read_data <= rsp_rdata[{byte_offset, 3'b000} +: 8];
            mem_ready <= 1'b1;
            mem_error <= rsp_error;
            state <= ST_IDLE;
          end

        ST_MMIO:
          if (mmio_ack) begin
            mmio_req <= 1'b0;
            if (!saved_write)
              mem_read_data <= mmio_read_data[{mmio_byte, 3'b000} +: 8];
            mem_ready <= 1'b1;
            state <= ST_IDLE;
          end

        default: state <= ST_IDLE;
      endcase
    end
  end
endmodule

`default_nettype wire
