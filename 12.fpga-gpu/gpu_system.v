`default_nettype none
module gpu_system #(parameter SIMT_DEPTH=8, SIMT_REGION_DEPTH=SIMT_DEPTH, SIMT_PATH_DEPTH=8) (
    input clk, reset, gpu_reset,
    input run_request, halt_request, step_request,
    output halted, error,
    output [7:0] error_code,
    output instruction_retired,
    input [31:0] host_address,
    input [7:0] host_write_data,
    input host_write_enable, host_read_enable,
    output reg [7:0] host_read_data,
    output reg host_ready, host_error,
    input [4:0] debug_register,
    output [31:0] debug_data, debug_pc
);
    wire core_reset=reset || gpu_reset;
    reg [2:0] debug_warp, debug_lane;
    wire [2:0] error_warp,error_lane;
    wire error_lane_valid;
    wire [31:0] error_pc,retired_count,debug_warp_retired_count;
    wire [31:0] cfg_read_data;
    wire cfg_write;
    wire fetch_valid,fetch_ready,fetch_rsp_valid,fetch_rsp_ready,fetch_error;
    wire [31:0] fetch_address,fetch_data;
    wire lsu_valid,lsu_ready,lsu_write,lsu_rsp_valid,lsu_rsp_ready;
    wire [2:0] lsu_tag,lsu_rsp_tag;
    wire [7:0] lsu_mask,lsu_rsp_error,occupied;
    wire [255:0] lsu_address,lsu_data,lsu_rsp_data;
    wire [7:0] bank_valid,bank_ready,bank_write,bank_rsp_valid,bank_rsp_ready,bank_rsp_error;
    wire [95:0] bank_row;
    wire [255:0] bank_data,bank_rsp_data;

    // Capture the byte monitor's single-cycle request. It remains stable until
    // the backend responds; host ownership is granted only after LSU drains.
    reg [1:0] host_state;
    reg [31:0] address;
    reg [7:0] write_data;
    reg writing;
    wire mmio=address[31:12]==20'h80000;
    wire cfg_region=address[11:7]==0;
    wire [3:0] byte_strobe=4'b0001 << address[1:0];
    wire [31:0] expanded_data={4{write_data}};
    assign cfg_write=host_state==1 && mmio && cfg_region && writing && halted;
    wire aux_valid,aux_ready,aux_rsp_valid,aux_rsp_ready,aux_error;
    wire [31:0] aux_address,aux_write_data,aux_read_data;
    wire [3:0] aux_strobe;
    assign aux_valid=halted ? (host_state==1 && !mmio) : fetch_valid;
    assign aux_address=halted ? {address[31:2],2'b0} : fetch_address;
    assign aux_write_data=expanded_data;
    assign aux_strobe=halted && writing ? byte_strobe : 4'b0;
    assign aux_rsp_ready=halted ? host_state==2 : fetch_rsp_ready;
    assign fetch_ready=!halted && aux_ready;
    assign fetch_rsp_valid=!halted && aux_rsp_valid;
    assign fetch_data=aux_read_data;
    assign fetch_error=aux_error;
    // Do not launch while a host transaction owns the auxiliary port.
    wire host_idle=host_state==0 && !host_write_enable && !host_read_enable;
    gpu_sm #(.SIMT_DEPTH(SIMT_DEPTH), .SIMT_REGION_DEPTH(SIMT_REGION_DEPTH), .SIMT_PATH_DEPTH(SIMT_PATH_DEPTH)) sm (
        .clk(clk),.reset(core_reset),.run_request(run_request && host_idle),
        .halt_request(halt_request),.step_request(step_request && host_idle),
        .halted(halted),.error(error),.error_code(error_code),
        .error_warp(error_warp),.error_lane(error_lane),.error_lane_valid(error_lane_valid),
        .error_pc(error_pc),.instruction_retired(instruction_retired),.retired_count(retired_count),
        .debug_warp(debug_warp),.debug_lane(debug_lane),.debug_register(debug_register),
        .debug_data(debug_data),.debug_pc(debug_pc),
        .debug_warp_retired_count(debug_warp_retired_count),
        .cfg_write(cfg_write),.cfg_word(address[6:2]),.cfg_data(expanded_data),
        .cfg_strobe(byte_strobe),.cfg_read_data(cfg_read_data),
        .imem_valid(fetch_valid),.imem_ready(fetch_ready),.imem_address(fetch_address),
        .imem_rsp_valid(fetch_rsp_valid),.imem_rsp_ready(fetch_rsp_ready),
        .imem_data(fetch_data),.imem_error(fetch_error),
        .lsu_valid(lsu_valid),.lsu_ready(lsu_ready),.lsu_tag(lsu_tag),.lsu_mask(lsu_mask),
        .lsu_write(lsu_write),.lsu_address(lsu_address),.lsu_data(lsu_data),
        .lsu_rsp_valid(lsu_rsp_valid),.lsu_rsp_ready(lsu_rsp_ready),.lsu_rsp_tag(lsu_rsp_tag),
        .lsu_rsp_data(lsu_rsp_data),.lsu_rsp_error(lsu_rsp_error),.lsu_occupied(occupied)
    );
    gpu_lsu lsu (
        .clk(clk),.reset(core_reset),.req_valid(lsu_valid),.req_ready(lsu_ready),
        .req_tag(lsu_tag),.req_mask(lsu_mask),.req_write(lsu_write),
        .req_address(lsu_address),.req_data(lsu_data),.rsp_valid(lsu_rsp_valid),
        .rsp_ready(lsu_rsp_ready),.rsp_tag(lsu_rsp_tag),.rsp_data(lsu_rsp_data),
        .rsp_error(lsu_rsp_error),.occupied(occupied),.bank_valid(bank_valid),
        .bank_ready(bank_ready),.bank_row(bank_row),.bank_data(bank_data),.bank_write(bank_write),
        .bank_rsp_valid(bank_rsp_valid),.bank_rsp_ready(bank_rsp_ready),
        .bank_rsp_data(bank_rsp_data),.bank_rsp_error(bank_rsp_error)
    );
    gpu_bram bram (
        .clk(clk),.reset(core_reset),.req_valid(bank_valid),.req_ready(bank_ready),
        .req_row(bank_row),.req_data(bank_data),.req_write(bank_write),
        .rsp_valid(bank_rsp_valid),.rsp_ready(bank_rsp_ready),.rsp_data(bank_rsp_data),.rsp_error(bank_rsp_error),
        .aux_valid(aux_valid),.aux_ready(aux_ready),.aux_address(aux_address),
        .aux_write_data(aux_write_data),.aux_strobe(aux_strobe),.aux_rsp_valid(aux_rsp_valid),
        .aux_rsp_ready(aux_rsp_ready),.aux_read_data(aux_read_data),.aux_error(aux_error)
    );
    reg [31:0] mmio_data;
    reg mmio_bad;
    always @* begin
        mmio_data=0; mmio_bad=0;
        if(cfg_region) begin
            mmio_data=cfg_read_data;
            if(writing && address[3:2]==3) mmio_bad=1;
        end else case(address[11:2])
            10'h040: mmio_data={24'b0,2'b0,debug_warp,debug_lane};
            10'h041: begin mmio_data={24'b0,occupied}; mmio_bad=writing; end
            10'h042: begin mmio_data=retired_count; mmio_bad=writing; end
            10'h043: begin mmio_data={16'b0,error_code,1'b0,error_lane_valid,error_warp,error_lane}; mmio_bad=writing; end
            10'h044: begin mmio_data=error_pc; mmio_bad=writing; end
            10'h045: begin mmio_data=debug_warp_retired_count; mmio_bad=writing; end
            default: mmio_bad=1;
        endcase
    end
    always @(posedge clk) begin
        host_ready<=0;
        if(core_reset) begin
            host_state<=0; address<=0; write_data<=0; writing<=0;
            host_ready<=0; host_error<=0; host_read_data<=0;
            debug_warp<=0; debug_lane<=0;
        end else case(host_state)
            0: if(host_write_enable || host_read_enable) begin
                if(!halted) begin host_ready<=1; host_error<=1; end
                else begin
                    address<=host_address; write_data<=host_write_data;
                    writing<=host_write_enable; host_state<=1;
                end
            end
            1: begin
                if(mmio) begin
                    host_read_data<=mmio_data[address[1:0]*8 +: 8];
                    host_error<=mmio_bad; host_ready<=1; host_state<=0;
                    if(writing && address[11:0]==12'h100) begin
                        debug_lane<=write_data[2:0]; debug_warp<=write_data[5:3];
                    end
                end else if(aux_ready) host_state<=2;
            end
            2: if(aux_rsp_valid) begin
                host_read_data<=aux_read_data[address[1:0]*8 +: 8];
                host_error<=aux_error; host_ready<=1; host_state<=0;
            end
        endcase
    end
endmodule
`default_nettype wire
