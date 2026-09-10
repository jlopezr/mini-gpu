# TODO

Por orden de prioridad.

## 1. `10.fpga-cpu-ram` no implementa `MUL`, `MULFX` ni `DIV`

Es un defecto confirmado, no una sospecha: el caso `multiply` **falla hoy** en esa
versión.

```text
python run_gpu_tests.py --backend cpu-fpga --version sdram --port COM3
FAIL multiply [cpu-fpga]
  error_code: esperado 0x00000000, obtenido 0x00000001   (opcode inválido)
  pc: esperado 0x00000010, obtenido 0x00000008           (el MUL)
```

En `10.fpga-cpu-ram/cpu.v` el opcode aparece solo dos veces: la declaración
(línea 65) y la lista de codificaciones válidas (línea 152). No hay ejecución.
La versión EBR sí lo tiene completo, en `6.fpga-cpu/cpu.v:402`, con su máquina de
estados sobre los multiplicadores del ECP5.

Hay que decidir entre dos caminos, y el segundo también es legítimo:

- Implementarlo en la variante SDRAM, portando lo de `6.fpga-cpu`.
- Declarar que la variante SDRAM cubre un subconjunto de la ISA, y dejarlo
  reflejado en `isa.md` y en las expectativas de los casos afectados.

Mientras no se decida, `--backend cpu-fpga --version sdram` no puede pasar la
suite entera.

## 2. Acceso a memoria por bytes: `LOADB`, `LOADUB`, `STOREB`

Hoy solo hay acceso a palabra de 32 bits. Es la carencia que más se nota al
escribir programas reales, y bloquea cualquier trabajo con framebuffer de bytes.

## 3. Revisar los inmediatos de la ISA en conjunto

Los inmediatos en desplazamientos, `AND`, `OR`, etc. pueden ahorrar bastantes
instrucciones.

Decidido ya: **no** añadir `SHLI` solo por este motivo. `SHL`/`SHR`/`SAR` son
suficientes por ahora. La revisión debe ser global, no instrucción a
instrucción.

## 4. Opcodes reservados pendientes de implementar

`isa.md` los documenta como *Reservada — Implementada: No*, y ni el ensamblador
ni los simuladores los ejecutan:

| Opcode | Mnemónico |
|---|---|
| `0x0B` | `MULHI` |
| `0x0D` | `DIVU` |
| `0x0E` | `REM` |
| `0x0F` | `REMU` |

Son los únicos mnemónicos de la ISA sin ningún test, y así debe seguir siendo
hasta que se implementen: un test que fijara hoy su comportamiento
(`ERROR_OPCODE`) habría que borrarlo justo al implementarlos.

Aquí van también los opcodes aún sin asignar que se tengan pensados.

## 5. Mejoras al controlador de SDRAM

¿Qué mejoras podemos hacer? ¿Qué hacía supuestamente el de `7.fpga-ram`, que no
funciona?

## 6. Ejecución paso a paso

Avanzar una instrucción de warp, inspeccionar registros y memoria, y detenerse
en un PC o un warp concreto. `TextTrace` ya hace el trabajo sucio.

Debe ser una herramienta **aparte**, no una opción de `run_gpu_tests.py`: el
runner responde pasa/falla y un depurador interactivo es otro oficio.

Prioridad baja a propósito: no encuentra fallos, ayuda a entenderlos una vez
encontrados, y con las expectativas actuales `--trace-detail` ya cubre casi
todos los casos.

## 7. Snapshots de ejecución

Guardar y restaurar memoria, PC, registros, máscaras y estado del scheduler.
Extensión del fichero de lanzamiento, con un propósito distinto.

Es lo de mayor impacto de la lista: `mandelbrot` son ~100 s y supone el 99,8 %
del tiempo de la suite GPU; reproducir un fallo tardío pasaría de minutos a un
instante. Además permitiría comparar simulador y FPGA **en un punto intermedio**,
no solo al final.

**Pero va el último a propósito.** Un snapshot tiene que serializar
`region_stack` y `path_stack`, que es justo lo que está en diseño activo. Congelar
ese formato ahora obliga a migrar snapshots cada vez que se toque la semántica
de `SSY`. Hacerlo cuando `SSY` esté cerrado.

---

## Hecho

- **Ampliar ejemplos y pruebas** (máscara parcial, warps con PC distintos, copia
  de memoria, fallo en un hilo concreto, orden de ejecución): cubierto por
  `memory/vecsum-partial`, `scheduling/independent-pcs`, `memory/memory-copy` y
  `faults/division-by-zero`. El orden round-robin lo fija
  `test_gpu_runner.py:117`.
- **Completar el diagnóstico de errores**: el campo `expect.fault` verifica PC,
  warp, hilo y dirección, y lo usan ocho casos. Que los demás warps dejen de
  avanzar lo comprueba `faults/trap-global`.
