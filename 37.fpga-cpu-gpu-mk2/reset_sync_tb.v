`timescale 1ns / 1ps
`default_nettype none

/*
 * Banco de reset_sync: comprueba que
 *   1. la aserción es asincrona (rst sube sin esperar al reloj, incluso con el
 *      reloj parado),
 *   2. la liberacion es exactamente STAGES flancos despues y alineada con el
 *      reloj, tanto si arst baja lejos del flanco como pegado a el,
 *   3. un pulso corto de arst entre flancos tambien deja rst activo,
 *   4. rst nunca baja antes de tiempo (sin glitches) mientras arst esta alto.
 */
module reset_sync_tb;
    localparam integer STAGES = 3;
    reg clk = 1'b0;
    reg clk_run = 1'b1;
    reg arst = 1'b1;
    wire rst;
    integer errors = 0;
    integer edges;

    reset_sync #(.STAGES(STAGES)) dut(.clk(clk), .arst(arst), .rst(rst));

    always #5 if (clk_run) clk = ~clk;

    task check(input cond, input [255:0] what);
        begin
            if (!cond) begin
                errors = errors + 1;
                $display("FALLO: %0s (t=%0t)", what, $time);
            end
        end
    endtask

    // Cuenta flancos de subida hasta que rst baja (maximo 20).
    task release_and_count(input integer offset_ns);
        begin
            edges = 0;
            #(offset_ns);
            arst = 1'b0;
            while (rst && edges < 20) begin
                @(posedge clk);
                #1;
                edges = edges + 1;
            end
        end
    endtask

    initial begin
        // Arranca con arst alto: rst debe estar alto desde el principio.
        #1 check(rst === 1'b1, "rst alto al arrancar");
        repeat (4) @(posedge clk);
        check(rst === 1'b1, "rst sigue alto mientras arst=1");

        // Liberacion lejos del flanco.
        @(negedge clk);
        release_and_count(1);
        check(edges == STAGES, "liberacion tras STAGES flancos (lejos)");
        check(rst === 1'b0, "rst bajo tras liberar");

        // Reasercion asincrona con el reloj corriendo, entre flancos.
        #2 arst = 1'b1;
        #0.1 check(rst === 1'b1, "aserción asincrona inmediata");

        // Liberacion pegada al flanco de subida.
        repeat (3) @(posedge clk);
        @(negedge clk);
        #4.9;
        release_and_count(0);
        check(edges >= STAGES && edges <= STAGES + 1,
              "liberacion tras STAGES(+1) flancos (pegada al flanco)");
        check(rst === 1'b0, "rst bajo tras liberar (pegada)");

        // Aserción con el reloj PARADO.
        clk_run = 1'b0;
        #20 arst = 1'b1;
        #1 check(rst === 1'b1, "aserción asincrona con el reloj parado");
        clk_run = 1'b1;
        repeat (3) @(posedge clk);

        // Pulso corto de arst, mas estrecho que un periodo, entre flancos.
        @(negedge clk);
        arst = 1'b0;
        repeat (STAGES + 2) @(posedge clk);
        check(rst === 1'b0, "rst bajo antes del pulso corto");
        @(negedge clk);
        #1 arst = 1'b1;
        #1 arst = 1'b0;
        #0.1 check(rst === 1'b1, "un pulso corto de arst deja rst alto");
        repeat (STAGES + 1) @(posedge clk);
        #1 check(rst === 1'b0, "rst vuelve a bajar tras el pulso corto");

        if (errors == 0)
            $display("PASS: reset_sync");
        else
            $display("FAIL: reset_sync (%0d errores)", errors);
        $finish;
    end
endmodule

`default_nettype wire
