# bench-rop

Mide en la placa 38 los ciclos de pared de CPU frente a ROP para FILL, COPY y
un SPAN Z16/Color16 con prueba `LT`. La preparación y comprobación quedan fuera
de la ventana de medida; ROP se mide hasta `ROPWAIT.INV`.

```sh
run-board --prototype 38 --program bench_rop.asm
python bench_rop_report.py
```

El simulador funcional sirve para comprobar los resultados, pero `bench.inc`
devuelve cero sin `BOARD`: los ciclos solo tienen valor en la placa.
