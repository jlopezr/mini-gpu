`default_nettype none
// Cliente sintetico que imita el TRAFICO de un scanout de video, sin dibujar
// nada. Sirve para medir cuanto le cuesta a la GPU compartir el canal ANTES de
// escribir una linea de video_scanout/line_buffer/HDMI.
//
// Modela el patron real, que es a rafagas y no un goteo constante: un line
// buffer se rellena de golpe con una linea entera y luego calla hasta la
// siguiente. Se modela asi a proposito porque es MAS duro que el goteo, y
// porque es lo que de verdad hace daño a un cliente limitado por latencia.
//
// Valores por defecto = framebuffer de 21 (320x240 RGB565 doblado a 640x480):
//
//   320 px x 2 B = 640 B por linea fuente = 40 transacciones de 16 B
//   240 lineas fuente a 60 Hz, con blanking: una linea nueva cada ~1588
//   ciclos a 25 MHz
//   -> 40 x 240 x 60 x 16 B = 9,2 MB/s
//
// `urgent` va alto durante la rafaga: es lo que hace memory_fabric_4 para que
// el video no pierda su plazo, y es justo lo que encarece al resto.
module video_traffic_gen #(
    parameter integer BURST  = 40,     // transacciones por linea fuente
    parameter integer PERIOD = 1588,   // ciclos entre lineas
    parameter [31:0] FB_BASE = 32'h0010_0000
) (
    input wire clk, reset, enable,

    output wire         req_valid,
    input  wire         req_ready,
    output wire         req_write,
    output reg  [31:0]  req_addr,
    output wire [127:0] req_wdata,
    output wire [15:0]  req_wmask,
    output wire         urgent,

    input  wire         rsp_valid,
    output wire         rsp_ready,
    input  wire [127:0] rsp_rdata,
    input  wire         rsp_error,

    output reg [31:0] transactions
);
    reg [15:0] tick;
    reg [7:0] pending;

    assign req_write=1'b0;
    assign req_wdata=128'd0;
    assign req_wmask=16'd0;
    assign req_valid=enable && pending!=0;
    assign urgent=enable && pending!=0;
    assign rsp_ready=1'b1;

    always @(posedge clk) begin
        if(reset) begin
            tick<=0; pending<=0; req_addr<=FB_BASE; transactions<=0;
        end else if(enable) begin
            if(tick>=PERIOD[15:0]-1) begin
                tick<=0;
                // Si la rafaga anterior no acabo, el video ya iba tarde: se
                // pisa igualmente, como haria un line buffer de verdad.
                pending<=BURST[7:0];
            end else tick<=tick+1'b1;

            if(rsp_valid && pending!=0) begin
                pending<=pending-1'b1;
                transactions<=transactions+1'b1;
                req_addr<=req_addr+32'd16;
            end
        end
    end
endmodule
`default_nettype wire
