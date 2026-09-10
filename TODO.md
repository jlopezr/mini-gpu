# TODO

- que mejoras podemos hacer al controlador de SDRAM? Que supuestamente hacia el de 7-fpga-ram de claude, que no funciona?

- Así que no añadiría SHLI solo por esto. SHL/SHR/SAR son suficientes por ahora.
Eso sí, los inmediatos en operaciones como shifts, AND, OR, etc. es algo que podemos revisar globalmente en tu ISA, porque ahí sí puede haber oportunidades de ahorrar bastantes instrucciones.

- STOREB, LOADB, LOADUB

---

Ampliar los ejemplos y pruebas. Suma de vectores con máscara parcial, warps con PC distintos, copia de memoria y un fallo en un hilo concreto. Comprobar tanto resultados como orden de ejecución.

Completar el diagnóstico de errores. Permitir que el runner verifique el PC, warp, hilo y dirección del fallo, además del código. Probar que los demás warps dejan de avanzar.

Añadir ejecución paso a paso. Poder avanzar una instrucción de warp, inspeccionar registros/memoria y detenerse en un PC o warp concreto. Aprovechar la traza actual.

Añadir snapshots de ejecución. Guardar y restaurar memoria, PC, registros, máscaras y estado del scheduler. Sería una extensión del archivo de lanzamiento, con un propósito distinto