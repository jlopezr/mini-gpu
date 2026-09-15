`default_nettype none
// Envoltorio gemelo de lsu_timing_top.v pero para la LSU v1 (gpu_lsu.v, la de
// 17.fpga-gpu-ram-v2). Existe solo para tener una REFERENCIA: el Fmax de la v2
// en aislado no significa nada por si mismo, solo comparado con el de la v1
// medida exactamente igual, en el mismo chip vacio y con el mismo envoltorio.
module lsu1_timing_top(
    input clk_25mhz,
    input ftdi_txd,
    output [7:0] led,
    output wifi_gpio0
);
    assign wifi_gpio0=1'b1;

    reg [7:0] power_on=0;
    wire reset=!(&power_on);
    always @(posedge clk_25mhz) if(reset) power_on<=power_on+1'b1;

    reg [63:0] lfsr=64'h1234_5678_9abc_def0;
    always @(posedge clk_25mhz)
        lfsr<={lfsr[62:0], lfsr[63]^lfsr[62]^lfsr[60]^lfsr[59]^ftdi_txd};

    wire [255:0] wide={lfsr,~lfsr,{lfsr[31:0],lfsr[63:32]},{~lfsr[15:0],lfsr[47:0]}};

    wire req_ready, rsp_valid, aux_ready, aux_rsp_valid, aux_error;
    wire mem_req_valid, mem_req_write;
    wire [2:0] rsp_tag;
    wire [255:0] rsp_data;
    wire [7:0] rsp_error, occupied;
    wire [31:0] aux_read_data;
    wire [23:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    wire [1:0] mem_req_wmask;

    gpu_lsu dut(
        .clk(clk_25mhz), .reset(reset),
        .req_valid(lfsr[0]), .req_ready(req_ready), .req_tag(lfsr[3:1]),
        .req_mask(lfsr[11:4]), .req_write(lfsr[12]),
        .req_address(wide), .req_data(~wide),
        .rsp_valid(rsp_valid), .rsp_ready(lfsr[13]), .rsp_tag(rsp_tag),
        .rsp_data(rsp_data), .rsp_error(rsp_error), .occupied(occupied),
        .aux_valid(lfsr[17]), .aux_ready(aux_ready), .aux_address(wide[31:0]),
        .aux_write_data(wide[63:32]), .aux_strobe(lfsr[21:18]),
        .aux_rsp_valid(aux_rsp_valid), .aux_rsp_ready(lfsr[22]),
        .aux_read_data(aux_read_data), .aux_error(aux_error),
        .init_done(1'b1),
        .mem_req_valid(mem_req_valid), .mem_req_ready(lfsr[14]),
        .mem_req_write(mem_req_write), .mem_req_addr(mem_req_addr),
        .mem_req_wdata(mem_req_wdata), .mem_req_wmask(mem_req_wmask),
        .mem_done(lfsr[15]), .mem_rdata(wide[15:0]));

    reg [7:0] squeeze;
    always @(posedge clk_25mhz)
        squeeze<={^rsp_data[255:128], ^rsp_data[127:0], ^aux_read_data,
                  ^mem_req_addr, ^{mem_req_wdata,mem_req_wmask,rsp_error,occupied,rsp_tag},
                  req_ready^rsp_valid, mem_req_valid^mem_req_write,
                  aux_ready^aux_rsp_valid^aux_error};
    assign led=squeeze;
endmodule
`default_nettype wire
