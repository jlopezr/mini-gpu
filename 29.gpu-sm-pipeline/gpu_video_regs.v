`default_nettype none
// Registros de video de la MiniGPU, en 0x80000000.
//
// Misma direccion y MISMOS OFFSETS que en los cores de CPU (16, 18, 19, 21).
// Antes este bloque estaba en 0x80000200, porque 0x80000000 lo ocupaba la
// configuracion de warps; ahora los warps viven en 0x80001000 (segunda pagina,
// exclusiva de la GPU) y la primera pagina queda para lo compartido. Ver
// docs/resumen-prototipos.md.
//
// Que coincida el bloque no basta si no coinciden los offsets dentro de el, asi
// que VIDEO_CTRL -que solo tiene la GPU- se va al FINAL en vez de ocupar el
// offset 0: asi ningun programa de CPU cambia y solo se toca esta carpeta.
//
//   0x80000000  FB_FRONT     RW  direccion de byte del buffer que se MUESTRA
//   0x80000004  FB_BACK      RW  direccion de byte del buffer que se DIBUJA
//   0x80000008  SWAP         RW  escribir 1: pedir intercambio en el proximo
//                                vsync; leer bit 0: intercambio pendiente
//   0x8000000c  VIDEO_STATUS RW  bit 0     underflow del line buffer (pegajoso)
//                                bit 1     intercambio pendiente
//                                31:16     contador de frames de video
//                                escribir bit 0 a 1: borra el underflow
//   0x80000010  SWAP_COUNT   R   intercambios completados desde el reset
//   0x80000014  (HALT_AT)    R0  solo CPU. Aqui lee cero y la escritura se
//                                ignora, igual que la CPU con un registro que no
//                                tiene. La GPU no se para sola: la paran las
//                                ordenes del monitor, y sus kernels terminan con
//                                HALT, asi que no hace falta armar una captura.
//   0x80000018  VIDEO_CTRL   RW  bits 1:0  modo de salida
//                                    0  BLANK    negro, sin leer SDRAM
//                                    1  PATTERN  patron de prueba, sin leer SDRAM
//                                    2  SCANOUT  framebuffer desde SDRAM
//                                    3  reservado (se trata como BLANK)
//
// Doble buffer
// ------------
// Sin el, el scanout lee a 60 Hz la MISMA memoria que la GPU reescribe a ~8
// fps: cada imagen mostrada mezcla contenido viejo y nuevo y la frontera se
// mueve, que es lo que se veia como una imagen inestable.
//
// El intercambio se hace en el pulso de vsync, no cuando se pide: cambiar la
// direccion a mitad de un frame mostrado partiria la imagen en dos, que es
// justo lo que se quiere evitar.
//
// Quien pide el intercambio es la GPU, no el host. Eso solo es posible desde
// que la ventana MMIO esta abierta a la LSU (ver mmio.md); en 21 lo hace la
// CPU, y aqui no habria nadie que pudiera hacerlo 8 veces por segundo.
//
// Tras el reset el modo es PATTERN, no SCANOUT. La razon esta en
// video-scanout.md: la SDRAM recien encendida contiene basura, asi que arrancar
// en SCANOUT es elegir un valor por defecto cuya salida es indefinida. Con
// PATTERN, ver el patron demuestra que HDMI, PLL, cable y monitor funcionan, y
// no verlo senala aguas arriba. Los dos fallos dejan de parecerse.
module gpu_video_regs (
    input wire clk, reset,

    input wire        sel,          // la direccion cae en el bloque de video
    input wire [3:0]  word,         // address[5:2]
    input wire        write,
    input wire [31:0] write_data,
    input wire [3:0]  write_strobe,
    output reg [31:0] read_data,
    output reg        bad,

    input wire underflow,
    input wire frame_pulse,         // un pulso por vsync, dominio de sistema

    // VIDEO_TX (§9.7): una transaccion de memoria del scanout por pulso.
    // Vivia en `gpu_perf_counters` y se ha mudado aqui porque §12.1 dice que
    // un contador es de quien GENERA el evento, y el scanout es de VIDEO.
    //
    // `running` viene con el: alli el contador estaba gated por «la GPU
    // corre», porque el scanout sigue leyendo SDRAM con la GPU parada y contar
    // ese trafico ensucia el reparto entre datos, video y fetch. La regla se
    // muda con el contador; si se pierde, el numero vuelve a medir el reloj de
    // pared y no el programa.
    input wire video_tx,
    input wire running,

    output reg [1:0]  video_mode,
    output wire [23:0] fb_base,     // al scanout: PALABRA de 16 bits del frente
    output wire       underflow_clear
);
    localparam [1:0] MODE_PATTERN=2'd1;
    // Los offsets son los del contrato compartido con la CPU: MMIO v2 §9, los
    // mismos numeros que `video_registers.v` de 16/18/19/21.
    //
    // ESTE ES EL BLOQUE QUE MAS SE MUEVE al pasar de v1 a v2, y no cambia de
    // base sino de reparto INTERNO. En v1 `CTRL` estaba al final, en la palabra
    // 6, porque se anadio despues; en v2 esta en la 0 y empuja a los demas.
    // Los cuatro que usan los kernels --FB_FRONT, FB_BACK, SWAP y CTRL--
    // cambian los cuatro. Un programa migrado a medias no falla al ensamblar:
    // escribe en el registro de al lado.
    //
    // Y aparece `FRAME_COUNT` como registro propio (§9.5). En v1 el contador
    // de frames viajaba empotrado en los bits 31:16 de `STATUS`; ahora STATUS
    // son solo las dos banderas y el contador es una palabra entera de 32
    // bits, no de 16.
    localparam [3:0] REG_CTRL        = 4'd0;   // +0x00
    localparam [3:0] REG_FB_FRONT    = 4'd1;   // +0x04
    localparam [3:0] REG_FB_BACK     = 4'd2;   // +0x08
    localparam [3:0] REG_SWAP        = 4'd3;   // +0x0C
    localparam [3:0] REG_STATUS      = 4'd4;   // +0x10
    localparam [3:0] REG_FRAME_COUNT = 4'd5;   // +0x14
    localparam [3:0] REG_SWAP_COUNT  = 4'd6;   // +0x18
    localparam [3:0] REG_HALT_AT     = 4'd7;   // +0x1C
    localparam [3:0] REG_HALT_TARGET = 4'd8;   // +0x20
    localparam [3:0] REG_VIDEO_TX    = 4'd9;   // +0x24

    reg underflow_sticky;
    reg [15:0] frame_count;
    reg [31:0] video_tx_count;

    // §9.2: una base de framebuffer mal alineada genera ERROR, «no se trunca
    // ni se corrige». Hasta aqui esto truncaba en silencio --4 bytes en CPU y
    // 16 en GPU--, o sea que el mismo programa dibujaba bien en una placa y
    // torcido en la otra sin que nada avisara. Es el motivo que da §9.2 para
    // exigir el error, y `shared-video-fb-desalineada` es el caso que lo mide.
    //
    // Se juzga la palabra ENTERA que llega, no el registro ya guardado: el
    // error sale ANTES de escribir nada. Y solo con los cuatro strobes, que es
    // como escribe WRITE_WORD: una escritura byte a byte no puede juzgarse a
    // trozos --el registro pasa por estados intermedios desalineados que son
    // legitimos-- y por eso el caso usa la palabra entera.
    wire fb_desalineada = sel && write && write_strobe==4'b1111 &&
                          (word==REG_FB_FRONT || word==REG_FB_BACK) &&
                          |write_data[3:0];
    reg clear_pulse;
    assign underflow_clear=clear_pulse;

    // Los registros guardan direcciones de BYTE, que es lo que espera ver quien
    // los escribe. video_line_source_burst quiere una direccion de PALABRA de
    // 16 bits (hace `fb_base + fill_line*320`), asi que la conversion es >>1 --
    // no >>2, que es en lo que me equivoque primero y el banco no lo vio porque
    // solo comprobaba que hubiera peticiones, no a donde iban.
    reg [31:0] fb_front, fb_back;
    reg swap_pending;
    reg [31:0] swap_count;
    assign fb_base={fb_front[24:4],3'b000};

    always @* begin
        read_data=32'd0; bad=1'b0;
        if(fb_desalineada) bad=1'b1;
        if(sel) case(word)
            REG_CTRL:       read_data={30'd0,video_mode};
            REG_FB_FRONT:   read_data={fb_front[31:4],4'b0000};
            REG_FB_BACK:    read_data={fb_back[31:4],4'b0000};
            REG_SWAP:       read_data={31'd0,swap_pending};
            // El bit 1 es `swap_pending`, igual que en 16/18/19/21. Antes era
            // cero fijo aqui, y un programa que sondease ese bit esperando al
            // intercambio funcionaba en CPU y se colgaba en esta placa.
            //
            // En v2 STATUS son SOLO las dos banderas: el contador de frames se
            // ha ido a su propio registro. Un programa de v1 que leyera STATUS
            // y se quedara con los bits 31:16 para tener el frame ahora lee
            // ceros -- no falla, devuelve otra cosa. Por eso la migracion de
            // los `.asm` se hace por simbolo y no a ojo.
            REG_STATUS:      read_data={30'd0,swap_pending,underflow_sticky};
            REG_FRAME_COUNT: read_data={16'd0,frame_count};
            REG_SWAP_COUNT:  read_data=swap_count;
            // HALT_AT, HALT_TARGET y VIDEO_TX no existen aqui: la GPU no se
            // para sola, la paran las ordenes del monitor. Leen CERO en vez de
            // levantar `bad`, que es lo que hace la CPU con un registro ausente
            // del bloque (video_registers.v, `default: read_data = 32'd0`). Si
            // fallaran, una lectura en bloque del bloque de video entero --que
            // la lista blanca de monitor.v permite-- daria NACK a mitad, y un
            // programa que sondee el registro se comportaria distinto en cada
            // familia. Escribirlos se ignora, igual que en CPU.
            REG_VIDEO_TX:    read_data=video_tx_count;
            REG_HALT_AT,
            REG_HALT_TARGET: read_data=32'd0;
            default:        bad=1'b1;
        endcase
    end

    always @(posedge clk) begin
        clear_pulse<=1'b0;
        if(reset) begin
            video_mode<=MODE_PATTERN;
            fb_front<=32'd0; fb_back<=32'd0;
            swap_pending<=1'b0; swap_count<=32'd0;
            underflow_sticky<=1'b0;
            frame_count<=16'd0;
            video_tx_count<=32'd0;
        end else begin
            // Gated por `running`, igual que cuando vivia en los contadores.
            if(video_tx && running) video_tx_count<=video_tx_count+1'b1;
            if(underflow) underflow_sticky<=1'b1;
            if(frame_pulse) begin
                frame_count<=frame_count+1'b1;
                // El intercambio ocurre AQUI, en el vsync, no cuando se pide.
                if(swap_pending) begin
                    fb_front<=fb_back;
                    fb_back<=fb_front;
                    swap_pending<=1'b0;
                    swap_count<=swap_count+1'b1;
                end
            end
            // `!fb_desalineada`: una base rechazada no se guarda ni a medias.
        if(sel && write && !fb_desalineada) case(word)
                REG_CTRL: if(write_strobe[0]) video_mode<=write_data[1:0];
                // Byte a byte, que es como escribe el monitor; la GPU escribe
                // los cuatro a la vez. La alineacion a 16 bytes se impone al
                // leer, no al escribir.
                REG_FB_FRONT: begin
                    if(write_strobe[0]) fb_front[7:0]  <=write_data[7:0];
                    if(write_strobe[1]) fb_front[15:8] <=write_data[15:8];
                    if(write_strobe[2]) fb_front[23:16]<=write_data[23:16];
                    if(write_strobe[3]) fb_front[31:24]<=write_data[31:24];
                end
                REG_FB_BACK: begin
                    if(write_strobe[0]) fb_back[7:0]  <=write_data[7:0];
                    if(write_strobe[1]) fb_back[15:8] <=write_data[15:8];
                    if(write_strobe[2]) fb_back[23:16]<=write_data[23:16];
                    if(write_strobe[3]) fb_back[31:24]<=write_data[31:24];
                end
                REG_SWAP: if(write_strobe[0] && write_data[0]) swap_pending<=1'b1;
                REG_STATUS: if(write_strobe[0] && write_data[0]) begin
                    underflow_sticky<=1'b0; clear_pulse<=1'b1;
                end
                default: ;
            endcase
        end
    end
endmodule
`default_nettype wire
