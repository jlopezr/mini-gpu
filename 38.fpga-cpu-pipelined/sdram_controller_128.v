`default_nettype none

// Controlador SDRAM BL8 con los cuatro bancos trabajando en paralelo.
//
// El de la 34 era secuencial: ACTIVE, esperar tRCD, READ/WRITE, rafaga,
// esperar tRP y recien entonces aceptar la peticion siguiente. De unos 16
// ciclos por peticion de 16 bytes, el bus de datos solo se usaba en 8.
//
// Aqui cada banco tiene su propio SLOT de peticion y su propia maquina de
// temporizacion. Mientras un banco esta en tRCD o en su precarga automatica, otro
// puede recibir su ACTIVE o estar sacando su rafaga. Lo unico que se
// serializa es lo que es fisicamente unico:
//
//   - el bus de comandos: un comando por ciclo;
//   - el bus de datos: una rafaga de ocho beats cada vez;
//   - tRRD entre dos ACTIVE de bancos distintos.
//
// Politica
// --------
//
// * Pagina cerrada: cada acceso es ACTIVE + READ/WRITE con auto-precarga, como
//   en la 34. No se reutilizan filas abiertas.
// * Los ACTIVE se adelantan: cualquier slot cuyo banco este libre recibe su
//   ACTIVE sin esperar a que le toque, mas antiguo primero.
// * Los READ/WRITE salen EN ORDEN DE LLEGADA. Asi las respuestas salen en el
//   mismo orden que las peticiones sin buffers de reordenacion, que es lo que
//   el fabric espera (una FIFO de destinos, sin etiquetas).
//
// Interfaz
// --------
//
// Es la misma que la de la 34 salvo la semantica, que ahora es de tuberia:
//
// * `req_ready` es verdadero cuando el SLOT DEL BANCO de `req_addr` esta
//   libre (y no hay refresco pendiente). Depende de la direccion, no solo del
//   estado: el fabric debe presentar la peticion y esperar, no sondear.
// * Puede haber hasta cuatro peticiones aceptadas a la vez, mas las que ya
//   han lanzado su comando y esperan su `done`.
// * `done` es un pulso por peticion aceptada, EN ORDEN, y `rdata` es valida
//   en ese mismo ciclo. En una escritura `rdata` no significa nada.
//
// Todas las salidas hacia la SDRAM salen de registros.
module sdram_controller_128 #(
    parameter integer CLK_FREQ_HZ = 25_000_000,
    parameter integer POWERUP_DELAY_US = 200,
    parameter integer REFRESH_RATE_HZ = 128_000,

    // Margen para vaciar los cuatro slots antes de refrescar: con refresco
    // pendiente no se aceptan peticiones nuevas, y lo que ya esta dentro tiene
    // que terminar (hasta cuatro operaciones, unos 12 ciclos cada una si van
    // al mismo banco).
    parameter integer MAX_ACCESS_CYCLES = 64,

    parameter integer TRP_NS = 20,
    parameter integer TRCD_NS = 20,
    parameter integer TRFC_NS = 66,
    // Entre dos ACTIVE de bancos distintos. W9825G6KH: 12 ns (-6) / 15 ns (-75).
    parameter integer TRRD_NS = 15,

    parameter integer TMRD_CYCLES = 2,
    parameter integer CAS_LATENCY_CYCLES = 2,
    parameter integer TWR_CYCLES = 2,

    // Ciclos de guardia al pasar de leer a escribir: la SDRAM suelta DQ y la
    // FPGA lo coge, y no deben coincidir ni un instante.
    parameter integer TURNAROUND_CYCLES = 1,

    // Ciclos que hay que esperar POR ENCIMA de la latencia CAS antes de
    // muestrear DQ. No es margen de sobra: entre que la FPGA emite el comando y
    // ve el dato de vuelta estan el camino de salida, el pin, la pista, el pin
    // de vuelta y el camino de entrada, y a 100 MHz eso pasa de un ciclo.
    //
    // ESTE PARAMETRO ES CALIBRACION DE PLACA. Un banco de pruebas no puede
    // fijarlo: el modelo tiene el mismo parametro, asi que controlador y modelo
    // se ponen de acuerdo en el valor que sea y la simulacion pasa igual. Lo
    // unico que decide es el hardware.
    //
    // Nacio valiendo 1 por analogia con el sdram_controller BL1 de la 16, que
    // muestrea en ST_READ + dos esperas + ST_READ_CAPTURE. La analogia era
    // mala: la 16 corre a 100 MHz y esta a 80. El retardo de ida y vuelta es
    // fisico y no cambia con el reloj, asi que a 10 ns se sale del ciclo y a
    // 12,5 ns cabe dentro.
    //
    // Cuenta flancos de SUBIDA, pero DQ se muestrea en la BAJADA anterior
    // (ver `dq_negedge` mas abajo), asi que el instante real de captura es
    // medio ciclo antes de lo que sugiere este numero. Con la captura
    // centrada en el ojo, el valor correcto para esta placa vuelve a ser 1.
    //
    // POR ESO SE DERIVA DEL RELOJ Y NO SE FIJA A UN NUMERO. Si el retardo es
    // fisico y constante, los ciclos que hay que esperar NO lo son: dependen de
    // cuanto dure un ciclo. Dejarlo en 1 fijo es correcto a 80 MHz (21) y
    // ROMPE a 25 MHz (22), donde hace muestrear un ciclo tarde y el dato
    // vuelve desplazado una palabra de 16 bits.
    //
    // ROUND_TRIP_PS esta calibrado con DOS puntos medidos en placa:
    //
    //   80 MHz -> 1   (21.fpga-cpu-hdmi-alu, en produccion)
    //   25 MHz -> 0   (22, confirmado: con 1 la primera instruccion daba
    //                  ERROR_INVALID_ENCODING y con 0 el programa corre)
    //
    // Los dos juntos acotan el retardo real entre 12,5 y 25 ns; se toma 18 ns,
    // a mitad del intervalo. Lo que la formula predice para OTROS relojes
    // (1 hasta 111 MHz, 2 hasta 166 MHz) sigue siendo inferencia: cada reloj
    // nuevo hay que confirmarlo en placa.
    parameter integer ROUND_TRIP_PS = 18_000,
    // Division entera = suelo. Se calcula en MHz x ps para no desbordar el
    // entero de 32 bits, que CLK_FREQ_HZ * ROUND_TRIP_PS si haria.
    parameter integer READ_DELAY_CYCLES =
        (CLK_FREQ_HZ / 1_000_000) * ROUND_TRIP_PS / 1_000_000
) (
    input wire clk,
    input wire reset,

    // ------------------------------------------------------------
    // Interfaz logica
    //
    // Cada request transfiere 128 bits = 16 bytes.
    //
    // req_addr sigue direccionando palabras SDRAM de 16 bits.
    // Debe cumplir req_addr[2:0] == 3'b000.
    //
    // Beat 0 -> bits [15:0]
    // Beat 1 -> bits [31:16]
    // ...
    // Beat 7 -> bits [127:112]
    // ------------------------------------------------------------

    input wire req_valid,
    input wire req_write,

    input wire [23:0] req_addr,

    input wire [127:0] req_wdata,

    // Byte enable.
    //
    // bit 0 -> byte bajo beat 0
    // bit 1 -> byte alto beat 0
    // ...
    // bit 15 -> byte alto beat 7
    //
    // 1 = escribir byte
    // 0 = preservar byte
    input wire [15:0] req_wmask,

    output wire req_ready,

    output reg done,
    output reg [127:0] rdata,

    output reg init_done,
    output wire busy,

    // ------------------------------------------------------------
    // SDRAM
    // ------------------------------------------------------------

    output wire sdram_clk,

    output reg sdram_cke,
    output wire sdram_csn,
    output wire sdram_rasn,
    output wire sdram_casn,
    output wire sdram_wen,

    output wire [12:0] sdram_a,
    output wire [1:0] sdram_ba,
    output wire [1:0] sdram_dqm,

    inout wire [15:0] sdram_d
);

    // ------------------------------------------------------------
    // SDRAM commands
    // {CS#, RAS#, CAS#, WE#}
    // ------------------------------------------------------------

    localparam [3:0]
        CMD_MRS       = 4'b0000,
        CMD_REFRESH   = 4'b0001,
        CMD_PRECHARGE = 4'b0010,
        CMD_ACTIVE    = 4'b0011,
        CMD_WRITE     = 4'b0100,
        CMD_READ      = 4'b0101,
        CMD_NOP       = 4'b0111;

    // Arranque.
    localparam [2:0]
        I_WAIT     = 3'd0,
        I_PRE      = 3'd1,
        I_PRE_WAIT = 3'd2,
        I_REF      = 3'd3,
        I_REF_WAIT = 3'd4,
        I_MRS      = 3'd5,
        I_MRS_WAIT = 3'd6;

    // Refresco periodico.
    localparam [1:0]
        R_NONE  = 2'd0,   // nada pendiente
        R_DRAIN = 2'd1,   // sin peticiones nuevas, esperando a quedar en reposo
        R_WAIT  = 2'd2;   // REFRESH emitido, esperando tRFC

    // ------------------------------------------------------------
    // Timing conversion
    // ------------------------------------------------------------

    function integer ns_to_cycles;
        input integer delay_ns;
        integer result;
        begin
            result =
                (((CLK_FREQ_HZ / 1000) * delay_ns) + 999_999)
                / 1_000_000;

            ns_to_cycles = (result < 1) ? 1 : result;
        end
    endfunction

    localparam integer POWERUP_DELAY_CYCLES =
        (((CLK_FREQ_HZ / 1000) * POWERUP_DELAY_US) + 999)
        / 1000;

    localparam integer REFRESH_PERIOD_CYCLES =
        CLK_FREQ_HZ / REFRESH_RATE_HZ;

    localparam integer REFRESH_TRIGGER_CYCLES =
        (REFRESH_PERIOD_CYCLES > MAX_ACCESS_CYCLES)
            ? (REFRESH_PERIOD_CYCLES - MAX_ACCESS_CYCLES)
            : 1;

    localparam integer TRP_CYCLES  = ns_to_cycles(TRP_NS);
    localparam integer TRCD_CYCLES = ns_to_cycles(TRCD_NS);
    localparam integer TRFC_CYCLES = ns_to_cycles(TRFC_NS);
    localparam integer TRRD_CYCLES = ns_to_cycles(TRRD_NS);

    // ------------------------------------------------------------
    // Cuentas de la planificacion
    //
    // Todo se mide en ciclos desde el ciclo en que se DECIDE un comando; el
    // comando aparece en los pines un ciclo despues, porque las salidas son
    // registros. Un contador cargado con X en la decision vale 0 X+1 ciclos
    // mas tarde, y ese es el primer ciclo en que se puede decidir lo siguiente.
    // Por eso todo lo de abajo es "distancia en ciclos menos uno".
    //
    //   BL = 8 beats = 8 ciclos de bus de datos.
    //
    //   mismo banco, tras READ : ACTIVE 8 + tRP ciclos despues del READ
    //   mismo banco, tras WRITE: ACTIVE 8 + tWR + tRP despues del WRITE
    //                            (la precarga automatica no arranca hasta
    //                            cumplirse tWR desde el ultimo dato)
    //   dos columnas seguidas  : 8 ciclos
    //   READ -> WRITE          : CL + 8 + 1 + guardia: el WRITE mete su dato
    //                            en el mismo ciclo que su comando, y la SDRAM
    //                            sigue soltando el ultimo de la lectura hasta
    //                            CL + 8 ciclos despues del READ
    //   WRITE -> READ          : 8 (el dato del READ vuelve CL despues, cuando
    //                            la FPGA ya ha soltado DQ)
    // ------------------------------------------------------------

    localparam integer BL = 8;

    localparam integer RD_RECOVERY = BL + TRP_CYCLES - 1;
    localparam integer WR_RECOVERY = BL + TWR_CYCLES + TRP_CYCLES - 1;
    localparam integer GAP_SAME = BL - 1;
    localparam integer GAP_RD_TO_WR = CAS_LATENCY_CYCLES + BL + TURNAROUND_CYCLES;

    // Los temporizadores son registros TERMOMETRICOS de TW bits: cargar X es
    // poner X unos por abajo, y avanzar un ciclo es desplazar a la derecha.
    // "Vale 0" es no tener ningun uno, y "vale 0 el ciclo que viene" es que
    // el bit 1 sea 0. No hay sumas ni restas: con contadores binarios yosys
    // fusionaba los decrementos en una sola ALU compartida, con los operandos
    // elegidos por la propia logica de decision, y esa ALU acabo en el camino
    // critico de la memoria (a 100 MHz sobran 10 ns para todo).
    //
    // TW debe ser mayor que todo valor que se cargue; hay una comprobacion en
    // simulacion al final. 16 es el paso de cada banco dentro de su vector.
    localparam integer TW = 16;

    localparam [TW-1:0] T_RD_RECOVERY  = (1 << RD_RECOVERY) - 1;
    localparam [TW-1:0] T_WR_RECOVERY  = (1 << WR_RECOVERY) - 1;
    localparam [TW-1:0] T_GAP_SAME     = (1 << GAP_SAME) - 1;
    localparam [TW-1:0] T_GAP_RD_TO_WR = (1 << GAP_RD_TO_WR) - 1;
    localparam [TW-1:0] T_TRCD         = (1 << (TRCD_CYCLES - 1)) - 1;
    localparam [TW-1:0] T_TRRD         = (1 << (TRRD_CYCLES - 1)) - 1;

    // Ciclo, contado desde el comando READ, en que se muestrea el beat 0.
    // Identico a lo que esperaba el controlador secuencial: ST_READ_CMD, luego
    // CL - 1 + READ_DELAY_CYCLES esperas, luego el primer ST_READ_BURST.
    localparam integer DCAP = CAS_LATENCY_CYCLES + READ_DELAY_CYCLES;

    // ------------------------------------------------------------
    // Slots: una peticion pendiente por banco
    //
    // Direccion de palabra de 24 bits: fila [23:11], banco [10:9], columna
    // [8:0]. La columna siempre acaba en 000 (peticiones alineadas a 16 bytes).
    // ------------------------------------------------------------

    wire [1:0] req_bank = req_addr[10:9];

    reg [3:0]         slot_valid;
    reg [3:0]         slot_write;
    reg [4*16-1:0]    slot_row;
    reg [4*8-1:0]     slot_col;
    reg [4*128-1:0]   slot_wdata;
    reg [4*16-1:0]    slot_wmask;

    // Fila abierta para la peticion del slot (ACTIVE ya emitido).
    reg [3:0]         row_open;
    reg [4*TW-1:0]    rcd_t;      // hasta poder emitir READ/WRITE
    reg [4*TW-1:0]    rec_t;      // hasta poder emitir el siguiente ACTIVE

    reg [TW-1:0]      gap_rd_t;   // hasta poder emitir un READ
    reg [TW-1:0]      gap_wr_t;   // hasta poder emitir un WRITE
    reg [TW-1:0]      trrd_t;     // hasta poder emitir otro ACTIVE

    // "El temporizador vale 0", registrado. Las decisiones de cada ciclo miran
    // estas banderas y no los temporizadores. Cada bandera se mantiene con
    //   z <= !t[1]                al avanzar (t <= 1 unos => 0 el ciclo que viene),
    //   z <= (valor cargado == 0) al cargar.
    reg [3:0]         rcd_z;
    reg [3:0]         rec_z;
    reg               gap_rd_z;
    reg               gap_wr_z;
    reg               trrd_z;

    // Orden de llegada de las peticiones cuyo READ/WRITE aun no ha salido.
    // Cada banco aparece como mucho una vez (un slot por banco).
    //
    // `ord_v` es termometrico (ord_v[p] = la posicion p esta ocupada) en vez de
    // un contador: asi no hay comparadores ni sumas entre el registro y las
    // decisiones, solo desplazamientos.
    reg [7:0]         ord_q;
    reg [3:0]         ord_v;

    // ------------------------------------------------------------
    // Estado de arranque, refresco y registros de salida
    // ------------------------------------------------------------

    reg [2:0]  ini_state;
    reg [31:0] init_count;
    reg [3:0]  init_refreshes;
    reg [15:0] timing_count;

    reg [1:0]  ref_state;
    reg [15:0] refresh_count;
    reg        refresh_due;

    reg [3:0]  cmd_q;
    reg [12:0] a_q;
    reg [1:0]  ba_q;
    reg [1:0]  dqm_q;

    reg        dq_oe;
    reg [15:0] dq_out;

    reg [127:0] wr_buf;
    reg [15:0]  wr_mask;
    reg [2:0]   wr_idx;
    reg         wr_run;

    reg [DCAP:0]   rd_pipe;       // rd_pipe[k] = hace k ciclos que salio un READ
    reg [DCAP+7:0] dn_pipe;       // idem para cualquier READ/WRITE
    reg            cap_run;
    // Beat que se captura en este ciclo, en one-hot registrado: el 0 al
    // arrancar (`cap0`) y luego `cap_oh[i]`, que avanza un bit por ciclo. Un
    // contador con decodificador por beat ponia un comparador delante de cada
    // habilitacion de `rdata`.
    reg [7:1]      cap_oh;
    wire           cap0 = rd_pipe[DCAP] && !cap_run;

    // Copia registrada de !wr_run: la habilitacion de wr_buf (144 flops) no
    // cuelga del mismo registro que usa el resto de la FSM.
    reg            wr_free;

    // Copia registrada de ref_state == R_WAIT, para el camino de act_issue.
    reg            ref_wait;

    reg [3:0]  inflight;

    assign sdram_clk = clk;
    assign {sdram_csn, sdram_rasn, sdram_casn, sdram_wen} = cmd_q;
    assign sdram_a   = a_q;
    assign sdram_ba  = ba_q;
    assign sdram_dqm = dqm_q;

    // ------------------------------------------------------------
    // Captura de DQ en el flanco de BAJADA
    // ------------------------------------------------------------
    //
    // La SDRAM recibe nuestro mismo reloj, asi que sus datos de lectura salen
    // alineados con el flanco de subida, viajan por el pin, la pista y el pin
    // de vuelta, y llegan CERCA del flanco siguiente. Muestrear ahi es
    // muestrear en el borde del ojo.
    //
    // Lo enseno la placa y no la simulacion. Con captura en subida:
    //
    //   - un ciclo antes (READ_DELAY_CYCLES=0) la rafaga sale casi bien, con
    //     unos pocos bits sueltos mal: fallaban los beats 3 y 7 en DQ4 y DQ5, y
    //     al recompilar con otra semilla los bits malos CAMBIABAN a DQ4 y DQ6.
    //     Un fallo que se mueve con la colocacion es margen, no logica;
    //   - un ciclo despues (=1) la rafaga sale entera corrida un beat.
    //
    // O sea que el limite del beat cae entre los dos flancos, y el centro del
    // ojo esta a mitad de camino. Este registro muestrea justo ahi: medio
    // ciclo, 6,25 ns a 80 MHz, de margen por los dos lados en vez de cero.
    //
    // Con esto, READ_DELAY_CYCLES vuelve a ser 1: el beat 0 se captura en la
    // bajada de T+2 y se guarda en la subida de T+3.
    reg [15:0] dq_negedge;
    always @(negedge clk) begin
        dq_negedge <= sdram_d;
    end

    // DQ solo lo maneja la FPGA durante las rafagas de escritura.
    assign sdram_d = dq_oe ? dq_out : 16'hzzzz;

    // ------------------------------------------------------------
    // Decisiones del ciclo
    // ------------------------------------------------------------

    wire run = init_done;

    wire accepting =
        run &&
        (ref_state == R_NONE) &&
        !refresh_due;

    assign req_ready = accepting && !slot_valid[req_bank];

    wire accept = req_valid && req_ready;

    assign busy = !init_done || (inflight != 4'd0) || (ref_state != R_NONE);

    // READ/WRITE: solo la peticion mas antigua.
    wire [1:0] hb = ord_q[1:0];
    wire hb_write = slot_write[hb];

    // Datos de la peticion mas antigua, con multiplexores explicitos.
    reg [127:0] hb_wdata;
    reg [15:0]  hb_wmask;
    reg [5:0]   hb_col;

    always @* begin
        case (hb)
            2'd0: begin
                hb_wdata = slot_wdata[127:0];
                hb_wmask = slot_wmask[15:0];
                hb_col   = slot_col[5:0];
            end
            2'd1: begin
                hb_wdata = slot_wdata[255:128];
                hb_wmask = slot_wmask[31:16];
                hb_col   = slot_col[13:8];
            end
            2'd2: begin
                hb_wdata = slot_wdata[383:256];
                hb_wmask = slot_wmask[47:32];
                hb_col   = slot_col[21:16];
            end
            default: begin
                hb_wdata = slot_wdata[511:384];
                hb_wmask = slot_wmask[63:48];
                hb_col   = slot_col[29:24];
            end
        endcase
    end

    // Palabra y mascara del beat que toca de la rafaga de escritura.
    reg [15:0] wr_word;
    reg [1:0]  wr_msk2;
    integer    wk;

    always @* begin
        wr_word = 16'd0;
        wr_msk2 = 2'd0;
        for (wk = 0; wk < 8; wk = wk + 1)
            if (wr_idx == wk[2:0]) begin
                wr_word = wr_buf[wk*16 +: 16];
                wr_msk2 = wr_mask[wk*2 +: 2];
            end
    end

    wire col_issue =
        run &&
        ord_v[0] &&
        row_open[hb] &&
        rcd_z[hb] &&
        (hb_write ? gap_wr_z : gap_rd_z);

    // ACTIVE: la peticion mas antigua cuyo banco este libre.
    //
    // La candidata se elige UN CICLO ANTES de poder usarse (ver `sel_v`), asi
    // que se mira `rec_zn`, "rec_z valdra 1 el ciclo que viene". Si se mirara
    // `rec_z` el ACTIVE saldria un ciclo tarde justo en el caso que mas
    // importa, el de un banco que se recupera con la siguiente peticion ya
    // esperando.
    wire [3:0] rec_zn = {!rec_t[3*16 + 1], !rec_t[2*16 + 1],
                         !rec_t[1*16 + 1], !rec_t[0*16 + 1]};

    // Elegibilidad, banco y fila de CADA posicion de la cola, en paralelo, y
    // despues una seleccion one-hot de la primera elegible. Antes era un
    // recorrido en serie (`!act_found` encadenaba las cuatro posiciones), de ahi
    // salia `act_bank` y SOLO ENTONCES un mux 4:1 de 13 bits elegia la fila:
    // 13 LUT hasta `sel_row`, 11,7 ns en la 36 con la GPU delante (sdram_clk
    // 85,5 MHz). Ahora el mux de fila de cada posicion se calcula a la vez que
    // la elegibilidad y la primera elegible solo lo selecciona.
    wire [1:0]  act_pb0 = ord_q[1:0], act_pb1 = ord_q[3:2],
                act_pb2 = ord_q[5:4], act_pb3 = ord_q[7:6];

    function [12:0] row_of_bank;
        input [1:0] b;
        input [4*16-1:0] rows;
        begin
            case (b)
                2'd0:    row_of_bank = rows[12:0];
                2'd1:    row_of_bank = rows[28:16];
                2'd2:    row_of_bank = rows[44:32];
                default: row_of_bank = rows[60:48];
            endcase
        end
    endfunction

    wire [3:0] act_e = {
        ord_v[3] && !row_open[act_pb3] && rec_zn[act_pb3],
        ord_v[2] && !row_open[act_pb2] && rec_zn[act_pb2],
        ord_v[1] && !row_open[act_pb1] && rec_zn[act_pb1],
        ord_v[0] && !row_open[act_pb0] && rec_zn[act_pb0]};
    // La primera elegible, one-hot: cada posicion mira solo a las anteriores.
    wire [3:0] act_f = {act_e[3] && !(|act_e[2:0]),
                        act_e[2] && !(|act_e[1:0]),
                        act_e[1] && !act_e[0],
                        act_e[0]};

    wire       act_found = |act_e;
    // Sin candidata vale 0 (banco 0, fila 0); `sel_v` es 0 y nadie la usa.
    wire [1:0] act_bank = ({2{act_f[0]}} & act_pb0) | ({2{act_f[1]}} & act_pb1) |
                          ({2{act_f[2]}} & act_pb2) | ({2{act_f[3]}} & act_pb3);
    wire [12:0] act_row =
        ({13{act_f[0]}} & row_of_bank(act_pb0, slot_row)) |
        ({13{act_f[1]}} & row_of_bank(act_pb1, slot_row)) |
        ({13{act_f[2]}} & row_of_bank(act_pb2, slot_row)) |
        ({13{act_f[3]}} & row_of_bank(act_pb3, slot_row));

    // La candidata se REGISTRA: elegirla (recorrer la cola de orden, mirar
    // fila abierta y recuperacion de cada banco) y ademas emitir el comando
    // en el mismo ciclo eran nueve niveles de logica a 100 MHz. Con la
    // candidata en un registro, el ciclo siguiente solo la revalida.
    //
    // Revalidar es mirar `row_open` de ese banco: lo unico que puede haber
    // cambiado entre elegirla y usarla es que el ACTIVE de esa misma
    // candidata saliera en el ciclo intermedio. Un slot ocupado no se libera
    // sin fila abierta, y `rec_z` solo puede subir.
    reg        sel_v;
    reg [1:0]  sel_b;
    reg [12:0] sel_row;

    wire act_issue =
        run && !col_issue && sel_v && !row_open[sel_b] &&
        trrd_z && !ref_wait;

    // Valor que tendra wr_run el ciclo siguiente.
    wire wr_run_n = (col_issue && hb_write) ? 1'b1 :
                    col_issue ? wr_run :
                    (wr_run && wr_idx != 3'd7);

    // REFRESH: solo con los cuatro bancos precargados y el bus quieto.
    wire all_idle =
        !ord_v[0] && (&rec_z) &&
        gap_rd_z && gap_wr_z && !wr_run;

    wire refresh_issue = (ref_state == R_DRAIN) && all_idle;

    // Cola de orden: sale la cabeza al emitir columna, entra la peticion nueva.
    reg [7:0] ord_n;
    reg [3:0] v_n;
    integer   ord_p;

    always @* begin
        ord_n = ord_q;
        v_n = ord_v;
        if (col_issue) begin
            ord_n = {2'b00, ord_q[7:2]};
            v_n = {1'b0, ord_v[3:1]};
        end
        // La peticion nueva ocupa la primera posicion libre.
        for (ord_p = 0; ord_p < 4; ord_p = ord_p + 1)
            if (accept && !v_n[ord_p] && (ord_p == 0 || v_n[(ord_p + 3) % 4]))
                ord_n[ord_p*2 +: 2] = req_bank;
        if (accept)
            v_n = {v_n[2:0], 1'b1};
    end

    // ------------------------------------------------------------
    // Main FSM
    // ------------------------------------------------------------

    integer i;

    always @(posedge clk) begin

        if (reset) begin

            ini_state <= I_WAIT;
            init_count <= 0;
            init_refreshes <= 0;
            timing_count <= 0;

            ref_state <= R_NONE;
            ref_wait <= 1'b0;
            refresh_count <= 0;
            refresh_due <= 1'b0;

            cmd_q <= CMD_NOP;
            a_q <= 0;
            ba_q <= 0;
            dqm_q <= 2'b11;
            dq_oe <= 1'b0;
            dq_out <= 16'h0000;

            slot_valid <= 0;
            slot_write <= 0;
            row_open <= 0;
            rcd_t <= 0;
            rec_t <= 0;
            gap_rd_t <= 0;
            gap_wr_t <= 0;
            trrd_t <= 0;
            rcd_z <= 4'hf;
            rec_z <= 4'hf;
            gap_rd_z <= 1'b1;
            gap_wr_z <= 1'b1;
            trrd_z <= 1'b1;
            ord_q <= 0;
            ord_v <= 0;
            sel_v <= 1'b0;
            sel_b <= 2'd0;
            sel_row <= 13'd0;

            wr_run <= 1'b0;
            wr_idx <= 0;
            rd_pipe <= 0;
            dn_pipe <= 0;
            cap_run <= 1'b0;
            cap_oh <= 0;
            wr_free <= 1'b1;
            inflight <= 0;

            done <= 1'b0;
            rdata <= 0;

            init_done <= 1'b0;

            sdram_cke <= 1'b1;

        end else begin

            // Por defecto, NOP y DQ suelto; lo que sigue lo sobreescribe.
            cmd_q <= CMD_NOP;
            a_q <= 13'd0;
            ba_q <= 2'd0;
            dqm_q <= 2'b00;
            dq_oe <= 1'b0;
            done <= 1'b0;

            // ----------------------------------------------------
            // Temporizadores
            // ----------------------------------------------------

            for (i = 0; i < 4; i = i + 1) begin
                rcd_t[i*16 +: TW] <= {1'b0, rcd_t[i*16 + 1 +: TW-1]};
                rec_t[i*16 +: TW] <= {1'b0, rec_t[i*16 + 1 +: TW-1]};
                rcd_z[i] <= !rcd_t[i*16 + 1];
                rec_z[i] <= !rec_t[i*16 + 1];
            end
            gap_rd_t <= {1'b0, gap_rd_t[TW-1:1]};
            gap_wr_t <= {1'b0, gap_wr_t[TW-1:1]};
            trrd_t <= {1'b0, trrd_t[TW-1:1]};
            gap_rd_z <= !gap_rd_t[1];
            gap_wr_z <= !gap_wr_t[1];
            trrd_z <= !trrd_t[1];

            // El temporizador de refresco se detiene al vencer: lo unico que
            // importa es que haya vencido, y asi `refresh_due` es un bit
            // registrado en vez de una comparacion de 32 bits delante de
            // `req_ready`.
            if (init_done && !refresh_due) begin
                refresh_count <= refresh_count + 1'b1;
                if (refresh_count + 16'd1 >= REFRESH_TRIGGER_CYCLES[15:0])
                    refresh_due <= 1'b1;
            end

            // ====================================================
            // INICIALIZACION
            // ====================================================

            if (!init_done) begin
                case (ini_state)

                    I_WAIT: begin
                        dqm_q <= 2'b11;
                        if (init_count + 1 >= POWERUP_DELAY_CYCLES) begin
                            init_count <= 0;
                            ini_state <= I_PRE;
                        end else begin
                            init_count <= init_count + 1'b1;
                        end
                    end

                    I_PRE: begin
                        cmd_q <= CMD_PRECHARGE;
                        a_q <= 13'h0400;    // A10=1 -> todos los bancos
                        timing_count <= 0;
                        ini_state <= I_PRE_WAIT;
                    end

                    I_PRE_WAIT: begin
                        if (timing_count + 16'd1 >= TRP_CYCLES[15:0]) begin
                            timing_count <= 0;
                            ini_state <= I_REF;
                        end else begin
                            timing_count <= timing_count + 1'b1;
                        end
                    end

                    I_REF: begin
                        cmd_q <= CMD_REFRESH;
                        timing_count <= 0;
                        ini_state <= I_REF_WAIT;
                    end

                    I_REF_WAIT: begin
                        if (timing_count + 16'd1 >= TRFC_CYCLES[15:0]) begin
                            timing_count <= 0;
                            if (init_refreshes == 4'd7) begin
                                init_refreshes <= 0;
                                ini_state <= I_MRS;
                            end else begin
                                init_refreshes <= init_refreshes + 1'b1;
                                ini_state <= I_REF;
                            end
                        end else begin
                            timing_count <= timing_count + 1'b1;
                        end
                    end

                    I_MRS: begin
                        cmd_q <= CMD_MRS;
                        // A2:A0 = 011 -> burst length 8
                        // A3    = 0   -> secuencial
                        // A6:A4 = 010 -> CAS latency 2
                        // A9    = 0   -> escritura con la longitud programada
                        a_q <= 13'h023;
                        timing_count <= 0;
                        ini_state <= I_MRS_WAIT;
                    end

                    I_MRS_WAIT: begin
                        if (timing_count + 16'd1 >= TMRD_CYCLES[15:0]) begin
                            timing_count <= 0;
                            init_done <= 1'b1;
                            refresh_count <= 0;
                        end else begin
                            timing_count <= timing_count + 1'b1;
                        end
                    end

                    default: ini_state <= I_WAIT;
                endcase
            end

            // ====================================================
            // OPERACION
            // ====================================================

            // ---- Refresco periodico ------------------------------

            case (ref_state)
                R_NONE: begin
                    if (refresh_due)
                        ref_state <= R_DRAIN;
                end

                R_DRAIN: begin
                    if (refresh_issue) begin
                        cmd_q <= CMD_REFRESH;
                        refresh_count <= 0;
                        refresh_due <= 1'b0;
                        timing_count <= TRFC_CYCLES[15:0] - 16'd1;
                        ref_state <= R_WAIT;
                        ref_wait <= 1'b1;
                    end
                end

                default: begin   // R_WAIT
                    if (timing_count == 0) begin
                        ref_state <= R_NONE;
                        ref_wait <= 1'b0;
                    end else
                        timing_count <= timing_count - 1'b1;
                end
            endcase

            // ---- Aceptar una peticion en el slot de su banco ------

            // Bucles con indice constante en vez de `[req_bank*N +: M]`: un
            // selector variable genera aritmetica de indices (sumas de 33 bits
            // en el netlist) justo en el camino de decision.
            for (i = 0; i < 4; i = i + 1) begin
                if (accept && req_bank == i[1:0]) begin
                    slot_valid[i] <= 1'b1;
                    slot_write[i] <= req_write;
                    slot_row[i*16 +: 13] <= req_addr[23:11];
                    slot_col[i*8 +: 6] <= req_addr[8:3];
                    slot_wdata[i*128 +: 128] <= req_wdata;
                    slot_wmask[i*16 +: 16] <= req_wmask;
                end else if (col_issue && hb == i[1:0]) begin
                    // Un slot ocupado nunca recibe una peticion nueva, asi que
                    // las dos condiciones no coinciden en el mismo banco.
                    slot_valid[i] <= 1'b0;
                end
            end

            ord_q <= ord_n;
            ord_v <= v_n;

            sel_v <= act_found;
            sel_b <= act_bank;
            sel_row <= act_row;

            case ({accept, done})
                2'b10: inflight <= inflight + 1'b1;
                2'b01: inflight <= inflight - 1'b1;
                default: inflight <= inflight;
            endcase

            // ---- ACTIVE ------------------------------------------

            if (act_issue) begin
                cmd_q <= CMD_ACTIVE;
                a_q <= sel_row;
                ba_q <= sel_b;
                trrd_t <= T_TRRD;
                trrd_z <= (TRRD_CYCLES - 1 == 0);
            end

            for (i = 0; i < 4; i = i + 1) begin
                if (act_issue && sel_b == i[1:0]) begin
                    row_open[i] <= 1'b1;
                    rcd_t[i*16 +: TW] <= T_TRCD;
                    rcd_z[i] <= (TRCD_CYCLES - 1 == 0);
                end
                if (col_issue && hb == i[1:0]) begin
                    row_open[i] <= 1'b0;
                    rec_t[i*16 +: TW] <=
                        hb_write ? T_WR_RECOVERY : T_RD_RECOVERY;
                    rec_z[i] <= 1'b0;     // los dos recuperos son >= 1
                end
            end

            // ---- READ / WRITE ------------------------------------

            // El buffer de escritura se precarga desde el slot de la cabeza
            // mientras no haya una escritura en curso. En el ciclo en que sale
            // el WRITE, `wr_run` aun vale 0 y carga justo el dato de ese slot;
            // despues `wr_run` lo congela. Asi su habilitacion no cuelga de
            // `col_issue`, que ya tiene bastante fanout.
            if (wr_free) begin
                wr_buf <= hb_wdata;
                wr_mask <= hb_wmask;
            end

            if (col_issue) begin
                cmd_q <= hb_write ? CMD_WRITE : CMD_READ;

                // A10 = 1 -> auto-precarga. A9 = 0. A8:A0 = columna.
                a_q <= {2'b00, 1'b1, 1'b0, hb_col, 3'b000};
                ba_q <= hb;

                gap_rd_t <= T_GAP_SAME;
                gap_wr_t <= hb_write ? T_GAP_SAME : T_GAP_RD_TO_WR;
                gap_rd_z <= 1'b0;
                gap_wr_z <= 1'b0;

                if (hb_write) begin
                    // El beat 0 sale junto con el comando. Los otros siete
                    // salen de wr_buf, asi que el slot queda libre ya.
                    dq_oe <= 1'b1;
                    dq_out <= hb_wdata[15:0];

                    // DQM = 1 enmascara el byte; nuestra mascara es 1 = escribir.
                    dqm_q <= ~hb_wmask[1:0];

                    wr_idx <= 3'd1;
                    wr_run <= 1'b1;
                end
            end else if (wr_run) begin
                dq_oe <= 1'b1;
                dq_out <= wr_word;
                dqm_q <= ~wr_msk2;
                wr_idx <= wr_idx + 1'b1;
                if (wr_idx == 3'd7)
                    wr_run <= 1'b0;
            end

            // ---- Captura de la rafaga de lectura -----------------

            rd_pipe <= {rd_pipe[DCAP-1:0], col_issue && !hb_write};
            dn_pipe <= {dn_pipe[DCAP+6:0], col_issue};

            // Del registro de flanco de bajada, no de DQ directamente.
            // Ver `dq_negedge` arriba.
            if (cap0)
                rdata[15:0] <= dq_negedge;
            for (i = 1; i < 8; i = i + 1)
                if (cap_oh[i])
                    rdata[i*16 +: 16] <= dq_negedge;
            cap_oh <= {cap_oh[6:1], cap0};
            cap_run <= cap0 || (|cap_oh[6:1]);

            wr_free <= !wr_run_n;

            // `done` sube en el ciclo en que el ultimo beat ya esta en rdata.
            // Las escrituras usan la misma latencia: asi los `done` salen en
            // el orden de las peticiones aunque se mezclen lecturas y
            // escrituras.
            done <= dn_pipe[DCAP+7];
        end
    end

    // ------------------------------------------------------------
    // Simulation checks
    // ------------------------------------------------------------

`ifndef SYNTHESIS

    // Los temporizadores termometricos tienen TW bits; un valor que no quepa
    // se cargaria truncado y el controlador emitiria comandos demasiado pronto.
    initial begin
        if (RD_RECOVERY >= TW || WR_RECOVERY >= TW || GAP_SAME >= TW ||
            GAP_RD_TO_WR >= TW || TRCD_CYCLES - 1 >= TW || TRRD_CYCLES - 1 >= TW)
            $error("sdram_controller_128: un temporizador no cabe en TW=%0d bits; sube TW", TW);
    end

    always @(posedge clk) begin

        if (
            !reset &&
            req_valid &&
            req_ready &&
            req_addr[2:0] != 3'b000
        ) begin

            // Dos literales pegados no son Verilog, aunque lo parezcan: asi
            // escrito, este fichero ni siquiera elaboraba.
            $error("sdram_controller_128: req_addr debe estar alineado a 8 palabras de SDRAM / 16 bytes");
        end

        // El `done` de una escritura o lectura nunca puede llegar sin
        // peticion pendiente.
        if (!reset && done && inflight == 4'd0)
            $error("sdram_controller_128: done sin peticion en vuelo");
    end

`endif

endmodule

`default_nettype wire
