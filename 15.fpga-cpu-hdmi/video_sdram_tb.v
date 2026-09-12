`timescale 1ns/1ps
`default_nettype none

// Banco de pruebas del hito C: el camino SDRAM -> line buffer.
//
// Monta el lector de lineas contra el adaptador real y un modelo funcional de
// memoria. No se usa el controlador de SDRAM fisico: lo que se comprueba aqui
// es la aritmetica de direcciones del framebuffer y el arbitraje entre video y
// CPU, no la temporizacion JEDEC, que ya tiene su propio banco.
//
// Se comprueban tres cosas:
//
//   1. Una linea llega completa, en orden y con el contenido correcto.
//   2. La direccion base de cada linea es la que toca (se prueban dos lineas
//      distintas y no consecutivas, que es donde se ve un error de pitch).
//   3. La CPU sigue avanzando mientras el video lee. El video tiene prioridad,
//      pero prioridad no es monopolio: si esto fallara, un fill de linea
//      congelaria la CPU entera.

module video_sdram_tb;
  localparam integer SRC_W     = 16;
  localparam integer ADDR_BITS = 5;
  localparam integer LINE_BITS = 6;
  localparam [23:0] FB_BASE = 24'h000100;

  reg clk = 1'b0;
  reg reset = 1'b1;
  always #4.1667 clk = ~clk;

  // ---- modelo de memoria ----
  localparam integer MEM_WORDS = 1024;
  reg [15:0] mem [0:MEM_WORDS-1];

  wire req_valid, req_write;
  wire [23:0] req_addr;
  wire [15:0] req_wdata;
  wire [1:0] req_wmask;
  reg req_ready = 1'b1;
  reg done = 1'b0;
  reg [15:0] rdata = 16'h0000;

  // Latencia de tres ciclos, para que el handshake no se pruebe solo en el
  // caso comodo de respuesta inmediata.
  reg [2:0] latency;
  reg [23:0] pending_addr;
  reg pending;

  always @(posedge clk) begin
    done <= 1'b0;
    if (reset) begin
      pending <= 1'b0;
      latency <= 3'd0;
    end else if (!pending) begin
      if (req_valid && req_ready) begin
        pending <= 1'b1;
        pending_addr <= req_addr;
        latency <= 3'd3;
        if (req_write) begin
          if (req_wmask[0]) mem[req_addr[9:0]][7:0] <= req_wdata[7:0];
          if (req_wmask[1]) mem[req_addr[9:0]][15:8] <= req_wdata[15:8];
        end
      end
    end else if (latency != 3'd0) begin
      latency <= latency - 1'b1;
    end else begin
      rdata <= mem[pending_addr[9:0]];
      done <= 1'b1;
      pending <= 1'b0;
    end
  end

  // ---- adaptador ----
  reg [31:0] monitor_address = 32'h0;
  reg [7:0] monitor_write_data = 8'h0;
  reg monitor_write_enable = 1'b0, monitor_read_enable = 1'b0;
  wire [7:0] monitor_read_data;
  wire monitor_ready, monitor_error;

  reg cpu_halted = 1'b0;
  reg cpu_imem_valid = 1'b0;
  reg [31:0] cpu_imem_address = 32'h0;
  wire [31:0] cpu_imem_read_data;
  wire cpu_imem_ready;

  reg cpu_dmem_valid = 1'b0;
  reg [31:0] cpu_dmem_address = 32'h0;
  reg [31:0] cpu_dmem_write_data = 32'h0;
  reg [3:0] cpu_dmem_write_enable = 4'h0;
  wire [31:0] cpu_dmem_read_data;
  wire cpu_dmem_ready, cpu_dmem_error;

  wire video_req, video_ready;
  wire [23:0] video_addr;
  wire [15:0] video_read_data;

  sdram_system_adapter adapter_i(
      .clk(clk), .reset(reset), .init_done(1'b1),
      .monitor_address(monitor_address),
      .monitor_write_data(monitor_write_data),
      .monitor_write_enable(monitor_write_enable),
      .monitor_read_enable(monitor_read_enable),
      .monitor_read_data(monitor_read_data), .monitor_ready(monitor_ready),
      .monitor_error(monitor_error),
      .cpu_halted(cpu_halted),
      .cpu_imem_valid(cpu_imem_valid), .cpu_imem_address(cpu_imem_address),
      .cpu_imem_read_data(cpu_imem_read_data), .cpu_imem_ready(cpu_imem_ready),
      .cpu_dmem_valid(cpu_dmem_valid), .cpu_dmem_address(cpu_dmem_address),
      .cpu_dmem_write_data(cpu_dmem_write_data),
      .cpu_dmem_write_enable(cpu_dmem_write_enable),
      .cpu_dmem_read_data(cpu_dmem_read_data), .cpu_dmem_ready(cpu_dmem_ready),
      .cpu_dmem_error(cpu_dmem_error),
      .mmio_select(), .mmio_write(), .mmio_write_mask(), .mmio_address(),
      .mmio_write_data(), .mmio_read_data(32'h0000_0000),
      .video_req(video_req), .video_addr(video_addr),
      .video_read_data(video_read_data), .video_ready(video_ready),
      .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr),
      .req_wdata(req_wdata), .req_wmask(req_wmask), .req_ready(req_ready),
      .done(done), .rdata(rdata));

  // ---- lector de lineas ----
  reg fill_start = 1'b0;
  reg [LINE_BITS-1:0] fill_line = 0;
  wire fill_we, fill_done;
  wire [ADDR_BITS-1:0] fill_addr;
  wire [15:0] fill_data;

  video_line_source_sdram #(
      .SRC_W(SRC_W), .ADDR_BITS(ADDR_BITS), .LINE_BITS(LINE_BITS)
  ) source_i(
      .clk(clk), .reset(reset), .fb_base(FB_BASE),
      .fill_start(fill_start), .fill_line(fill_line),
      .fill_we(fill_we), .fill_addr(fill_addr), .fill_data(fill_data),
      .fill_done(fill_done),
      .video_req(video_req), .video_addr(video_addr),
      .video_read_data(video_read_data), .video_ready(video_ready));

  // ---- captura de lo escrito en el line buffer ----
  reg [15:0] captured [0:SRC_W-1];
  reg [31:0] captured_count;
  reg [31:0] expected_addr;
  integer i;

  always @(posedge clk) begin
    if (reset) begin
      captured_count <= 0;
    end else if (fill_we) begin
      captured[fill_addr] <= fill_data;
      // Las palabras deben llegar en orden y sin huecos.
      if (fill_addr !== captured_count[ADDR_BITS-1:0])
        $fatal(1, "escritura fuera de orden: addr=%0d esperado %0d",
               fill_addr, captured_count);
      captured_count <= captured_count + 1;
    end
  end

  // Duracion de cada fill en ciclos: es la magnitud que decide si el scanout
  // llega a tiempo, y la que empeora al dar turnos a la CPU.
  reg counting = 1'b0;
  integer fill_cycles = 0;
  always @(posedge clk) begin
    if (fill_start) begin
      counting <= 1'b1;
      fill_cycles <= 0;
    end else if (counting) begin
      fill_cycles <= fill_cycles + 1;
      if (fill_done) counting <= 1'b0;
    end
  end

  task fetch_line(input [LINE_BITS-1:0] line);
    begin
      @(negedge clk);
      captured_count = 0;
      fill_line = line;
      fill_start = 1'b1;
      @(negedge clk);
      fill_start = 1'b0;
      wait (fill_done);
      // `fill_done` y el ultimo `fill_we` se ponen a uno en la misma
      // asignacion no bloqueante, asi que el `wait` despierta un flanco antes
      // de que el bloque de captura llegue a muestrear esa ultima palabra.
      // Hace falta dejar pasar el flanco de subida siguiente.
      @(posedge clk);
      @(negedge clk);
      if (captured_count !== SRC_W)
        $fatal(1, "linea %0d: %0d palabras, esperadas %0d",
               line, captured_count, SRC_W);
      for (i = 0; i < SRC_W; i = i + 1) begin
        expected_addr = FB_BASE + line * SRC_W + i;
        if (captured[i] !== mem[expected_addr[9:0]])
          $fatal(1, "linea %0d pixel %0d: %04x, esperado %04x (palabra %0d)",
                 line, i, captured[i], mem[expected_addr[9:0]], expected_addr);
      end
      $display("linea %0d correcta: %0d pixeles desde la palabra %0d en %0d ciclos",
               line, SRC_W, FB_BASE + line * SRC_W, fill_cycles);
    end
  endtask

  // ---- la CPU pide memoria en paralelo ----
  //
  // Se modela como se comporta la CPU real: baja `valid` al recibir `ready`.
  // El adaptador exige ese gesto en su etapa de release, asi que un banco que
  // dejara `valid` alto para siempre bloquearia el arbitro y no probaria nada.
  reg cpu_active = 1'b0;
  integer cpu_reads_done = 0;
  integer baseline_cycles = 0;

  initial begin
    forever begin
      @(negedge clk);
      if (cpu_active) begin
        cpu_dmem_valid = 1'b1;
        wait (cpu_dmem_ready);
        @(negedge clk);
        cpu_dmem_valid = 1'b0;
      end
    end
  end

  // Se cuenta `ready` a secas: para cuando el contador lo muestrea, el proceso
  // que modela la CPU ya ha bajado `valid` medio ciclo antes. `ready` solo
  // pulsa cuando hay una transaccion de CPU de verdad, asi que basta.
  always @(posedge clk) begin
    if (!reset && cpu_dmem_ready)
      cpu_reads_done = cpu_reads_done + 1;
    if (!reset && cpu_dmem_error)
      $fatal(1, "el adaptador rechazo una lectura de CPU valida");
  end

  initial begin
    $dumpvars(0, video_sdram_tb);

    for (i = 0; i < MEM_WORDS; i = i + 1) mem[i] = i[15:0] ^ 16'ha5a5;

    repeat (3) @(negedge clk);
    reset = 1'b0;
    repeat (3) @(negedge clk);

    fetch_line(0);
    baseline_cycles = fill_cycles;
    fetch_line(5);
    fetch_line(19);  // linea alta: aqui se ve un error de pitch

    // La CPU pide sin parar mientras se llena una linea entera.
    cpu_dmem_address = 32'h0000_0040;
    cpu_dmem_write_enable = 4'h0;
    cpu_active = 1'b1;
    fetch_line(2);
    cpu_active = 1'b0;
    repeat (20) @(negedge clk);

    if (cpu_reads_done == 0)
      $fatal(1, "la CPU no completo ninguna lectura durante el fill: la prioridad de video se ha convertido en monopolio");

    // La otra mitad del trato: los turnos que se le dan a la CPU no pueden
    // hacer que el fill llegue tarde. Con VIDEO_RUN=4 y una transaccion de CPU
    // costando el doble que una de video, el modelo predice un 50 % mas de
    // duracion; se admite hasta un 60 % antes de considerarlo una regresion.
    if (fill_cycles * 10 > baseline_cycles * 16)
      $fatal(1, "el fill con CPU activa tarda %0d ciclos frente a %0d en vacio: demasiada cesion",
             fill_cycles, baseline_cycles);

    $display("OK: lineas correctas, %0d lecturas de CPU durante el fill, %0d ciclos frente a %0d en vacio",
             cpu_reads_done, fill_cycles, baseline_cycles);
    $finish;
  end

  initial begin
    #500_000;
    $fatal(1, "timeout");
  end
endmodule

`default_nettype wire

