// Identidad del prototipo (MMIO v2 §5). GENERADO por `tools/generate-sysid`
// desde el RTL de esta carpeta. §5.4 lo pide asi: «no se escribe a mano en
// cada `top.v` [...]. Un bitmap escrito a mano seria una tercera gemela junto
// a las ventanas del decodificador y la lista del cliente Python».
`include "sysid_params.vh"
`default_nettype none

module top (
    input clk_25mhz,
    output [7:0] led,
    output wifi_gpio0,
    input ftdi_txd,
    output ftdi_rxd
);

  // 100 MHz / 100 = 1 Mbaud exacto, el mismo que 16, 18, 19 y 21, que tambien
  // corren a 100 u 80. Con el reloj a 120 eran 40 y 3 Mbaud; a 100 no hay
  // divisor que de 3 Mbaud (33,33) y `uart.v` ademas exige multiplo de 4
  // --sobremuestrea a x4--, lo que descarta 50. Y 2,5 Mbaud tampoco vale: el
  // FTDI solo sabe 3 MHz / n con n entero o n,5 a partir de 2, y 1,2 no es de
  // los suyos. `monitor.py` lleva el mismo numero.
  localparam UART_DIVISOR = 100;

  assign wifi_gpio0 = 1'b1;

  // Clock and reset
  wire clk;
  wire locked;
  wire reset;

  assign reset = ~locked;

  pll_100 pll_100_i (
      .clkin  (clk_25mhz),
      .clkout0(clk),
      .locked (locked)
  );

  // UART interface: 100 MHz / 100 = 1 Mbaud
  wire [7:0] uart_rx_data;
  wire uart_rx_strobe;
  wire [7:0] uart_tx_data;
  wire uart_tx_strobe;
  wire uart_tx_ready;

  uart #(
      .DIVISOR(UART_DIVISOR)
  ) uart_i (
      .clk(clk),
      .reset(reset),
      .serial_txd(ftdi_rxd),
      .serial_rxd(ftdi_txd),
      .rxd(uart_rx_data),
      .rxd_strobe(uart_rx_strobe),
      .txd(uart_tx_data),
      .txd_strobe(uart_tx_strobe),
      .txd_ready(uart_tx_ready)
  );

  // Command monitor
  wire [7:0] last_command;
  wire monitor_busy;
  wire [31:0] mem_address;
  wire [7:0] mem_write_data;
  wire [31:0] mem_write_word;  // la palabra entera, para WRITE_WORD
  wire mem_write_word_enable;
  wire mem_write_enable;
  wire mem_read_enable;
  wire [7:0] mem_read_data;
  wire [31:0] mem_read_word;   // la misma lectura sin trocear
  wire mem_ready;
  wire mem_error;

  // ---------------------------------------------------------------------
  // Bloque SYSTEM (MMIO v2, 1.isa/mmio.md seccion 5)
  // ---------------------------------------------------------------------
  //
  // Esta carpeta NO tiene MMIO, y no lo gana aqui. `sysid` cuelga del camino
  // del MONITOR y nada mas: la CPU no lo ve, no hay decodificador, no hay
  // pagina de dispositivos y un programa no puede leerlo. La leccion de esta
  // carpeta --memoria plana, sin perifericos-- se queda como estaba.
  //
  // Lo unico que cambia al pasar a MMIO v2 es DONDE y CUANTO: el bloque de
  // identificacion se mueve de 0x80000F00, donde eran cuatro palabras, a
  // 0x80000000, donde son siete. No se anade ningun dispositivo.
  //
  // Existe porque la version de monitor dejo de servir para identificar la
  // placa. Al renumerarla por JUEGO DE COMANDOS, la 6 y la 10 contestan lo
  // mismo, asi que sin esto `--version ebr` daria por buena una 10 flasheada y
  // se mediria el hardware equivocado, que es exactamente el fallo que este
  // bloque existe para cerrar. Ver docs/resumen-prototipos.md.
  //
  // POR QUE LA SELECCION LLEVA DOS COMPARACIONES. Siete palabras no son una
  // potencia de dos, asi que `[31:5]` --que es lo que cuesta un solo
  // comparador-- cubriria OCHO y la palabra 7 (+0x1C) contestaria el `default`
  // del modulo, o sea un cero, en vez de dar error. La seccion 5 lo prohibe
  // expresamente: el resto del bloque da error, no devuelve cero ni repite las
  // palabras por alias. La segunda comparacion la excluye, y con eso +0x1C cae
  // en `memory_map` y recibe error de direccion, igual que el resto del slot.
  // Es el mismo criterio que `mmio_decoder.v` aplica con `offset[7:2] > 6'd6`
  // en las carpetas que si tienen decodificador.
  wire sysid_selected = (mem_address[31:5] == 27'h400_0000) &&
                        (mem_address[4:2] != 3'd7);
  wire [31:0] sysid_word;
  sysid #(
      .FOLDER(`SYSID_FOLDER),
      // bit 0 MUL, bit 1 DIV. Esta CPU los tiene; no tiene sub-palabra ni SIMT.
      .ISA_PROFILE(`SYSID_ISA_PROFILE),
      // Seccion 5.4: bit 0 SYSTEM, bit 3 EBR, bit 9 CPU. Ni SDRAM, ni video,
      // ni serie, ni fabric.
      //
      // AQUI DECIA que el bit 9 no iba «porque es del bloque CPU PERFORMANCE
      // de 0x81010000, que aqui no existe». Esa lectura --un bit por bloque
      // MMIO-- no es la de §5.4, que dice «bitmap de dispositivos PRESENTES» y
      // reserva un bit para EBR, que no es ningun bloque. Con la lectura vieja
      // el bit seria cero en las diez carpetas, porque ni CPU CORE ni GPU CORE
      // estan implementados, y el bitmap no distinguiria una CPU de una GPU.
      // La 6 y la 10 eran las dos unicas que la seguian; las otras ocho ya
      // declaraban su nucleo.
      .DEVICES(`SYSID_DEVICES),
      // 32 KiB de EBR como region contigua (seccion 3.1 y decision 41).
      .MEM_BASE(`SYSID_MEM_BASE), .MEM_SIZE(`SYSID_MEM_SIZE),
      // (mayor << 8) | menor, con los MISMOS numeros que el `monitor #(...)`
      // de mas abajo. No se deduce de nada: copiar el de otra carpeta es un
      // numero valido que hace declarar un juego de comandos que esta carpeta
      // no implementa, y no lo dice ningun test.
      .MONITOR_VERSION(`SYSID_MONITOR_VERSION)   // 3.6, el mismo que monitor_i
  ) sysid_i (
      .word(mem_address[4:2]),
      .read_data(sysid_word)
  );

  // La respuesta se registra igual que la de la memoria, para que el monitor
  // vea el mismo protocolo venga de donde venga: pide, y un ciclo despues hay
  // `ready`. Las escrituras fallan; el resto del slot va a memory_map y
  // recibe error de direccion, sin alias de las cuatro palabras.
  reg sysid_ready;
  reg sysid_error;
  reg [7:0] sysid_byte;
  always @(posedge clk) begin
    if (reset) begin
      sysid_ready <= 1'b0;
      sysid_error <= 1'b0;
      sysid_byte <= 8'h00;
    end else begin
      sysid_ready <= sysid_selected && (mem_read_enable || mem_write_enable);
      sysid_error <= mem_write_enable;
      sysid_byte <= sysid_word[8*mem_address[1:0] +: 8];
    end
  end

  wire [7:0] map_read_data;
  wire [31:0] map_read_word;
  wire map_ready, map_error;
  assign mem_read_data = sysid_ready ? sysid_byte : map_read_data;
  assign mem_read_word = sysid_ready ? sysid_word : map_read_word;
  assign mem_ready = sysid_ready || map_ready;
  assign mem_error = sysid_ready ? sysid_error : map_error;

  wire cpu_run_request;
  wire cpu_halt_request;
  wire cpu_step_request;
  wire cpu_reset_request;
  wire cpu_halted;
  wire cpu_error;
  wire [7:0] cpu_error_code;
  wire cpu_instruction_retired;
  wire [4:0] cpu_debug_register_address;
  wire [31:0] cpu_debug_register_data;
  wire [31:0] cpu_pc;

  wire cpu_imem_valid;
  wire [31:0] cpu_imem_address;
  wire [31:0] cpu_imem_read_data;
  wire cpu_imem_ready;

  wire cpu_dmem_valid;
  wire [31:0] cpu_dmem_address;
  wire [31:0] cpu_dmem_write_data;
  wire [3:0] cpu_dmem_write_enable;
  wire [31:0] cpu_dmem_read_data;
  wire cpu_dmem_ready;
  wire cpu_dmem_error;

  // La version: MAYOR = juego de comandos (1 = base, 13 comandos), MENOR =
  // numero de carpeta. Ver docs/unificacion-mmio.md fase 5.
  //
  // BACKPORT DE R0 CABLEADO A CERO. `R0` paso a valer siempre cero y a
  // descartar las escrituras, que es un cambio INCOMPATIBLE con lo que hacia
  // esta carpeta antes: un programa que use `R0` como registro general no para
  // con error, da otro resultado en silencio. Ver 1.isa/isa.md seccion 1.
  //
  // La unica ventana es la del bloque SYSTEM. Esta carpeta no tiene MMIO de
  // verdad --ni video, ni serie, ni contadores-- pero si identificacion, y sin
  // declararla aqui un READ_BLOCK sobre 0x80000000 se rechazaria antes de
  // llegar a `sysid`. Gemela de MONITOR_REGIONS en monitor.py.
  //
  // La ventana es el BLOQUE ENTERO de 64 KiB, no las siete palabras que hay
  // hoy, por la razon que las carpetas con decodificador ya dejaron escrita:
  // un subconjunto seria una tercera gemela que mantener, y ya se quedo atras
  // una vez. Quien rechaza un offset sin registro es el que lo sabe --aqui, la
  // seleccion de `sysid_selected` y `memory_map`--, no la lista del host.
  monitor #(.VERSION_MAJOR(8'd3),.VERSION_MINOR(8'd6),
      .RAM_END(33'h0_0000_8000),
      .WINDOW0_BASE(33'h0_8000_0000),.WINDOW0_END(33'h0_8001_0000))  // SYSTEM
    monitor_i (
      .clk(clk),
      .reset(reset),
      .rx_data(uart_rx_data),
      .rx_strobe(uart_rx_strobe),
      .tx_data(uart_tx_data),
      .tx_strobe(uart_tx_strobe),
      .tx_ready(uart_tx_ready),
      .mem_address(mem_address),
      .mem_write_data(mem_write_data),
      .mem_write_enable(mem_write_enable),
      .mem_write_word(mem_write_word),
      .mem_write_word_enable(mem_write_word_enable),
      .mem_read_enable(mem_read_enable),
      .mem_read_data(mem_read_data), .mem_read_word(mem_read_word),
      .mem_ready(mem_ready),
      .mem_error(mem_error),
      .cpu_run_request(cpu_run_request),
      .cpu_halt_request(cpu_halt_request),
      .cpu_step_request(cpu_step_request),
      .cpu_reset_request(cpu_reset_request),
      .cpu_halted(cpu_halted),
      .cpu_error(cpu_error),
      .cpu_error_code(cpu_error_code),
      .cpu_pc(cpu_pc),
      .cpu_debug_register_address(cpu_debug_register_address),
      .cpu_debug_register_data(cpu_debug_register_data),
      // Sin puerto serie: HAS_SERIAL = 0 y las entradas a cero. Las
      // salidas se quedan al aire y la sintesis se las lleva.
      .serial_rx_free(8'd0), .serial_tx_data(8'd0),
      .serial_tx_count(8'd0),
      .last_command(last_command),
      .busy(monitor_busy)
  );

  cpu cpu_i (
      .clk(clk),
      .reset(reset || cpu_reset_request),
      .run_request(cpu_run_request),
      .halt_request(cpu_halt_request),
      .step_request(cpu_step_request),
      .halted(cpu_halted),
      .error(cpu_error),
      .error_code(cpu_error_code),
      .instruction_retired(cpu_instruction_retired),
      .imem_valid(cpu_imem_valid),
      .imem_address(cpu_imem_address),
      .imem_read_data(cpu_imem_read_data),
      .imem_ready(cpu_imem_ready),
      .dmem_valid(cpu_dmem_valid),
      .dmem_address(cpu_dmem_address),
      .dmem_write_data(cpu_dmem_write_data),
      .dmem_write_enable(cpu_dmem_write_enable),
      .dmem_read_data(cpu_dmem_read_data),
      .dmem_ready(cpu_dmem_ready),
      .dmem_error(cpu_dmem_error),
      .debug_register_address(cpu_debug_register_address),
      .debug_register_data(cpu_debug_register_data),
      .debug_pc(cpu_pc)
  );

  // Unified global map: monitor when halted, CPU while running.
  memory_map memory_map_i (
      .clk(clk),
      .reset(reset),
      .address(mem_address),
      .write_data(mem_write_data),
      .write_word(mem_write_word),
      .write_word_enable(mem_write_word_enable && !sysid_selected),
      // El acceso al bloque SYSTEM no llega a la memoria: alli 0x80000000 esta
      // fuera del mapa y levantaria `error`. Eso es justamente lo que se quiere
      // para la palabra 7 y para el resto del slot, que `sysid_selected` deja
      // pasar a proposito.
      .write_enable(mem_write_enable && !sysid_selected),
      .read_enable(mem_read_enable && !sysid_selected),
      .read_data(map_read_data), .read_word(map_read_word),
      .ready(map_ready),
      .error(map_error),
      .cpu_halted(cpu_halted),
      .cpu_imem_valid(cpu_imem_valid),
      .cpu_imem_address(cpu_imem_address),
      .cpu_imem_read_data(cpu_imem_read_data),
      .cpu_imem_ready(cpu_imem_ready),
      .cpu_dmem_valid(cpu_dmem_valid),
      .cpu_dmem_address(cpu_dmem_address),
      .cpu_dmem_write_data(cpu_dmem_write_data),
      .cpu_dmem_write_enable(cpu_dmem_write_enable),
      .cpu_dmem_read_data(cpu_dmem_read_data),
      .cpu_dmem_ready(cpu_dmem_ready),
      .cpu_dmem_error(cpu_dmem_error)
  );

  // Display the last command. LED 7 lights while a response is pending.
  assign led = {monitor_busy, cpu_error, cpu_halted, last_command[4:0]};
endmodule

`default_nettype wire
