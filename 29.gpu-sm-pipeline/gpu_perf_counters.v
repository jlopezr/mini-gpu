`default_nettype none
// Contadores de rendimiento: GPU PERFORMANCE de MMIO v2, en 0x82030000. Solo
// lectura.
//
// Existen porque hasta ahora todo se ha medido en simulacion, y la simulacion
// de un frame entero tarda diez minutos. Con estos contadores un programa se
// mide A SI MISMO en la placa, en tiempo real: lee CYCLES antes y despues de
// dibujar y ya sabe lo que costo, sin cronometro ni UART de por medio.
//
//   0x82030000  CYCLES       ciclos CON LA GPU CORRIENDO (da la vuelta)
//   0x82030004  RETIRED      instrucciones retiradas
//   0x82030008  IMEM_HITS    aciertos del bufer de instrucciones
//   0x8203000c  IMEM_MISSES  fallos del bufer de instrucciones
//   0x82030010  LSU_TX       transacciones emitidas por la LSU vectorial
//   0x82030014  STALL_MEM    ciclos con la LSU esperando a memoria
//   0x82030018  LANE_OPS     operaciones de HILO (suma de lanes activas)
//
// VIDEO_TX estaba aqui en v1 y ahora vive en VIDEO, en 0x80200024 (§9.7).
//
// Los que responden a "¿donde se va el tiempo?": con CYCLES, STALL_MEM e
// IMEM_MISSES se separa computo de memoria de fetch sin instrumentar nada mas.
//
// LANE_OPS mide DIVERGENCIA, que es justo lo que RETIRED no puede decir:
// RETIRED cuenta instrucciones de WARP, sin mirar cuantas lanes iban activas.
// Con los dos juntos salen las dos cifras que interesan:
//
//   lanes activas por instruccion = LANE_OPS / RETIRED    (8 = sin divergencia)
//   utilizacion de las ALU        = LANE_OPS / (CYCLES*8)
//
// Hace falta antes de plantearse empaquetar warps distintos en las lanes que
// deja libres la divergencia: si los programas no divergen, ahi no hay nada
// que recuperar. Ver sm-pipeline.md.
module gpu_perf_counters (
    input wire clk, reset,

    input wire        sel,
    input wire [3:0]  word,
    output reg [31:0] read_data,
    output reg        bad,

    // Todos los contadores solo avanzan con la GPU CORRIENDO.
    //
    // CYCLES era libre, y eso hacia que la medida desde el host no midiera el
    // programa sino el reloj de pared: entre las dos lecturas caben las ordenes
    // por serie y, sobre todo, la granularidad del bucle que sondea si ha
    // parado. La primera medida en placa salio con un CPI de 43 por esto, no
    // porque el cauce fuera lento.
    //
    // VIDEO_TX se contaba gated por la misma razon --el scanout sigue leyendo
    // SDRAM con la GPU parada-- y esa razon se ha ido con el a `gpu_video_regs`,
    // donde `running` ahora entra como puerto para conservarla. Si alguien lo
    // quita de alli, el contador vuelve a medir el reloj de pared.
    input wire running,

    input wire retired,
    input wire [7:0] retired_lanes,
    input wire [31:0] imem_hits, imem_misses,
    input wire lsu_tx, stall_mem
);
    // Ranuras de MMIO v2 §14.4. `VIDEO_TX` YA NO ESTA AQUI: se ha ido al
    // bloque VIDEO, que es donde §9.7 lo pone --«pertenece a VIDEO, no al
    // bloque de contadores de la GPU, por la regla de §12.1: cada contador
    // pertenece al componente que GENERA el evento. En su dia vivio en los
    // contadores de la GPU, y eso era un accidente de que solo la GPU tenia
    // contadores»--. Al irse, STALL_MEM baja de la ranura 6 a la 5, que es
    // donde §14.4 lo pone, y LANE_OPS de la 7 a la 6.
    //
    // LANE_OPS no lo nombra el mapa. Se queda en la primera ranura libre
    // detras de las seis de §14.4; §12.6 da sitio para 64 y esto es una
    // extension de esta carpeta, no del contrato.
    localparam [3:0] REG_CYCLES=4'd0, REG_RETIRED=4'd1, REG_IMEM_HITS=4'd2,
                     REG_IMEM_MISSES=4'd3, REG_LSU_TX=4'd4,
                     REG_STALL_MEM=4'd5, REG_LANE_OPS=4'd6;

    reg [31:0] cycles, retired_count, lsu_tx_count, stall_count;
    reg [31:0] lane_ops;
    // popcount de la mascara: cuantas lanes retiran con esta instruccion.
    wire [3:0] lanes_now = {3'b000,retired_lanes[0]}+{3'b000,retired_lanes[1]}+{3'b000,retired_lanes[2]}+{3'b000,retired_lanes[3]}
                         + {3'b000,retired_lanes[4]}+{3'b000,retired_lanes[5]}+{3'b000,retired_lanes[6]}+{3'b000,retired_lanes[7]};

    always @* begin
        read_data=32'd0; bad=1'b0;
        if(sel) case(word)
            REG_CYCLES:      read_data=cycles;
            REG_RETIRED:     read_data=retired_count;
            REG_IMEM_HITS:   read_data=imem_hits;
            REG_IMEM_MISSES: read_data=imem_misses;
            REG_LSU_TX:      read_data=lsu_tx_count;
            REG_STALL_MEM:   read_data=stall_count;
            REG_LANE_OPS:    read_data=lane_ops;
            default:         bad=1'b1;
        endcase
    end

    always @(posedge clk) begin
        if(reset) begin
            cycles<=0; retired_count<=0; lsu_tx_count<=0;
            stall_count<=0; lane_ops<=0;
        end else if(running) begin
            cycles<=cycles+1'b1;
            if(retired) begin
                retired_count<=retired_count+1'b1;
                lane_ops<=lane_ops+{28'd0,lanes_now};
            end
            if(lsu_tx)    lsu_tx_count<=lsu_tx_count+1'b1;
            if(stall_mem) stall_count<=stall_count+1'b1;
        end
    end
endmodule
`default_nettype wire
