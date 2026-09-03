`default_nettype none

/*
 * Shared frontend for the MiniCPU, UART monitor and the 16-bit SDRAM port.
 *
 * Unified physical byte map:
 *   0x00000000..0x01ffffff  32 MiB SDRAM
 *
 * Both CPU ports and the monitor use the same addresses. The ports remain
 * separate only as a CPU interface detail: instruction fetches are reads,
 * while the data port can read or write any SDRAM word. CPU words are
 * little-endian and are transferred as two independent SDRAM BL1 accesses.
 * The monitor owns memory only while the CPU is halted.
 */
module sdram_system_adapter (
    input  wire        clk,
    input  wire        reset,
    input  wire        init_done,

    input  wire [31:0] monitor_address,
    input  wire [7:0]  monitor_write_data,
    input  wire        monitor_write_enable,
    input  wire        monitor_read_enable,
    output reg  [7:0]  monitor_read_data,
    output reg         monitor_ready,
    output reg         monitor_error,

    input  wire        cpu_halted,
    input  wire        cpu_imem_valid,
    input  wire [31:0] cpu_imem_address,
    output reg  [31:0] cpu_imem_read_data,
    output reg         cpu_imem_ready,

    input  wire        cpu_dmem_valid,
    input  wire [31:0] cpu_dmem_address,
    input  wire [31:0] cpu_dmem_write_data,
    input  wire [3:0]  cpu_dmem_write_enable,
    output reg  [31:0] cpu_dmem_read_data,
    output reg         cpu_dmem_ready,
    output reg         cpu_dmem_error,

    output reg         req_valid,
    output reg         req_write,
    output reg  [23:0] req_addr,
    output reg  [15:0] req_wdata,
    output reg  [1:0]  req_wmask,
    input  wire        req_ready,
    input  wire        done,
    input  wire [15:0] rdata
);
  localparam [2:0] OWNER_NONE    = 3'd0;
  localparam [2:0] OWNER_MONITOR = 3'd1;
  localparam [2:0] OWNER_IMEM    = 3'd2;
  localparam [2:0] OWNER_DMEM    = 3'd3;

  localparam STATE_IDLE        = 3'd0;
  localparam STATE_WAIT_FIRST  = 3'd1;
  localparam STATE_START_NEXT  = 3'd2;
  localparam STATE_WAIT_SECOND = 3'd3;
  localparam STATE_RELEASE     = 3'd4;
  localparam STATE_VALIDATE_MONITOR = 3'd5;

  reg [2:0] state;
  reg [2:0] owner;
  reg saved_monitor_byte;
  reg saved_monitor_read;
  reg saved_cpu_read;
  reg [15:0] first_read_data;
  reg [23:0] second_addr;
  reg [15:0] second_wdata;
  reg [1:0] second_wmask;
  reg [31:0] saved_monitor_address;
  reg [7:0] saved_monitor_write_data;
  reg saved_monitor_write_enable;

  wire monitor_request = monitor_write_enable || monitor_read_enable;
  wire cpu_imem_address_valid =
      cpu_imem_address[31:25] == 0 && cpu_imem_address[1:0] == 0;
  wire cpu_dmem_address_valid =
      cpu_dmem_address[31:25] == 0 && cpu_dmem_address[1:0] == 0;

  always @(posedge clk) begin
    monitor_ready <= 1'b0;
    monitor_error <= 1'b0;
    cpu_imem_ready <= 1'b0;
    cpu_dmem_ready <= 1'b0;
    cpu_dmem_error <= 1'b0;

    if (reset) begin
      state <= STATE_IDLE;
      owner <= OWNER_NONE;
      monitor_read_data <= 8'h00;
      cpu_imem_read_data <= 32'h0000_0000;
      cpu_dmem_read_data <= 32'h0000_0000;
      req_valid <= 1'b0;
      req_write <= 1'b0;
      req_addr <= 24'h000000;
      req_wdata <= 16'h0000;
      req_wmask <= 2'b00;
      saved_monitor_byte <= 1'b0;
      saved_monitor_read <= 1'b0;
      saved_cpu_read <= 1'b0;
      first_read_data <= 16'h0000;
      second_addr <= 24'h000000;
      second_wdata <= 16'h0000;
      second_wmask <= 2'b00;
      saved_monitor_address <= 32'h0000_0000;
      saved_monitor_write_data <= 8'h00;
      saved_monitor_write_enable <= 1'b0;
    end else begin
      case (state)
        STATE_IDLE: begin
          req_valid <= 1'b0;
          owner <= OWNER_NONE;

          if (monitor_request) begin
            owner <= OWNER_MONITOR;
            saved_monitor_address <= monitor_address;
            saved_monitor_write_data <= monitor_write_data;
            saved_monitor_write_enable <= monitor_write_enable;
            saved_monitor_read <= monitor_read_enable;
            state <= STATE_VALIDATE_MONITOR;
          end else if (!cpu_halted && cpu_imem_valid) begin
            if (!init_done || !cpu_imem_address_valid) begin
              owner <= OWNER_IMEM;
              cpu_imem_read_data <= 32'hf800_0000;
              cpu_imem_ready <= 1'b1;
              state <= STATE_RELEASE;
            end else begin
              owner <= OWNER_IMEM;
              saved_cpu_read <= 1'b1;
              // imem and dmem share the same physical SDRAM address space.
              req_addr <= cpu_imem_address[24:1];
              req_write <= 1'b0;
              req_wdata <= 16'h0000;
              req_wmask <= 2'b00;
              second_addr <= cpu_imem_address[24:1] + 1'b1;
              second_wdata <= 16'h0000;
              second_wmask <= 2'b00;
              req_valid <= 1'b1;
              state <= STATE_WAIT_FIRST;
            end
          end else if (!cpu_halted && cpu_dmem_valid) begin
            if (!init_done || !cpu_dmem_address_valid) begin
              owner <= OWNER_DMEM;
              cpu_dmem_ready <= 1'b1;
              cpu_dmem_error <= 1'b1;
              state <= STATE_RELEASE;
            end else begin
              owner <= OWNER_DMEM;
              saved_cpu_read <= !(|cpu_dmem_write_enable);
              req_addr <= cpu_dmem_address[24:1];
              req_write <= |cpu_dmem_write_enable;
              req_wdata <= cpu_dmem_write_data[15:0];
              req_wmask <= cpu_dmem_write_enable[1:0];
              second_addr <= cpu_dmem_address[24:1] + 1'b1;
              second_wdata <= cpu_dmem_write_data[31:16];
              second_wmask <= cpu_dmem_write_enable[3:2];
              req_valid <= 1'b1;
              state <= STATE_WAIT_FIRST;
            end
          end
        end

        // Address checking is isolated from the SDRAM request registers. This
        // prevents the seven-bit range comparison becoming a 120 MHz path from
        // the registered monitor address to req_addr/req_wdata.
        STATE_VALIDATE_MONITOR: begin
          if (!cpu_halted || !init_done ||
              saved_monitor_address[31:25] != 0 ||
              (saved_monitor_write_enable && saved_monitor_read)) begin
            monitor_ready <= 1'b1;
            monitor_error <= 1'b1;
            state <= STATE_RELEASE;
          end else begin
            saved_monitor_byte <= saved_monitor_address[0];
            req_addr <= saved_monitor_address[24:1];
            req_write <= saved_monitor_write_enable;
            req_wdata <= saved_monitor_address[0] ?
                {saved_monitor_write_data, 8'h00} :
                {8'h00, saved_monitor_write_data};
            req_wmask <= saved_monitor_address[0] ? 2'b10 : 2'b01;
            req_valid <= 1'b1;
            state <= STATE_WAIT_FIRST;
          end
        end

        STATE_WAIT_FIRST: begin
          if (req_valid && req_ready)
            req_valid <= 1'b0;
          if (done) begin
            if (owner == OWNER_MONITOR) begin
              if (saved_monitor_read)
                monitor_read_data <= saved_monitor_byte ? rdata[15:8] : rdata[7:0];
              monitor_ready <= 1'b1;
              state <= STATE_RELEASE;
            end else begin
              if (saved_cpu_read)
                first_read_data <= rdata;
              // A zero lower write mask still issues a harmless masked write.
              // This keeps the sequencer simple and does not affect CPU STORE,
              // which currently writes all four bytes.
              state <= STATE_START_NEXT;
            end
          end
        end

        STATE_START_NEXT: begin
          req_addr <= second_addr;
          req_write <= !saved_cpu_read;
          req_wdata <= second_wdata;
          req_wmask <= saved_cpu_read ? 2'b00 : second_wmask;
          req_valid <= 1'b1;
          state <= STATE_WAIT_SECOND;
        end

        STATE_WAIT_SECOND: begin
          if (req_valid && req_ready)
            req_valid <= 1'b0;
          if (done) begin
            if (owner == OWNER_IMEM) begin
              cpu_imem_read_data <= {rdata, first_read_data};
              cpu_imem_ready <= 1'b1;
            end else begin
              if (saved_cpu_read)
                cpu_dmem_read_data <= {rdata, first_read_data};
              cpu_dmem_ready <= 1'b1;
            end
            state <= STATE_RELEASE;
          end
        end

        // Handshake release stage: never accept a still-high valid twice.
        // The requester observes ready one clock
        // after it is registered here. Do not accept the still-high request a
        // second time while its owner is deasserting valid.
        STATE_RELEASE: begin
          req_valid <= 1'b0;
          if ((owner == OWNER_MONITOR && !monitor_request) ||
              (owner == OWNER_IMEM && !cpu_imem_valid) ||
              (owner == OWNER_DMEM && !cpu_dmem_valid))
            state <= STATE_IDLE;
        end
      endcase
    end
  end
endmodule

`default_nettype wire
