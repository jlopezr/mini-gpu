`default_nettype none
// Eight true dual-port banks, each 4096 x 32 bits (16 KiB).
// Port A: LSU bank channels. Port B: unified fetch / stopped-host access.
// Every channel has independent request and response handshakes.
module gpu_bram (
    input clk, reset,
    input [7:0] req_valid,
    output [7:0] req_ready,
    input [95:0] req_row,
    input [255:0] req_data,
    input [7:0] req_write,
    output [7:0] rsp_valid,
    input [7:0] rsp_ready,
    output [255:0] rsp_data,
    output [7:0] rsp_error,
    input aux_valid,
    output aux_ready,
    input [31:0] aux_address, aux_write_data,
    input [3:0] aux_strobe,
    output reg aux_rsp_valid,
    input aux_rsp_ready,
    output [31:0] aux_read_data,
    output reg aux_error
);
    wire aux_bad = |aux_address[31:17] || |aux_address[1:0];
    wire [255:0] aux_bank_data;
    reg [2:0] aux_bank;
    assign aux_ready = !aux_rsp_valid;
    assign aux_read_data = aux_bank_data[aux_bank*32 +: 32];
    assign rsp_error = 0;
    always @(posedge clk) begin
        if (reset) begin aux_rsp_valid <= 0; aux_error <= 0; aux_bank <= 0; end
        else begin
            if (aux_rsp_valid && aux_rsp_ready) aux_rsp_valid <= 0;
            if (aux_valid && aux_ready) begin
                aux_rsp_valid <= 1;
                aux_error <= aux_bad;
                aux_bank <= aux_address[4:2];
            end
        end
    end
    genvar b;
    generate for (b=0; b<8; b=b+1) begin: banks
        reg valid_a;
        assign req_ready[b] = !valid_a;
        assign rsp_valid[b] = valid_a;
`ifdef DIAMOND
        // Synplify (Diamond) no infiere una RAM con dos puertos de escritura (ni con
        // un solo always, ni con syn_ramstyle): la deja en 1 Mbit de registros y no
        // termina. Aqui se instancian los DP16KD a mano, como los cablea el propio
        // Synplify con una escritura: 8 bloques de 4 bits por banco (ancho 4: ADx[1:0]
        // a 0 y ADx[13:2] = direccion de 12 bits). Un WE por byte, compartido por sus
        // dos nibbles. Puerto A (LSU): palabra entera. Puerto B (aux): por bytes.
        // A en NORMAL: la salida no cambia al escribir, como data_a en la rama de
        // simulacion. B en READBEFOREWRITE: solo importa su lectura (strobe == 0).
        wire [31:0] data_a, data_b;
        wire ce_a = !reset && req_valid[b] && req_ready[b];
        wire ce_b = !reset && aux_valid && aux_ready && !aux_bad && aux_address[4:2] == b[2:0];
        wire [11:0] row_a = req_row[b*12 +: 12];
        wire [11:0] row_b = aux_address[16:5];
        genvar n;
        for (n = 0; n < 8; n = n + 1) begin: nib
            DP16KD #(
                .DATA_WIDTH_A(4), .DATA_WIDTH_B(4),
                .REGMODE_A("NOREG"), .REGMODE_B("NOREG"),
                .WRITEMODE_A("NORMAL"), .WRITEMODE_B("READBEFOREWRITE"),
                .GSR("DISABLED")
            ) ram (
                .CLKA(clk), .CEA(ce_a), .OCEA(ce_a), .WEA(req_write[b]), .RSTA(1'b0),
                .CSA0(1'b0), .CSA1(1'b0), .CSA2(1'b0),
                .ADA0(1'b0), .ADA1(1'b0), .ADA2(row_a[0]), .ADA3(row_a[1]), .ADA4(row_a[2]), .ADA5(row_a[3]),
                .ADA6(row_a[4]), .ADA7(row_a[5]), .ADA8(row_a[6]), .ADA9(row_a[7]), .ADA10(row_a[8]), .ADA11(row_a[9]), .ADA12(row_a[10]), .ADA13(row_a[11]),
                .DIA0(req_data[b*32+4*n+0]), .DIA1(req_data[b*32+4*n+1]), .DIA2(req_data[b*32+4*n+2]), .DIA3(req_data[b*32+4*n+3]),
                .DIA4(1'b0), .DIA5(1'b0), .DIA6(1'b0), .DIA7(1'b0), .DIA8(1'b0), .DIA9(1'b0), .DIA10(1'b0), .DIA11(1'b0), .DIA12(1'b0), .DIA13(1'b0), .DIA14(1'b0), .DIA15(1'b0), .DIA16(1'b0), .DIA17(1'b0),
                .DOA0(data_a[4*n+0]), .DOA1(data_a[4*n+1]), .DOA2(data_a[4*n+2]), .DOA3(data_a[4*n+3]),
                .DOA4(), .DOA5(), .DOA6(), .DOA7(), .DOA8(), .DOA9(), .DOA10(), .DOA11(), .DOA12(), .DOA13(), .DOA14(), .DOA15(), .DOA16(), .DOA17(),
                .CLKB(clk), .CEB(ce_b), .OCEB(ce_b), .WEB(aux_strobe[n/2]), .RSTB(1'b0),
                .CSB0(1'b0), .CSB1(1'b0), .CSB2(1'b0),
                .ADB0(1'b0), .ADB1(1'b0), .ADB2(row_b[0]), .ADB3(row_b[1]), .ADB4(row_b[2]), .ADB5(row_b[3]),
                .ADB6(row_b[4]), .ADB7(row_b[5]), .ADB8(row_b[6]), .ADB9(row_b[7]), .ADB10(row_b[8]), .ADB11(row_b[9]), .ADB12(row_b[10]), .ADB13(row_b[11]),
                .DIB0(aux_write_data[4*n+0]), .DIB1(aux_write_data[4*n+1]), .DIB2(aux_write_data[4*n+2]), .DIB3(aux_write_data[4*n+3]),
                .DIB4(1'b0), .DIB5(1'b0), .DIB6(1'b0), .DIB7(1'b0), .DIB8(1'b0), .DIB9(1'b0), .DIB10(1'b0), .DIB11(1'b0), .DIB12(1'b0), .DIB13(1'b0), .DIB14(1'b0), .DIB15(1'b0), .DIB16(1'b0), .DIB17(1'b0),
                .DOB0(data_b[4*n+0]), .DOB1(data_b[4*n+1]), .DOB2(data_b[4*n+2]), .DOB3(data_b[4*n+3]),
                .DOB4(), .DOB5(), .DOB6(), .DOB7(), .DOB8(), .DOB9(), .DOB10(), .DOB11(), .DOB12(), .DOB13(), .DOB14(), .DOB15(), .DOB16(), .DOB17()
            );
        end
`else
        // Cross-port read/write collisions (self-modifying code without a
        // synchronization boundary) have unspecified read data.
        (* ram_style = "block", no_rw_check *) reg [31:0] words[0:4095];
        reg [31:0] data_a, data_b;
        // No reset on data or RAM: preserves block RAM inference and contents.
        always @(posedge clk) begin
            if (!reset && req_valid[b] && req_ready[b]) begin
                if (req_write[b]) words[req_row[b*12 +: 12]] <= req_data[b*32 +: 32];
                else data_a <= words[req_row[b*12 +: 12]];
            end
        end
        always @(posedge clk) begin
            if (!reset && aux_valid && aux_ready && !aux_bad && aux_address[4:2] == b[2:0]) begin
                if (aux_strobe==0) data_b <= words[aux_address[16:5]];
                if (aux_strobe[0]) words[aux_address[16:5]][7:0] <= aux_write_data[7:0];
                if (aux_strobe[1]) words[aux_address[16:5]][15:8] <= aux_write_data[15:8];
                if (aux_strobe[2]) words[aux_address[16:5]][23:16] <= aux_write_data[23:16];
                if (aux_strobe[3]) words[aux_address[16:5]][31:24] <= aux_write_data[31:24];
            end
        end
`endif
        assign rsp_data[b*32 +: 32] = data_a;
        assign aux_bank_data[b*32 +: 32] = data_b;
        always @(posedge clk) begin
            if (reset) valid_a <= 0;
            else begin
                if (valid_a && rsp_ready[b]) valid_a <= 0;
                if (req_valid[b] && req_ready[b]) valid_a <= 1;
            end
        end
    end endgenerate
endmodule
`default_nettype wire
