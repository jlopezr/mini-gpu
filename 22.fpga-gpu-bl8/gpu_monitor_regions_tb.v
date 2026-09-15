`timescale 1ns/1ps
// Comprueba la LISTA BLANCA de direcciones de monitor.v (`block_range_valid`).
//
// Por que existe este banco
// -------------------------
// monitor.v mantiene su propia tabla de ventanas validas, SEPARADA del mapa que
// implementa gpu_system_bl8. Todos los demas bancos atacan el puerto del host
// directamente, asi que se saltan esa tabla: ninguno la ejercitaba.
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

    monitor dut(.clk(clk),.reset(reset),
        .rx_data(rx_data),.rx_strobe(rx_strobe),
        .tx_data(tx_data),.tx_strobe(tx_strobe),.tx_ready(tx_ready),
        .mem_address(mem_address),.mem_write_data(mem_write_data),
        .mem_write_enable(mem_write_enable),.mem_read_enable(mem_read_enable),
        .mem_read_data(8'h5a),.mem_ready(mem_ready),.mem_error(1'b0),
        .cpu_run_request(),.cpu_halt_request(),.cpu_step_request(),
        .cpu_reset_request(),.cpu_halted(1'b1),.cpu_error(1'b0),
        .cpu_error_code(8'd0),.cpu_pc(32'd0),
        .cpu_debug_register_address(),.cpu_debug_register_data(32'd0),
        .last_command(),.busy());

    reg [7:0] first_response;
    integer responses;
    reg trace=0;
    always @(posedge clk) if(tx_strobe) begin
        if(responses==0) first_response<=tx_data;
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

    initial begin
        responses=0;
        repeat(20) @(negedge clk); reset=0;
        repeat(20) @(negedge clk);

        // Las cuatro ventanas del mapa. Tienen que coincidir una a una con
        // MONITOR_REGIONS de monitor.py: si se anade una alli y no aqui (o al
        // reves) el fallo aparece solo en placa.
        read_block(32'h0000_0000, 16'd4, 1, "SDRAM baja");
        read_block(32'h01ff_fffc, 16'd4, 1, "SDRAM alta, ultima palabra");
        read_block(32'h8000_0000, 16'd4, 1, "configuracion de warps");
        read_block(32'h8000_0100, 16'd4, 1, "depuracion");
        read_block(32'h8000_0200, 16'd4, 1, "VIDEO_CTRL");
        read_block(32'h8000_0214, 16'd4, 1, "SWAP_COUNT");
        read_block(32'h8000_0300, 16'd4, 1, "CYCLES");
        read_block(32'h8000_031c, 16'd4, 1, "LANE_OPS");

        // Y los bordes: una ventana que acepta de mas es tan mala como una que
        // rechaza de menos, porque el acceso acaba en un decodificador que no
        // sabe que contestar.
        read_block(32'h0200_0000, 16'd4, 0, "por encima de la SDRAM");
        read_block(32'h8000_0218, 16'd4, 0, "justo despues del bloque de video");
        read_block(32'h8000_0320, 16'd4, 0, "justo despues de los contadores");
        read_block(32'h8000_0280, 16'd4, 0, "hueco entre video y contadores");
        read_block(32'h8000_0210, 16'd16, 0, "bloque que desborda el video");

        $display("PASS lista blanca de monitor.v: 4 ventanas validas, 5 bordes rechazados");
        $finish;
    end
    initial begin #5000000; $fatal(1,"watchdog"); end
endmodule
