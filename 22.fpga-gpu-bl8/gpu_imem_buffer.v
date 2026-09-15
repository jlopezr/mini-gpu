`default_nettype none
// Pone instruction_buffer.v (el de 21) detras del puerto imem de gpu_sm.
//
// Los dos contratos se parecen pero no son iguales:
//
//   cpu.v          : cpu_imem_valid sostenido, cpu_imem_ready pulsa con el dato
//   gpu_sm.v       : imem_valid/imem_ready para aceptar, y DESPUES
//                    imem_rsp_valid/imem_rsp_ready para la respuesta
//
// Este modulo es solo ese pegamento: acepta la peticion de gpu_sm, la sostiene
// contra el bufer hasta que pulsa ready, y devuelve la respuesta con el
// handshake que gpu_sm espera.
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
    localparam S_IDLE=2'd0, S_FETCH=2'd1, S_RESP=2'd2;
    reg [1:0] st;
    reg [31:0] addr_q, data_q;
    reg err_q;

    wire buf_ready;
    wire [31:0] buf_data;

    assign imem_ready=!reset && st==S_IDLE;
    assign imem_rsp_valid=st==S_RESP;
    assign imem_data=data_q;
    assign imem_error=err_q;

    // Mismo criterio de fault que tenia el camino auxiliar de la v1, para que
    // gpu_sm siga viendo el mismo error ante una direccion imposible; el bufer
    // por su cuenta responderia con opcode invalido, que no es lo mismo.
    wire bad=|addr_q[31:25] || |addr_q[1:0];

    instruction_buffer #(.LINES(LINES),.INDEX_BITS(INDEX_BITS),
                         .SDRAM_SIZE_BYTES(SDRAM_SIZE_BYTES)) ib (
        .clk(clk),.reset(reset),.init_done(init_done),.cpu_halted(halted),
        .cpu_imem_valid(st==S_FETCH),.cpu_imem_address(addr_q),
        .cpu_imem_read_data(buf_data),.cpu_imem_ready(buf_ready),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),
        .req_addr(req_addr),.req_wdata(req_wdata),.req_wmask(req_wmask),
        .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),
        .rsp_rdata(rsp_rdata),.rsp_error(rsp_error),
        .hit_count(hit_count),.miss_count(miss_count));

    always @(posedge clk) begin
        if(reset) begin
            st<=S_IDLE; addr_q<=0; data_q<=0; err_q<=0;
        end else case(st)
            S_IDLE: if(imem_valid) begin addr_q<=imem_address; st<=S_FETCH; end
            S_FETCH: if(buf_ready) begin data_q<=buf_data; err_q<=bad; st<=S_RESP; end
            S_RESP: if(imem_rsp_ready) begin err_q<=0; st<=S_IDLE; end
            default: st<=S_IDLE;
        endcase
    end
endmodule
`default_nettype wire
