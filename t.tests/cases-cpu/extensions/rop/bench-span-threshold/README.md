# Umbral de `ROPSPAN`

Mide en la placa 38 cuándo compensa reemplazar el bucle de fragmentos de
MiniGL 3D por `ROPSPAN`: RGB565/Z16, profundidad `LESS`, Z Q8 saturada y
escritura de Z y color. Cada punto procesa 64 scanlines; el ROP recibe un
`CONFIG` y spans compactos, por lo que incluye tanto el envío como el drenaje
de la FIFO.

```sh
tools/run-board --prototype 38 --program span_threshold.asm --yes
.venv/bin/python span_threshold_report.py
```

La preparación de Z y las comprobaciones quedan fuera de las ventanas de
tiempo. La curva mide el coste de un triángulo alto; no es todavía el tiempo de
un frame ni incluye la generación de cobertura del rasterizador.
