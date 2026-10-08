# Salto indirecto con destinos distintos por lane

`JALR` y `JR` sacan el destino de un registro. Si las lanes activas de un warp lo
tienen distinto, no hay un destino que apilar en la pila de divergencia, y la GPU
para con `ERROR_SIMT` (0x06) en lugar de serializar en silencio. Un warp
convergente (o con lanes enmascaradas que coinciden) funciona, y eso lo cubre
[`cases-shared/calls/call-return`](../../../cases-shared/calls/call-return/).

La CPU no tiene este caso: no hay lanes que puedan discrepar.
