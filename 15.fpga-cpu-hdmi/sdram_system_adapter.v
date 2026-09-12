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
 *
 * The video port is the third client and has priority over both the monitor
 * and the CPU: if the line buffer runs dry the picture breaks, while a stalled
 * CPU merely runs slower. It is also the cheapest client, because one RGB565
 * pixel is exactly one 16-bit SDRAM access, so a video read needs a single BL1
 * transfer instead of the two a 32-bit CPU word takes.
 *
 * Priority is bounded, not absolute. The line source re-asserts video_req one
 * cycle after each grant, so plain priority would hand video the bus for the
 * whole fill and freeze the CPU and monitor for tens of microseconds at a
 * time. After VIDEO_RUN consecutive grants video yields one turn whenever
 * anyone else is waiting.
 *
 * Sizing, per pair of display lines (the time available to fetch one source
 * line), at 120 MHz and 25 MHz pixel clock:
 *
 *   presupuesto        2 * 800 pixeles / 25 MHz = 64 us = 7680 ciclos
 *   video              SRC_W accesos de 16 bits
 *   coste por turno    VIDEO_RUN accesos de video + uno de CPU (dos mitades)
 *
 *   total = SRC_W * V + (SRC_W / VIDEO_RUN) * C
 *
 * With SRC_W=320, V=10 and C=20 cycles: VIDEO_RUN=1 needs 9600 cycles and does
 * not fit; VIDEO_RUN=4 needs 4800 and leaves 37 % of margin while giving the
 * CPU a slot roughly every half microsecond. That margin absorbs a video
 * access costing up to 19 cycles instead of 10.
 */
module sdram_system_adapter #(
    parameter integer VIDEO_RUN = 4
) (
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

    // Ventana de registros de video en 0x80000000. No toca la SDRAM: se
    // resuelve en un ciclo. La atienden tanto la CPU (palabra completa) como
    // el monitor (byte a byte), porque poder mover el framebuffer desde el PC
    // sin escribir un programa es la forma rapida de probar el swap.
    output reg mmio_select,
    output reg mmio_write,
    output reg [3:0] mmio_write_mask,
    output reg [3:0] mmio_address,
    output reg [31:0] mmio_write_data,
    input wire [31:0] mmio_read_data,

    // Video scanout: single 16-bit read, halfword address, no range check
    // because the line source can only generate addresses inside the frame
    // buffer. `video_req` stays high until `video_ready` pulses.
    input  wire        video_req,
    input  wire [23:0] video_addr,
    output reg  [15:0] video_read_data,
    output reg         video_ready,

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
  localparam [2:0] OWNER_VIDEO   = 3'd4;

  localparam STATE_IDLE        = 3'd0;
  localparam STATE_WAIT_FIRST  = 3'd1;
  localparam STATE_START_NEXT  = 3'd2;
  localparam STATE_WAIT_SECOND = 3'd3;
  localparam STATE_RELEASE     = 3'd4;
  localparam STATE_VALIDATE_MONITOR = 3'd5;
  localparam STATE_WAIT_VIDEO  = 3'd6;
  localparam STATE_MMIO_WAIT   = 3'd7;

  // Ventana de registros de video: 0x80000000..0x8000000f. Se decodifica
  // estricta; cualquier otra direccion alta sigue siendo un error, como antes.
  localparam [27:0] MMIO_PREFIX = 28'h800_0000;

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

  reg [7:0] video_run;
  wire monitor_request = monitor_write_enable || monitor_read_enable;
  wire other_request = monitor_request ||
      (!cpu_halted && (cpu_imem_valid || cpu_dmem_valid));
  // El video cede un turno cuando ya ha encadenado VIDEO_RUN accesos y hay
  // alguien esperando. Sin esto, `video_req` vuelve a subir antes de que el
  // arbitro mire a los demas y la prioridad se convierte en monopolio.
  wire video_must_yield = (video_run >= VIDEO_RUN[7:0]) && other_request;
  wire video_grant = video_req && init_done && !video_must_yield;
  wire cpu_imem_address_valid =
      cpu_imem_address[31:25] == 0 && cpu_imem_address[1:0] == 0;
  wire cpu_dmem_address_valid =
      cpu_dmem_address[31:25] == 0 && cpu_dmem_address[1:0] == 0;
  wire cpu_dmem_mmio =
      cpu_dmem_address[31:4] == MMIO_PREFIX && cpu_dmem_address[1:0] == 0;
  // El monitor accede byte a byte, asi que no exige alineamiento.
  wire monitor_mmio = saved_monitor_address[31:4] == MMIO_PREFIX;

  always @(posedge clk) begin
    monitor_ready <= 1'b0;
    monitor_error <= 1'b0;
    cpu_imem_ready <= 1'b0;
    cpu_dmem_ready <= 1'b0;
    cpu_dmem_error <= 1'b0;
    video_ready <= 1'b0;

    mmio_select <= 1'b0;
    mmio_write <= 1'b0;

    if (reset) begin
      video_read_data <= 16'h0000;
      video_run <= 8'd0;
      mmio_write_mask <= 4'b0000;
      mmio_address <= 4'h0;
      mmio_write_data <= 32'h0000_0000;
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

          if (video_grant) begin
            // Prioridad acotada: el scanout va primero, pero cede un turno
            // cada VIDEO_RUN accesos si hay alguien esperando. Antes de
            // `init_done` no se atiende y la peticion queda pendiente, que es
            // justo lo que hace falta durante los 200 us de arranque de la
            // SDRAM: el scanout se queda en el prellenado, sin marcar underflow.
            if (video_run < VIDEO_RUN[7:0]) video_run <= video_run + 1'b1;
            owner <= OWNER_VIDEO;
            req_addr <= video_addr;
            req_write <= 1'b0;
            req_wdata <= 16'h0000;
            req_wmask <= 2'b00;
            req_valid <= 1'b1;
            state <= STATE_WAIT_VIDEO;
          end else if (monitor_request) begin
            video_run <= 8'd0;
            owner <= OWNER_MONITOR;
            saved_monitor_address <= monitor_address;
            saved_monitor_write_data <= monitor_write_data;
            saved_monitor_write_enable <= monitor_write_enable;
            saved_monitor_read <= monitor_read_enable;
            state <= STATE_VALIDATE_MONITOR;
          end else if (!cpu_halted && cpu_imem_valid) begin
            video_run <= 8'd0;
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
            video_run <= 8'd0;
            if (cpu_dmem_mmio) begin
              // Registros de video: un ciclo, sin tocar la SDRAM.
              owner <= OWNER_DMEM;
              saved_cpu_read <= !(|cpu_dmem_write_enable);
              mmio_select <= 1'b1;
              mmio_write <= |cpu_dmem_write_enable;
              mmio_write_mask <= cpu_dmem_write_enable;
              mmio_address <= cpu_dmem_address[3:0];
              mmio_write_data <= cpu_dmem_write_data;
              state <= STATE_MMIO_WAIT;
            end else if (!init_done || !cpu_dmem_address_valid) begin
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
          if (saved_monitor_write_enable && saved_monitor_read) begin
            monitor_ready <= 1'b1;
            monitor_error <= 1'b1;
            state <= STATE_RELEASE;
          end else if (monitor_mmio) begin
            // Los registros de video se atienden aunque la CPU este corriendo:
            // no hay coherencia que romper y poder leer el contador de frames
            // mientras la CPU anima es justo para lo que sirve. La regla de
            // "el monitor posee la memoria solo con la CPU parada" sigue
            // aplicandose sin cambios a la SDRAM.
            mmio_select <= 1'b1;
            mmio_write <= saved_monitor_write_enable;
            mmio_write_mask <= 4'b0001 << saved_monitor_address[1:0];
            mmio_address <= saved_monitor_address[3:0];
            mmio_write_data <= {4{saved_monitor_write_data}};
            state <= STATE_MMIO_WAIT;
          end else if (!cpu_halted || !init_done ||
                       saved_monitor_address[31:25] != 0) begin
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

        // `mmio_address` se registro al salir de IDLE, asi que la lectura
        // combinacional del bloque de registros ya es valida en este ciclo. La
        // escritura, si la hay, ocurre en el flanco que cierra este estado:
        // `mmio_select` esta alto exactamente un ciclo.
        STATE_MMIO_WAIT: begin
          if (owner == OWNER_MONITOR) begin
            if (saved_monitor_read)
              monitor_read_data <=
                  mmio_read_data[{saved_monitor_address[1:0], 3'b000} +: 8];
            monitor_ready <= 1'b1;
          end else begin
            if (saved_cpu_read) cpu_dmem_read_data <= mmio_read_data;
            cpu_dmem_ready <= 1'b1;
          end
          state <= STATE_RELEASE;
        end

        // Un pixel RGB565 es exactamente un acceso de 16 bits: no hay segunda
        // mitad que buscar, a diferencia de una palabra de CPU.
        STATE_WAIT_VIDEO: begin
          if (req_valid && req_ready)
            req_valid <= 1'b0;
          if (done) begin
            video_read_data <= rdata;
            video_ready <= 1'b1;
            state <= STATE_RELEASE;
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
              (owner == OWNER_DMEM && !cpu_dmem_valid) ||
              (owner == OWNER_VIDEO && !video_req))
            state <= STATE_IDLE;
        end
      endcase
    end
  end
endmodule

`default_nettype wire
