`default_nettype none

/*
 * Puerto de datos de la CPU sobre el bus de 128 bits, con combinacion de
 * escrituras.
 *
 * Traduce los accesos de palabra de 32 bits de `dmem` a peticiones de 16 bytes
 * contra memory_fabric_4, y decodifica la ventana de registros de video en
 * 0x80000000, que no toca la SDRAM y se resuelve en un ciclo.
 *
 * =====================================================================
 * Combinacion de escrituras, y por que NO es una cache
 * =====================================================================
 *
 * El motivo no es el coste: es que **el subsistema de video lee el framebuffer
 * de la SDRAM por su cuenta**. Una cache con escritura diferida guardaria
 * pixeles que el barrido no puede ver, y saldria la imagen a medias sin que el
 * programa haya hecho nada mal.
 *
 * Un bufer de combinacion acaba escribiendolo todo, solo que a tandas. Guarda
 * UNA linea de 16 bytes con su mascara de byte; mientras la CPU siga escribiendo
 * dentro de esa linea, las escrituras se funden ahi y se contestan en un ciclo,
 * sin tocar la memoria. Al salirse de la linea, se vuelca de una sola rafaga.
 *
 * Cuatro `STORE` consecutivos con `+4` —que es exactamente lo que hace el bucle
 * interior de swap_demo_fast— caben en una linea. Asi que 160 escrituras pasan
 * de 160 rafagas a 40, y ademas la CPU deja de esperar a la memoria en tres de
 * cada cuatro.
 *
 * ---------------------------------------------------------------------
 * Los vaciados forzados, que es donde esta toda la dificultad
 * ---------------------------------------------------------------------
 *
 * Un bufer que se vacia solo cuando le apetece es un error de coherencia
 * esperando a ocurrir. Hay tres momentos en los que hay que vaciarlo si o si:
 *
 *   1. **Cualquier acceso MMIO.** Cubre el caso importante, que es escribir el
 *      registro SWAP: si el intercambio ocurriera con pixeles todavia en el
 *      bufer, se mostraria un frame incompleto. Se vacia ANTES de dejar pasar
 *      el acceso, no despues, porque el orden es justo lo que importa.
 *
 *   2. **Al parar la CPU**, para que el monitor lea memoria de verdad. Y no
 *      basta con empezar el vaciado: el monitor no puede tocar la SDRAM hasta
 *      que termine, asi que este modulo saca `wb_dirty` y
 *      monitor_mem_adapter_128 lo espera. Sin eso hay una carrera: la CPU para,
 *      el PC lee inmediatamente y ve la memoria de antes.
 *
 *   3. **Una lectura que caiga en la linea guardada.** Devolveria el dato
 *      viejo de la SDRAM. Las lecturas a otras lineas pasan de largo sin
 *      vaciar, que es lo habitual.
 *
 * ---------------------------------------------------------------------
 * Escribir sin leer antes
 * ---------------------------------------------------------------------
 *
 * El volcado NO necesita leer la linea primero: la mascara de byte del
 * controlador, de 16 bits, deja intactos los bytes que nadie escribio. Sin esa
 * mascara habria que hacer lectura-modificacion-escritura y la combinacion no
 * compensaria.
 */
module cpu_dmem_adapter #(
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000,
    parameter [19:0] MMIO_PREFIX = 20'h80000
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        init_done,
    input  wire        cpu_halted,

    // Lado CPU: identico al puerto dmem de cpu.v.
    input  wire        dmem_valid,
    input  wire [31:0] dmem_address,
    input  wire [31:0] dmem_write_data,
    input  wire [3:0]  dmem_write_enable,
    output reg  [31:0] dmem_read_data,
    output reg         dmem_ready,
    output reg         dmem_error,

    // Alto mientras haya escrituras sin volcar. El adaptador del monitor lo
    // espera antes de tocar la SDRAM.
    output wire        wb_dirty,

    // Ventana de registros de video.
    output reg         mmio_req,
    input  wire        mmio_ack,
    output reg         mmio_write,
    output reg  [3:0]  mmio_write_mask,
    output reg  [11:0] mmio_address,
    output reg  [31:0] mmio_write_data,
    input  wire [31:0] mmio_read_data,
    input wire mmio_error,

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
    input  wire         rsp_error,

    // Para los bancos: cuantas escrituras se fundieron y cuantos volcados hubo.
    output reg  [31:0] merge_count,
    output reg  [31:0] flush_count
);
  localparam [2:0] ST_IDLE = 3'd0, ST_ISSUE = 3'd1, ST_WAIT = 3'd2,
                   ST_MMIO = 3'd3, ST_DONE = 3'd4;

  // Que hacer cuando termine un volcado.
  localparam [1:0] PEND_NONE = 2'd0, PEND_MMIO = 2'd1, PEND_READ = 2'd2,
                   PEND_WRITE = 2'd3;

  reg [2:0] state;
  reg [1:0] pending;
  reg [1:0] word_offset;
  reg saved_read;

  // -- El bufer de combinacion ----------------------------------------------
  reg wb_valid;
  reg [27:0] wb_line;          // direccion de byte de la linea, bits [31:4]
  reg [127:0] wb_data;
  reg [15:0] wb_mask;

  // Datos de la peticion en curso, guardados para despues del volcado.
  reg [31:0] held_address;
  reg [31:0] held_wdata;
  reg [3:0] held_wen;

  // Sucio mientras haya algo sin volcar O un volcado en vuelo. Las dos partes
  // hacen falta: `wb_valid` se limpia al ARRANCAR el volcado, asi que sin
  // `wb_flushing` esta senal bajaria antes de que el dato estuviera en memoria
  // y el monitor leeria justo el frame anterior. Es la carrera que la senal
  // existe para cerrar, y el banco la caza.
  reg wb_flushing;
  assign wb_dirty = wb_valid || wb_flushing;
  assign req_valid = (state == ST_ISSUE);
  assign rsp_ready = (state == ST_WAIT);

  localparam [31:0] ADDR_RANGE_MASK = ~(SDRAM_SIZE_BYTES - 32'd1);
  // Cualquier byte del rango vale: desde que existen STOREB/LOADB la direccion
  // efectiva ya no tiene por que ser multiplo de cuatro. Los bits [1:0] no se
  // usan aqui (la palabra se elige con [3:2] y la mascara la trae la CPU), y la
  // alineacion que la ISA si exige --par para las medias palabras-- la
  // comprueba `address_misaligned` en cpu.v, antes de llegar al bus.
  wire address_in_sdram = ((dmem_address & ADDR_RANGE_MASK) == 32'd0);
  wire address_is_mmio =
      (dmem_address[31:12] == MMIO_PREFIX) && (dmem_address[1:0] == 2'b00);
  wire is_write = |dmem_write_enable;
  wire same_line = wb_valid && (dmem_address[31:4] == wb_line);

  // La palabra colocada en su sitio dentro de la linea, y su mascara.
  wire [127:0] shifted_data =
      {96'd0, dmem_write_data} << {dmem_address[3:2], 5'b00000};
  wire [15:0] shifted_mask =
      {12'd0, dmem_write_enable} << {dmem_address[3:2], 2'b00};

  task arrancar_volcado;
    begin
      req_addr <= {wb_line, 4'b0000};
      req_write <= 1'b1;
      req_wdata <= wb_data;
      req_wmask <= wb_mask;
      wb_valid <= 1'b0;
      wb_flushing <= 1'b1;
      flush_count <= flush_count + 1'b1;
      state <= ST_ISSUE;
    end
  endtask

  always @(posedge clk) begin
    dmem_ready <= 1'b0;
    dmem_error <= 1'b0;

    if (reset) begin
      state <= ST_IDLE;
      pending <= PEND_NONE;
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
      mmio_address <= 12'h000;
      mmio_write_data <= 32'h0000_0000;
      wb_valid <= 1'b0;
      wb_flushing <= 1'b0;
      wb_line <= 28'd0;
      wb_data <= 128'd0;
      wb_mask <= 16'd0;
      held_address <= 32'd0;
      held_wdata <= 32'd0;
      held_wen <= 4'd0;
      merge_count <= 32'd0;
      flush_count <= 32'd0;
    end else begin
      case (state)
        // `dmem_ready` alto significa que se acaba de responder: la CPU
        // mantiene `valid` un ciclo mas antes de bajarlo.
        ST_IDLE: begin
          held_address <= dmem_address;
          held_wdata <= dmem_write_data;
          held_wen <= dmem_write_enable;

          if (cpu_halted && wb_valid) begin
            // Vaciado 2: la CPU se ha parado y el monitor va a querer leer
            // memoria de verdad. `wb_dirty` lo hace esperar hasta que acabe.
            pending <= PEND_NONE;
            arrancar_volcado;
          end else if (dmem_valid && !dmem_ready && !dmem_error) begin
            if (address_is_mmio) begin
              // Vaciado 1: ningun acceso MMIO se combina, y el volcado va
              // ANTES. Con SWAP el orden es justo lo que importa.
              if (wb_valid) begin
                pending <= PEND_MMIO;
                arrancar_volcado;
              end else begin
                saved_read <= !is_write;
                mmio_req <= 1'b1;
                mmio_write <= is_write;
                mmio_write_mask <= dmem_write_enable;
                mmio_address <= dmem_address[11:0];
                mmio_write_data <= dmem_write_data;
                state <= ST_MMIO;
              end
            end else if (!init_done || !address_in_sdram) begin
              dmem_ready <= 1'b1;
              dmem_error <= 1'b1;
              state <= ST_DONE;
            end else if (is_write) begin
              if (!wb_valid) begin
                // Linea nueva.
                wb_valid <= 1'b1;
                wb_line <= dmem_address[31:4];
                wb_data <= shifted_data;
                wb_mask <= shifted_mask;
                dmem_ready <= 1'b1;
                state <= ST_DONE;
              end else if (same_line) begin
                // El caso que hace que esto valga la pena: se funde en el
                // bufer y se contesta en un ciclo, sin tocar la memoria.
                wb_data <= (wb_data & ~expand(shifted_mask)) |
                           (shifted_data & expand(shifted_mask));
                wb_mask <= wb_mask | shifted_mask;
                merge_count <= merge_count + 1'b1;
                dmem_ready <= 1'b1;
                state <= ST_DONE;
              end else begin
                // Otra linea: volcar la de antes y empezar la nueva.
                pending <= PEND_WRITE;
                arrancar_volcado;
              end
            end else begin
              // Lectura. Vaciado 3: solo si cae en la linea guardada; a otra
              // linea pasa de largo, que es lo habitual.
              if (same_line) begin
                pending <= PEND_READ;
                arrancar_volcado;
              end else begin
                saved_read <= 1'b1;
                word_offset <= dmem_address[3:2];
                req_addr <= {dmem_address[31:4], 4'b0000};
                req_write <= 1'b0;
                req_wmask <= 16'd0;
                state <= ST_ISSUE;
              end
            end
          end
        end

        ST_ISSUE:
          if (req_ready) state <= ST_WAIT;

        ST_WAIT:
          if (rsp_valid) begin
            // El volcado ya esta en memoria: ahora si puede bajar `wb_dirty`.
            wb_flushing <= 1'b0;
            case (pending)
              PEND_MMIO: begin
                // El volcado ya esta en memoria: ahora si puede pasar el MMIO.
                saved_read <= !(|held_wen);
                mmio_req <= 1'b1;
                mmio_write <= |held_wen;
                mmio_write_mask <= held_wen;
                mmio_address <= held_address[11:0];
                mmio_write_data <= held_wdata;
                pending <= PEND_NONE;
                state <= ST_MMIO;
              end

              PEND_WRITE: begin
                // Empezar la linea nueva con la escritura que provoco el
                // volcado, y contestarla ya.
                wb_valid <= 1'b1;
                wb_line <= held_address[31:4];
                wb_data <= {96'd0, held_wdata} << {held_address[3:2], 5'b00000};
                wb_mask <= {12'd0, held_wen} << {held_address[3:2], 2'b00};
                dmem_ready <= 1'b1;
                pending <= PEND_NONE;
                state <= ST_DONE;
              end

              PEND_READ: begin
                saved_read <= 1'b1;
                word_offset <= held_address[3:2];
                req_addr <= {held_address[31:4], 4'b0000};
                req_write <= 1'b0;
                req_wmask <= 16'd0;
                pending <= PEND_NONE;
                state <= ST_ISSUE;
              end

              default: begin
                // Volcado suelto, el del `halt`. Nadie espera respuesta.
                if (saved_read) begin
                  dmem_read_data <= rsp_rdata[{word_offset, 5'b00000} +: 32];
                  dmem_ready <= 1'b1;
                  dmem_error <= rsp_error;
                  saved_read <= 1'b0;
                  state <= ST_DONE;
                end else begin
                  state <= ST_IDLE;
                end
              end
            endcase
          end

        ST_MMIO:
          if (mmio_ack) begin
            dmem_error <= mmio_error;
            mmio_req <= 1'b0;
            if (saved_read) dmem_read_data <= mmio_read_data;
            dmem_ready <= 1'b1;
            state <= ST_DONE;
          end

        // No aceptar la misma peticion dos veces mientras la CPU baja `valid`.
        ST_DONE: begin
          // Y dejar `saved_read` limpio: el vaciado del `halt` pasa por la
          // misma rama de ST_WAIT que una lectura suelta, y las distingue
          // precisamente por esta senal. Si se quedara puesta de una lectura
          // anterior, el volcado del halt contestaria a una CPU que no ha
          // pedido nada.
          saved_read <= 1'b0;
          if (!dmem_valid) state <= ST_IDLE;
        end

        default: state <= ST_IDLE;
      endcase
    end
  end

  // Convierte una mascara de byte en una mascara de bits, para fundir la
  // palabra nueva sobre la guardada sin pisar los bytes que no toca.
  function [127:0] expand;
    input [15:0] mask;
    integer k;
    begin
      expand = 128'd0;
      for (k = 0; k < 16; k = k + 1)
        expand[k*8 +: 8] = mask[k] ? 8'hff : 8'h00;
    end
  endfunction
endmodule

`default_nettype wire
