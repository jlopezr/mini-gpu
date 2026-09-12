# TODO

Por orden de prioridad.

## 0. Que la CPU no este tanto esperando a la SDRAM

Usar BL8...

## 1. Optimizar LSU

El codigo es muy inocente y es lo que hace que hayamos bajado de 120Mhz a 32Mhz.

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
|--------|-----------|
| `0x0B` | `MULHI`   |
| `0x0D` | `DIVU`    |
| `0x0E` | `REM`     |
| `0x0F` | `REMU`    |

Son los únicos mnemónicos de la ISA sin ningún test, y así debe seguir siendo
hasta que se implementen: un test que fijara hoy su comportamiento
(`ERROR_OPCODE`) habría que borrarlo justo al implementarlos.

Aquí van también los opcodes aún sin asignar que se tengan pensados.

## 5. Mejoras al controlador de SDRAM

¿Qué mejoras podemos hacer? ¿Qué hacía supuestamente el de `7.fpga-ram`, que no
funciona?

## 6. Ejecución paso a paso o N pasos

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

----------------------------------------------------------

1. Buscar inexactitudes entre doc y codigo
2. Que todos los RTL compartan el mismo estilo de documentacion:
    - ISA.md
    - Ciclos.md
    - Optimizacion.md
3. Resumen de RTL
    - GPU/CPU
    - Numero de Version
    - Ciclos
    - Fmax
    - ISA implementado
4. Revisar que no haya cosas divergentes innecesariamente. una optimizacion en una version si y en otra no. MULX no esta en CPU pero si en GPU...
    - Que ciclos hay para cada version de la CPU y GPU, y que sean consistentes.
5. Si hay algun test individual de una version que tiene sentido en tescases.
6. Tools compartidas en carpeta tools.
    - Para hacer sweep
    - Para hacer test
    - Para ensamblar, lanzar un programa
    - build que se guarde el detalle del build (Fmax, caminos críticos, histograma) y que se pueda tener historico. Que sea facil de usar para humanos y IA :)