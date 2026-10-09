`default_nettype none

/*
 * MiniISA register file.
 *
 * - 32 registers of 32 bits, of which R0 is hardwired to zero.
 * - Two combinational read ports for Ra and Rb.
 * - One synchronous write port for Rd.
 * - One registered read-only debug port.
 *
 * R0 IS HARDWIRED TO ZERO: writes are dropped, reads always return zero. It is
 * a rule of the ISA, not of this implementation. See 1.isa/isa.md section 1.
 *
 * EN ESTA CARPETA ESTE FICHERO NO ES EL DE LAS DEMAS (experimento, 9 de octubre
 * de 2026). Las demas ponen a cero los 32 registros en el ciclo del reset, y eso
 * obliga a la sintesis a usar flip-flops: 1.061 FF y 2.589 LUT4 de
 * multiplexores para tres lecturas. Aqui el banco es una RAM distribuida
 * (3 copias de 16 DPR16X4: 48 celdas, 43 FF y 141 LUT4) y el reset arranca un
 * BARRIDO de 32 ciclos que escribe cero en cada direccion. Mientras dura, y
 * mientras `reset` este alto, `busy` vale 1 y quien instancia el banco debe
 * mantener a la CPU parada: durante el barrido las lecturas no valen. Por eso
 * `registers[0]` sigue siendo cero: el barrido lo escribe y nada mas lo escribe.
 */
module register_file (
    input clk,
    input reset,

    input [4:0] read_address_a,
    output [31:0] read_data_a,
    input [4:0] read_address_b,
    output [31:0] read_data_b,

    input write_enable,
    input [4:0] write_address,
    input [31:0] write_data,

    input [4:0] debug_address,
    output reg [31:0] debug_data,

    output busy
);

  reg [31:0] registers[0:31];

  // 0..31 barre; 32 (bit 5) = terminado. El reset lo vuelve a 0.
  reg [5:0] sweep = 6'd0;
  wire sweeping = !sweep[5];
  assign busy = reset || sweeping;

  /*
   * Debug is intentionally two cycles deep: first capture the requested
   * address, then capture the selected register. UART debug traffic tolerates
   * this latency and the large 32-to-1 mux no longer ends at a distant monitor
   * register. The CPU read ports remain combinational. See timing.md.
   */
  reg [4:0] debug_address_registered;

  assign read_data_a = registers[read_address_a];
  assign read_data_b = registers[read_address_b];

  wire        normal_write = write_enable && write_address != 5'd0;
  wire [4:0]  waddr = sweeping ? sweep[4:0] : write_address;
  wire [31:0] wdata = sweeping ? 32'h0000_0000 : write_data;

  always @(posedge clk) begin
    if (reset) sweep <= 6'd0;
    else if (sweeping) sweep <= sweep + 6'd1;

    if (sweeping || normal_write) registers[waddr] <= wdata;

    if (reset) begin
      debug_address_registered <= 5'd0;
      debug_data <= 32'h0000_0000;
    end else begin
      debug_address_registered <= debug_address;
      debug_data <= registers[debug_address_registered];
    end
  end
endmodule

`default_nettype wire
