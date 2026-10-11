# Llamadas y saltos indirectos, igual en CPU y GPU

Un solo hilo activo recorre `JAL` (llamada y retorno con `JR`), `JALR` con
desplazamiento, `JALR` con `Rd = Ra` (el destino se lee antes de escribir el
enlace) y `JR` con los dos bits bajos del destino sucios, que se descartan. Cada
resultado va a RAM y `expected.hex` fija los cuatro.

Lo que **no** cubre, por no existir en la CPU: un salto indirecto cuyo destino
difiere entre lanes de un warp. Eso es un error de la GPU (`ERROR_SIMT`, 0x06) y
lo prueba [`cases-gpu/calls/indirect-divergence`](../../../cases-gpu/calls/indirect-divergence/).
