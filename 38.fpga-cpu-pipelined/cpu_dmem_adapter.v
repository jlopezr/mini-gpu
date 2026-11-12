`default_nettype none

/*
 * Puerto de datos de la CPU sobre el bus de 128 bits, con combinacion de
 * escrituras.
 *
 * Traduce los accesos de palabra de 32 bits de `dmem` a peticiones de 16 bytes
 * contra memory_fabric_4, y decodifica el espacio MMIO --todo lo que empieza
 * en 0x80000000, segun mmio.md v2--, que no toca la SDRAM y se resuelve en un
 * ciclo.
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
 * Cuatro `STORE` consecutivos con `+4` caben en una linea. Asi que 160
 * escrituras pasan de 160 rafagas a 40.
 *
 * ---------------------------------------------------------------------
 * Los volcados no esperan su respuesta
 * ---------------------------------------------------------------------
 *
 * Antes, al cambiar de linea, el adaptador mandaba el volcado y no aceptaba
 * nada mas hasta que la SDRAM lo confirmaba, unos 16-18 ciclos. En un bucle
 * que rellena el framebuffer eso era la mitad del tiempo perdido: el STORE
 * siguiente esperaba el volcado entero.
 *
 * Ahora el volcado se entrega al puerto (`slot_*` -> `req_*`) y la linea nueva
 * empieza enseguida. Se puede porque la cola del puerto (fabric_fifo_bridge)
 * guarda la escritura ENTERA --direccion, 128 bits y mascara--: en cuanto la
 * acepta, este modulo ya no necesita los datos. Puede haber tantas escrituras
 * en vuelo como quepan en esa cola; `writes_out` cuenta las aceptadas sin
 * respuesta.
 *
 * El orden lo da el camino hasta la SDRAM, que es en orden para un mismo
 * puerto: la cola del puente, la cabeza de puerto de memory_fabric_fifo_6, un
 * slot por banco en sdram_controller_128 y sus READ/WRITE en orden de llegada.
 * Asi que una lectura mandada DETRAS de un volcado a la misma linea ve lo
 * escrito, sin esperar su respuesta. Las respuestas vuelven en orden, y como
 * la CPU solo tiene una lectura a la vez basta con contar cuantas respuestas
 * llegan antes que la suya (`responses_before_read`).
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
 *      bufer, se mostraria un frame incompleto. El MMIO NO va por el puerto,
 *      asi que el orden de la cola no lo protege: se vuelca la linea y se
 *      espera a que `writes_out` llegue a cero (ST_DRAIN) antes de dejarlo
 *      pasar.
 *
 *   2. **Al parar la CPU**, para que el monitor lea memoria de verdad. El
 *      monitor usa OTRO puerto del arbitro, cuyo orden respecto a este no esta
 *      garantizado, asi que `wb_dirty` sigue alto mientras quede algo en el
 *      bufer, en el puerto sin aceptar o sin confirmar, y
 *      monitor_mem_adapter_128 lo espera. Sin eso hay una carrera: la CPU para,
 *      el PC lee inmediatamente y ve la memoria de antes.
 *
 *   3. **Una lectura que caiga en la linea guardada.** Devolveria el dato
 *      viejo de la SDRAM. Se manda el volcado y la lectura justo detras, sin
 *      esperar entre medias (ST_READ_ISSUE). Las lecturas a otras lineas salen
 *      directamente.
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
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        init_done,
    input  wire        cpu_halted,

    // Lado CPU: el puerto dmem de cpu.v, con peticion y respuesta separadas,
    // como imem. La peticion se acepta en el ciclo en que `valid` y `ready`
    // estan altos; la respuesta llega despues con `rvalid` (y `error`), una
    // por peticion y en orden. `ready` sale de registros.
    input  wire        dmem_valid,
    input  wire [31:0] dmem_address,
    input  wire [31:0] dmem_write_data,
    input  wire [3:0]  dmem_write_enable,
    output wire        dmem_ready,
    output reg  [31:0] dmem_read_data,
    // La linea entera de la ultima lectura de SDRAM, valida con `rvalid`.
    // Solo la usa dcache.v, para guardarla al fallar.
    output reg  [127:0] dmem_read_line,
    output reg         dmem_rvalid,
    output reg         dmem_error,

    // Alto mientras haya escrituras sin confirmar. El adaptador del monitor lo
    // espera antes de tocar la SDRAM.
    output wire        wb_dirty,

    // Espacio MMIO. La direccion va ENTERA: quien vive en cada bloque lo
    // decide el decodificador, no este modulo.
    output reg         mmio_req,
    input  wire        mmio_ack,
    output reg         mmio_write,
    output reg  [3:0]  mmio_write_mask,
    output reg  [31:0] mmio_address,
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
  // ST_READ_ISSUE: la lectura espera a que el puerto acepte el volcado que va
  // delante. ST_READ_WAIT: la lectura esta mandada. ST_DRAIN: un MMIO espera a
  // que se confirmen todas las escrituras.
  localparam [2:0] ST_IDLE = 3'd0, ST_READ_ISSUE = 3'd1, ST_READ_WAIT = 3'd2,
                   ST_DRAIN = 3'd3, ST_MMIO = 3'd4;

  reg [2:0] state;

  // -- El bufer de combinacion ----------------------------------------------
  reg wb_valid;
  reg [27:0] wb_line;          // direccion de byte de la linea, bits [31:4]
  reg [127:0] wb_data;
  reg [15:0] wb_mask;

  // Datos de la peticion que espera (lectura tras volcado, o MMIO).
  reg [31:0] held_address;
  reg [31:0] held_wdata;
  reg [3:0] held_wen;

  // -- El puerto ---------------------------------------------------------------
  // `slot_busy`: hay una peticion en `req_*` que el puerto aun no ha aceptado.
  reg slot_busy;
  assign req_valid = slot_busy;
  wire port_accept = slot_busy && req_ready;
  // Las respuestas se aceptan siempre: cada una o confirma una escritura o es
  // la de la lectura en curso.
  assign rsp_ready = 1'b1;

  // Peticiones aceptadas por el puerto y aun sin respuesta. Mas de las cuatro
  // de la cola del puente pueden estar dentro (el fabric y los slots del
  // controlador tambien guardan), asi que cuatro bits.
  reg [3:0] outstanding;
  reg [3:0] writes_out;
  reg read_out;
  reg [3:0] responses_before_read;
  wire rsp_is_read = rsp_valid && read_out && (responses_before_read == 4'd0);

  // Sucio mientras haya algo en el bufer, una escritura en el puerto sin
  // aceptar o una aceptada sin confirmar.
  assign wb_dirty = wb_valid || (slot_busy && req_write) || (writes_out != 4'd0);

  // Sale de registros. Un acceso nuevo necesita el puerto libre (puede tener
  // que mandar un volcado), y con la CPU parada el vaciado va primero.
  assign dmem_ready = (state == ST_IDLE) && !slot_busy && !(cpu_halted && wb_valid);

  localparam [31:0] ADDR_RANGE_MASK = ~(SDRAM_SIZE_BYTES - 32'd1);
  // Cualquier byte del rango vale: la palabra se elige con [3:2] y la mascara
  // la trae la CPU; la alineacion que la ISA exige la comprueba cpu.v.
  wire address_in_sdram = ((dmem_address & ADDR_RANGE_MASK) == 32'd0);
  // MMIO v2 (1.isa/mmio.md §21.4): todo lo que empieza en 0x8000_0000. Las
  // direcciones sin dispositivo dan error en el decodificador, no aqui.
  wire address_is_mmio = dmem_address[31] && (dmem_address[1:0] == 2'b00);
  wire is_write = |dmem_write_enable;
  wire same_line = wb_valid && (dmem_address[31:4] == wb_line);
  wire accept = dmem_valid && dmem_ready;

  // La palabra colocada en su sitio dentro de la linea, y su mascara.
  wire [127:0] shifted_data =
      {96'd0, dmem_write_data} << {dmem_address[3:2], 5'b00000};
  wire [15:0] shifted_mask =
      {12'd0, dmem_write_enable} << {dmem_address[3:2], 2'b00};

  // Pone el volcado de la linea actual en el puerto. `req_wdata` no se carga
  // aqui sino en cada ciclo con el puerto libre, sin condicion: asi sus 128
  // enables no cuelgan de la decision (comparacion de 28 bits con `wb_line`),
  // que era el camino critico de la 30.
  //
  // La tarea NO toca `wb_valid`: lo hace cada llamada. Con `wb_valid <= 0`
  // aqui dentro y `wb_valid <= 1` despues (un STORE que vuelca y empieza
  // linea), el RTL simulado dejaba la ultima asignacion, pero Yosys dejaba la
  // de la tarea: la linea nueva nacia invalida y se perdia la palabra que la
  // creaba. Lo cazo la placa (la primera palabra de cada linea a 0) y lo
  // reproduce el banco contra la netlist de Yosys, no contra el RTL.
  task send_flush;
    begin
      slot_busy <= 1'b1;
      req_write <= 1'b1;
      req_addr <= {wb_line, 4'b0000};
      req_wmask <= wb_mask;
      flush_count <= flush_count + 1'b1;
    end
  endtask

  task send_read(input [31:0] address);
    begin
      slot_busy <= 1'b1;
      req_write <= 1'b0;
      req_addr <= {address[31:4], 4'b0000};
      req_wmask <= 16'd0;
    end
  endtask

  always @(posedge clk) begin
    dmem_rvalid <= 1'b0;
    dmem_error <= 1'b0;

    if (reset) begin
      state <= ST_IDLE;
      dmem_read_data <= 32'h0000_0000;
      dmem_read_line <= 128'd0;
      slot_busy <= 1'b0;
      req_write <= 1'b0;
      req_addr <= 32'h0000_0000;
      req_wdata <= 128'd0;
      req_wmask <= 16'd0;
      outstanding <= 4'd0;
      writes_out <= 4'd0;
      read_out <= 1'b0;
      responses_before_read <= 4'd0;
      mmio_req <= 1'b0;
      mmio_write <= 1'b0;
      mmio_write_mask <= 4'b0000;
      mmio_address <= 32'h0000_0000;
      mmio_write_data <= 32'h0000_0000;
      wb_valid <= 1'b0;
      wb_line <= 28'd0;
      wb_data <= 128'd0;
      wb_mask <= 16'd0;
      held_address <= 32'd0;
      held_wdata <= 32'd0;
      held_wen <= 4'd0;
      merge_count <= 32'd0;
      flush_count <= 32'd0;
    end else begin
      // ---- El puerto: aceptar y contestar --------------------------------
      if (!slot_busy) req_wdata <= wb_data;
      if (port_accept) slot_busy <= 1'b0;

      outstanding <= outstanding + {3'd0, port_accept} - {3'd0, rsp_valid};
      writes_out <= writes_out + {3'd0, port_accept && req_write}
                              - {3'd0, rsp_valid && !rsp_is_read};
      if (rsp_valid && read_out && !rsp_is_read)
        responses_before_read <= responses_before_read - 4'd1;
      if (port_accept && !req_write) begin
        // Solo hay una lectura a la vez: las respuestas que aun faltan por
        // delante son las de ahora menos la que llega en este ciclo.
        read_out <= 1'b1;
        responses_before_read <= outstanding - {3'd0, rsp_valid};
      end
      if (rsp_is_read) begin
        read_out <= 1'b0;
        dmem_read_data <= rsp_rdata[{held_address[3:2], 5'b00000} +: 32];
        dmem_read_line <= rsp_rdata;
        dmem_error <= rsp_error;
        dmem_rvalid <= 1'b1;
      end

      // ---- El lado de la CPU -----------------------------------------------
      case (state)
        // En ST_IDLE con `dmem_ready` alto, `valid` es una peticion aceptada.
        ST_IDLE: begin
          if (cpu_halted && wb_valid && !slot_busy) begin
            // Vaciado 2: la CPU se ha parado y el monitor va a querer leer
            // memoria de verdad. `wb_dirty` lo hace esperar.
            send_flush;
            wb_valid <= 1'b0;
          end else if (accept) begin
            held_address <= dmem_address;
            held_wdata <= dmem_write_data;
            held_wen <= dmem_write_enable;
            if (address_is_mmio) begin
              // Vaciado 1: el MMIO espera a que todo este en memoria. Si no
              // hay nada en el bufer ni por confirmar, sale ya (el puerto esta
              // libre: `dmem_ready` lo exige); ST_DRAIN costaria un ciclo.
              if (!wb_valid && writes_out == 4'd0) begin
                mmio_req <= 1'b1;
                mmio_write <= is_write;
                mmio_write_mask <= dmem_write_enable;
                mmio_address <= dmem_address;
                mmio_write_data <= dmem_write_data;
                state <= ST_MMIO;
              end else begin
                if (wb_valid) begin
                  send_flush;
                  wb_valid <= 1'b0;
                end
                state <= ST_DRAIN;
              end
            end else if (!init_done || !address_in_sdram) begin
              dmem_rvalid <= 1'b1;
              dmem_error <= 1'b1;
            end else if (is_write) begin
              if (same_line) begin
                // El caso que hace que esto valga la pena: se funde en el
                // bufer y se contesta en un ciclo, sin tocar la memoria.
                wb_data <= (wb_data & ~expand(shifted_mask)) |
                           (shifted_data & expand(shifted_mask));
                wb_mask <= wb_mask | shifted_mask;
                merge_count <= merge_count + 1'b1;
              end else begin
                // Linea nueva. Si habia otra, su volcado va al puerto y no se
                // espera: la nueva empieza ya.
                if (wb_valid) send_flush;
                wb_valid <= 1'b1;
                wb_line <= dmem_address[31:4];
                wb_data <= shifted_data;
                wb_mask <= shifted_mask;
              end
              dmem_rvalid <= 1'b1;
            end else if (same_line) begin
              // Vaciado 3: la lectura va justo detras del volcado.
              send_flush;
              wb_valid <= 1'b0;
              state <= ST_READ_ISSUE;
            end else begin
              send_read(dmem_address);
              state <= ST_READ_WAIT;
            end
          end
        end

        ST_READ_ISSUE:
          if (!slot_busy) begin
            send_read(held_address);
            state <= ST_READ_WAIT;
          end

        ST_READ_WAIT:
          if (rsp_is_read) state <= ST_IDLE;

        // Se pasa al MMIO con el puerto vacio y sin escrituras por confirmar.
        // `port_accept` y la respuesta de este ciclo ya estan contadas en
        // `writes_out` el ciclo siguiente, asi que se mira el registro.
        ST_DRAIN:
          if (!slot_busy && writes_out == 4'd0) begin
            mmio_req <= 1'b1;
            mmio_write <= |held_wen;
            mmio_write_mask <= held_wen;
            mmio_address <= held_address;
            mmio_write_data <= held_wdata;
            state <= ST_MMIO;
          end

        ST_MMIO:
          if (mmio_ack) begin
            dmem_error <= mmio_error;
            mmio_req <= 1'b0;
            if (!mmio_write) dmem_read_data <= mmio_read_data;
            dmem_rvalid <= 1'b1;
            state <= ST_IDLE;
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
