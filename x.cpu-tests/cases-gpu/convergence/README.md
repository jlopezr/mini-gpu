# Convergencia SIMT

Caso mínimo para estudiar `SSY`, una rama divergente y la reconvergencia. Las
lanes 0–3 ejecutan el camino `low`, las lanes 4–7 el camino fall-through; ambos
caminos se reúnen en `join`, incrementan su valor y escriben en `0x200`.

Desde `x.cpu-tests`:

```powershell
python run_gpu_tests.py cases-gpu/convergence/test.json --backend gpu-simulator --trace --trace-detail --trace-file convergence.log
```

El caso comprueba los ocho resultados de memoria, el valor final de `R1` y `R3`
de cada lane, la máscara vacía y las 15 instrucciones de warp completadas. El
`--trace-detail` permite ver que el scheduler ejecuta ambos caminos antes de
continuar por `join`.
