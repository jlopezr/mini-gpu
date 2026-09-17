`default_nettype none
// Contadores de rendimiento de la MiniCPU, en 0x80000300. Solo lectura.
//
//   0x80000300  CYCLES    ciclos CON LA CPU EN MARCHA (da la vuelta)
//   0x80000304  RETIRED   instrucciones retiradas
//
// POR QUE ESTAN AQUI Y NO EN top.v. Hasta ahora eran dos registros sueltos que
// solo leia el HOST, con los comandos de monitor 0x36 y 0x37: para saber cuanto
// tardo un bucle habia que PARAR la CPU y preguntar por serie. En MMIO el
// programa se mide A SI MISMO, en marcha, que es lo que la MiniGPU ya hacia --
// ver gpu_perf_counters.v, del que este bloque es un PREFIJO exacto: alli
// +0x00 es CYCLES y +0x04 es RETIRED, los dos unicos que tiene la CPU. Asi un
// programa que lea los dos primeros registros vale en las dos familias.
//
// Y con esto desaparece el juego de comandos "+contadores" entero: de tres
// juegos se pasa a dos, y ninguno es ya "el que tiene contadores", porque los
// contadores pasan a ser un dispositivo como los demas.
//
// DAN LA VUELTA, no saturan. Antes saturaban, con el argumento de que un
// contador que ha dado la vuelta miente en silencio. El problema es que a
// 80 MHz 2^32 ciclos son 53 segundos: un programa de un minuto satura y deja de
// medir NADA, mientras que dando la vuelta las DIFERENCIAS siguen siendo
// correctas, que es como se usan. Ademas es lo que hace la GPU, y dos bloques
// con el mismo nombre y distinta aritmetica es peor que cualquiera de las dos.
//
// SE REINICIAN EN CADA `run`, a diferencia de la GPU, que solo lo hace con el
// reset del nucleo. Se conserva la semantica de la CPU a proposito: asi
// `run`/`halt`/`run` da tres medidas independientes en vez de una suma que
// crece sin sentido, que es justo lo que se quiere al comparar versiones. La
// GPU no lo necesita porque sus kernels se lanzan una vez y se miden por
// deltas.
//
// AVISO DE MEDIDA. Leer CYCLES con un LOAD cuesta ciclos y retira una
// instruccion, y en la 21 ademas drena el bufer de escrituras: el programa
// perturba su propia medida. Se mide por deltas y se asume el sesgo. La GPU ya
// vive con eso.
module cpu_perf_counters (
    input wire clk,
    input wire reset,

    // Solo la direccion: no hace falta `select`. Como son de SOLO LECTURA no
    // hay escritura que filtrar, y `read_data` no depende de `select` a
    // proposito --el decodificador lo explica: el cliente solo lo mira en el
    // ciclo de su `ack`, y dejarlo fuera del mux ahorra un nivel--.
    input wire [7:0] address,
    output reg [31:0] read_data,

    // Alto mientras la CPU NO esta parada. Incluye lo que espera a memoria, que
    // es justo lo que interesa medir: la diferencia entre 9 ciclos por
    // instruccion ejecutando desde EBR y los 35 de la 21 es toda espera.
    input wire running,
    input wire retired,
    // Un pulso al arrancar: cada `run` empieza una medida nueva.
    input wire restart
);
  localparam [5:0] REG_CYCLES  = 6'd0;
  localparam [5:0] REG_RETIRED = 6'd1;

  reg [31:0] cycles;
  reg [31:0] retired_count;

  wire [5:0] selected = address[7:2];

  always @(posedge clk) begin
    if (reset || restart) begin
      cycles <= 32'd0;
      retired_count <= 32'd0;
    end else begin
      if (running) cycles <= cycles + 1'b1;
      // RETIRED no se condiciona a `running`, y esa es la diferencia entre
      // contar bien y contar una de menos SIEMPRE: el HALT retira en el mismo
      // ciclo en que la CPU se para, asi que con el filtro puesto se perdia
      // justo esa. Lo delato el contraste con el simulador en `--measure`: 11
      // contra 12 en todos los programas a la vez, que es un off-by-one de
      // definicion y no dos CPUs distintas.
      if (retired) retired_count <= retired_count + 1'b1;
    end
  end

  // Escribir se IGNORA, no es error: es la misma decision que en el bloque de
  // identificacion, y la que ya tomaba esta familia con cualquier registro de
  // solo lectura. La GPU levanta `bad`; reconciliarlo pide una ruta de error de
  // bus que esta familia no tiene todavia.
  always @* begin
    case (selected)
      REG_CYCLES:  read_data = cycles;
      REG_RETIRED: read_data = retired_count;
      default:     read_data = 32'd0;
    endcase
  end
endmodule

`default_nettype wire
