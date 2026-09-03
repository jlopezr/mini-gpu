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

Los ficheros de memoria inicial y los dumps esperados pueden ser binarios o
`.hex`. En un fichero `.hex`, cada línea representa una palabra de 32 bits que
se convierte a cuatro bytes little-endian; se admiten comentarios con `#`.

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

## Estado de error

Los errores detienen la CPU y hacen que el PC observable señale la instrucción
causante. Los códigos comunes son:

| Código | Significado                                             |
|-------:|---------------------------------------------------------|
| `0x01` | Opcode reservado, desconocido o todavía no implementado |
| `0x02` | Acceso de memoria inválido                              |
| `0x03` | Instrucción `TRAP` explícita                            |
| `0x04` | División por cero                                       |
| `0x05` | Opcode conocido con campos reservados inválidos         |

Los casos de `cases/errors` verifican por separado `TRAP`, opcode inválido y
encoding inválido sobre ambos backends.

## Programas de integración

`cases/programs` contiene cargas de trabajo pequeñas pero completas:

- `fibonacci`: bucle, aritmética y generación secuencial de un array;
- `array-sum`: entrada inicial, acumulación con wrap y resultado en memoria;
- `memory-copy`: dos punteros, `LOAD`, `STORE` y offset negativo;
- `shift-multiply`: multiplicación sin `MUL`, mediante sumas y shifts.

Estos casos complementan los tests unitarios de RTL comprobando el flujo entero
ensamblador, CPU, memoria, monitor y backend.
