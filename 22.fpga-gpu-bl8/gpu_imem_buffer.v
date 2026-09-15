`default_nettype none
// Pone instruction_buffer.v (el de 21) detras del puerto imem de gpu_sm.
//
// Los dos contratos se parecen pero no son iguales:
//
//   cpu.v          : cpu_imem_valid sostenido, cpu_imem_ready pulsa con el dato
//   gpu_sm.v       : imem_valid/imem_ready para aceptar, y DESPUES
//                    imem_rsp_valid/imem_rsp_ready para la respuesta
//
// La primera version de este modulo traducia con una maquina de tres estados
// (S_IDLE -> S_FETCH -> S_RESP). Funcionaba, pero costaba DOS CICLOS DE MAS en
// cada busqueda, incluso acertando:
//
//   antes:  C0 handshake y latch de la direccion
//           C1 presentar al bufer, que registra el dato
//           C2 registrar el dato otra vez aqui
//           C3 devolverlo al SM                      -> 4 ciclos
//
//   ahora:  C0 handshake, el bufer registra el dato
//           C1 el pulso del bufer ES la respuesta    -> 2 ciclos
//
// Medido sobre un frame de plasma: 170 486 busquedas x 2 ciclos = 340 972 de
// 3 334 230, o sea un 10,2% del tiempo de frame (ver profiling.md).
//
// Las dos etapas sobraban por dos razones concretas:
//
//   - `imem_address` es `context_pc`, un REGISTRO del SM que no cambia durante
//     toda la busqueda: el SM se queda en FETCH_WAIT hasta la respuesta. No hay
//     nada que copiar, ni siquiera en un fallo, que tarda decenas de ciclos.
//   - `instruction_buffer` ya latchea en su ST_IDLE todo lo que necesita
//     (fill_index, fill_tag, want_word), asi que le basta un pulso de un ciclo
//     en `cpu_imem_valid`. Y su `cpu_imem_read_data` ya sale registrado:
//     volver a registrarlo aqui era redundante.
//
// INVARIANTE del que depende esto: el SM no puede tener dos busquedas en
// vuelo. `imem_valid` es `state==FETCH` y solo se sale de FETCH_WAIT con la
// respuesta, asi que nunca llega una peticion con el bufer ocupado, y por eso
// `imem_ready` puede ser constante. El dia que el SM segmente su cauce (la
// optimizacion grande de profiling.md) hay que revisar justo esto.
//
// El bufer se vacia mientras `halted` esta alto, que es cuando el monitor
// escribe la memoria de programa. Es el unico caso de incoherencia que hay:
// la GPU no escribe su propio codigo.
module gpu_imem_buffer #(
    parameter integer LINES = 4,
    parameter integer INDEX_BITS = 2,
    parameter [31:0] SDRAM_SIZE_BYTES = 32'h0200_0000
) (
    input wire clk, reset, init_done, halted,

    // Lado gpu_sm.
    input  wire        imem_valid,
    output wire        imem_ready,
    input  wire [31:0] imem_address,
    output wire        imem_rsp_valid,
    input  wire        imem_rsp_ready,
    output wire [31:0] imem_data,
    output wire        imem_error,

    // Lado fabric.
    output wire         req_valid,
    input  wire         req_ready,
    output wire         req_write,
    output wire [31:0]  req_addr,
    output wire [127:0] req_wdata,
    output wire [15:0]  req_wmask,
    input  wire         rsp_valid,
    output wire         rsp_ready,
    input  wire [127:0] rsp_rdata,
    input  wire         rsp_error,

    output wire [31:0] hit_count, miss_count
);
    wire buf_ready;
    wire [31:0] buf_data;

    assign imem_ready=!reset;
    assign imem_rsp_valid=buf_ready;
    assign imem_data=buf_data;

    // Mismo criterio de fault que tenia el camino auxiliar de la v1, para que
    // gpu_sm siga viendo el mismo error ante una direccion imposible; el bufer
    // por su cuenta responderia con opcode invalido, que no es lo mismo.
    // Se calcula de `imem_address` directamente porque, por el invariante de
    // arriba, sigue siendo la de esta busqueda cuando llega la respuesta.
    assign imem_error=|imem_address[31:25] || |imem_address[1:0];

    instruction_buffer #(.LINES(LINES),.INDEX_BITS(INDEX_BITS),
                         .SDRAM_SIZE_BYTES(SDRAM_SIZE_BYTES)) ib (
        .clk(clk),.reset(reset),.init_done(init_done),.cpu_halted(halted),
        .cpu_imem_valid(imem_valid),.cpu_imem_address(imem_address),
        .cpu_imem_read_data(buf_data),.cpu_imem_ready(buf_ready),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),
        .req_addr(req_addr),.req_wdata(req_wdata),.req_wmask(req_wmask),
        .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),
        .rsp_rdata(rsp_rdata),.rsp_error(rsp_error),
        .hit_count(hit_count),.miss_count(miss_count));
endmodule
`default_nettype wire
