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
//   0x8203001c  NO_WARP_STALL burbujas de SCH sin warp elegible
//   0x82030020  RR_RAW_STALL dependencias RAW/WAW bloqueadas por scoreboard
//   0x82030024  LSU_RSP_BLOCKED respuesta LSU esperando MEM/WB
//   0x82030028  ISSUE_AFTER_LOAD instruccion joven emitida tras un LOAD
//   0x8203002c  WB_ARB_MEM_WAIT respuesta MEM que espera al packet WB
//   0x82030030  SCH_ISSUED  tokens admitidos desde SCH
//   0x82030034  IS_CYCLES   residencia en IS (ciclos-token)
//   0x82030038  IF_CYCLES   residencia en IF (ciclos-token)
//   0x8203003c  ID_CYCLES   residencia en ID (ciclos-token)
//   0x82030040  RR_CYCLES   residencia en RR (ciclos-token)
//   0x82030044  EX_CYCLES   residencia en EX (ciclos-token)
//   0x82030048  MEM_WARP_CYCLES tokens de memoria pendientes (ciclos-token)
//   0x8203004c  WB_PACKET_CYCLES packets en las colas de WB (ciclos-packet)
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
    input wire [5:0]  word,
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
    input wire lsu_tx, stall_mem,
    input wire no_warp_stall,
    input wire rr_raw_stall, lsu_rsp_blocked,
    input wire issue_after_load, wb_arb_mem_wait,
    input wire sch_issued,
    input wire is_stage_valid, if_stage_valid, id_stage_valid, rr_stage_valid,
    input wire ex_stage_valid,
    input wire [3:0] mem_stage_warps,
    input wire [1:0] wb_stage_packets
);
    // Ranuras de MMIO v2 §14.4. `VIDEO_TX` YA NO ESTA AQUI: se ha ido al
    // bloque VIDEO, que es donde §9.7 lo pone --«pertenece a VIDEO, no al
    // bloque de contadores de la GPU, por la regla de §12.1: cada contador
    // pertenece al componente que GENERA el evento. En su dia vivio en los
    // contadores de la GPU, y eso era un accidente de que solo la GPU tenia
    // contadores»--. Al irse, STALL_MEM baja de la ranura 6 a la 5, que es
    // donde §14.4 lo pone, y LANE_OPS de la 7 a la 6.
    //
    // Las ranuras 6--11 son extensiones del cauce de esta carpeta. §12.6 da
    // sitio para 64: no cambian las seis ranuras base del contrato.
    localparam [5:0] REG_CYCLES=6'd0, REG_RETIRED=6'd1, REG_IMEM_HITS=6'd2,
                     REG_IMEM_MISSES=6'd3, REG_LSU_TX=6'd4,
                     REG_STALL_MEM=6'd5, REG_LANE_OPS=6'd6,
                     REG_NO_WARP_STALL=6'd7, REG_RR_RAW_STALL=6'd8,
                     REG_LSU_RSP_BLOCKED=6'd9, REG_ISSUE_AFTER_LOAD=6'd10,
                     REG_WB_ARB_MEM_WAIT=6'd11, REG_SCH_ISSUED=6'd12,
                     REG_IS_CYCLES=6'd13, REG_IF_CYCLES=6'd14,
                     REG_ID_CYCLES=6'd15, REG_RR_CYCLES=6'd16,
                     REG_EX_CYCLES=6'd17, REG_MEM_WARP_CYCLES=6'd18,
                     REG_WB_PACKET_CYCLES=6'd19;

    reg [31:0] cycles, retired_count, lsu_tx_count, stall_count;
    reg [31:0] lane_ops;
    // Ciclos en los que S tenia hueco (F libre) y aun asi ningun warp paso
    // pick_found, con algo vivo. Distingue burbuja por falta de warps
    // elegibles (este prototipo, 29, sin bypass) de contrapresion del cauce
    // o simplemente el programa habiendo terminado. Ver gpu_sm.v.
    reg [31:0] no_warp_stall_count;
    reg [31:0] rr_raw_stall_count, lsu_rsp_blocked_count;
    reg [31:0] issue_after_load_count, wb_arb_mem_wait_count;
    reg [31:0] sch_issued_count;
    reg [31:0] is_cycles, if_cycles, id_cycles, rr_cycles, ex_cycles;
    reg [31:0] mem_warp_cycles, wb_packet_cycles;
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
            REG_NO_WARP_STALL: read_data=no_warp_stall_count;
            REG_RR_RAW_STALL: read_data=rr_raw_stall_count;
            REG_LSU_RSP_BLOCKED: read_data=lsu_rsp_blocked_count;
            REG_ISSUE_AFTER_LOAD: read_data=issue_after_load_count;
            REG_WB_ARB_MEM_WAIT: read_data=wb_arb_mem_wait_count;
            REG_SCH_ISSUED: read_data=sch_issued_count;
            REG_IS_CYCLES: read_data=is_cycles;
            REG_IF_CYCLES: read_data=if_cycles;
            REG_ID_CYCLES: read_data=id_cycles;
            REG_RR_CYCLES: read_data=rr_cycles;
            REG_EX_CYCLES: read_data=ex_cycles;
            REG_MEM_WARP_CYCLES: read_data=mem_warp_cycles;
            REG_WB_PACKET_CYCLES: read_data=wb_packet_cycles;
            default:         bad=1'b1;
        endcase
    end

    always @(posedge clk) begin
        if(reset) begin
            cycles<=0; retired_count<=0; lsu_tx_count<=0;
            stall_count<=0; lane_ops<=0; no_warp_stall_count<=0;
            rr_raw_stall_count<=0; lsu_rsp_blocked_count<=0;
            issue_after_load_count<=0; wb_arb_mem_wait_count<=0;
            sch_issued_count<=0; is_cycles<=0; if_cycles<=0; id_cycles<=0;
            rr_cycles<=0; ex_cycles<=0; mem_warp_cycles<=0; wb_packet_cycles<=0;
        end else if(running) begin
            cycles<=cycles+1'b1;
            if(retired) begin
                retired_count<=retired_count+1'b1;
                lane_ops<=lane_ops+{28'd0,lanes_now};
            end
            if(lsu_tx)    lsu_tx_count<=lsu_tx_count+1'b1;
            if(stall_mem) stall_count<=stall_count+1'b1;
            if(no_warp_stall) no_warp_stall_count<=no_warp_stall_count+1'b1;
            if(rr_raw_stall) rr_raw_stall_count<=rr_raw_stall_count+1'b1;
            if(lsu_rsp_blocked) lsu_rsp_blocked_count<=lsu_rsp_blocked_count+1'b1;
            if(issue_after_load) issue_after_load_count<=issue_after_load_count+1'b1;
            if(wb_arb_mem_wait) wb_arb_mem_wait_count<=wb_arb_mem_wait_count+1'b1;
            if(sch_issued) sch_issued_count<=sch_issued_count+1'b1;
            if(is_stage_valid) is_cycles<=is_cycles+1'b1;
            if(if_stage_valid) if_cycles<=if_cycles+1'b1;
            if(id_stage_valid) id_cycles<=id_cycles+1'b1;
            if(rr_stage_valid) rr_cycles<=rr_cycles+1'b1;
            if(ex_stage_valid) ex_cycles<=ex_cycles+1'b1;
            if(|mem_stage_warps) mem_warp_cycles<=mem_warp_cycles+{28'd0,mem_stage_warps};
            if(|wb_stage_packets) wb_packet_cycles<=wb_packet_cycles+{30'd0,wb_stage_packets};
        end
    end
endmodule
`default_nettype wire
