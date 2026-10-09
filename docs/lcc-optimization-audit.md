# Auditoría de optimización de LCC / MiniISA

Fecha de la auditoría: 9 de octubre de 2026. Línea base del superproyecto:
`192dca5`; submódulo `y.lcc`: `895f564`.

Última actualización: 9 de octubre de 2026, con `y.lcc` en `d7d2523` y el
superproyecto a partir de `59908b5`. Los datos de la sección 11 siguen siendo los de la
línea base; el estado y las cifras actuales están en las secciones 12 a 14.

## 1. Resumen ejecutivo

Mini-LCC no es un compilador «sin optimizaciones». Es LCC 4.2 con simplificación
de árboles, constant folding, selección por BURG, DAG/CSE local, poda de ciertos
temporales, asignación de registros y strength reduction de operaciones
concretas. El backend MiniISA participa activamente mediante costes y reglas de
máquina y añade lowering de 64 bits, soft-float, helpers, parámetros de hojas en
temporales y supresión de `MOVI R0,0`.

La carencia principal es de alcance: no hay una IR de función con SSA ni una
pasada global clásica. La información se fragmenta en bosques de DAG; llamadas,
saltos y stores invalidan el DAG. La asignación es local sobre la lista
linealizada de cada bosque, no usa liveness de CFG y no hace coalescing global.
De ahí proceden la mayoría de stores/loads, copias y frames observados.

Hallazgos prioritarios:

1. **Promoción local de escalares y eliminación de stores muertos.** Variables
   AUTO con menos de tres referencias se quedan en memoria. Casos tan sencillos
   como `int a=7; return a+x;`, una cadena de copias, o una asignación
   sobrescrita generan STORE/LOAD evitables. Es la oportunidad de mayor alcance.
   **Estado:** hecho en hojas (`mini.md:local` y `stackslots`); ver sección 12.
2. **Coalescing/copy propagation después de asignar registros.** La copia de
   retorno `ADD R15,R1,R0`, copias de parámetros y muchas copias alrededor de
   comparaciones son sistemáticas. El `mini-opt` ya confirmado elimina una parte
   con análisis de CFG y obtuvo −11,4 % estático y −7,7 % dinámico en el corpus
   de esta auditoría. **Estado:** hecho; con todos los pases actuales, −14,2 %
   estático en los 166 casos de mini-tst y −12,7 % de instrucciones ejecutadas
   en la demo de `z.tui` (sección 13).
3. **Mejorar valores vivos a través de llamadas.** El asignador solo puede
   conservarlos en variables REGISTER preasignadas R16–R29; los demás
   temporales R7–R15 se vuelcan al llegar a una llamada. El caso `mix` guarda
   parámetros y resultados en pila aunque hay registros preservados libres.

Las tres mejoras más fáciles son: ~~(a) integrar peephole/copyprop y DCE de
`mini-opt` en la validación de LCC~~ **(hecho)**; ~~(b) eliminar código
inalcanzable posterior a un branch resuelto o `BRA`~~ **(hecho)**; (c) relajar la alineación del frame a
4 bytes, aunque esta última ahorra memoria y offsets, no instrucciones, mientras
los inmediatos sigan cabiendo.

No se recomienda cambiar MiniABI antes de mejorar la generación. Aumentar a 6 u
8 registros de argumentos beneficia llamadas anchas, pero choca con R5/R6,
reservados como scratch, y no corrige la causa dominante de los accesos a pila.
Tampoco se recomienda todavía cambiar masivamente callee/caller-saved: el
asignador actual no explota bien ninguno de los dos conjuntos. La alineación de
16 a 4 sí es un cambio de bajo riesgo, pero de beneficio de rendimiento nulo en
los casos medidos.

`mini-opt` no es hipotético en este `HEAD`: ya existe en `tools/mini_opt/` con
CFG, liveness, dominadores, constant/copy propagation, DCE local, LICM, saltos e
infraestructura GPU. Es útil y produjo ganancias reales, pero no puede recuperar
con seguridad las variables virtuales ni deshacer la asignación de slots/spills.
La recomendación es híbrida: conservarlo para optimizaciones post-RA y GPU, y
corregir dentro del backend/LCC la promoción, los spills y los frames.

## 2. Línea base y reproducibilidad

### Worktree

- Worktree: `C:\Users\j_lop\Documents\repos\mini-gpu-lcc-audit`.
- Rama: `analysis/lcc-optimization`.
- El árbol original permaneció en `main` y no se modificó.
- El original tenía cambios locales, incluidos cambios no confirmados en
  `tools/mini_opt`; quedaron fuera de esta auditoría.

El superproyecto fija `y.lcc` a `895f564ea47552c8b5df1a778eb9394f8f0232ab`,
pero `origin` del submódulo no contiene ese objeto (`upload-pack: not our ref`).
El objeto solo estaba en la copia local limpia, un commit por delante de
`origin/main` (`f55d490`). Se importó desde esa copia local al clon aislado y se
hizo checkout detached del SHA exacto. Un clon limpio remoto del superproyecto
no es reproducible hasta publicar ese commit.

### Construcción y pruebas

Se ejecutó `build-mini.ps1 rebuild` con MSVC x86: construcción correcta. La
arquitectura x86 es requisito real porque `lburg` guarda punteros en `int`.

Se ejecutó la suite completa con simulación funcional:

```text
164/164 compiled+simulated (+2 xfail)
23551 generated instructions
```

Los dos `xfail` son los inicializadores designados C99 (`97` y `98`). También se
ejecutaron las 56 pruebas de `x.tests/test_mini_opt.py`: todas correctas. Pytest
no estaba instalado en el entorno; la suite se ejecutó directamente con
`unittest`.

## 3. Versión y arquitectura real de LCC

### Versión y modificaciones locales

`y.lcc/README` identifica la distribución como **LCC 4.2**. El backend MiniISA
se introdujo en `67db371` sobre el padre `2b5cf35`. Comparado con ese padre, el
fork modifica solo diez fuentes preexistentes del frontend/núcleo
(`bind.c`, `c.h`, `dag.c`, `enode.c`, `lex.c`, `simp.c`, `stmt.c`, `sym.c`,
además de build) y añade `src/mini.md`, runtime, headers y pruebas. Las
modificaciones de frontend relevantes son soporte correcto de constantes de 64
bits y semántica de comparaciones FP; no hay una nueva IR global.

### Flujo de compilación real

```text
parser/semántica -> Tree -> simplify()
                 -> listnodes(): DAG local
                 -> undag()/prune()
                 -> BURG label/reduce/rewrite
                 -> linearize()
                 -> ralloc()/spill()
                 -> emit()
```

- Árboles y roots de sentencias: `src/tree.c`, `tree()`, `root()`.
- Construcción semántica: `src/enode.c` (`addtree`, `multree`, `asgntree`,
  `calltree`).
- Simplificación: `src/simp.c:simplify()`.
- DAG: `src/dag.c:listnodes()`; `node()` comparte nodos por operación, símbolo e
  hijos. `killnodes()` invalida lecturas al escribir un símbolo y `reset()`
  vacía toda la tabla ante alias incierto, llamada o salto.
- Conversión de DAG compartido: `undag()`, `visit()`, `tmpnode()` y
  `asgnnode()` materializan CSE en temporales.
- Selección: `src/gen.c:rewrite()` invoca las tablas generadas por `lburg` desde
  `src/mini.md`; los costes de reglas deciden patrones.
- Asignación: `src/gen.c:ralloc()` después de linealizar el árbol.
- Spills: `spillee()`, `spillr()`, `genspill()` y `genreload()`.
- Emisión y frame: `src/mini.md:emit2()` y `function()`.

`miniIR.wants_dag` vale 0. Esto no significa que no haya DAG: LCC lo construye y
lo usa para CSE, pero `undag()` lo vuelve a árboles/temporales antes del backend.
No existe CFG de función dentro de LCC ni una API de pasada intermedia global.
Añadir una requiere actuar sobre la lista `Code`/bosques antes de `gencode()` o
introducir una representación nueva. En cambio, `mini-opt` sí construye CFG
sobre el ensamblador.

### Información de flujo disponible

El frontend conoce labels, roots y la secuencia `Code`, y hace simplificaciones
estructurales en `stmt.c` (`foldcond`, `equatelab`, `reachable`). No calcula
liveness, dominadores ni bucles de función. El DAG conserva dependencias dentro
de una región recta, pero se reinicia en fronteras conservadoras. No hay análisis
interprocedimental ni perfiles.

## 4. Auditoría de optimizaciones

| Optimización | Estado | Alcance/evidencia | Limitación MiniISA |
|---|---|---|---|
| Constant folding | Implementada y efectiva | `simp.c:simplify`; enteros de 64 bits corregidos por el fork | No cruza sentencias/variables |
| Simplificación algebraica | Implementada y efectiva | identidades, conmutación, `x*2^n -> x<<n`, división unsigned por potencia de dos | Conjunto finito de patrones |
| Constant propagation | Implementada, pero limitada | Solo dentro del árbol/DAG; `mini-opt` la hace post-RA en CFG | `int a=7; return a+x` conserva STORE/LOAD |
| Copy propagation | Implementada, pero limitada | `dag.c:prune/replace`; `mini-opt` propaga registros | Cadenas AUTO entre sentencias siguen en pila |
| CSE | Implementada y efectiva localmente | Hash-DAG de `dag.c:node`; `(a+b)*(a+b)` genera un ADD | Se invalida en llamadas, saltos y stores/alias |
| DCE | Implementada, pero limitada | roots eliminan expresiones puras; `mini-opt:dce` hace DCE físico independiente y se intercala entre fases | Un store AUTO sobrescrito sigue emitido |
| Register allocation | Implementada, pero limitada | asignación local bottom-up/lineal en `gen.c:ralloc` | Sin CFG, sin intervalos globales, sin coalescing |
| Liveness | Implementada, pero limitada | cadenas `lastuse/prevuse` solo en la lista lineal actual; CFG en `mini-opt` | No liveness pre-RA de función |
| Coalescing | Ausente en LCC; limitado en mini-opt | `mini-opt:copyprop` elimina copias físicas seguras | No puede cambiar decisiones de spill ya tomadas |
| Reutilización de slots | Implementada, pero limitada | `blockbeg/blockend` restaura `offset` por bloque léxico | Cada spill usa `newtemp(AUTO)`; sin coloreo por vida |
| Leaf optimization | Implementada, pero limitada | `mini_is_leaf`; parámetros a R7–R15 | Copia todos los parámetros usados; no resuelve retorno/argumento en sitio |
| Frame cero | Implementada y efectiva | `function()` emite ajustes solo si `framesize>0` | Cualquier local mínimo redondea a 16 |
| Prólogo/epílogo | Implementada, pero limitada | guarda solo R16–R29 usados y R31 si llama; `mini-opt:tailcalls` elimina casos finales seguros | No hay shrink wrapping |
| Saltos | Implementada, pero limitada | folding frontend; `mini-opt:jumps` y `branches` resuelven cadenas y branches constantes/idénticos; `invert` quita el `BRA` de `Bcc ; BRA ; L1:` y `boolean` convierte los booleanos con salto en `SLT`/`SLTU` | No hay threading general ni análisis interprocedimental |
| Inalcanzables | Implementada post-RA | `reachable()` en LCC y `mini-opt:unreachable` sobre CFG | Las funciones con saltos indirectos se dejan opacas por seguridad |
| LICM | Ausente en LCC; implementada limitada en mini-opt | `mini-opt:licm`, solo instrucciones puras | No mueve cargas por alias; `p[0]` se carga por vuelta |
| Strength reduction | Implementada, pero limitada | potencias de dos en `simp.c`; inmediatos/reglas MiniISA | No hay inducciones ni reducción global de bucles |
| Inlining | Ausente | No hay infraestructura interprocedimental | Fuera de la filosofía/objetivo inmediato |
| Tail calls | Implementada post-RA, restringida | `mini-opt:tailcalls` restaura el epílogo y cambia `JAL` por `BRA` | Rechaza stack args, varargs, punteros al frame, destinos externos/privados e indirectos |
| Argument optimization | Implementada, pero limitada | R1–R4; `argreg`, `doarg`, `rtarget` | >4 argumentos van a memoria; área mínima 16 con llamadas C |
| Peephole | Implementada fuera de LCC | `mini-opt` hace jumps/constprop/copyprop/branches/unreachable/DCE/LICM/tailcalls/invert/boolean | Integrado opt-in en mini-tst, no por defecto en toda compilación C |
| Instruction selection | Implementada y efectiva | BURG en `mini.md`, ADDI/ANDI/etc., 64-bit y helpers | Scratch R5/R6 reduce temporales asignables a nueve |

No se debe equiparar «no hay pasada llamada CSE/DCE» con ausencia: el DAG y la
selección consiguen CSE y eliminaciones locales. A la inversa, los probes
demuestran que esos mecanismos no equivalen a propagación o DCE de función.

## 5. Backend MiniISA: registros y spills

### Algoritmo real

`gen.c:gen()` reescribe, poda y linealiza en postorden. Para cada instrucción,
`ralloc()` libera hijos en su último uso y pide un registro. Si no hay uno,
`spillee()` elige entre los ocupados el que tenga el **uso siguiente más
lejano**, explorando hacia delante en esa lista. Es un asignador local tipo
next-use, no graph coloring ni linear scan de función.

Clases efectivas:

- R0: cero.
- R1:R2: retorno, fijados por `target()` según ancho.
- R1–R4: argumentos, fijados en nodos ARG/CALL.
- R5/R6: scratch invisible al asignador.
- R7–R15: `MINITMP`, nueve registros para temporales.
- R16–R29: `MINIVAR`, variables REGISTER callee-saved.
- R30/R31: SP/link.

Los valores de 64 bits se asignan como pares **consecutivos** mediante
`ireg2[i]=mkreg(...,mask=3)`. Esto contradice el texto de `abi.md` que permite
pares internos arbitrarios; la ABI externa no se rompe, pero la documentación
describe una libertad que este backend no implementa. Además reduce las
opciones de asignación y puede crear fragmentación.

### Llamadas

`mini.md:clobber()` llama `spill(MINITMP,...)` en CALL y en helpers ocultos. Por
tanto todo temporal R7–R15 vivo a través de llamada se vuelca. Los registros
R16–R29 solo se usan para símbolos que `checkref()` promueve a REGISTER
(`ref >= 3`) antes de generación; un temporal calculado no migra a un
callee-saved libre.

Ejemplo medido, `mix(a,b)`:

```asm
STORE R1, R30, 32
STORE R2, R30, 36
LOAD  R1, R30, 32
JAL   R31, inc
STORE R1, R30, 28
...
```

La función produce 14 accesos estáticos/dinámicos a pila en el programa de
prueba. Es correcto, pero varios son evitables si se asignan los valores que
cruzan calls a R16–R29 con su coste de save/restore evaluado una vez.

### Spills y movimientos

`spillr()` crea un `newtemp(AUTO)` por valor derramado, inserta store tras su
definición y reload antes de usos posteriores. No hay slot coloring por
intervalos. Los scopes léxicos sí reutilizan el contador de offset al hacer
`blockend`, por lo que no es correcto afirmar que nunca se reutiliza pila.

En `pressure`, ocho locales de uso posterior producen ocho STORE y ocho LOAD:

```asm
ADDI R11, R15, 1
STORE R11, R30, 28
...
LOAD R11, R30, 28
```

No son spills causados por falta de registros: son variables AUTO porque cada
una no alcanza `ref >= 3`. Este diagnóstico importa: tocar el heurístico de
spilling no arreglaría el patrón; hace falta promoción/copy propagation.

Los movimientos redundantes más repetidos son `ADD d,s,R0`: copias de
parámetros hoja, retorno de CALL y coalescing fallido. `mini-opt:copyprop`
elimina parte de ellos con liveness de CFG.

## 6. Stack frames, llamadas y prólogos

`mkauto()` asigna offsets negativos; `function()` calcula:

```text
framesize = roundup(maxargoffset + saves + maxoffset, 16)
```

La disposición coincide con la ABI: argumentos salientes, saves, locals/spills.
Resultados:

- Los frames cero se omiten.
- R31 solo se salva con CALL o llamada oculta.
- Solo se guardan R16–R29 realmente usados.
- R29 nunca se usa como frame pointer: permanece en `MINIVAR`.
- R30 solo se ajusta una vez al entrar/salir; no hay VLA/alloca.
- No se detectó ajuste redundante dentro de una función.
- El área saliente mínima de 16 bytes se reserva para funciones C llamadas,
  porque el callee puede volcar R1–R4.

La alineación a 16 causa frames de 16/32/48 en casos que solo requieren múltiplo
de 4. Reducirla ahorra 0–12 bytes por activación, relevante para recursión, pero
no elimina los dos ADDI de prólogo/epílogo. En `fib(8)`, 1046 instrucciones y
336 accesos a pila se mantendrían; solo bajaría el consumo máximo de RAM.

En la línea base no había tail-call optimization. El probe
`tail(x){return constprop(x);}` reserva
32 bytes, salva R31, vuelca/recarga el argumento, llama, restaura y retorna. Una
transformación segura a `BRA constprop` evitaría todo el frame en el caso
directo compatible con ABI si se hiciera antes de crear el prólogo.
**Resuelto parcialmente después de la auditoría:** `mini-opt:tailcalls`
elimina la llamada/retorno y adelanta el epílogo cuando puede demostrar las
condiciones de seguridad descritas en la sección 12; al ser post-RA todavía no
elimina el frame ya emitido.

## 7. Selección de instrucciones

La selección usa instrucciones MiniISA apropiadas:

- ADDI y lógicas inmediatas cuando el árbol conserva una constante;
- MUL/SHL y DIVU/RSH para patrones que `simp.c` reduce;
- SLT/SLTU para comparaciones y carry/borrow;
- LOADB/H con extensión correcta;
- reglas especializadas de 64 bits y producto ancho;
- cero en R0 sin MOVI.

La pérdida ocurre antes o después de selección: si una constante pasó por un
AUTO, se materializa, almacena y recarga; si dos registros físicos son copias,
BURG ya no puede coalescerlos. `mini-opt:constprop` recupera ADDI/ANDI/ORI/XORI
post-RA y borra la constante muerta.

Compatibilidad: el backend objetivo emite SLT/SLTU y otras capacidades del ISA
actual; no parametriza selección por versión de prototipo. Los binarios C deben
ejecutarse en implementaciones que declaren dichas capacidades. Cualquier nueva
selección debe contrastarse con `tools/capabilities.json` y los simuladores.

## 8. Evaluación de MiniABI

| Alternativa | Mejora observada/estimada | Coste y riesgo | Recomendación |
|---|---|---|---|
| Más caller-saved (p.ej. R16–R23) | Más temporales en código hoja | Más spills alrededor de cada call; `clobber`, masks y runtime cambian | No todavía; primero allocator con coste de calls |
| 6 registros de argumento | En `sum8`, evita 2 STORE + 2 LOAD (estimado 4 instrucciones) | R5/R6 son scratch; hay que relocalizarlos y cambiar ABI/runtime/tests | Posponer |
| 8 registros de argumento | En `sum8`, evita 4 STORE + 4 LOAD; frame estimado 48→32, 38→30 instrucciones | Conflicto R5/R6, menos temporales, mayor clobber; incompatibilidad asm | Solo con corpus grande y rediseño scratch |
| Alineación 16→4 | Hasta 12 bytes menos por frame; 16 bytes menos en `sum8` por disposición | ABI y tests; ninguna instrucción menos medida | Candidato independiente de memoria, no de velocidad |
| Frame pointer obligatorio | Ninguna mejora en código fijo | 2+ instrucciones, save extra y pierde R29 | Rechazar |
| Frame pointer opcional actual | R29 disponible y sin overhead | Debug/unwind más difíciles | Mantener |
| Más callee-saved | Puede reducir spills a través de calls si se usan | Save/restore por función; hoy ya sobran R16–R29 | No aporta sin allocator global |
| Menos callee-saved | Menos saves en hojas con REGISTER | Más spills caller; rompe asm existente | No justificar aún |

### Argumentos de 64 bits

La regla externa (dos slots consecutivos, alineación 4, no partir escalar entre
registros/pila) simplifica el backend y está probada. No se recomienda añadir
alineación par: desperdiciaría un slot. La implementación `argreg()` respeta el
caso de 8 bytes y evita comenzar si solo queda R4. Mantener.

### Impacto de un cambio ABI

Habría que modificar `1.isa/abi.md`, `mini.md` (`masks`, `argreg`, `target`,
`clobber`, helpers a mano, soft-float generado), runtime/crt si aplica,
`mini-tst`, tests del ensamblador y todo ensamblador manual que llame C. Sin
linker/versionado de objetos no hay detección automática de mezcla de ABI.

## 9. mini-opt y metadatos

### Estado real

`tools/mini_opt` ya separa funciones, construye basic blocks y CFG, calcula
liveness, dominadores/postdominadores y bucles. Sus pases por defecto, en orden,
son: `intrinsics`, `kernels`, `stackslots`, `jumps`, `boolean`, `constprop`, `dce`,
`copyprop`, `dce`, `branches`, `unreachable`, `licm`, `dce`, `sharebase`,
`tailcalls`, `unreachable`, `invert`, `ssy`.
Esto cambia la conclusión del planteamiento inicial: no hay que decidir si
crear desde cero un optimizador externo, sino si ampliar/integrar el existente.

### Qué puede reconstruirse sin metadatos

- límites de función/label/bloque;
- defs/uses de registros físicos;
- CFG, dominadores, liveness física;
- calls directas/indirectas y clobbers definidos por ABI;
- patrones de prólogo/epílogo y frame;
- loads/stores relativos a R30;
- constantes y copias físicas.

### Qué no puede recuperarse con seguridad

- identidad y tipo de temporales virtuales antes de RA;
- si un slot es variable, spill o argumento reutilizable;
- si la dirección de un objeto escapó;
- alias/noalias y volatilidad perdida en el texto;
- vida pre-RA y alternativas de asignación;
- correspondencia exacta IR↔instrucciones tras expansiones múltiples;
- efectos semánticos de calls externas más allá del contrato ABI.

### Metadatos mínimos útiles

Si se añaden, deben ser pocos y verificables:

```asm
; @miniopt v=1 function=foo fact
; @miniopt v=1 slot=24 size=4 kind=spill id=t17 fact
; @miniopt v=1 slot=28 size=4 kind=local address_escapes=0 fact
; @miniopt v=1 call clobbers=R1-R15,R31 fact
```

No hace falta emitir livein/liveout: mini-opt ya los calcula y una copia en
comentarios se desincroniza fácilmente. Tampoco límites de bloques: labels y
terminadores bastan. La identidad virtual/slots y escape sí aportan información
irrecuperable.

Seguridad propuesta:

- cabecera versionada por función y `source-hash` de la secuencia de
  instrucciones normalizada;
- facts separados de hints; una optimización correcta nunca depende de hints;
- IDs de instrucción/slot, no asociación por «comentario anterior» solamente;
- validar offsets, tamaños, solapamientos y hash antes de usar;
- descartar todos los metadatos de la función ante contradicción;
- asm manual o editado sin metadatos sigue por el camino conservador actual.

**Helpers del backend (`__mini_*`): hoy no se transfiere nada.** Lo único que
cruza por el `.s` es el hecho `volatile`. Los helpers que añade mini-lcc
(`__mini_memcpy`, `__mini_divfx`, `__mini_udivmod64` y los de soft-float)
usan un convenio privado (entradas en R5–R9, retorno en R7–R10, enlace por R15
o R31), así que `Function.opaque` (`model.py`) los marca **por el prefijo del
nombre** y todos los pases los saltan. El efecto es más amplio que el helper:
una función que hace `JAL` a un `__mini_*`, o cualquier `JAL`/`JR` con enlace
distinto de R31, también es opaca y no se optimiza en absoluto. Es la vía
conservadora correcta mientras no haya un contrato explícito; sería el segundo
metadato justificado, después de `volatile`, por ejemplo
`; @miniopt helper NOMBRE in=R5,R6,R7 out=R7 clobbers=R5-R15 link=R31`, que
permitiría tratar el `JAL` como una llamada con clobbers conocidos en lugar de
descartar la función entera. Sin medir cuántas funciones de mini-tst quedan
opacas por esto, no hay cifra de ganancia.

**Medido el 9 de octubre de 2026 y descartado por ahora.** En mini-tst, 34 de
640 funciones son opacas (10 son los propios helpers, 24 de usuario), en 11 de
166 ficheros: 760 de 22.930 instrucciones (3,3 %). En los ejemplos de
`32.cpu-gpu-func-sim/examples/c` (cubo, rotación, `plane`, `diverge`, `memset`,
kernels de sistema) no aparece ningún `__mini_*` y no hay ninguna función
opaca. Con un uso real nulo, el metadato `helper` no compensa tocar `y.lcc` ni
su submódulo; solo reabrirlo si algún programa nuevo usa soft-float, divisiones
de 64 bits, `divfx` o copias de bloque grandes y el recuento sube.

No se recomienda empezar por metadatos. Primero deben medirse transformaciones
que los necesiten. Para copyprop, DCE, jumps y LICM pura, el ensamblador basta.

**Primer metadato en uso:** `; @miniopt volatile NOMBRE` (lcc lo escribe en un comentario, que el ensamblador no
ve y mini-opt lee en `parse_unit`). Es el caso que se mencionaba arriba: la volatilidad se pierde en el texto y la
LICM de cargas no puede decidir sin ella. Lo demás que hace falta para esa transformación (que la dirección no
escape) sí se reconstruye con el ensamblador de toda la unidad, sin metadatos.

## 10. Ubicación recomendada de transformaciones

| Transformación | Lugar recomendado | Razón |
|---|---|---|
| Folding/algebra local adicional | `simp.c` | tipos y semántica C disponibles |
| Promoción AUTO y store DCE | IR/lista Code antes de RA | requiere identidad, alias y escape |
| CSE local | Mantener DAG | ya efectivo y simple |
| Mejor RA/spills/coalescing pre-RA | `gen.c`/capa MiniISA antes de físico | información virtual todavía presente |
| Copias físicas, DCE de registros | `mini-opt` | CFG/liveness ya implementados |
| Saltos/threading/unreachable asm | `mini-opt` | transformación sencilla post-emisión |
| LICM aritmética pura | `mini-opt` | ya existe y es conservadora |
| LICM de loads | Dentro de LCC | necesita alias/volatile/escape |
| Tail call | backend antes de prólogo o pase post-RA con metadatos | debe coordinar frame/ABI |
| Frame size/save layout | `mini.md:function()` | decisión propia del backend |
| Slot coloring de spills | pre-emisión | mini-opt no conoce identidades/escape |
| Selección inmediata/peephole | reglas MiniISA + mini-opt | primera oportunidad y recuperación post-RA |
| GPU intrinsics/SSY | `mini-opt` | ya es su función natural |

## 11. Casos y métricas reproducibles

Fuentes: `analysis/lcc-audit/probes/`. Script:
`analysis/lcc-audit/measure.py`. Salidas y `metrics.csv` en la misma carpeta
(los `.s`/`.bin` están bajo `out/`). Las métricas cuentan el programa completo,
incluidos `_start` y `main`. «Mem» cuenta loads/stores de datos, no fetch de
instrucciones; «pila» usa R30 como base. El simulador funcional no modela ciclos,
por lo que no se presentan cifras de ciclos ni speedup.

| Caso | Est. LCC | Est. opt | Din. LCC | Din. opt | Mem din. | Pila din. | Frame máx. |
|---|---:|---:|---:|---:|---:|---:|---:|
| args8 | 38 | 33 | 38 | 33 | 10 | 10 | 48 |
| arrays_escape | 37 | 34 | 37 | 34 | 16 | 4 | 48 |
| calls | 37 | 34 | 43 | 38 | 14 | 14 | 32 |
| control | 30 | 28 | 79 | 77 | 6 | 6 | 32 |
| leaf | 20 | 16 | 20 | 16 | 2 | 2 | 32 |
| locals | 26 | 24 | 26 | 24 | 8 | 8 | 32 |
| opt_patterns | 117 | 101 | 128 | 111 | 41 | 39 | 48 |
| pressure | 52 | 47 | 52 | 47 | 18 | 18 | 32 |
| recursive | 32 | 29 | 1046 | 979 | 336 | 336 | 32 |
| volatile | 26 | 24 | 26 | 24 | 8 | 4 | 32 |
| wide | 32 | 26 | 32 | 26 | 2 | 2 | 32 |
| **Total** | **447** | **396** | **1527** | **1409** | | | |

Resultado mini-opt: −51 instrucciones estáticas (−11,4 %) y −118 dinámicas
(−7,7 %). Todos los resultados R1 coincidieron. La ganancia no incluye mejoras
de pila porque los pases actuales no deshacen stores de variables/spills.

Ejemplos probados:

```asm
; CSE sí efectivo
ADD R13, R15, R14
MUL R1, R13, R13

; propagación entre sentencias ausente
MOVI  R14, 7
STORE R14, R30, 12
LOAD  R14, R30, 12
ADD   R1, R14, R15

; store muerto no eliminado
ADDI  R14, R15, 1
STORE R14, R30, 12
ADDI  R14, R15, 2
STORE R14, R30, 12
```

La prueba `volatile` conserva tres accesos a la global como exige C; cualquier
pase de memoria debe mantener esa barrera. `arrays_escape` separa locales
addressed obligatorios de spills evitables. `wide` cubre pares de 64 bits.

### Código real: `z.tui` y el cubo

Los probes son casos mínimos. Con programas reales (medido el 9 de octubre de
2026, con todos los pases por defecto):

- **Demo de `z.tui`** (`tui_unity_mini.c`, unas 12.400 instrucciones, ejecutada
  en el simulador con ESC; la pantalla es idéntica con y sin pases):
  362.017 → 316.008 instrucciones ejecutadas (−12,7 %) y binario de 83.640 →
  80.748 B (−3,5 %). `TuiDemoTest` (`x.tests/test_mini_opt.py`) lo comprueba.
- **Cubo** (`examples/c/race/cube.c`, un fotograma de cada método en estado
  estable; `compare_cube.py`): C frente a ensamblador a mano, 1,00 (CPU), 1,00
  (GPU inocente) y 1,01 (GPU buena). El arranque del demo, que genera las
  texturas, sí es más caro en C (unas 670.000 instrucciones frente a 530.000),
  pero ocurre una sola vez; una medida anterior de 1,12 en CPU era ese arranque
  y no el método.
- **Guardados de R16–R29 en `cube_cpu`** (14 `STORE` y 14 `LOAD` por llamada):
  `mini-opt:kernels` ya los quita en los kernels de GPU, donde no hay a quién
  devolver. En una función de CPU la ABI los exige y lcc ya guarda solo los
  usados; aquí lo son todos. Son 28 accesos por fotograma de ~321.000
  instrucciones (0,009 %), así que no hay nada que ganar; evitarlos en una
  función llamada muchas veces pediría análisis interprocedural o shrink
  wrapping.
- **`tailcalls` en `z.tui`:** 66 saltos de cola convertidos; en 33 el epílogo
  original queda sin uso (−1 instrucción cada uno) y en 33 está compartido con
  otro `return` y se duplica (≈ +4 cada uno): neto +99 instrucciones estáticas
  (+0,8 %) frente a −6 instrucciones ejecutadas en la demo. Un salto de cola
  ahorra una instrucción y un salto tomado por ejecución; su ventaja real es la
  pila en recursión, que `z.tui` no tiene. Se deja como está; si más adelante
  una medida en la placa muestra un camino caliente que lo justifique, o al
  contrario, se puede restringir a epílogos que mueren y recursión propia
  (parámetro `--tailcalls`).

## 12. Oportunidades priorizadas

Estado actualizado tras la implementación y validación del 9 de octubre de
2026. Las oportunidades completadas se conservan tachadas para mantener el
historial de la auditoría.

| Optimización | Estado actual | Beneficio observado/probable | Complejidad | Ubicación |
|---|---|---|---|---|
| ~~Copyprop + DCE físico~~ | **Hecho:** DCE independiente e integración opt-in en mini-tst | Suite unificada actual: 23.601 → 20.242 instrucciones (−14,2 %, medida el 9 de octubre de 2026 con `y.lcc` en `87ef9cf` y los pases `invert` y `boolean`) | Baja | mini-opt + runner LCC |
| ~~Promoción de AUTO a registro~~ | **Hecho en dos capas:** `mini.md:local` (hojas: escalares de `ref<3` o que no caben en R16–R29 van a temporales R7–R15, dejando 5 libres) y `stackslots` en mini-opt como red de seguridad (huecos de pila a registros libres, con su marco) | Cubo GPU «buena» en placa: 1,56 M → 1,34 M ciclos (ASM: 1,257 M); casi todo lo aportó `stackslots`. Con el cambio en lcc, `__kernel_cube_good` ya sale sin pila aunque se apague el pase | Media | LCC pre-RA + mini-opt |
| Store-to-load forwarding / DSE entre bloques | Ausente (lcc lo hace dentro de un bloque con el DAG) | Funciones con llamadas y huecos fríos que `stackslots` no cubre | Media | mini-opt (huecos privados: sin aliasing) |
| Valores vivos a través de calls | Limitado | Alto en calls/recursión/softfloat | Media-alta | RA/backend |
| Slot coloring de spills | Ausente | Frame/memoria; depende de presión | Media | pre-emisión |
| ~~Tail calls directas~~ | **Hecho, restringido:** solo epílogos y destinos demostrablemente seguros. Decidido dejarlo así | 36 instrucciones adicionales en mini-tst. En `z.tui`: +99 instrucciones estáticas (+0,8 %) y −6 ejecutadas en la demo; ahorra 1 instrucción y 1 salto tomado por ejecución, y pila en recursión (sección 11) | Baja-media | mini-opt |
| ~~Unreachable asm~~ | **Hecho:** branches conocidos + poda por CFG | 27 instrucciones adicionales frente al pipeline anterior | Baja | mini-opt |
| ~~Rama invertida~~ | **Hecho:** pase `invert`, `Bcc a,b,L1 ; BRA L2 ; L1:` → `B!cc a,b,L2 ; L1:`; solo con `L2` en la misma función y menos de 32.000 instrucciones (el branch condicional lleva 16 bits) | Suite 20.459 → 20.420 (−39); `z.tui` −71 instrucciones (−0,6 %) | Baja | mini-opt |
| ~~Booleano como valor~~ | **Hecho:** pase `boolean`, `Bcc ; MOVI r,1 ; BRA ; Lf: ; r=0 ; Le:` → `SLT`/`SLTU` (+ `XORI`; `SUB` para `BEQ`/`BNE`); sin liveness, solo si nadie más salta a `Lf` | Suite 20.420 → 20.242 (−178); `z.tui` −70 instrucciones (29 de 40 casos); cubo y rotación sin cambios | Baja | mini-opt |
| Guardados de R16–R29 en funciones de CPU | **Sin acción:** en kernels de GPU ya los quita `mini-opt:kernels`; en CPU los exige la ABI y lcc guarda solo los usados | `cube_cpu`: 28 accesos por fotograma de ~321.000 instrucciones (0,009 %). Solo importaría en una función pequeña y muy llamada | Alta (interprocedural o shrink wrapping) | RA/backend |
| Helpers `__mini_*` opacos para `mini-opt` | **Medido y descartado por ahora:** 3,3 % de las instrucciones de mini-tst y ninguna en los ejemplos (sección 9) | Reabrir si un programa usa soft-float, `divfx` o `memcpy` grande | Media | lcc + mini-opt |
| ~~Plegado de constantes ampliado y base compartida de `LI`~~ | **Hecho:** `constprop` (evaluación de dos constantes, identidades, fusión MUL+SHL; las copias no se evalúan para no dejar sin trabajo a `copyprop`) y `sharebase` | `sharebase` ~1–2 % en el cubo en placa | Baja | mini-opt |
| ~~LICM aritmética~~ | **Hecho, también en bucles anidados:** de dentro afuera, lo que sube del bucle interior sube del exterior si no depende de él. Un fallo del análisis de definiciones que alcanzan (una `ENTRY` falsa atrapada en el ciclo) lo impedía y se corrigió | Rotación GPU buena 1,04× → 1,01× el ASM; CPU 1,00×; `fill_rect`/`blit` −1,5 % a −2 % | Baja | mini-opt |
| ~~LICM de memoria~~ | **Hecho, ahora demostrado en lugar de supuesto:** en un kernel, la carga de una global que el kernel solo lee sale del bucle si ningún puntero puede alcanzarla. `mini-opt` mira la unidad entera (la dirección no escapa de ninguna función: solo base de `LOAD`/`STORE`, directa o por un puntero calculado a partir de ella; no está en un `.word`), lcc le dice qué símbolos son `volatile` con `; @miniopt volatile NOMBRE`, y `build.py` le pasa el arranque, el runtime y la otra unidad (`--extern-refs`). `--assume-noalias` queda como suposición explícita, apagada por defecto | Mismo resultado que con la suposición en el cubo (~2 %, 1,326 M ciclos), sin ella. Supuestos que no se pueden comprobar desde el texto: que nadie escriba el símbolo mientras el kernel corre y que no se fabrique un puntero desde un entero | Media | mini-opt + hecho de lcc |
| Relajar frame a 4 | Ausente | Memoria, no instrucciones | Baja, cambio ABI | backend/ABI |
| 6/8 args | ABI actual 4 | 4/8 instrucciones en sum8 (estimado) | Alta por scratch/compatibilidad | ABI+backend |
| Metadatos slot/virtual | **Parcial:** el mecanismo existe y lleva un solo hecho, `; @miniopt volatile NOMBRE` (lcc lo escribe en un comentario, `parse_unit` lo lee). Ausentes los de slot/spill/escape/virtual y las salvaguardas propuestas en la sección 9 (cabecera versionada, hash de la secuencia, validación) | `volatile` habilita la LICM de cargas demostrada. Los de slot y virtual: habilitador, no beneficio directo | Media | backend comments |

## 13. Plan incremental sugerido

1. ~~**Integración medida, sin ABI:** aplicar `mini-opt` al pipeline C de CPU de
   forma opt-in y correr mini-tst completo antes/después.~~ **Hecho:**
   `--optimize` y `--compare-optimizer`; 23.551 → 20.384 instrucciones
   (−13,4 %) tras integrar también `stackslots`, `sharebase` y la propagación
   rica del trabajo paralelo. Evolución de la medida con `rcc` reconstruido
   y `--simulate --compare-optimizer` (166/166 casos simulados, +2 xfail):

   | Estado | Instrucciones | Tests de mini-opt |
   |---|---:|---:|
   | Tras `mini.md:local` | 23.601 → 20.459 (−13,3 %) | 155 |
   | + `invert` | 23.601 → 20.420 (−13,5 %) | 165 |
   | + `boolean` (actual) | 23.601 → 20.242 (−14,2 %) | 177 |

   El sin optimizar creció 50 y el optimizado 75 respecto a la medida anterior
   a `mini.md:local`; no se ha desglosado cuánto es de los tests nuevos y
   cuánto de ese cambio. Los 177 tests incluyen 3 que compilan la demo de
   `z.tui` (se omiten sin MSVC); además hay 134 de simulación CPU+GPU. La tabla
   de instrucciones ejecutadas de `examples/c` no cambia con `invert` ni
   `boolean`.
2. **Quick wins post-RA:** ~~eliminar inalcanzables tras branches conocidos~~ y
   ~~tail-call directo muy restringido~~ **(hechos)**, y los dos peepholes que
   quedaban, ~~rama invertida~~ y ~~booleano como valor~~ **(hechos, sin
   liveness)**; ampliar más peepholes solo con liveness/CFG. Verificar cada uno
   con asm manual adversarial, volatile y llamadas indirectas. `tailcalls`
   rechaza ahora cualquier función (origen o destino) que calcule una
   dirección de su marco (`takes_frame_address`): con el marco ya cerrado el
   destino podía pisarla. Con un caso reproducido en el simulador de CPU.
3. **Promoción local pre-RA:** ~~mantener escalares no addressed en
   temporales aunque `ref<3`~~ **(hecho, `mini.md:local`)**: en una hoja, un
   escalar de 4 bytes sin dirección tomada va a un temporal R7–R15 si `ref<3`
   o si no caben en R16–R29 (dejando 5 temporales para expresiones). El
   `__kernel_cube_good` ya no toca la pila sin `stackslots`; este pase queda
   como red de seguridad (test con el `.s` de antes en `StackSlotsTest`).
   Pendiente: store-to-load forwarding y DSE entre bloques, y la misma idea
   para funciones con llamadas (necesita R16–R29 y su coste de save).
4. **Calls/spills:** asignar valores que cruzan llamadas a R16–R29 comparando el
   coste save/restore con stores por call. Medir `calls`, `recursive`, soft-float
   y 64-bit helpers.
5. **Slots:** colorear únicamente temps de spill por intervalos no solapados;
   no mezclar variables addressed. Medir frame y stack traffic.
6. **Reevaluar ABI:** solo tras esos pasos. Recoger distribución real del número
   de argumentos y profundidad de pila; entonces decidir alineación 4 y quizá
   más registros de argumentos. No combinar ambos cambios para conservar una
   atribución clara.
7. **Metadatos:** ~~primer hecho, `volatile`~~ **(hecho)**. Añadir más solo si
   una transformación demostrada necesita identidad de spill/escape. El hecho
   `volatile` no lleva todavía versión ni hash; al añadir el segundo formato
   hay que versionar y validar desde el principio.

Cada fase es independiente salvo que el análisis de spills se beneficia de la
promoción anterior. No hace falta esperar a cambios ABI para integrar mini-opt,
promover locales o ampliar prudentemente las tail calls.

## 14. Conclusiones para decisión

- **Tres de mayor beneficio probable:** ~~promoción de escalares~~ **(hecha)**
  y DSE/forwarding entre bloques; asignación consciente de llamadas;
  copyprop/DCE post-RA ya existente.
- **Tres más fáciles:** ~~integrar copyprop/DCE existente~~ **(hecho)**;
  ~~unreachable/branch cleanup~~ **(hecho)**; ~~tail-call directo restringido~~ **(hecho)** (la alineación a 4 es aún más simple,
  pero no mejora instrucciones). El resto de peepholes de TODO.md
  (~~rama invertida~~, ~~booleano como valor~~) también está hecho.
- **¿Cambiar MiniABI ya?** No. Solo considerar alineación por memoria como cambio
  separado; 6/8 argumentos requiere antes resolver scratch y medir corpus.
- **¿Metadatos?** Ya hay uno, `volatile`, porque la LICM de cargas no puede
  decidir sin él. Los de slots/virtuales/escape siguen siendo innecesarios para
  los pases actuales: no priorizarlos.
- **¿Hace falta mini-opt?** Ya existe y sí aporta; no sustituye mejoras pre-RA.
  La arquitectura adecuada es híbrida.
- **Cambios independientes:** integración mini-opt, promotion/DSE, tail calls,
  slot coloring y alineación pueden evaluarse por separado.
- **Validación:** mini-tst simulada completa, 177 tests de mini-opt, corpus de
  probes, volatile/MMIO, 64 bits, recursión, >4 args, y comparación dinámica en
  simulador. Para ciclos reales, usar después `test-board --measure`; esta
  auditoría no inventa equivalencia entre instrucciones y ciclos.

Esta fase no modifica MiniABI. Implementa la integración opt-in de `mini-opt`,
DCE físico independiente, simplificación de branches constantes/idénticos,
eliminación de bloques inalcanzables, tail calls directas restringidas,
`stackslots`, `sharebase`, plegado ampliado, LICM de loads opt-in, rama
invertida (`invert`) y booleano como valor (`boolean`). En el
compilador, un único cambio: en hojas, los locales que no caben en R16–R29 o
tienen `ref<3` van a temporales (`mini.md:local`). El resto de oportunidades
permanece abierto.
