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
        // Cross-port read/write collisions (self-modifying code without a
        // synchronization boundary) have unspecified read data.
        (* ram_style = "block", no_rw_check *) reg [31:0] words[0:4095];
        reg [31:0] data_a, data_b;
        reg valid_a;
        assign req_ready[b] = !valid_a;
        assign rsp_valid[b] = valid_a;
        assign rsp_data[b*32 +: 32] = data_a;
        assign aux_bank_data[b*32 +: 32] = data_b;
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
