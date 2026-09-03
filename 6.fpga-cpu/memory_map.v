`default_nettype none

/*
 * Unified architectural map backed by two independent 16 KiB EBR banks:
 *
 *   0x00000000 - 0x00003fff: bank 0
 *   0x00100000 - 0x00103fff: bank 1
 *   all other addresses:       bus error
 *
 * The monitor and both CPU ports use these exact global addresses. imem is a
 * read-only interface, but it can fetch from either bank; dmem can read or
 * write either bank. The CPU currently issues imem and dmem requests at
 * different times, so a single registered router can feed both physical banks.
 */
module memory_map (
    input clk, input reset,
    input [31:0] address, input [7:0] write_data,
    input write_enable, input read_enable,
    output [7:0] read_data, output ready, output error,
    input cpu_halted,
    input cpu_imem_valid, input [31:0] cpu_imem_address,
    output [31:0] cpu_imem_read_data, output cpu_imem_ready,
    input cpu_dmem_valid, input [31:0] cpu_dmem_address,
    input [31:0] cpu_dmem_write_data,
    input [3:0] cpu_dmem_write_enable,
    output [31:0] cpu_dmem_read_data,
    output cpu_dmem_ready, output cpu_dmem_error
);
  localparam [1:0] OWNER_NONE=2'd0, OWNER_MONITOR=2'd1,
                   OWNER_IMEM=2'd2, OWNER_DMEM=2'd3;

  wire monitor_bank0 = address[31:14] == 18'h00000;
  wire monitor_bank1 = address[31:14] == 18'h00040;
  wire monitor_request = write_enable || read_enable;
  wire imem_bank0 = cpu_imem_address[31:14] == 18'h00000;
  wire imem_bank1 = cpu_imem_address[31:14] == 18'h00040;
  wire imem_address_valid = (imem_bank0 || imem_bank1) &&
                            cpu_imem_address[1:0] == 2'b00;
  wire dmem_bank0 = cpu_dmem_address[31:14] == 18'h00000;
  wire dmem_bank1 = cpu_dmem_address[31:14] == 18'h00040;
  wire dmem_address_valid = (dmem_bank0 || dmem_bank1) &&
                            cpu_dmem_address[1:0] == 2'b00;
  wire [3:0] monitor_byte_enable = 4'b0001 << address[1:0];
  wire [31:0] monitor_word_data = {4{write_data}};

  reg [11:0] bank0_request_address;
  reg [31:0] bank0_request_write_data;
  reg [3:0] bank0_request_write_enable;
  reg bank0_request_read_enable;
  reg [1:0] bank0_request_owner;
  reg [11:0] bank1_request_address;
  reg [31:0] bank1_request_write_data;
  reg [3:0] bank1_request_write_enable;
  reg bank1_request_read_enable;
  reg [1:0] bank1_request_owner;
  wire [31:0] bank0_read_data, bank1_read_data;
  wire bank0_ready, bank1_ready;
  reg bank0_response_valid, bank1_response_valid;
  reg [1:0] bank0_response_owner, bank1_response_owner;
  reg [31:0] bank0_response_data, bank1_response_data;

  reg invalid_monitor_ready, invalid_imem_ready, invalid_dmem_ready;
  reg monitor_ready_r, monitor_error_r;
  reg [31:0] monitor_read_word;
  reg [1:0] monitor_byte_offset;
  reg imem_ready_r;
  reg [31:0] imem_read_data_r;
  reg dmem_ready_r, dmem_error_r;
  reg [31:0] dmem_read_data_r;
  reg transaction_active, release_wait;
  reg [1:0] transaction_owner;

  memory bank0_memory (
      .clk(clk), .reset(reset), .address(bank0_request_address),
      .write_data(bank0_request_write_data),
      .write_enable(bank0_request_write_enable),
      .read_enable(bank0_request_read_enable),
      .read_data(bank0_read_data), .ready(bank0_ready)
  );
  memory bank1_memory (
      .clk(clk), .reset(reset), .address(bank1_request_address),
      .write_data(bank1_request_write_data),
      .write_enable(bank1_request_write_enable),
      .read_enable(bank1_request_read_enable),
      .read_data(bank1_read_data), .ready(bank1_ready)
  );

  always @(posedge clk) begin
    if (reset) begin
      bank0_request_address <= 0;
      bank0_request_write_data <= 0;
      bank0_request_write_enable <= 0;
      bank0_request_read_enable <= 0;
      bank0_request_owner <= OWNER_NONE;
      bank1_request_address <= 0;
      bank1_request_write_data <= 0;
      bank1_request_write_enable <= 0;
      bank1_request_read_enable <= 0;
      bank1_request_owner <= OWNER_NONE;
      bank0_response_valid <= 0;
      bank1_response_valid <= 0;
      bank0_response_owner <= OWNER_NONE;
      bank1_response_owner <= OWNER_NONE;
      bank0_response_data <= 0;
      bank1_response_data <= 0;
      invalid_monitor_ready <= 0;
      invalid_imem_ready <= 0;
      invalid_dmem_ready <= 0;
      monitor_ready_r <= 0;
      monitor_error_r <= 0;
      monitor_read_word <= 0;
      monitor_byte_offset <= 0;
      imem_ready_r <= 0;
      imem_read_data_r <= 0;
      dmem_ready_r <= 0;
      dmem_error_r <= 0;
      dmem_read_data_r <= 0;
      transaction_active <= 0;
      release_wait <= 0;
      transaction_owner <= OWNER_NONE;
    end else begin
      bank0_request_write_enable <= 0;
      bank0_request_read_enable <= 0;
      bank1_request_write_enable <= 0;
      bank1_request_read_enable <= 0;
      invalid_monitor_ready <= 0;
      invalid_imem_ready <= 0;
      invalid_dmem_ready <= 0;
      monitor_ready_r <= 0;
      monitor_error_r <= 0;
      imem_ready_r <= 0;
      dmem_ready_r <= 0;
      dmem_error_r <= 0;
      bank0_response_valid <= bank0_ready;
      bank1_response_valid <= bank1_ready;

      // Capture each EBR output before the cross-bank response mux. This extra
      // stage keeps the slow block-RAM clock-to-output path within 120 MHz.
      if (bank0_ready) begin
        bank0_response_owner <= bank0_request_owner;
        bank0_response_data <= bank0_read_data;
      end
      if (bank1_ready) begin
        bank1_response_owner <= bank1_request_owner;
        bank1_response_data <= bank1_read_data;
      end

      if (release_wait) begin
        if ((transaction_owner == OWNER_MONITOR && !monitor_request) ||
            (transaction_owner == OWNER_IMEM && !cpu_imem_valid) ||
            (transaction_owner == OWNER_DMEM && !cpu_dmem_valid))
          release_wait <= 0;
      end else if (!transaction_active && monitor_request) begin
        transaction_active <= 1;
        transaction_owner <= OWNER_MONITOR;
        if (!cpu_halted) begin
          invalid_monitor_ready <= 1;
        end else if (monitor_bank0) begin
          bank0_request_address <= address[13:2];
          bank0_request_write_data <= monitor_word_data;
          bank0_request_write_enable <= write_enable ? monitor_byte_enable : 0;
          bank0_request_read_enable <= read_enable;
          bank0_request_owner <= OWNER_MONITOR;
          monitor_byte_offset <= address[1:0];
        end else if (monitor_bank1) begin
          bank1_request_address <= address[13:2];
          bank1_request_write_data <= monitor_word_data;
          bank1_request_write_enable <= write_enable ? monitor_byte_enable : 0;
          bank1_request_read_enable <= read_enable;
          bank1_request_owner <= OWNER_MONITOR;
          monitor_byte_offset <= address[1:0];
        end else begin
          invalid_monitor_ready <= 1;
        end
      end else if (!transaction_active && cpu_imem_valid) begin
        transaction_active <= 1;
        transaction_owner <= OWNER_IMEM;
        if (!imem_address_valid) begin
          invalid_imem_ready <= 1;
        end else if (imem_bank0) begin
          bank0_request_address <= cpu_imem_address[13:2];
          bank0_request_read_enable <= 1;
          bank0_request_owner <= OWNER_IMEM;
        end else begin
          bank1_request_address <= cpu_imem_address[13:2];
          bank1_request_read_enable <= 1;
          bank1_request_owner <= OWNER_IMEM;
        end
      end else if (!transaction_active && cpu_dmem_valid) begin
        transaction_active <= 1;
        transaction_owner <= OWNER_DMEM;
        if (!dmem_address_valid) begin
          invalid_dmem_ready <= 1;
        end else if (dmem_bank0) begin
          bank0_request_address <= cpu_dmem_address[13:2];
          bank0_request_write_data <= cpu_dmem_write_data;
          bank0_request_write_enable <= cpu_dmem_write_enable;
          bank0_request_read_enable <= !(|cpu_dmem_write_enable);
          bank0_request_owner <= OWNER_DMEM;
        end else begin
          bank1_request_address <= cpu_dmem_address[13:2];
          bank1_request_write_data <= cpu_dmem_write_data;
          bank1_request_write_enable <= cpu_dmem_write_enable;
          bank1_request_read_enable <= !(|cpu_dmem_write_enable);
          bank1_request_owner <= OWNER_DMEM;
        end
      end

      // Invalid requests are delayed one cycle, matching the EBR response path.
      if (invalid_monitor_ready) begin
        transaction_active <= 0;
        release_wait <= 1;
        monitor_ready_r <= 1;
        monitor_error_r <= 1;
      end
      if (invalid_imem_ready) begin
        transaction_active <= 0;
        release_wait <= 1;
        imem_read_data_r <= 32'hf800_0000;
        imem_ready_r <= 1;
      end
      if (invalid_dmem_ready) begin
        transaction_active <= 0;
        release_wait <= 1;
        dmem_ready_r <= 1;
        dmem_error_r <= 1;
      end

      if (bank0_response_valid) begin
        transaction_active <= 0;
        release_wait <= 1;
        case (bank0_response_owner)
          OWNER_MONITOR: begin
            monitor_read_word <= bank0_response_data;
            monitor_ready_r <= 1;
          end
          OWNER_IMEM: begin
            imem_read_data_r <= bank0_response_data;
            imem_ready_r <= 1;
          end
          OWNER_DMEM: begin
            dmem_read_data_r <= bank0_response_data;
            dmem_ready_r <= 1;
          end
        endcase
      end
      if (bank1_response_valid) begin
        transaction_active <= 0;
        release_wait <= 1;
        case (bank1_response_owner)
          OWNER_MONITOR: begin
            monitor_read_word <= bank1_response_data;
            monitor_ready_r <= 1;
          end
          OWNER_IMEM: begin
            imem_read_data_r <= bank1_response_data;
            imem_ready_r <= 1;
          end
          OWNER_DMEM: begin
            dmem_read_data_r <= bank1_response_data;
            dmem_ready_r <= 1;
          end
        endcase
      end
    end
  end

  assign read_data = monitor_byte_offset == 0 ? monitor_read_word[7:0] :
                     monitor_byte_offset == 1 ? monitor_read_word[15:8] :
                     monitor_byte_offset == 2 ? monitor_read_word[23:16] :
                                                monitor_read_word[31:24];
  assign ready = monitor_ready_r;
  assign error = monitor_error_r;
  assign cpu_imem_read_data = imem_read_data_r;
  assign cpu_imem_ready = imem_ready_r;
  assign cpu_dmem_read_data = dmem_read_data_r;
  assign cpu_dmem_ready = dmem_ready_r;
  assign cpu_dmem_error = dmem_error_r;
endmodule

`default_nettype wire
