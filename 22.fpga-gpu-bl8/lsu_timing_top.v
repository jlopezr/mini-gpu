`default_nettype none
// Top SOLO PARA MEDIR TIMING de gpu_lsu2 en aislado. No es un diseno util:
// no hace nada. Existe porque gpu_lsu2 tiene ~800 bits de E/S y la ULX3S no
// tiene tantos pines, asi que no se puede poner como top directamente.
//
// El truco: un LFSR alimenta todas las entradas anchas y un XOR reduce todas
// las salidas a un LED. El LFSR no es constante, asi que yosys no puede
// plegar la logica interna de la LSU -- lo que se mide es la LSU de verdad.
//
// COMO LEER EL NUMERO: este Fmax NO es comparable con el del sistema completo.
// Aqui la LSU esta sola en un chip vacio, sin competir por rutado ni por
// fanout con el SM. Es optimista por construccion. Sirve para responder "¿es
// esta logica catastroficamente lenta?", no para predecir el Fmax del sistema.
// Ese numero solo sale del build del sistema entero y de su camino critico.
module lsu_timing_top(
    input clk_25mhz,
    input ftdi_txd,
    output [7:0] led,
    output wifi_gpio0
);
    assign wifi_gpio0=1'b1;

    reg [7:0] power_on=0;
    wire reset=!(&power_on);
    always @(posedge clk_25mhz) if(reset) power_on<=power_on+1'b1;

    // Fuente pseudoaleatoria: ni constante ni optimizable.
    reg [63:0] lfsr=64'h1234_5678_9abc_def0;
    always @(posedge clk_25mhz)
        lfsr<={lfsr[62:0], lfsr[63]^lfsr[62]^lfsr[60]^lfsr[59]^ftdi_txd};

    wire [255:0] wide={lfsr,~lfsr,{lfsr[31:0],lfsr[63:32]},{~lfsr[15:0],lfsr[47:0]}};

    wire req_ready, rsp_valid, mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [2:0] rsp_tag;
    wire [255:0] rsp_data;
    wire [7:0] rsp_error, occupied;
    wire [31:0] mem_req_addr;
    wire [127:0] mem_req_wdata;
    wire [15:0] mem_req_wmask;
    // El camino escalar de MMIO (ver mmio.md) tambien va al LFSR. Dejarlo sin
    // conectar no era solo un aviso de verilator: yosys poda logica muerta,
    // asi que el Fmax salia de una LSU SIN ese camino -- justo lo que este
    // prototipo anadio. Con esto se mide la LSU que se sintetiza de verdad.
    wire mmio_req_valid, mmio_req_write, mmio_rsp_ready;
    wire [31:0] mmio_req_addr, mmio_req_wdata;

    gpu_lsu2 dut(
        .clk(clk_25mhz), .reset(reset),
        .req_valid(lfsr[0]), .req_ready(req_ready), .req_tag(lfsr[3:1]),
        .req_mask(lfsr[11:4]), .req_write(lfsr[12]),
        .req_address(wide), .req_data(~wide),
        .rsp_valid(rsp_valid), .rsp_ready(lfsr[13]), .rsp_tag(rsp_tag),
        .rsp_data(rsp_data), .rsp_error(rsp_error), .occupied(occupied),
        .mem_req_valid(mem_req_valid), .mem_req_ready(lfsr[14]),
        .mem_req_write(mem_req_write), .mem_req_addr(mem_req_addr),
        .mem_req_wdata(mem_req_wdata), .mem_req_wmask(mem_req_wmask),
        .mem_rsp_valid(lfsr[15]), .mem_rsp_ready(mem_rsp_ready),
        .mem_rsp_rdata(wide[127:0]), .mem_rsp_error(lfsr[16]),
        .mmio_req_valid(mmio_req_valid), .mmio_req_ready(lfsr[17]),
        .mmio_req_write(mmio_req_write), .mmio_req_addr(mmio_req_addr),
        .mmio_req_wdata(mmio_req_wdata),
        .mmio_rsp_valid(lfsr[18]), .mmio_rsp_ready(mmio_rsp_ready),
        .mmio_rsp_rdata(wide[159:128]), .mmio_rsp_error(lfsr[19]));

    // Reduccion a 8 bits: registrada, para que el camino critico medido sea el
    // interno de la LSU y no el arbol de XOR hacia los pines.
    reg [7:0] squeeze;
    always @(posedge clk_25mhz)
        squeeze<={^rsp_data[255:128], ^rsp_data[127:0], ^mem_req_wdata,
                  ^{mem_req_addr,mmio_req_addr,mmio_req_wdata},
                  ^{mem_req_wmask,rsp_error,occupied,rsp_tag},
                  req_ready^rsp_valid, mem_req_valid^mem_req_write,
                  mem_rsp_ready^mmio_req_valid^mmio_req_write^mmio_rsp_ready};
    assign led=squeeze;
endmodule
`default_nettype wire
