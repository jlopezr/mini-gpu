# TODO

- que mejoras podemos hacer al controlador de SDRAM? Que supuestamente hacia el de 7-fpga-ram de claude, que no funciona?

- Así que no añadiría SHLI solo por esto. SHL/SHR/SAR son suficientes por ahora.
Eso sí, los inmediatos en operaciones como shifts, AND, OR, etc. es algo que podemos revisar globalmente en tu ISA, porque ahí sí puede haber oportunidades de ahorrar bastantes instrucciones.

Ampliar los ejemplos y pruebas. Suma de vectores con máscara parcial, warps con PC distintos, copia de memoria y un fallo en un hilo concreto. Comprobar tanto resultados como orden de ejecución.

Completar el diagnóstico de errores. Permitir que el runner verifique el PC, warp, hilo y dirección del fallo, además del código. Probar que los demás warps dejan de avanzar.

Añadir ejecución paso a paso. Poder avanzar una instrucción de warp, inspeccionar registros/memoria y detenerse en un PC o warp concreto. Aprovechar la traza actual.

Implementar divergencia y reconvergencia. Es el siguiente salto arquitectónico: permitir que un BEQ tome caminos distintos según el hilo. Requiere definir cómo guardar las máscaras y los caminos pendientes.

Separar máscara activa de hilos terminados. Con divergencia, un hilo que no participa en el camino actual puede tener trabajo pendiente. HALT debe retirarlo definitivamente.

Introducir barreras y espera de warps. Primero definir el alcance —dentro del warp o entre warps— y después añadir estados de espera y detección de bloqueos. Esto necesitará decisiones de ISA.

Probar otras políticas de scheduling. Mantener round-robin como referencia y permitir políticas reproducibles para detectar programas que dependen accidentalmente del orden de ejecución.

Añadir snapshots de ejecución. Guardar y restaurar memoria, PC, registros, máscaras y estado del scheduler. Sería una extensión del archivo de lanzamiento, con un propósito distinto