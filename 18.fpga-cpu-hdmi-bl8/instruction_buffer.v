`default_nettype none

/*
 * Bufer de instrucciones: LINES lineas de 16 bytes, mapeo directo.
 *
 * Se intercala entre el puerto `imem` de la CPU y el bus de memoria. Del lado
 * de la CPU el contrato es el de `imem` tal cual; del lado de la memoria es un
 * puerto de 128 bits contra memory_fabric_4.
 *
 * Y ahi esta la razon de que una linea sean 16 bytes y no otra cosa: **una
 * linea es exactamente una rafaga BL8**. Un fallo se resuelve con UNA peticion,
 * no con cuatro transacciones de 32 bits como en la version anterior de este
 * modulo, ni con los ocho accesos de 16 bits que costaban las cuatro busquedas
 * sueltas de la 16.
 *
 * Por que un bufer y no una cache: la medida de docs/medida-inicial.md dice
 * que las busquedas son 645 de las 805 transacciones del bucle interior de
 * swap_demo_fast, y que servirlas en un ciclo vale 2,74x. Como el bucle entero
 * son cuatro instrucciones, 16 bytes, cabe en una linea y a partir de la
 * primera iteracion no vuelve a la SDRAM. No hacen falta ni asociatividad ni
 * politica de reemplazo: lo que hace falta es que quepa un bucle.
 *
 * Por que cuatro lineas y no una: si el bucle cae a caballo entre dos lineas de
 * 16 bytes, con una sola linea se falla en CADA iteracion, y el bufer sale peor
 * que no tenerlo. El indice son los dos bits de direccion que siguen a la
 * linea, asi que dos lineas contiguas nunca chocan y un bucle de hasta 64 bytes
 * entra entero, este alineado o no. Son 512 biestables de datos.
 *
 * Coherencia. El monitor escribe la memoria de programa mientras la CPU esta
 * parada, asi que el bufer se vacia entero mientras `cpu_halted` esta alto: la
 * primera busqueda despues de arrancar falla siempre, por construccion. Eso
 * cubre el unico caso de incoherencia que existe aqui, porque esta CPU no
 * escribe su propio codigo: `dmem` no pasa por aqui.
 *
 * Lo que NO se guarda: las direcciones fuera de la SDRAM y las busquedas
 * anteriores a `init_done`. Se responden con 0xf8000000, que es un opcode
 * invalido a proposito, igual que hacia el adaptador de la 16; guardarlo lo
 * haria permanente.
 */
module instruction_buffer #(
    parameter integer LINES = 4,          // potencia de dos
    parameter integer INDEX_BITS = 2,     // $clog2(LINES)
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        init_done,
    input  wire        cpu_halted,

    // Lado CPU: identico al puerto imem de cpu.v.
    input  wire        cpu_imem_valid,
    input  wire [31:0] cpu_imem_address,
    output reg  [31:0] cpu_imem_read_data,
    output reg         cpu_imem_ready,

    // Puerto de 128 bits hacia el arbitro, con direccion de BYTE alineada a 16.
    output wire         req_valid,
    input  wire         req_ready,
    output wire         req_write,
    output reg  [31:0]  req_addr,
    output wire [127:0] req_wdata,
    output wire [15:0]  req_wmask,

    input  wire         rsp_valid,
    output wire         rsp_ready,
    input  wire [127:0] rsp_rdata,
    input  wire         rsp_error,

    // Solo para los bancos de prueba. Un bufer que no acierta nunca funciona
    // igual de bien y no sirve de nada, y sin contadores no hay forma de
    // distinguirlo.
    output reg  [31:0] hit_count,
    output reg  [31:0] miss_count
);
  localparam integer TAG_LSB = 4 + INDEX_BITS;
  localparam integer TAG_BITS = 32 - TAG_LSB;

  localparam [2:0] ST_IDLE = 3'd0, ST_ISSUE = 3'd2,
                   ST_WAIT = 3'd3, ST_SERVE = 3'd4;

  // Una linea son cuatro palabras de 32 bits, o sea los 128 bits de una rafaga.
  reg [127:0] line_data[0:LINES-1];
  reg [TAG_BITS-1:0] line_tag[0:LINES-1];
  reg line_valid[0:LINES-1];

  reg [2:0] state;
  reg [INDEX_BITS-1:0] fill_index;
  reg [TAG_BITS-1:0] fill_tag;
  reg [1:0] want_word;
  reg fill_cacheable;

  // El bufer nunca escribe.
  assign req_write = 1'b0;
  assign req_wdata = 128'd0;
  assign req_wmask = 16'd0;
  // `req_valid` se mantiene hasta ver `req_ready`: en memory_fabric_4 la
  // concesion mira el `valid` del puerto, asi que bajarlo antes cuelga.
  assign req_valid = (state == ST_ISSUE);
  assign rsp_ready = (state == ST_WAIT);

  wire [1:0] word_sel = cpu_imem_address[3:2];
  wire [INDEX_BITS-1:0] index = cpu_imem_address[TAG_LSB-1:4];
  wire [TAG_BITS-1:0] tag = cpu_imem_address[31:TAG_LSB];
  // Comparar el rango con `<` cuesta un comparador de magnitud de 32 bits, y
  // este cono llega hasta el `imem_valid` de la CPU: con la resta completa, la
  // sintesis se quedaba en 84 MHz. Con el tamano siendo potencia de dos basta
  // con mirar los bits altos, que son siete NOR. Es la misma forma que usaba
  // sdram_system_adapter en la 16 (`address[31:25] == 0`), escrita para no
  // atarse a los 32 MiB.
  localparam [31:0] ADDR_RANGE_MASK = ~(SDRAM_SIZE_BYTES - 32'd1);
  wire cacheable = init_done &&
                   ((cpu_imem_address & ADDR_RANGE_MASK) == 32'd0) &&
                   (cpu_imem_address[1:0] == 2'b00);
  // Las cuatro etiquetas se comparan EN PARALELO y luego se multiplexa un bit.
  // Escrito como `line_valid[index] && line_tag[index] == tag` sale al reves
  // —multiplexar 19 bits por cuatro y despues comparar—, y ese cono acaba en el
  // `imem_valid` de la CPU. El area es la misma de cuatro comparadores en vez
  // de uno, que aqui no se nota, y el camino baja varios niveles de LUT.
  //
  // Se probo ademas a partir la busqueda en dos ciclos, con la comparacion
  // arrancando de un registro local en vez de la direccion de la CPU. NO
  // compro margen —seguian cerrando la misma semilla de ocho, porque el camino
  // critico esta en otro sitio y es de routing— y costaba un 8 % de
  // rendimiento, asi que se deshizo. Queda anotado para no repetirlo.
  wire [LINES-1:0] line_match;
  genvar g;
  generate
    for (g = 0; g < LINES; g = g + 1) begin : tag_compare
      assign line_match[g] = line_valid[g] && (line_tag[g] == tag);
    end
  endgenerate
  wire hit_now = line_match[index];

  integer i;

  always @(posedge clk) begin
    cpu_imem_ready <= 1'b0;

    if (reset) begin
      state <= ST_IDLE;
      req_addr <= 32'h0000_0000;
      cpu_imem_read_data <= 32'h0000_0000;
      fill_index <= 0;
      fill_tag <= 0;
      want_word <= 2'd0;
      fill_cacheable <= 1'b0;
      hit_count <= 32'd0;
      miss_count <= 32'd0;
    end else begin
      case (state)
        // `cpu_imem_ready` alto significa que se acaba de servir: la CPU
        // mantiene `valid` un ciclo mas antes de bajarlo, y sin esta guarda la
        // misma busqueda se serviria dos veces.
        ST_IDLE: begin
          if (cpu_imem_valid && !cpu_imem_ready) begin
            fill_index <= index;
            fill_tag <= tag;
            want_word <= word_sel;
            fill_cacheable <= cacheable;
            req_addr <= {cpu_imem_address[31:4], 4'b0000};
            if (!cacheable) begin
              // Igual que respondia el adaptador de la 16: opcode invalido,
              // sin guardar nada.
              cpu_imem_read_data <= 32'hf800_0000;
              cpu_imem_ready <= 1'b1;
            end else if (hit_now) begin
              cpu_imem_read_data <=
                  line_data[index][{word_sel, 5'b00000} +: 32];
              cpu_imem_ready <= 1'b1;
              hit_count <= hit_count + 1'b1;
            end else begin
              miss_count <= miss_count + 1'b1;
              state <= ST_ISSUE;
            end
          end
        end

        ST_ISSUE:
          if (req_ready) state <= ST_WAIT;

        ST_WAIT:
          if (rsp_valid) begin
            if (rsp_error) begin
              // No deberia pasar: `cacheable` ya filtro el rango. Si pasa, se
              // responde con opcode invalido y no se guarda la linea.
              cpu_imem_read_data <= 32'hf800_0000;
              cpu_imem_ready <= 1'b1;
              state <= ST_IDLE;
            end else begin
              line_data[fill_index] <= rsp_rdata;
              line_tag[fill_index] <= fill_tag;
              line_valid[fill_index] <= 1'b1;
              state <= ST_SERVE;
            end
          end

        ST_SERVE: begin
          cpu_imem_read_data <=
              line_data[fill_index][{want_word, 5'b00000} +: 32];
          cpu_imem_ready <= 1'b1;
          state <= ST_IDLE;
        end

        default: state <= ST_IDLE;
      endcase

      // El vaciado va al final del bloque a proposito: mientras la CPU esta
      // parada tiene que ganar a cualquier escritura de `line_valid` que haya
      // hecho el `case`, incluida la de un relleno que estuviera terminando
      // justo cuando llego el `halt`.
      if (cpu_halted) begin
        for (i = 0; i < LINES; i = i + 1) line_valid[i] <= 1'b0;
      end
    end
  end

  initial begin
    for (i = 0; i < LINES; i = i + 1) begin
      line_valid[i] = 1'b0;
      line_tag[i] = 0;
      line_data[i] = 128'd0;
    end
  end
endmodule

`default_nettype wire
