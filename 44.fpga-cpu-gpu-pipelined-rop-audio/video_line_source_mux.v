`default_nettype none

// Elige cual de las dos fuentes de linea llena el line buffer, y la SOSTIENE
// hasta que la linea termina.
//
// Por que existe este modulo
// --------------------------
// Antes esto eran cuatro `assign` sueltos dentro de top_bl8, puerteados
// directamente por `video_mode`:
//
//     .fill_start(fill_start && scanout_on)     <- fuente SDRAM
//     .fill_start(fill_start && !scanout_on)    <- fuente patron
//     assign fill_done = scanout_on ? burst_done : pat_done;
//
// `video_mode` vive en el dominio de sistema y cambia cuando el software
// escribe VIDEO_CTRL, sin ninguna relacion con el llenado en curso. Si cambiaba
// con una linea a medias, la fuente que estaba trabajando dejaba de pasar el
// mux -- su `fill_done` ya no llegaba -- y la otra nunca habia visto su
// `fill_start`, asi que no tenia nada que terminar. Nadie daba el `fill_done`
// que video_scanout espera, y el video se quedaba ENCALLADO para siempre: cero
// peticiones al fabric, sin underflow (nadie pide datos que falten) y con el
// dominio de pixel intacto. En placa solo se recuperaba reprogramando la FPGA;
// el reset de la GPU no toca esto.
//
// Se veia poco mientras el host encendia el scanout una vez por sesion, con la
// GPU parada. Desde que los kernels se configuran el video ellos mismos, el
// salto PATTERN -> SCANOUT lo hace la GPU en marcha, en un instante arbitrario
// y en CADA arranque de programa.
//
// La regla
// --------
// El modo se muestrea en el pulso de `fill_start` y se guarda en `mode_active`.
// Durante toda la linea el mux usa ese registro, no `video_mode`. Un cambio de
// modo a media linea no se pierde: se aplica en la linea SIGUIENTE. Como mucho
// se ve una linea con el contenido del modo anterior, que a 60 Hz nadie percibe
// y es infinitamente preferible a colgar el video.
//
// Las fuentes registran sus salidas, asi que no producen nada el mismo ciclo
// del `fill_start`; para cuando la primera palabra sale, `mode_active` ya esta
// actualizado. Por eso el muestreo puede ser sincrono sin perder el primer dato.
//
// Lo comprueba gpu_video_mode_switch_tb.

module video_line_source_mux (
    input  wire        clk,
    input  wire        reset,

    // Modo pedido por software (VIDEO_CTRL). Cambia de forma asincrona al
    // llenado; aqui dentro se domestica.
    input  wire [1:0]  video_mode,

    // Peticion de linea del video_scanout.
    input  wire        fill_start,

    // Arranque puerteado hacia cada fuente.
    output wire        start_sdram,
    output wire        start_pattern,

    // Lo que devuelve la fuente de SDRAM.
    input  wire        burst_we,
    input  wire [8:0]  burst_addr,
    input  wire [15:0] burst_data,
    input  wire        burst_done,

    // Lo que devuelve la fuente de patron.
    input  wire        pat_we,
    input  wire [8:0]  pat_addr,
    input  wire [15:0] pat_data,
    input  wire        pat_done,

    // Hacia el line buffer.
    output wire        fill_we,
    output wire [8:0]  fill_addr,
    output wire [15:0] fill_data,
    output wire        fill_done
);
    localparam [1:0] MODE_SCANOUT = 2'd2;

    wire mode_now = (video_mode == MODE_SCANOUT);

    // El arranque va con el modo del instante: es el mismo ciclo en que se
    // muestrea, asi que la fuente que arranca es la que luego selecciona
    // `mode_active`.
    assign start_sdram   =  fill_start && mode_now;
    assign start_pattern =  fill_start && !mode_now;

    reg mode_active;
    always @(posedge clk) begin
        if (reset) mode_active <= 1'b0;
        else if (fill_start) mode_active <= mode_now;
    end

    assign fill_we   = mode_active ? burst_we   : pat_we;
    assign fill_addr = mode_active ? burst_addr : pat_addr;
    assign fill_data = mode_active ? burst_data : pat_data;
    assign fill_done = mode_active ? burst_done : pat_done;
endmodule

`default_nettype wire
