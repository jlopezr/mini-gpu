
`default_nettype none

module dma_engine #(
    parameter integer NUM_CHANNELS = 2,
    parameter integer TAG_DEPTH = 8
)(
    input wire clk,
    input wire reset,

    // MMIO: direccion relativa a 0x8050_0000.
    input wire select,
    input wire write,
    input wire [3:0] write_mask,
    input wire [15:0] address,
    input wire [31:0] write_data,
    output reg [31:0] read_data,
    output reg mmio_error,

    output wire irq,

    // Maestro de memoria de 128 bits.
    output wire req_valid,
    input wire req_ready,
    output wire req_write,
    output wire [31:0] req_addr,
    output wire [127:0] req_wdata,
    output wire [15:0] req_wmask,

    input wire rsp_valid,
    output wire rsp_ready,
    input wire [127:0] rsp_rdata,
    input wire rsp_error
);

    localparam integer CB = $clog2(NUM_CHANNELS);
    localparam integer TB = $clog2(TAG_DEPTH);
    localparam [31:0] CH_MASK =
        (32'h1 << NUM_CHANNELS) - 1;

    // Configuracion de cada canal.
    reg [31:0] src        [0:NUM_CHANNELS-1];
    reg [31:0] dst        [0:NUM_CHANNELS-1];
    reg [31:0] width      [0:NUM_CHANNELS-1];
    reg [31:0] height     [0:NUM_CHANNELS-1];
    reg [31:0] src_stride [0:NUM_CHANNELS-1];
    reg [31:0] dst_stride [0:NUM_CHANNELS-1];
    reg [31:0] pattern    [0:NUM_CHANNELS-1];

    // Estado de canal.
    reg [NUM_CHANNELS-1:0] busy, done, error;
    reg [NUM_CHANNELS-1:0] fill_mode;
    reg [NUM_CHANNELS-1:0] aborted;
    reg [NUM_CHANNELS-1:0] read_pending;
    reg [NUM_CHANNELS-1:0] data_valid;

    reg [31:0] src_cur       [0:NUM_CHANNELS-1];
    reg [31:0] dst_cur       [0:NUM_CHANNELS-1];
    reg [31:0] src_row       [0:NUM_CHANNELS-1];
    reg [31:0] dst_row       [0:NUM_CHANNELS-1];
    reg [31:0] rows_left     [0:NUM_CHANNELS-1];
    reg [31:0] words_left    [0:NUM_CHANNELS-1];
    reg [31:0] bytes_done    [0:NUM_CHANNELS-1];
    reg [127:0] read_buffer  [0:NUM_CHANNELS-1];
    reg [7:0] writes_pending [0:NUM_CHANNELS-1];

    reg [NUM_CHANNELS-1:0] irq_pending;
    reg [NUM_CHANNELS-1:0] irq_enable;
    assign irq = |(irq_pending & irq_enable);

    // ------------------------------------------------------------
    // MMIO
    // Canales: 0x40 bytes por canal, hasta +0x1FF.
    // Globales: desde +0x200.
    // ------------------------------------------------------------

    wire [2:0] mmio_ch = address[8:6];
    wire [5:0] mmio_off = address[5:0];
    wire channel_region = address[15:9] == 7'd0;
    wire global_region = address[15:9] == 7'd1;
    wire channel_exists = mmio_ch < NUM_CHANNELS;

    wire start_access =
        channel_region && channel_exists &&
        mmio_off == 6'h1c && write;

    wire start_valid =
        write_data[0] &&
        write_data[31:2] == 0 &&
        width[mmio_ch] != 0 &&
        width[mmio_ch][3:0] == 0 &&
        height[mmio_ch] != 0 &&
        dst[mmio_ch][3:0] == 0 &&
        dst_stride[mmio_ch][3:0] == 0 &&
        (write_data[1] ||
          (src[mmio_ch][3:0] == 0 &&
           src_stride[mmio_ch][3:0] == 0));

    always @* begin
        read_data = 32'd0;
        mmio_error = 1'b0;

        if (select) begin
            if (address[1:0] != 0 ||
            (write && write_mask != 4'hf)) begin
                mmio_error = 1'b1;
            end else if (channel_region && channel_exists) begin
                case (mmio_off)
                    6'h00: read_data = src[mmio_ch];
                    6'h04: read_data = dst[mmio_ch];
                    6'h08: read_data = width[mmio_ch];
                    6'h0c: read_data = height[mmio_ch];
                    6'h10: read_data = src_stride[mmio_ch];
                    6'h14: read_data = dst_stride[mmio_ch];
                    6'h18: read_data = pattern[mmio_ch];
                    6'h1c: begin
                        if (!write || busy[mmio_ch] ||
                            !start_valid)
                            mmio_error = 1'b1;
                    end
                    6'h20: begin
                        read_data = {29'd0,
                                     error[mmio_ch],
                                     done[mmio_ch],
                                     busy[mmio_ch]};
                        if (write && (write_data & ~32'h6))
                            mmio_error = 1'b1;
                    end
                    6'h24: begin
                        read_data = bytes_done[mmio_ch];
                        if (write) mmio_error = 1'b1;
                    end
                    default: mmio_error = 1'b1;
                endcase

                if (write && busy[mmio_ch] &&
                    mmio_off <= 6'h1c)
                    mmio_error = 1'b1;

            end else if (global_region) begin
                case (address[9:0])
                    10'h200: begin
                        read_data = 32'h444D_4131; // DMA1
                        if (write) mmio_error = 1'b1;
                    end
                    10'h204: begin
                        read_data = NUM_CHANNELS;
                        if (write) mmio_error = 1'b1;
                    end
                    10'h208: begin
                        read_data = {{(32-NUM_CHANNELS){1'b0}},
                                     irq_pending};
                        if (write && |(write_data & ~CH_MASK))
                            mmio_error = 1'b1;
                    end
                    10'h20c: begin
                        read_data = {{(32-NUM_CHANNELS){1'b0}},
                                     irq_enable};
                        if (write && |(write_data & ~CH_MASK))
                            mmio_error = 1'b1;
                    end
                    default: mmio_error = 1'b1;
                endcase
            end else begin
                mmio_error = 1'b1;
            end
        end
    end

    // ------------------------------------------------------------
    // Planificador de canales
    // ------------------------------------------------------------

    reg [CB-1:0] rr;
    reg found;
    reg [CB-1:0] chosen;
    reg chosen_read;
    integer j;
    integer candidate;

    always @* begin
        found = 1'b0;
        chosen = {CB{1'b0}};
        chosen_read = 1'b0;
        candidate = 0;

        for (integer k = 0; k < NUM_CHANNELS; k = k + 1) begin
            candidate = (rr + k) & (NUM_CHANNELS - 1);

            if (!found && busy[candidate] &&
                !aborted[candidate] &&
                rows_left[candidate] != 0) begin

                if (fill_mode[candidate]) begin
                    found = 1'b1;
                    chosen = candidate;
                    chosen_read = 1'b0;
                end else if (data_valid[candidate]) begin
                    found = 1'b1;
                    chosen = candidate;
                    chosen_read = 1'b0;
                end else if (!read_pending[candidate]) begin
                    found = 1'b1;
                    chosen = candidate;
                    chosen_read = 1'b1;
                end
            end
        end
    end

    // Slot de salida: mantiene estable la peticion hasta READY.
    reg slot_valid;
    reg [CB-1:0] slot_ch;
    reg slot_read;
    reg [31:0] slot_addr;
    reg [127:0] slot_data;

    reg [CB-1:0] tags_ch [0:TAG_DEPTH-1];
    reg tags_read [0:TAG_DEPTH-1];
    reg [TB-1:0] tag_wr, tag_rd;
    reg [TB:0] tag_count;

    wire tags_full = tag_count == TAG_DEPTH;
    wire tags_empty = tag_count == 0;

    assign req_valid = slot_valid && !tags_full &&
                       !reset && !aborted[slot_ch];
    assign req_write = !slot_read;
    assign req_addr = slot_addr;
    assign req_wdata = slot_data;
    assign req_wmask = slot_read ? 16'h0000 : 16'hffff;

    wire issue = req_valid && req_ready;
    wire issue_read = issue && slot_read;
    wire issue_write = issue && !slot_read;

    // La salida del arbitro local se acepta siempre que haya tag.
    assign rsp_ready = !reset && !tags_empty;
    wire response = rsp_valid && rsp_ready;
    wire [CB-1:0] response_ch = tags_ch[tag_rd];
    wire response_read = tags_read[tag_rd];

    integer i;

    always @(posedge clk) begin
        if (reset) begin
            rr <= 0;
            slot_valid <= 0;
            slot_ch <= 0;
            slot_read <= 0;
            slot_addr <= 0;
            slot_data <= 0;
            tag_wr <= 0;
            tag_rd <= 0;
            tag_count <= 0;
            irq_pending <= 0;
            irq_enable <= 0;
            busy <= 0;
            done <= 0;
            error <= 0;
            fill_mode <= 0;
            aborted <= 0;
            read_pending <= 0;
            data_valid <= 0;

            for (i = 0; i < NUM_CHANNELS; i = i + 1) begin
                src[i] <= 0;
                dst[i] <= 0;
                width[i] <= 0;
                height[i] <= 0;
                src_stride[i] <= 0;
                dst_stride[i] <= 0;
                pattern[i] <= 0;
                src_cur[i] <= 0;
                dst_cur[i] <= 0;
                src_row[i] <= 0;
                dst_row[i] <= 0;
                rows_left[i] <= 0;
                words_left[i] <= 0;
                bytes_done[i] <= 0;
                read_buffer[i] <= 0;
                writes_pending[i] <= 0;
            end
        end else begin

            // ----------------------------------------------------
            // Solicitudes y tags
            // ----------------------------------------------------

            if (!slot_valid && found && !tags_full) begin
                slot_valid <= 1'b1;
                slot_ch <= chosen;
                slot_read <= chosen_read;
                slot_addr <= chosen_read ? src_cur[chosen]
                                         : dst_cur[chosen];
                slot_data <= fill_mode[chosen]
                    ? {4{pattern[chosen]}}
                    : read_buffer[chosen];
            end

            if (slot_valid && aborted[slot_ch])
                slot_valid <= 1'b0;

            if (issue) begin
                slot_valid <= 1'b0;
                rr <= (slot_ch + 1'b1) & (NUM_CHANNELS - 1);

                tags_ch[tag_wr] <= slot_ch;
                tags_read[tag_wr] <= slot_read;
                tag_wr <= tag_wr + 1'b1;
            end

            if (response)
                tag_rd <= tag_rd + 1'b1;

            case ({issue, response})
                2'b10: tag_count <= tag_count + 1'b1;
                2'b01: tag_count <= tag_count - 1'b1;
                default: ;
            endcase

            // ----------------------------------------------------
            // Estado de transferencias
            // ----------------------------------------------------

            for (i = 0; i < NUM_CHANNELS; i = i + 1) begin

                if (issue_read && slot_ch == i)
                    read_pending[i] <= 1'b1;

                if (response && response_ch == i &&
                    response_read) begin
                    read_pending[i] <= 1'b0;
                    if (!rsp_error) begin
                        read_buffer[i] <= rsp_rdata;
                        data_valid[i] <= 1'b1;
                    end
                end

                writes_pending[i] <= writes_pending[i] +
                    ((issue_write && slot_ch == i) ? 8'd1 : 8'd0) -
                    ((response && !response_read &&
                      response_ch == i) ? 8'd1 : 8'd0);

                if (response && response_ch == i && rsp_error) begin
                    error[i] <= 1'b1;
                    aborted[i] <= 1'b1;
                    data_valid[i] <= 1'b0;
                end

                if (issue_write && slot_ch == i) begin
                    if (!fill_mode[i])
                        data_valid[i] <= 1'b0;

                    bytes_done[i] <= bytes_done[i] + 32'd16;

                    if (words_left[i] == 1) begin
                        rows_left[i] <= rows_left[i] - 1'b1;
                        words_left[i] <= width[i] >> 4;
                        src_row[i] <= src_row[i] + src_stride[i];
                        dst_row[i] <= dst_row[i] + dst_stride[i];
                        src_cur[i] <= src_row[i] + src_stride[i];
                        dst_cur[i] <= dst_row[i] + dst_stride[i];
                    end else begin
                        words_left[i] <= words_left[i] - 1'b1;
                        src_cur[i] <= src_cur[i] + 32'd16;
                        dst_cur[i] <= dst_cur[i] + 32'd16;
                    end
                end

                // DONE solo tras recibir todas las respuestas.
                if (busy[i] &&
                    (rows_left[i] == 0 || aborted[i]) &&
                    writes_pending[i] == 0 &&
                    !read_pending[i] &&
                    !data_valid[i] &&
                    !(slot_valid && slot_ch == i)) begin

                    busy[i] <= 1'b0;
                    if (!aborted[i])
                        done[i] <= 1'b1;
                    irq_pending[i] <= 1'b1;
                end
            end

            // ----------------------------------------------------
            // MMIO
            // ----------------------------------------------------

            if (select && write && !mmio_error) begin
                if (channel_region && channel_exists) begin
                    case (mmio_off)
                        6'h00: src[mmio_ch] <= write_data;
                        6'h04: dst[mmio_ch] <= write_data;
                        6'h08: width[mmio_ch] <= write_data;
                        6'h0c: height[mmio_ch] <= write_data;
                        6'h10: src_stride[mmio_ch] <= write_data;
                        6'h14: dst_stride[mmio_ch] <= write_data;
                        6'h18: pattern[mmio_ch] <= write_data;

                        6'h1c: begin
                            busy[mmio_ch] <= 1'b1;
                            done[mmio_ch] <= 1'b0;
                            error[mmio_ch] <= 1'b0;
                            aborted[mmio_ch] <= 1'b0;
                            read_pending[mmio_ch] <= 1'b0;
                            data_valid[mmio_ch] <= 1'b0;
                            fill_mode[mmio_ch] <= write_data[1];
                            irq_pending[mmio_ch] <= 1'b0;

                            src_row[mmio_ch] <= src[mmio_ch];
                            dst_row[mmio_ch] <= dst[mmio_ch];
                            src_cur[mmio_ch] <= src[mmio_ch];
                            dst_cur[mmio_ch] <= dst[mmio_ch];
                            rows_left[mmio_ch] <= height[mmio_ch];
                            words_left[mmio_ch] <= width[mmio_ch] >> 4;
                            bytes_done[mmio_ch] <= 0;
                            writes_pending[mmio_ch] <= 0;
                        end

                        6'h20: begin
                            if (write_data[1]) done[mmio_ch] <= 0;
                            if (write_data[2]) error[mmio_ch] <= 0;
                        end
                        default: ;
                    endcase
                end else if (global_region) begin
                    case (address[9:0])
                        10'h208:
                            irq_pending <= irq_pending &
                                           ~write_data[NUM_CHANNELS-1:0];
                        10'h20c:
                            irq_enable <= write_data[NUM_CHANNELS-1:0];
                        default: ;
                    endcase
                end
            end
        end
    end

endmodule

`default_nettype wire
