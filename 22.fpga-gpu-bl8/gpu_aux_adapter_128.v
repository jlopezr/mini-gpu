`default_nettype none
// Traduce el puerto auxiliar de 32 bits de gpu_system (fetch de instrucciones
// cuando la GPU corre, monitor/host byte a byte cuando esta halted) a un puerto
// de 128 bits de memory_fabric_4.
//
// Es deliberadamente tonto: un acceso en vuelo, sin cache. El
// instruction_buffer.v de 21 hace esto MISMO pero ademas cachea 4 lineas de 16
// bytes, que es donde esta la ganancia de verdad para el fetch. Se deja para
// despues a proposito: primero medir el cambio de canal (BL1 -> BL8) sin
// mezclarlo con el efecto de una cache, que si no no se sabe cual de los dos
// movio el numero.
//
// Las escrituras parciales van por mascara de bytes, sin leer antes: el
// controlador BL8 tiene mascara de 16 bits. Igual que cpu_dmem_adapter.v.
module gpu_aux_adapter_128 (
    input clk, reset, init_done,

    input aux_valid, output aux_ready,
    input [31:0] aux_address, aux_write_data,
    input [3:0] aux_strobe,
    output reg aux_rsp_valid, input aux_rsp_ready,
    output reg [31:0] aux_read_data, output reg aux_error,

    output req_valid, input req_ready,
    output req_write, output [31:0] req_addr,
    output [127:0] req_wdata, output [15:0] req_wmask,
    input rsp_valid, output rsp_ready,
    input [127:0] rsp_rdata, input rsp_error
);
    localparam IDLE=0, ISSUE=1, WAIT=2, RESPOND=3;
    reg [1:0] state;
    reg [31:0] address, write_data;
    reg [3:0] strobe;
    wire [1:0] slot=address[3:2];

    assign aux_ready=!reset && init_done && state==IDLE;
    assign req_valid=state==ISSUE;
    assign req_write=|strobe;
    assign req_addr={address[31:4],4'b0};
    assign req_wdata={4{write_data}};
    assign req_wmask={12'b0,strobe} << {slot,2'b0};
    assign rsp_ready=state==WAIT;

    always @(posedge clk) begin
        if(reset) begin
            state<=IDLE; address<=0; write_data<=0; strobe<=0;
            aux_rsp_valid<=0; aux_read_data<=0; aux_error<=0;
        end else case(state)
            IDLE: if(aux_valid && init_done) begin
                address<=aux_address; write_data<=aux_write_data; strobe<=aux_strobe;
                aux_error<=0;
                // Mismo criterio que la LSU v1: fuera de los 32 MB o no alineada
                // a palabra es fault, y no llega a tocar el fabric.
                if(|aux_address[31:25] || |aux_address[1:0]) begin
                    aux_error<=1; aux_read_data<=0; aux_rsp_valid<=1; state<=RESPOND;
                end else state<=ISSUE;
            end
            ISSUE: if(req_ready) state<=WAIT;
            WAIT: if(rsp_valid) begin
                aux_read_data<=rsp_rdata[{slot,5'b0} +: 32];
                aux_error<=rsp_error; aux_rsp_valid<=1; state<=RESPOND;
            end
            RESPOND: if(aux_rsp_ready) begin aux_rsp_valid<=0; state<=IDLE; end
        endcase
    end
endmodule
`default_nettype wire
