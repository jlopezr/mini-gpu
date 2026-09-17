`timescale 1ns/1ps
// Comprueba la LISTA BLANCA de direcciones de monitor.v (`block_range_valid`).
//
// Por que existe este banco
// -------------------------
// El monitor filtra por su propia tabla de ventanas validas, SEPARADA del mapa
// que implementa gpu_system_bl8. Todos los demas bancos atacan el puerto del
// host directamente, asi que se saltan esa tabla: ninguno la ejercitaba.
//
// Desde que monitor.v es copia identica en 12, 14, 17 y 22, la tabla llega por
// parametro: los de aqui abajo tienen que ser los mismos que pone top_bl8.v.
//
// El agujero se cobro una pieza. Al anadir los registros de video (0x200) y los
// contadores (0x300) se actualizo el mapa del sistema y la lista del cliente en
// monitor.py, pero no esta. En simulacion todo pasaba; en placa el monitor
// contestaba NACK antes de que la direccion llegara al decodificador, y el
// sintoma -- un comando rechazado -- se parece mucho mas a un bitstream viejo
// que a lo que era.
//
// Aqui el DUT es `monitor` SOLA, con una memoria falsa que siempre acepta: si
// algo rechaza, solo puede haber sido la lista blanca.
module gpu_monitor_regions_tb;
    reg clk=0; always #20 clk=~clk;
    reg reset=1;

    reg [7:0] rx_data=0;
    reg rx_strobe=0;
    wire [7:0] tx_data;
    wire tx_strobe;

    wire [31:0] mem_address;
    wire [7:0] mem_write_data;
    wire mem_write_enable, mem_read_enable;

    // Memoria falsa: contesta al ciclo siguiente, siempre bien y siempre 0x5a.
    // El contenido da igual; lo que se mira es si el comando llega a pedirlo.
    reg mem_ready=0;
    always @(posedge clk) mem_ready<=(mem_read_enable||mem_write_enable) && !mem_ready;

    // UART falsa. `tx_ready` NO puede quedarse fijo a 1: el monitor espera en
    // STATE_WAIT_TX_ACCEPT a verlo BAJAR, que es como sabe que la UART se ha
    // quedado con el byte. Con la senal clavada se emite la cabecera y ahi se
    // queda para siempre.
    reg [3:0] tx_busy=0;
    wire tx_ready=(tx_busy==0);
    always @(posedge clk)
        if(tx_strobe) tx_busy<=4'd8;
        else if(tx_busy!=0) tx_busy<=tx_busy-1'b1;

    // Mismos parametros que top_bl8: este banco comprueba justo la lista blanca.
    monitor #(.VERSION_MAJOR(8'd1),.VERSION_MINOR(8'd22),
        .RAM_END(33'h0_0200_0000),
        .WINDOW0_BASE(33'h0_8000_0000),.WINDOW0_END(33'h0_8000_001c),
        .WINDOW1_BASE(33'h0_8000_0100),.WINDOW1_END(33'h0_8000_0118),
        .WINDOW2_BASE(33'h0_8000_0300),.WINDOW2_END(33'h0_8000_0320),
        .WINDOW3_BASE(33'h0_8000_1000),.WINDOW3_END(33'h0_8000_1080),
        .WINDOW4_BASE(33'h0_8000_0f00),.WINDOW4_END(33'h0_8000_0f10))
      dut(.clk(clk),.reset(reset),
        .rx_data(rx_data),.rx_strobe(rx_strobe),
        .tx_data(tx_data),.tx_strobe(tx_strobe),.tx_ready(tx_ready),
        .mem_address(mem_address),.mem_write_data(mem_write_data),
        .mem_write_enable(mem_write_enable),.mem_read_enable(mem_read_enable),
        // La palabra es ASIMETRICA a proposito: asi el banco comprueba tambien
        // que READ_WORD la manda en little-endian y no al reves.
        .mem_read_data(8'h5a),.mem_read_word(32'hdead_beef),
        .mem_ready(mem_ready),.mem_error(1'b0),
        .cpu_run_request(),.cpu_halt_request(),.cpu_step_request(),
        .cpu_reset_request(),.cpu_halted(1'b1),.cpu_error(1'b0),
        .cpu_error_code(8'd0),.cpu_pc(32'd0),
        .cpu_debug_register_address(),.cpu_debug_register_data(32'd0),
        .last_command(),.busy());

    reg [7:0] first_response;
    reg [7:0] respuesta[0:7];
    integer responses;
    reg trace=0;
    always @(posedge clk) if(tx_strobe) begin
        if(responses==0) first_response<=tx_data;
        if(responses<8) respuesta[responses]<=tx_data;
        responses<=responses+1;
        if(trace) $display("  [%0t] tx %h (state=%0d)",$time,tx_data,dut.state);
    end

    task send;
        input [7:0] value;
        begin
            @(negedge clk); rx_data=value; rx_strobe=1;
            @(negedge clk); rx_strobe=0;
            repeat(4) @(negedge clk);
        end
    endtask

    // Lanza READ_BLOCK sobre [address, address+length) y espera `accept`.
    task read_block;
        input [31:0] address;
        input [15:0] length;
        input accept;
        input [255:0] name;
        begin
            responses=0; first_response=8'h00;
            send(8'h21);
            send(address[31:24]); send(address[23:16]);
            send(address[15:8]);  send(address[7:0]);
            send(length[15:8]);   send(length[7:0]);
            repeat(4000) @(negedge clk);
            if(responses==0) $fatal(1,"%0s: el monitor no contesto nada",name);
            if(accept && first_response!==8'ha1)
                $fatal(1,"%0s: rechazada (%h), y es una ventana valida",name,first_response);
            if(!accept && first_response!==8'hff)
                $fatal(1,"%0s: aceptada (%h), y esta fuera del mapa",name,first_response);
        end
    endtask

    // READ_WORD sobre `address`. Si `accept`, comprueba la cabecera 92, que
    // llegan CINCO bytes y que la palabra viene en little-endian.
    task read_word;
        input [31:0] address;
        input accept;
        input [255:0] name;
        begin
            responses=0; first_response=8'h00;
            send(8'h12);
            send(address[31:24]); send(address[23:16]);
            send(address[15:8]);  send(address[7:0]);
            repeat(4000) @(negedge clk);
            if(responses==0) $fatal(1,"%0s: el monitor no contesto nada",name);
            if(!accept) begin
                if(first_response!==8'hff)
                    $fatal(1,"%0s: aceptada (%h), y no esta alineada",name,first_response);
            end else begin
                if(first_response!==8'h92)
                    $fatal(1,"%0s: rechazada (%h), y esta alineada",name,first_response);
                if(responses!==5)
                    $fatal(1,"%0s: %0d bytes de respuesta, esperaba 5",name,responses);
                if(respuesta[1]!==8'hef || respuesta[2]!==8'hbe ||
                   respuesta[3]!==8'had || respuesta[4]!==8'hde)
                    $fatal(1,"%0s: la palabra salio %h %h %h %h, esperaba ef be ad de",
                           name,respuesta[1],respuesta[2],respuesta[3],respuesta[4]);
            end
        end
    endtask

    initial begin
        responses=0;
        repeat(20) @(negedge clk); reset=0;
        repeat(20) @(negedge clk);

        // Las cuatro ventanas del mapa. Tienen que coincidir una a una con
        // MONITOR_REGIONS de monitor.py: si se anade una alli y no aqui (o al
        // reves) el fallo aparece solo en placa.
        read_block(32'h0000_0000, 16'd4, 1, "SDRAM baja");
        read_block(32'h01ff_fffc, 16'd4, 1, "SDRAM alta, ultima palabra");
        read_block(32'h8000_0000, 16'd4, 1, "FB_FRONT");
        read_block(32'h8000_0018, 16'd4, 1, "VIDEO_CTRL");
        // El bloque de video ENTERO de una vez. Con 4 bytes no basta: el hueco
        // de HALT_AT (+0x14) queda en medio, y si fallara en vez de leer cero
        // este bloque daria NACK justo ahi.
        read_block(32'h8000_0000, 16'd28, 1, "bloque de video completo");
        read_block(32'h8000_0100, 16'd4, 1, "depuracion");
        read_block(32'h8000_0300, 16'd4, 1, "CYCLES");
        read_block(32'h8000_031c, 16'd4, 1, "LANE_OPS");
        read_block(32'h8000_1000, 16'd4, 1, "configuracion de warps");
        read_block(32'h8000_107c, 16'd4, 1, "ultimo descriptor de warp");
        read_block(32'h8000_0f00, 16'd16, 1, "bloque de identificacion entero");

        // Y los bordes: una ventana que acepta de mas es tan mala como una que
        // rechaza de menos, porque el acceso acaba en un decodificador que no
        // sabe que contestar.
        read_block(32'h0200_0000, 16'd4, 0, "por encima de la SDRAM");
        read_block(32'h8000_001c, 16'd4, 0, "justo despues del bloque de video");
        read_block(32'h8000_0320, 16'd4, 0, "justo despues de los contadores");
        read_block(32'h8000_0280, 16'd4, 0, "hueco donde estaba el video antes");
        read_block(32'h8000_0014, 16'd16, 0, "bloque que desborda el video");
        // La primera pagina ya no tiene los warps, y la segunda solo los tiene
        // a ellos: pedir el resto de la pagina GPU tiene que fallar.
        read_block(32'h8000_1080, 16'd4, 0, "justo despues de los warps");
        read_block(32'h8000_0f10, 16'd4, 0, "justo despues de la identificacion");

        // READ_WORD: cinco bytes de respuesta (92 + la palabra en little-endian)
        // en UNA transaccion de bus, que es lo que la hace atomica. La memoria de
        // este banco devuelve siempre 5a5a5a5a.
        read_word(32'h8000_000c, 1, "VIDEO_STATUS alineado");
        read_word(32'h8000_0300, 1, "CYCLES alineado");
        // Y exige alineamiento: la memoria entrega la palabra que CONTIENE la
        // direccion, asi que una no alineada devolveria otra palabra distinta de
        // la pedida. Mejor rechazarla que mentir.
        read_word(32'h8000_000e, 0, "VIDEO_STATUS desalineado");
        read_word(32'h8000_0001, 0, "FB_FRONT desalineado");

        $display("PASS lista blanca del monitor (por parametro): 9 ventanas validas, 7 bordes rechazados");
        $display("PASS READ_WORD: 2 lecturas alineadas, 2 desalineadas rechazadas");
        $finish;
    end
    initial begin #5000000; $fatal(1,"watchdog"); end
endmodule
