`default_nettype none

/*
 * Dos clientes para una sola ventana de registros de video.
 *
 * En la 16 esto no existia: `sdram_system_adapter` arbitraba monitor, CPU y
 * video en una sola maquina de estados, asi que los accesos MMIO ya salian
 * serializados por construccion. Al repartir los clientes en puertos
 * independientes del arbitro de memoria, la CPU y el monitor pueden pedir un
 * registro el mismo ciclo, y `video_registers` tiene un solo puerto.
 *
 * Un acceso MMIO se resuelve en un ciclo —la lectura es combinacional y la
 * escritura ocurre en el flanco que cierra el ciclo de `select`—, asi que no
 * hace falta round-robin ni cola: basta con atender a uno y que el otro espere
 * un ciclo. El monitor va primero porque sus peticiones son raras y las de la
 * CPU son un bucle que puede esperar; ademas asi un `SWAP` escrito desde el PC
 * no se queda detras de un programa que dibuja a toda velocidad.
 *
 * El contrato con cada cliente es de nivel: mantiene `req` alto hasta ver su
 * `ack`, que dura un ciclo. `mmio_read_data` es valido en el mismo ciclo que
 * el `ack`, porque la lectura de `video_registers` es combinacional respecto a
 * `address`, que se registro un ciclo antes en el propio cliente.
 */
module mmio_mux (
    input  wire        clk,
    input  wire        reset,

    // Cliente A: el monitor. Tiene preferencia.
    input  wire        a_req,
    output reg         a_ack,
    input  wire        a_write,
    input  wire [3:0]  a_write_mask,
    input  wire [4:0]  a_address,
    input  wire [31:0] a_write_data,

    // Cliente B: la CPU.
    input  wire        b_req,
    output reg         b_ack,
    input  wire        b_write,
    input  wire [3:0]  b_write_mask,
    input  wire [4:0]  b_address,
    input  wire [31:0] b_write_data,

    // Hacia video_registers.
    output reg         select,
    output reg         write,
    output reg  [3:0]  write_mask,
    output reg  [4:0]  address,
    output reg  [31:0] write_data
);
  // `select` dura exactamente un ciclo, que es lo que espera video_registers:
  // la escritura ocurre en el flanco que lo cierra.
  reg busy;
  // A quien se le concedio. Mirar `a_req` otra vez al confirmar no vale: si se
  // concedio a B y A pide en ese mismo ciclo, se confirmaria al que no era.
  reg granted_a;

  always @(posedge clk) begin
    a_ack <= 1'b0;
    b_ack <= 1'b0;
    select <= 1'b0;
    write <= 1'b0;

    if (reset) begin
      busy <= 1'b0;
      granted_a <= 1'b0;
      write_mask <= 4'b0000;
      address <= 5'h00;
      write_data <= 32'h0000_0000;
    end else if (!busy) begin
      if (a_req) begin
        select <= 1'b1;
        write <= a_write;
        write_mask <= a_write_mask;
        address <= a_address;
        write_data <= a_write_data;
        granted_a <= 1'b1;
        busy <= 1'b1;
      end else if (b_req) begin
        select <= 1'b1;
        write <= b_write;
        write_mask <= b_write_mask;
        address <= b_address;
        write_data <= b_write_data;
        granted_a <= 1'b0;
        busy <= 1'b1;
      end
    end else begin
      // El ciclo siguiente `select` ya esta alto y la lectura es valida, asi
      // que se confirma al cliente que corresponda.
      busy <= 1'b0;
      if (granted_a) a_ack <= 1'b1;
      else b_ack <= 1'b1;
    end
  end
endmodule

`default_nettype wire
