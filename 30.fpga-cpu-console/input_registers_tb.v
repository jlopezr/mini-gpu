`timescale 1ns / 1ps
`default_nettype none

/*
 * Banco diferencial de input_registers.v.
 *
 * Reproduce `input_vectors.hex`, que genera `tools/gen_input_vectors.py` con el
 * oraculo `InputDevice`: cada linea es una operacion (evento por el puerto del
 * adaptador, lectura o escritura por MMIO, presencia, colisiones en el mismo
 * ciclo) con el valor que el RTL debe contestar. Tras cada operacion se
 * compara tambien `free_slots`, que es el control de flujo del monitor.
 *
 * El timing de la transaccion es el de mmio_decoder: `select` dura un ciclo,
 * address/write/write_data siguen retenidos, y `read_data` vale en el ciclo
 * siguiente al `select` --justo antes del pop, que ocurre un ciclo despues--.
 * Todo se maneja en el flanco de bajada para que no haya carreras.
 *
 * Regenerar los vectores: python -m tools.gen_input_vectors
 */
module input_registers_tb;
  localparam [7:0] OP_END = 0, OP_EVENT = 1, OP_PRESENCE = 2, OP_READ = 3,
                   OP_WRITE = 4, OP_WRITE_BAD = 5, OP_FREE = 6,
                   OP_EVENT_POP = 7, OP_EVENT_FLUSH = 8, OP_EVENT_CLEAR = 9,
                   OP_WRITE_PARTIAL = 10;
  localparam [7:0] EVENT_DATA = 8'h00, EVENT_CTRL = 8'h08;

  reg clk = 0;
  always #5 clk = ~clk;

  reg        reset;
  reg        select, write;
  reg  [3:0] write_mask;
  reg  [7:0] address;
  reg [31:0] write_data;
  wire [31:0] read_data;
  wire        input_error;
  reg         event_valid;
  reg  [31:0] event_word;
  reg         presence_write, presence_keyboard, presence_mouse;
  wire  [4:0] free_slots;

  input_registers dut (
      .clk(clk), .reset(reset),
      .select(select), .write(write), .write_mask(write_mask),
      .address(address), .write_data(write_data), .read_data(read_data),
      .input_error(input_error),
      .event_valid(event_valid), .event_word(event_word),
      .presence_write(presence_write), .presence_keyboard(presence_keyboard),
      .presence_mouse(presence_mouse), .free_slots(free_slots));

  reg [71:0] vec [0:32767];
  integer pc, failures, checked;
  reg [7:0]  op;
  reg [31:0] arg, exp;

  task fail(input [255:0] what);
    begin
      failures = failures + 1;
      if (failures < 20)
        $display("FALLO linea %0d op=%0h arg=%08h exp=%08h: %0s (read=%08h free=%0d err=%b)",
                 pc, op, arg, exp, what, read_data, free_slots, input_error);
    end
  endtask

  // Una transaccion MMIO. `ev_when`: 0 sin evento, 1 evento en el ciclo del
  // `select` (FLUSH, CLEAR), 2 evento en el ciclo del pop (EVENT_DATA).
  task bus(input wr, input [7:0] addr, input [31:0] data, input [3:0] mask,
           input integer ev_when, input [31:0] ev_word, output [31:0] value);
    begin
      @(negedge clk);
      select = 1'b1; write = wr; address = addr; write_data = data;
      write_mask = mask;
      if (ev_when == 1) begin event_valid = 1'b1; event_word = ev_word; end
      @(negedge clk);
      select = 1'b0;
      if (ev_when == 1) event_valid = 1'b0;
      value = read_data;                  // valido justo antes del pop
      if (ev_when == 2) begin event_valid = 1'b1; event_word = ev_word; end
      @(negedge clk);
      event_valid = 1'b0;
      write = 1'b0;
    end
  endtask

  reg [31:0] value;

  initial begin
    failures = 0; checked = 0;
    reset = 1; select = 0; write = 0; write_mask = 4'hF; address = 0;
    write_data = 0; event_valid = 0; event_word = 0;
    presence_write = 0; presence_keyboard = 0; presence_mouse = 0;
    $readmemh("input_vectors.hex", vec);
    repeat (3) @(negedge clk);
    reset = 0;
    @(negedge clk);

    pc = 0;
    op = 8'hxx;
    forever begin
      op  = vec[pc][71:64];
      arg = vec[pc][63:32];
      exp = vec[pc][31:0];
      if (op === OP_END) begin
        $display("INPUT_REGISTERS: %0d operaciones comparadas, %0d fallos", checked, failures);
        if (failures == 0) $display("input_registers_tb PASS");
        else               $display("input_registers_tb FAIL");
        $finish;
      end
      case (op)
        OP_EVENT: begin
          @(negedge clk);
          event_valid = 1'b1; event_word = arg;
          @(negedge clk);
          event_valid = 1'b0;
        end
        OP_PRESENCE: begin
          @(negedge clk);
          presence_write = 1'b1;
          presence_keyboard = arg[0]; presence_mouse = arg[1];
          @(negedge clk);
          presence_write = 1'b0;
        end
        OP_READ: begin
          bus(1'b0, arg[7:0], 32'd0, 4'hF, 0, 32'd0, value);
          if (value !== exp) fail("lectura");
        end
        OP_WRITE: begin
          bus(1'b1, EVENT_CTRL, arg, 4'hF, 0, 32'd0, value);
          if (input_error) fail("error inesperado");
        end
        OP_WRITE_BAD: begin
          // El error es combinacional con la direccion y el dato retenidos.
          @(negedge clk);
          write = 1'b1; address = EVENT_CTRL; write_data = arg; write_mask = 4'hF;
          #1;
          if (!input_error) fail("deberia dar error");
          select = 1'b1;
          @(negedge clk);
          select = 1'b0; write = 1'b0;
        end
        OP_WRITE_PARTIAL: begin
          @(negedge clk);
          write = 1'b1; address = EVENT_CTRL; write_data = arg; write_mask = 4'b0111;
          #1;
          if (!input_error) fail("mascara parcial deberia dar error");
          select = 1'b1;
          @(negedge clk);
          select = 1'b0; write = 1'b0; write_mask = 4'hF;
        end
        OP_FREE: begin
          @(negedge clk);
          if (free_slots !== exp[4:0]) fail("huecos libres");
        end
        OP_EVENT_POP: begin
          bus(1'b0, EVENT_DATA, 32'd0, 4'hF, 2, arg, value);
          if (value !== exp) fail("lectura con push simultaneo");
        end
        OP_EVENT_FLUSH: begin
          bus(1'b1, EVENT_CTRL, 32'd1, 4'hF, 1, arg, value);
        end
        OP_EVENT_CLEAR: begin
          bus(1'b1, EVENT_CTRL, 32'd2, 4'hF, 1, arg, value);
        end
        default: begin
          $display("op desconocida %0h en la linea %0d", op, pc);
          failures = failures + 1;
        end
      endcase
      checked = checked + 1;
      // Hueco entre operaciones, para que cada una se vea aislada.
      @(negedge clk);
      pc = pc + 1;
    end
  end

  initial begin
    #200000000;
    $display("input_registers_tb TIMEOUT");
    $finish;
  end
endmodule

`default_nettype wire
