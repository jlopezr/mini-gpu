# Tests comunes de MiniCPU

Este directorio contiene casos que pueden ejecutarse sobre el simulador
funcional, la FPGA o ambos. Cada backend produce el mismo estado observable:
estado de parada, error, PC, registros solicitados y regiones de memoria.

## Ejecución

Desde `x.cpu-tests`:

```powershell
python run_cpu_tests.py --backend sim
python run_cpu_tests.py --backend fpga --port COM3
python run_cpu_tests.py --backend both --port COM3
```

Sin rutas explícitas se descubren todos los ficheros `cases/**/test.json`.
También se puede ejecutar uno o varios casos concretos:

```powershell
python run_cpu_tests.py cases/smoke/test.json --backend sim
```

El backend FPGA requiere que el bitstream con el protocolo de monitor 1.2 esté
cargado. `RESET_CPU` permite ejecutar casos consecutivos sin reconfigurar la
placa ni borrar sus memorias.

## Formato

`test.schema.json` formaliza el JSON. Las rutas se resuelven respecto al
directorio que contiene cada `test.json`.

```json
{
  "name": "ejemplo",
  "program": "program.asm",
  "max_instructions": 1000,
  "timeout_seconds": 2.0,
  "initial_memory": [
    {
      "address": "0x00000300",
      "file": "input/data.bin"
    }
  ],
  "expect": {
    "halted": true,
    "error": false,
    "error_code": "0x00",
    "pc": "0x00000020",
    "registers": {
      "R1": "0x12345678"
    },
    "memory_dumps": [
      {
        "address": "0x00000400",
        "file": "expected/result.bin"
      }
    ]
  }
}
```

Los programas pueden ser `.asm`, `.bin` o `.hex`. El runner los convierte en
memoria a palabras little-endian sin generar artefactos intermedios.

La longitud de cada región se deduce del tamaño del fichero binario. La
comparación informa de la primera dirección y offset distintos.

## Direcciones de datos

Los JSON utilizan siempre direcciones locales de la CPU entre `0x00000000` y
`0x00003fff`.

- El simulador accede directamente a esa dirección en su memoria unificada.
- El backend FPGA suma `0x00100000` al comunicarse con el monitor.

Los programas comunes deben mantener los datos fuera de la región que ocupa el
programa para no depender de la separación Harvard de la FPGA.

## Resultado diferencial

El modo `both` realiza primero la comparación de cada backend contra los valores
esperados. Después comprueba que los estados observados del simulador y la FPGA
sean idénticos. Los valores esperados siguen siendo necesarios: dos
implementaciones podrían compartir el mismo error.
