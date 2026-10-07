`default_nettype none

/*
 * Dos clientes para un solo camino de MMIO.
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
 *
 * ---------------------------------------------------------------------
 * BUS SEGMENTADO: EXTRA_CYCLES
 * ---------------------------------------------------------------------
 *
 * Con el decodificador combinacional, la direccion registrada aqui pasaba por
 * los comparadores de rango, el error y el filtro de `select` hasta el
 * `write enable` de un registro, todo en un ciclo; y la lectura, desde la RAM de
 * la consola hasta el registro del cliente. Eran los caminos criticos de la 30.
 *
 * `mmio_decoder` ahora registra dos veces (ver su cabecera), y este modulo
 * espera esos ciclos antes de confirmar. Los dos clientes son de nivel --piden
 * hasta ver `ack`-- y solo muestrean `read_data` y `error` EN el ciclo del
 * `ack`, asi que la latencia extra no les cambia nada mas que el tiempo.
 *
 * Cuenta ciclos desde el ciclo de `select`:
 *
 *   ciclo 0  select alto (un pulso); el decodificador registra la decodificacion
 *   ciclo 1  el decodificador pone `select` a los dispositivos; escriben
 *   ciclo 2  se muestrean `read_data` y `error`, con la escritura ya hecha
 *   ciclo 3  ack; `read_data` y `error` salen de registros
 *
 * EXTRA_CYCLES = 2 es lo que necesita `mmio_decoder`; con 0 el `ack` llega un
 * ciclo despues del `select`, como antes. Solo lo usan los bancos que montan
 * este modulo SIN decodificador.
 */
module mmio_mux #(
    // La direccion va entera desde los clientes hasta el decodificador. El bus
    // se declara UNA vez, aqui, y todo lo demas lo hereda: en v2 los bloques
    // estan a megabytes unos de otros y un ancho copiado a mano en cada sitio
    // es como la 18 mando los dieciseis dispositivos al de video.
    parameter ADDR_BITS = 32,
    // Ciclos que se espera, tras el de `select`, antes del `ack`. Tiene que
    // coincidir con la latencia de `mmio_decoder` (2); un banco sin
    // decodificador pone 0.
    parameter EXTRA_CYCLES = 2
) (
    input  wire        clk,
    input  wire        reset,

    // Cliente A: el monitor. Tiene preferencia.
    input  wire        a_req,
    output reg         a_ack,
    input  wire        a_write,
    input  wire [3:0]  a_write_mask,
    input  wire [ADDR_BITS-1:0] a_address,
    input  wire [31:0] a_write_data,

    // Cliente B: la CPU.
    input  wire        b_req,
    output reg         b_ack,
    input  wire        b_write,
    input  wire [3:0]  b_write_mask,
    input  wire [ADDR_BITS-1:0] b_address,
    input  wire [31:0] b_write_data,

    // Dispositivo LENTO (la GPU, en otro reloj). `slow_start` es el `select`
    // que el decodificador le manda; `slow_done` es su confirmacion. Si el
    // decodificador rechaza el acceso --direccion mala, mascara parcial-- no hay
    // `slow_start` y el acceso termina como cualquier otro, con su error.
    input  wire        slow_start,
    input  wire        slow_done,

    // Hacia video_registers.
    output reg         select,
    output reg         write,
    output reg  [3:0]  write_mask,
    output reg  [ADDR_BITS-1:0] address,
    output reg  [31:0] write_data
);
  // `select` dura exactamente un ciclo, que es lo que espera video_registers:
  // la escritura ocurre en el flanco que lo cierra.
  reg busy;
  // A quien se le concedio. Mirar `a_req` otra vez al confirmar no vale: si se
  // concedio a B y A pide en ese mismo ciclo, se confirmaria al que no era.
  reg granted_a;
  // Ciclos esperados desde el de `select`, hasta EXTRA_CYCLES.
  reg [1:0] waited;
  // Acceso a un dispositivo lento: el decodificador ya se lo paso (`slow_start`
  // se vio durante la espera) y falta la confirmacion (`slow_ok`). Cuando llega
  // se vuelve a esperar EXTRA_CYCLES, para que `read_data` y `error` del
  // decodificador recojan el valor definitivo.
  reg slow_started, slow_ok;

  always @(posedge clk) begin
    a_ack <= 1'b0;
    b_ack <= 1'b0;
    select <= 1'b0;
    if (slow_start) slow_started <= 1'b1;

    // Mantener direccion Y tipo de acceso hasta que el cliente consume ack.
    // Si write bajase con select, un STORE a solo lectura perderia su error
    // combinacional un ciclo antes de que lo muestree el adaptador.
    if (reset) begin
      write <= 1'b0;
      busy <= 1'b0;
      granted_a <= 1'b0;
      waited <= 2'd0;
      slow_started <= 1'b0;
      slow_ok <= 1'b0;
      write_mask <= 4'b0000;
      address <= {ADDR_BITS{1'b0}};
      write_data <= 32'h0000_0000;
    end else if (!busy) begin
      /*
       * `&& !a_ack` / `&& !b_ack` NO es defensa por si acaso: sin eso, cada
       * acceso se ejecutaba DOS VECES.
       *
       * El contrato con el cliente es de nivel: mantiene `req` hasta ver su
       * `ack`. El `ack` se levanta al final del ciclo de concesion, o sea que
       * el cliente lo ve un ciclo despues y baja `req` al siguiente. En ese
       * ciclo intermedio `busy` ya ha vuelto a cero y `req` sigue alto, asi que
       * el arbitro concedia otra vez la misma peticion.
       *
       * Estuvo asi desde que existe este modulo y no lo noto nadie, porque
       * todos los registros de video son IDEMPOTENTES: escribir FB_BACK dos
       * veces deja lo mismo, y pedir SWAP dos veces es un solo intercambio
       * pendiente. El primer registro con efecto secundario --DATA del puerto
       * serie, que saca un byte de la cola al leerlo-- lo enseno a la primera:
       * un LOAD se comia dos caracteres y un STORE mandaba el byte dos veces.
       *
       * Lo caza `cpu_serial_tb.v`.
       */
      if (a_req && !a_ack) begin
        select <= 1'b1;
        write <= a_write;
        write_mask <= a_write_mask;
        address <= a_address;
        write_data <= a_write_data;
        granted_a <= 1'b1;
        busy <= 1'b1;
      end else if (b_req && !b_ack) begin
        select <= 1'b1;
        write <= b_write;
        write_mask <= b_write_mask;
        address <= b_address;
        write_data <= b_write_data;
        granted_a <= 1'b0;
        busy <= 1'b1;
      end
    end else if (waited != EXTRA_CYCLES) begin
      // `address`, `write` y `write_data` se RETIENEN mientras dura la espera:
      // el decodificador los sigue leyendo en los ciclos que registra.
      waited <= waited + 2'd1;
    end else if ((slow_started || slow_start) && !slow_ok) begin
      // Dispositivo lento: se espera su confirmacion con todo retenido.
      if (slow_done) begin
        slow_ok <= 1'b1;
        waited <= 2'd0;
      end
    end else begin
      // Ya esta la lectura y el error en registros: se confirma al cliente que
      // corresponda.
      waited <= 2'd0;
      busy <= 1'b0;
      slow_started <= 1'b0;
      slow_ok <= 1'b0;
      if (granted_a) a_ack <= 1'b1;
      else b_ack <= 1'b1;
    end
  end
endmodule

`default_nettype wire
