Te quedan 52.896 recursos combinacionales, 74.624 registros y 192 bloques EBR. Mi valoración es esta; salvo las cifras medidas del repositorio, son estimaciones que habría que confirmar sintetizando.
Ampliación	¿Cabe?	Qué condiciona su utilidad
Salida de vídeo por HDMI	Con mucho margen para el generador	Alimentarlo con píxeles continuamente
CPU de control	Muy probable, con margen	Arbitraje de memoria y comunicación CPU↔GPU
Un SM adicional, dos en total	Parece viable	Recursos del SM aislado, timing y SDRAM compartida
Dos SM adicionales, tres en total	No lo daría por hecho	Requeriría medir y probablemente optimizar
LSU más avanzada	Sí, si se mejora gradualmente	Complejidad del arbitraje y caminos combinacionales
Bursts en SDRAM	Muy probable	Rediseñar y verificar controlador y peticiones
Cachés pequeñas	Sí, hay bastante EBR libre	Política de escrituras y coherencia


La salida de vídeo cuesta poco; el framebuffer es la parte importante. He revisado los informes de 13.hdmi: sus ejemplos utilizan entre 353 y 653 recursos combinacionales, una PLL y ningún bloque EBR. Eso corresponde al generador DVI por el conector HDMI, con imágenes generadas por lógica.
Mostrar una imagen calculada por la GPU requiere además framebuffer, lectura de vídeo y buffers entre dominios de reloj. Puedes mantener la GPU a 25 MHz y usar relojes independientes para vídeo.
Aquí aparece un límite concreto: tu bus SDRAM de 16 bits a 25 MHz tiene un máximo teórico de 50 MB/s, antes de descontar comandos, refrescos y esperas. Un framebuffer de 1280×720, 60 imágenes/s y 16 bits/píxel requiere aproximadamente 110,6 MB/s solo para mostrarlo. Eso no sería viable desde esta SDRAM a 25 MHz, incluso con bursts. Una imagen de menor resolución, ampliada en pantalla y con buffers EBR, es mucho más abordable.
Una CPU de control parece una incorporación razonable. Como referencia, el sistema completo de 10.fpga-cpu-ram —CPU, monitor y controlador incluidos— está documentado con unos 4.976 recursos combinacionales y 2.249 registros. No es el coste incremental exacto, pero indica que una CPU sencilla probablemente cabría holgadamente. Podría configurar trabajos, lanzar la GPU y esperar su finalización mediante registros de control.
Un segundo SM parece posible, pero no empezaría por ahí. Duplicar todo el diseño actual daría aproximadamente un 74 % de ocupación combinacional; eso sirve como orientación, no como presupuesto exacto de dos SM. Parte del sistema se compartiría y habría que añadir arbitraje. Además, dos SM compitiendo por el controlador actual, que atiende accesos individuales, podrían pasar mucho tiempo esperando memoria.
LSU, bursts y caché son mejoras complementarias:
- Coalescencia en la LSU: agrupar direcciones consecutivas de las lanes y distribuir después los resultados.
- Bursts en SDRAM: transferir varias medias palabras consecutivas amortizando los comandos.
- Caché de instrucciones: evitar que cada fetch vuelva a SDRAM; un buen primer candidato para medir.
- Caché de datos: también cabe, pero exige resolver qué ocurre cuando CPU, GPU o vídeo comparten datos. Una memoria local explícita en EBR puede ser una alternativa más sencilla.
Mi orden sería medir esperas de memoria → bursts y coalescencia → caché de instrucciones, incorporando vídeo o CPU según lo que quieras demostrar. Después mediría si compensa el segundo SM.
Un objetivo de un SM + CPU sencilla + vídeo de baja resolución + bursts + cachés pequeñas parece razonable con estos recursos. Añadir además otro SM merece una síntesis de prueba antes de comprometer esa arquitectura.