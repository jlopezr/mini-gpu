`default_nettype none

/*
 * Sincronizador de reset: aserción ASINCRONA, liberacion SINCRONA.
 *
 *   arst : reset asincrono de entrada, activo en alto (por ejemplo
 *          `!pll_locked || !boton`). Puede cambiar en cualquier momento.
 *   rst  : reset ya alineado con `clk`, activo en alto. Sube en cuanto sube
 *          `arst` (sin esperar al reloj, asi que funciona aunque el reloj este
 *          parado o inestable) y baja STAGES flancos de `clk` despues de que
 *          `arst` haya bajado, siempre alineado con un flanco.
 *
 * La metastabilidad solo puede aparecer en la primera etapa. Las siguientes le
 * dan un ciclo entero cada una para resolverse; STAGES >= 2.
 *
 * Sobre la implementacion en Diamond/Synplify: `syn_preserve` pide que no se
 * fusionen ni se eliminen estos registros, pero un atributo no garantiza el
 * resultado fisico (ya vimos que `keep` no impidio fusionar copias del reset).
 * Hay que comprobar en el EDIF / el informe de PAR que las etapas salen como
 * flops con clear ASINCRONO y que cada dominio tiene su propia cadena.
 */
module reset_sync #(
    parameter integer STAGES = 3
) (
    input  wire clk,
    input  wire arst,
    output wire rst
);
    (* syn_preserve = "true" *) reg [STAGES-1:0] q = {STAGES{1'b1}};

    always @(posedge clk or posedge arst) begin
        if (arst)
            q <= {STAGES{1'b1}};
        else
            q <= {q[STAGES-2:0], 1'b0};
    end

    assign rst = q[STAGES-1];
endmodule

`default_nettype wire
