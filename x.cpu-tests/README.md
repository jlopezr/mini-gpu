# Tests de MiniCPU y MiniGPU

También incluye el backend funcional MiniGPU (`--backend gpu-simulator`), con casos en
`cases-gpu`. Los casos CPU siguen en `cases` y el modo `both` sigue comparando
exclusivamente el simulador CPU con la FPGA.

## MiniGPU: ejemplo completo de suma de vectores

Desde `x.cpu-tests`:

```powershell
python run_gpu_tests.py --backend gpu-simulator
python run_gpu_tests.py cases-gpu/vecsum/test.json --backend gpu-simulator
python -m unittest discover -s . -p test_gpu_runner.py -v
```

El runner ensambla `vecsum.asm`, carga `a.hex` en 0x100 y `b.hex` en 0x140,
aplica `warps.json` y compara las 16 palabras de C en 0x180 con `expected.hex`.
No hace falta construir `memoria.bin` ni volcar resultados manualmente. El caso
comprueba también 28 instrucciones totales, PC=0x38 y 14 instrucciones por warp,
registros de varios hilos y que el warp 2 no haya ejecutado nada.

Los casos GPU requieren `architecture: "gpu"` y `warp_config`, una ruta relativa al `test.json`, y usan
los mismos campos `program`, `initial_memory` y `expect.memory_dumps` de CPU.
`expect.instructions_executed` cuenta instrucciones de warp completadas.
Para observar estado privado se usa, por ejemplo:

```json
{
  "warps": {
    "1": {
      "pc": "0x38",
      "active_mask": 0,
      "instructions_executed": 14,
      "registers": {
        "7": {"R1": 15, "R8": 115}
      }
    }
  }
}
```

Este fragmento va dentro de `expect`; las claves son ID de warp e ID local de
hilo. Solo se comparan las observaciones solicitadas. No existe un `expect.pc`
ni un banco `expect.registers` global para GPU. Un caso CPU enviado al backend
GPU, o uno GPU enviado a CPU/FPGA, se rechaza. Cada ejecución GPU crea memoria
nueva y admite programas de hasta 32 MiB; usa `max_instructions` como límite,
no `timeout_seconds`. `--version current` selecciona el simulador actual.

Este directorio contiene casos que pueden ejecutarse sobre el simulador
funcional, la FPGA o ambos. Cada backend produce el mismo estado observable:
estado de parada, error, PC, registros solicitados y regiones de memoria.

## Ejecución

Desde `x.cpu-tests`:

```powershell
python run_gpu_tests.py --backend cpu-simulator
python run_gpu_tests.py --backend cpu-fpga --version ebr --port COM3
python run_gpu_tests.py --backend cpu-fpga --version sdram --port COM3
python run_gpu_tests.py --backend both --version cpu-fpga=sdram --port COM3
```

Sin rutas explícitas se descubren todos los ficheros `cases/**/test.json`.
También se puede ejecutar uno o varios casos concretos:

```powershell
python run_gpu_tests.py cases/smoke/test.json --backend cpu-simulator
```

Los casos GPU admiten traza del scheduler. `--trace-limit` limita los eventos
mostrados, pero no la ejecución ni las comprobaciones del caso; `--trace-file`
los guarda en vez de escribirlos en stderr:

```powershell
python run_gpu_tests.py cases-gpu/vecsum/test.json --backend gpu-simulator `
    --trace --trace-limit 100 --trace-file ejecucion.log
```

`--trace-detail` añade cambios de registros y accesos a memoria. Para
Mandelbrot conviene usar siempre un límite pequeño, porque una ejecución completa
produce millones de eventos aunque solo se quieran inspeccionar los primeros.

`--version` selecciona la versión de cada backend. Con un único backend se
puede usar directamente `--version VERSION`; con varios se usa
`--version BACKEND=VERSION` y el parámetro puede repetirse:

```powershell
python run_gpu_tests.py --backend both `
    --version cpu-simulator=current --version cpu-fpga=sdram --port COM3
```

Cada backend declara internamente todas sus versiones y cuál es la
predeterminada. Añadir una variante nueva solo requiere incorporarla al
registro `VERSIONS` del módulo correspondiente; el runner no contiene una
lista especial de versiones FPGA o del simulador.

El backend FPGA comprueba además la versión física mediante `GET_VERSION`
antes de modificar la memoria:

| Valor | Proyecto | Monitor | Memoria implementada |
|---|---|---:|---|
| `ebr` | `6.fpga-cpu` | 1.6 | `0x00000000–0x00003fff`, `0x00100000–0x00103fff` |
| `sdram` | `10.fpga-cpu-ram` | 1.5 | `0x00000000–0x01ffffff` |

La versión predeterminada de FPGA es `ebr` para conservar la compatibilidad con los
comandos anteriores. Si el monitor conectado no coincide, el test termina con
un mensaje que indica qué bitstream debe cargarse. La comprobación ocurre
antes de `RESET_CPU` y antes de escribir el programa o los datos.

`RESET_CPU` permite ejecutar casos consecutivos sin reconfigurar la placa ni
borrar sus memorias.

## Formato

`test.schema.json` formaliza el JSON. Las rutas se resuelven respecto al
directorio que contiene cada `test.json`.

```json
{
  "architecture": "cpu",
  "name": "ejemplo",
  "program": "program.asm",
  "max_instructions": 1000,
  "timeout_seconds": 2.0,
  "initial_memory": [
    {
      "address": "0x00100300",
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
        "address": "0x00100400",
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

Los JSON, los programas, el simulador, la CPU y el monitor utilizan siempre
direcciones globales. El backend no suma ninguna base. Los casos compatibles
con ambas FPGA colocan el programa en `0x00000000–0x00003fff` y los datos en
`0x00100000–0x00103fff`; los casos que requieran otras direcciones deberán
seleccionar una versión con SDRAM.

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

## Casos GPU y diagnóstico de fallos

`cases-gpu` contiene:

| Caso | Qué comprueba |
|---|---|
| `vecsum` | Dos warps suman 16 elementos; registros, PC y contador |
| [mandelbrot](cases-gpu/mandelbrot/README.md) | Imagen Q16.16 de 320×240 con ocho warps; compara todos los píxeles con referencia escalar (prueba larga) |
| `vecsum-partial` | Máscara parcial; las salidas inactivas conservan `DEADBEEF` |
| `independent-pcs` | W0 y W3 empiezan en PC distintos y terminan en pasos distintos |
| `memory-copy` | Copia de 16 palabras con patrones de 32 bits; conserva la fuente |
| `division-by-zero` | Fallo en hilo 3; no modifica los destinos de los hilos anteriores |
| `load-out-of-bounds` | Lectura inválida del hilo 3; conserva todos los registros destino |
| `store-out-of-bounds` | Escritura inválida del hilo 3; conserva la memoria de los hilos anteriores |
| `trap-global` | Fallo común del warp sin hilo concreto |

Los casos de fallo verifican que el siguiente warp se queda en su PC anterior:
no ejecuta otra instrucción tras el error global. Las pruebas del runner también
comprueban el orden round-robin `[0, 3, 0, 3, 3]` del caso de PC independientes,
los pasos después del fallo y la conservación del primer diagnóstico.

El campo opcional `expect.fault` comprueba el diagnóstico completo:

```json
"fault": {
  "pc": "0x1C",
  "warp_id": 0,
  "core_id": 3,
  "address": "0x02000000"
}
```

Se combina con `error: true` y `error_code` (el ejemplo corresponde a código 2).
El objeto exige los cuatro campos; `core_id: null` representa un fallo común
del warp y `address: null` un fallo sin dirección de acceso, como DIV o TRAP.
`fault: null` exige que no exista fallo. Si se omite `fault`, no se comprueban
estos detalles. Solo está disponible para casos GPU. Un campo ausente en el
resultado del backend nunca equivale a un `null` esperado.

## Arquitectura y compatibilidad

Todos los casos declaran explícitamente `"architecture": "cpu"` o
`"architecture": "gpu"`. No se deduce la arquitectura del nombre del archivo
ni de su carpeta. GPU exige `warp_config`; CPU lo rechaza.

Los backends declaran `ARCHITECTURE`: `cpu-simulator` y `cpu-fpga` son CPU;
`gpu-simulator` es GPU y es el backend predeterminado de `run_gpu_tests.py`.
`both` sigue seleccionando los dos backends CPU. Las versiones se seleccionan,
por ejemplo, con `--version gpu-simulator=current`.

El descubrimiento automático omite casos de otra arquitectura y muestra cuántos.
Una ruta solicitada explícitamente con arquitectura incompatible produce código
2. Se valida la selección completa antes de construir los backends, ejecutar
programas o abrir conexiones FPGA; una selección mixta incompatible no ejecuta
parcialmente los casos válidos.
