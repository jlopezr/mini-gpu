`default_nettype none

/*
 * Puerto de datos de la CPU sobre el bus de 128 bits.
 *
 * Traduce los accesos de palabra de 32 bits de `dmem` a peticiones de 16 bytes
 * contra memory_fabric_4, y decodifica la ventana de registros de video en
 * 0x80000000, que no toca la SDRAM y se resuelve en un ciclo.
 *
 * Lo que hereda de sdram_system_adapter, porque son reglas que costaron
 * encontrar y no cambian al ensanchar el bus:
 *
 *   - fuera de la SDRAM y fuera de la ventana MMIO, `dmem_error`;
 *   - antes de `init_done`, tambien error: la memoria todavia no responde;
 *   - los registros de video SI responden con la CPU en marcha, al contrario
 *     que la SDRAM, porque no hay coherencia que romper y el contador de frames
 *     solo sirve si se puede leer mientras un programa dibuja.
 *
 * Escrituras sin lectura previa
 * -----------------------------
 *
 * Una escritura de 32 bits dentro de una linea de 16 bytes NO necesita leer la
 * linea antes: la mascara de byte del controlador deja intactos los otros doce.
 * Es la misma propiedad que usa el monitor para escribir un byte suelto, y es
 * la razon de que la mascara sea de 16 bits y no un simple `write`.
 *
 * Lo que este modulo NO hace es combinar escrituras consecutivas en una sola
 * rafaga. Eso es el paso 4 del plan, y va aparte porque necesita vaciados
 * forzados —en SWAP, al parar la CPU y en cualquier acceso MMIO— que aqui no
 * pintan nada.
 */
module cpu_dmem_adapter #(
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000,
    parameter [27:0] MMIO_PREFIX = 28'h800_0000
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        init_done,

    // Lado CPU: identico al puerto dmem de cpu.v.
    input  wire        dmem_valid,
    input  wire [31:0] dmem_address,
    input  wire [31:0] dmem_write_data,
    input  wire [3:0]  dmem_write_enable,
    output reg  [31:0] dmem_read_data,
    output reg         dmem_ready,
    output reg         dmem_error,

    // Ventana de registros de video.
    output reg         mmio_req,
    input  wire        mmio_ack,
    output reg         mmio_write,
    output reg  [3:0]  mmio_write_mask,
    output reg  [3:0]  mmio_address,
    output reg  [31:0] mmio_write_data,
    input  wire [31:0] mmio_read_data,

    // Puerto de 128 bits hacia el arbitro, con direccion de BYTE alineada a 16.
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
                   ST_MMIO = 3'd3, ST_DONE = 3'd4;

  reg [2:0] state;
  reg [1:0] word_offset;      // palabra de 32 bits dentro de la linea
  reg saved_read;

  // `req_valid` se mantiene alto hasta ver `req_ready`. No es opcional: en
  // memory_fabric_4 la concesion mira el `valid` del puerto, asi que `ready`
  // no llega nunca si no se pide primero.
  assign req_valid = (state == ST_ISSUE);
  assign rsp_ready = (state == ST_WAIT);

  // Mirar los bits altos en vez de restar 32 bits: el comparador de magnitud
  // completo acababa en el camino critico y costaba 16 MHz. Vale porque el
  // tamano es potencia de dos.
  localparam [31:0] ADDR_RANGE_MASK = ~(SDRAM_SIZE_BYTES - 32'd1);
  wire address_in_sdram =
      ((dmem_address & ADDR_RANGE_MASK) == 32'd0) &&
      (dmem_address[1:0] == 2'b00);
  wire address_is_mmio =
      (dmem_address[31:4] == MMIO_PREFIX) && (dmem_address[1:0] == 2'b00);
  wire is_write = |dmem_write_enable;

  always @(posedge clk) begin
    dmem_ready <= 1'b0;
    dmem_error <= 1'b0;

    if (reset) begin
      state <= ST_IDLE;
      dmem_read_data <= 32'h0000_0000;
      req_write <= 1'b0;
      req_addr <= 32'h0000_0000;
      req_wdata <= 128'd0;
      req_wmask <= 16'd0;
      word_offset <= 2'd0;
      saved_read <= 1'b0;
      mmio_req <= 1'b0;
      mmio_write <= 1'b0;
      mmio_write_mask <= 4'b0000;
      mmio_address <= 4'h0;
      mmio_write_data <= 32'h0000_0000;
    end else begin
      case (state)
        // `dmem_ready` alto significa que se acaba de responder: la CPU
        // mantiene `valid` un ciclo mas antes de bajarlo.
        ST_IDLE: begin
          if (dmem_valid && !dmem_ready && !dmem_error) begin
            if (address_is_mmio) begin
              saved_read <= !is_write;
              mmio_req <= 1'b1;
              mmio_write <= is_write;
              mmio_write_mask <= dmem_write_enable;
              mmio_address <= dmem_address[3:0];
              mmio_write_data <= dmem_write_data;
              state <= ST_MMIO;
            end else if (!init_done || !address_in_sdram) begin
              dmem_ready <= 1'b1;
              dmem_error <= 1'b1;
              state <= ST_DONE;
            end else begin
              saved_read <= !is_write;
              word_offset <= dmem_address[3:2];
              req_addr <= {dmem_address[31:4], 4'b0000};
              req_write <= is_write;
              // La palabra se coloca en su sitio dentro de la linea, y la
              // mascara solo habilita sus cuatro bytes: los otros doce
              // sobreviven sin leerlos antes.
              req_wdata <= {96'd0, dmem_write_data} <<
                           {dmem_address[3:2], 5'b00000};
              req_wmask <= is_write
                  ? ({12'd0, dmem_write_enable} << {dmem_address[3:2], 2'b00})
                  : 16'd0;
              state <= ST_ISSUE;
            end
          end
        end

        ST_ISSUE:
          if (req_ready) state <= ST_WAIT;

        ST_WAIT:
          if (rsp_valid) begin
            if (saved_read && !rsp_error)
              dmem_read_data <= rsp_rdata[{word_offset, 5'b00000} +: 32];
            dmem_ready <= 1'b1;
            dmem_error <= rsp_error;
            state <= ST_DONE;
          end

        ST_MMIO:
          if (mmio_ack) begin
            mmio_req <= 1'b0;
            if (saved_read) dmem_read_data <= mmio_read_data;
            dmem_ready <= 1'b1;
            state <= ST_DONE;
          end

        // No aceptar la misma peticion dos veces mientras la CPU baja `valid`.
        ST_DONE:
          if (!dmem_valid) state <= ST_IDLE;

        default: state <= ST_IDLE;
      endcase
    end
  end
endmodule

`default_nettype wire
