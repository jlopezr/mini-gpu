`default_nettype none

/*
 * Bufer de instrucciones: LINES lineas de 16 bytes, mapeo directo.
 *
 * Se intercala entre el puerto `imem` de la CPU y el `sdram_system_adapter`,
 * con el mismo contrato en los dos lados, asi que en `top.v` es un modulo en
 * medio de un cable y nada mas.
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
 * Lo que NO se guarda. Las direcciones fuera de la SDRAM y las busquedas
 * anteriores a `init_done` las responde el adaptador con 0xf8000000, que es un
 * opcode invalido a proposito. Guardar esa respuesta la haria permanente, asi
 * que esos casos pasan de largo sin tocar el bufer.
 */
module instruction_buffer #(
    parameter integer LINES = 4,          // potencia de dos
    parameter integer INDEX_BITS = 2      // $clog2(LINES)
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        init_done,
    input  wire        cpu_halted,

    // Lado CPU: identico al puerto imem del adaptador.
    input  wire        cpu_imem_valid,
    input  wire [31:0] cpu_imem_address,
    output reg  [31:0] cpu_imem_read_data,
    output reg         cpu_imem_ready,

    // Lado memoria: identico al puerto imem de la CPU.
    output reg         mem_imem_valid,
    output reg  [31:0] mem_imem_address,
    input  wire [31:0] mem_imem_read_data,
    input  wire        mem_imem_ready,

    // Solo para los bancos de prueba. Un bufer que no acierta nunca funciona
    // igual de bien y no sirve de nada, y sin contadores no hay forma de
    // distinguirlo.
    output reg  [31:0] hit_count,
    output reg  [31:0] miss_count
);
  localparam integer TAG_LSB = 4 + INDEX_BITS;
  localparam integer TAG_BITS = 25 - TAG_LSB;

  localparam [1:0] ST_IDLE = 2'd0, ST_WAIT = 2'd1, ST_NEXT = 2'd2,
                   ST_SERVE = 2'd3;

  reg [31:0] line_data[0:LINES*4-1];
  reg [TAG_BITS-1:0] line_tag[0:LINES-1];
  reg line_valid[0:LINES-1];

  reg [1:0] state;
  reg bypass;
  reg [INDEX_BITS-1:0] fill_index;
  reg [TAG_BITS-1:0] fill_tag;
  reg [1:0] fill_word;
  reg [1:0] want_word;

  wire [1:0] word_sel = cpu_imem_address[3:2];
  wire [INDEX_BITS-1:0] index = cpu_imem_address[TAG_LSB-1:4];
  wire [TAG_BITS-1:0] tag = cpu_imem_address[24:TAG_LSB];
  // Misma condicion que aplica el adaptador, para no guardar nunca una
  // respuesta de error.
  wire cacheable = init_done && cpu_imem_address[31:25] == 0 &&
                   cpu_imem_address[1:0] == 2'b00;
  wire hit = line_valid[index] && line_tag[index] == tag;

  integer i;

  always @(posedge clk) begin
    cpu_imem_ready <= 1'b0;

    if (reset) begin
      state <= ST_IDLE;
      mem_imem_valid <= 1'b0;
      mem_imem_address <= 32'h0000_0000;
      cpu_imem_read_data <= 32'h0000_0000;
      bypass <= 1'b0;
      fill_index <= 0;
      fill_tag <= 0;
      fill_word <= 2'd0;
      want_word <= 2'd0;
      hit_count <= 32'd0;
      miss_count <= 32'd0;
    end else begin
      case (state)
        // `cpu_imem_ready` alto significa que se acaba de servir: la CPU
        // mantiene `valid` un ciclo mas antes de bajarlo, y sin esta guarda la
        // misma busqueda se serviria dos veces.
        ST_IDLE: begin
          // `bypass` se calcula aqui fuera, sin mirar si hay acierto. Solo lo
          // usa ST_WAIT, y meter la comparacion de etiquetas en su cono lo
          // ponia en el camino critico: `line_tag` -> acierto -> ... ->
          // `bypass`, casi 10 ns y tres cuartas partes de routing.
          bypass <= !cacheable;
          if (cpu_imem_valid && !cpu_imem_ready) begin
            if (!cacheable) begin
              mem_imem_address <= cpu_imem_address;
              mem_imem_valid <= 1'b1;
              state <= ST_WAIT;
            end else if (hit) begin
              cpu_imem_read_data <= line_data[{index, word_sel}];
              cpu_imem_ready <= 1'b1;
              hit_count <= hit_count + 1'b1;
            end else begin
              fill_index <= index;
              fill_tag <= tag;
              fill_word <= 2'd0;
              want_word <= word_sel;
              // La linea se trae entera desde su base, en cuatro
              // transacciones de 32 bits. Son los mismos ocho accesos de 16
              // bits que costarian las cuatro busquedas sueltas, asi que el
              // codigo en linea recta no pierde nada; lo que gana es todo lo
              // que se vuelva a leer.
              mem_imem_address <= {cpu_imem_address[31:4], 4'b0000};
              mem_imem_valid <= 1'b1;
              miss_count <= miss_count + 1'b1;
              state <= ST_WAIT;
            end
          end
        end

        ST_WAIT: begin
          if (mem_imem_ready) begin
            // Hay que bajar `valid` entre transacciones: STATE_RELEASE del
            // adaptador no vuelve a IDLE mientras siga alto. Es el mismo
            // patron que usa la propia CPU entre FETCH_WAIT y FETCH_REQUEST.
            mem_imem_valid <= 1'b0;
            if (bypass) begin
              cpu_imem_read_data <= mem_imem_read_data;
              cpu_imem_ready <= 1'b1;
              state <= ST_IDLE;
            end else begin
              line_data[{fill_index, fill_word}] <= mem_imem_read_data;
              if (fill_word == 2'd3) begin
                line_tag[fill_index] <= fill_tag;
                line_valid[fill_index] <= 1'b1;
                state <= ST_SERVE;
              end else begin
                fill_word <= fill_word + 1'b1;
                mem_imem_address <= mem_imem_address + 3'd4;
                state <= ST_NEXT;
              end
            end
          end
        end

        ST_NEXT: begin
          mem_imem_valid <= 1'b1;
          state <= ST_WAIT;
        end

        ST_SERVE: begin
          cpu_imem_read_data <= line_data[{fill_index, want_word}];
          cpu_imem_ready <= 1'b1;
          state <= ST_IDLE;
        end
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
    end
    for (i = 0; i < LINES * 4; i = i + 1) line_data[i] = 32'h0000_0000;
  end
endmodule

`default_nettype wire
