# Trace --- Metodología de ingeniería y cierre progresivo de especificaciones

## 1. Propósito

Trace no presupone que un proyecto nazca perfectamente especificado.

Esta metodología describe cómo utilizar el metamodelo y las herramientas
de Trace para:

-   desarrollar sistemas top-down;
-   incorporar proyectos existentes;
-   descubrir huecos entre documentación e implementación;
-   convertir conocimiento disperso en diseño explícito;
-   cerrar decisiones;
-   completar especificaciones;
-   conectar implementación y verificación;
-   evolucionar versiones sin perder contexto;
-   utilizar agentes de ingeniería de forma controlada.

Este documento es metodológico, no normativo respecto al ProjectModel.
Cambiar esta metodología no cambia por sí mismo la validez semántica de
un modelo Trace.

------------------------------------------------------------------------

## 2. Idea central

Un proyecto real rara vez sigue una línea perfecta:

``` text
NEED
  ↓
REQUIREMENT
  ↓
SPECIFICATION
  ↓
IMPLEMENTATION
  ↓
VERIFICATION
```

En la práctica encontramos:

-   código anterior a la documentación;
-   tests que revelan comportamiento no especificado;
-   simuladores y RTL que discrepan;
-   decisiones tomadas en conversaciones;
-   documentos parciales;
-   especificaciones que evolucionan;
-   nuevas versiones todavía WIP;
-   comportamiento accidental que no queremos convertir en contrato.

Trace debe permitir trabajar en ese estado intermedio.

El objetivo es **hacer progresivamente explícito el conocimiento de
ingeniería**.

------------------------------------------------------------------------

## 3. Tres modos de trabajo

### 3.1 Top-down

Adecuado cuando se diseña algo nuevo:

``` text
NEED
 ↓
REQ
 ↓
DESIGN
 ↓
DECISION
 ↓
SPEC
 ↓
IMPL
 ↓
VER
 ↓
EVID
```

No todos los pasos son obligatorios para cada cambio.

Un cambio trivial puede ir directamente de SPEC a IMPL.

DESIGN y DECISION aparecen cuando existe razonamiento de ingeniería que
merece conservarse.

------------------------------------------------------------------------

### 3.2 Bottom-up

Adecuado para proyectos existentes:

``` text
IMPL + simulador + tests + documentación parcial
                     ↓
               model discovery
                     ↓
             posibles spec gaps
                     ↓
                  DESIGN
                     ↓
             DECISION si hace falta
                     ↓
                   SPEC
                     ↓
         trazabilidad implements/verifies
```

El objetivo no es justificar retroactivamente cualquier comportamiento
existente.

El objetivo es distinguir:

-   comportamiento intencional;
-   comportamiento accidental;
-   discrepancias;
-   decisiones todavía no cerradas;
-   contrato que realmente queremos mantener.

------------------------------------------------------------------------

### 3.3 Iterativo

Es probablemente el modo normal:

``` text
              SPEC parcial
              ↙         ↘
           IMPL         VER
              ↘         ↙
              observación
                   ↓
            gaps / cambios
                   ↓
                DESIGN
                   ↓
        decisión o nueva SPEC
                   ↓
                 ...
```

Trace debe soportar esta realimentación sin exigir que todo el proyecto
esté cerrado.

------------------------------------------------------------------------

## 4. Qué significa "cerrar" una parte del sistema

Una parte está progresivamente mejor cerrada cuando podemos contestar
con claridad:

1.  ¿qué necesidad o requisito la motiva?
2.  ¿qué especificación define su comportamiento?
3.  ¿qué implementación pretende realizarla?
4.  ¿cómo se verifica?
5.  ¿qué evidencia concreta tenemos?
6.  ¿qué decisiones justifican los aspectos no obvios?
7.  ¿qué cuestiones siguen abiertas?

No existe una obligación universal de tener todos esos elementos para
cada símbolo.

El nivel de trazabilidad requerido es una política del proyecto.

------------------------------------------------------------------------

## 5. Caso MiniGPU: documentación parcial

Supongamos que MiniGPU contiene:

``` text
ISA
ABI
memory map
MMIO
ISA extensions
simulator
RTL
tests
assembler/compiler
```

Parte de la ISA puede estar especificada formalmente, mientras que
algunas extensiones hayan surgido directamente durante implementación.

Podemos encontrar:

``` text
             assembler   simulator   RTL   tests   SPEC
SSY              ✓           ✓        ✓      ✓       ✓
BAR              ✓           ✓        ✓      ✓       ?
EXIT             ✓           ✓        ✓      ✓       ?
```

La ausencia de una columna SPEC conocida no demuestra automáticamente un
defecto, pero constituye una señal excelente para investigar.

------------------------------------------------------------------------

## 6. Qué es un specification gap

Un **specification gap** es una hipótesis de trabajo:

> Existe comportamiento relevante u observable en el sistema para el que
> no encontramos un contrato normativo suficiente.

No es necesariamente un Artifact core.

Puede ser el resultado de una query, regla o análisis.

Ejemplo:

``` text
GAP: BAR semantics

Observed in:
  simulator
  RTL
  assembler
  tests

Existing normative target:
  none or incomplete

Questions:
  participation mask?
  interaction with EXIT?
  multiple barriers?
```

------------------------------------------------------------------------

## 7. No todos los símbolos necesitan especificación

Una query ingenua:

``` text
all implementation symbols without incoming/outgoing implements
```

produciría demasiado ruido.

Un sistema contiene multitud de detalles internos:

-   helpers;
-   registros de pipeline;
-   funciones auxiliares;
-   FSM states;
-   glue logic;
-   temporales;
-   optimizaciones.

No necesitan una SPEC independiente.

La detección de gaps debe concentrarse en superficies relevantes, por
ejemplo:

-   interfaces observables;
-   instrucciones;
-   registros MMIO;
-   formatos;
-   protocolos;
-   APIs;
-   comportamiento visible;
-   requisitos de timing;
-   configuraciones soportadas;
-   capabilities.

El proyecto puede aportar reglas y adapters de dominio para identificar
esas superficies.

------------------------------------------------------------------------

## 8. Señales para detectar gaps

Un gap gana relevancia cuando el mismo concepto aparece en varias
fuentes.

Por ejemplo:

``` text
BAR
├── opcode en assembler
├── implementación en simulator
├── decode/execute en RTL
├── tests
└── sin sección normativa
```

O:

``` text
MMIO FONT_POS
├── dirección usada por software
├── registro en RTL
├── test de acceso
└── sin definición de lectura/escritura en SPEC
```

Cuantas más fuentes independientes convergen, más útil es investigar el
concepto.

------------------------------------------------------------------------

## 9. Queries de cobertura

Trace puede proporcionar queries reutilizables:

``` text
unimplemented
unverified
not_fully_verified
unspecified
specification_gaps
```

Deben interpretarse con precisión.

### `unimplemented`

Busca objetivos normativos sin una relación de implementación esperada.

### `unverified`

Busca objetivos sin verificación conocida.

### `not_fully_verified`

Busca objetivos para los que no existe cobertura `complete` declarada.

No equivale a `unverified`.

### `unspecified`

Busca elementos de implementación relevantes sin conexión normativa
suficiente según la política/query utilizada.

No significa automáticamente "error".

### `specification_gaps`

Puede combinar información de varios dominios para localizar
comportamiento aparentemente importante que carece de contrato
suficiente.

------------------------------------------------------------------------

## 10. Del gap al DESIGN

Cuando existe incertidumbre, no debe escribirse directamente una SPEC.

Primero puede crearse un DESIGN.

Ejemplo:

``` text
DES-MINIGPU-BAR
type: design
status: draft
```

Puede reunir:

``` text
Problem
Observed behavior
Existing documentation
RTL behavior
Simulator behavior
Tests
Alternatives
Questions
Proposed semantics
```

Esto permite trabajar con conocimiento incompleto sin otorgarle
autoridad normativa antes de tiempo.

------------------------------------------------------------------------

## 11. Cuando las implementaciones coinciden

Supongamos:

``` text
RTL:
  BAR waits for all active warps in the workgroup.

Simulator:
  same behavior.

Tests:
  cover 1, 2 and 4 active warps.

Documentation:
  missing.
```

La coincidencia es evidencia útil, pero no convierte automáticamente ese
comportamiento en especificación.

El flujo recomendado es:

``` text
observed agreement
      ↓
DESIGN / review
      ↓
confirm intentional behavior
      ↓
SPEC
      ↓
implements/verifies relations
```

El paso de observación a norma debe ser explícito.

------------------------------------------------------------------------

## 12. Cuando las implementaciones discrepan

Ejemplo:

``` text
RTL
  waits for all warps

Simulator
  waits for active warps only

Tests
  do not distinguish the cases

SPEC
  silent
```

El resultado correcto del análisis no es elegir arbitrariamente una
fuente.

Debe registrarse la contradicción:

``` text
DES-MINIGPU-BAR

Known:
  opcode
  operands
  basic synchronization behavior

Conflict:
  RTL        -> all warps
  simulator  -> active warps

Tests:
  insufficient to distinguish

Open question:
  intended participation semantics
```

Después puede producirse una DECISION:

``` text
DEC-MINIGPU-BAR-PARTICIPATION
```

y finalmente actualizar la SPEC.

------------------------------------------------------------------------

## 13. DESIGN, DECISION y SPEC

Esta secuencia es central:

``` text
DESIGN
  "estamos razonando"

     ↓

DECISION
  "hemos elegido"

     ↓

SPECIFICATION
  "esto es lo que debe cumplirse"
```

No toda SPEC necesita una DECISION.

No todo DESIGN termina en una DECISION.

Una exploración puede descartarse.

Una DECISION puede afectar a varias SPECs.

Una SPEC puede integrar varias decisiones.

------------------------------------------------------------------------

## 14. El papel de la implementación existente

En reverse engineering de un proyecto propio, la implementación es una
fuente de conocimiento, pero no necesariamente la autoridad normativa.

Debe distinguirse:

``` text
"el RTL hace X"
```

de:

``` text
"el sistema debe hacer X"
```

El primero es una observación.

El segundo es una afirmación normativa.

Trace debe ayudar a conservar esa frontera.

------------------------------------------------------------------------

## 15. El papel de los tests

Los tests son especialmente valiosos porque revelan expectativas.

Pero tampoco deben confundirse automáticamente con especificación.

Un test puede:

-   codificar el contrato correcto;
-   cubrir solo un caso;
-   reflejar comportamiento accidental;
-   estar obsoleto;
-   ser insuficiente para distinguir alternativas.

Por ello:

``` text
test passes
```

no implica:

``` text
specification complete
```

------------------------------------------------------------------------

## 16. El papel del simulador

En proyectos como MiniGPU puede haber:

``` text
SPEC
simulator funcional
RTL
```

Idealmente:

``` text
SIM --implements--> SPEC
RTL --implements--> SPEC
```

El simulador no debe convertirse implícitamente en la especificación
solo porque sea más fácil de leer que el RTL.

Cuando SIM y RTL discrepan y la SPEC no resuelve la cuestión, existe un
problema de ingeniería que debe hacerse explícito.

------------------------------------------------------------------------

## 17. Especificaciones compuestas

Un sistema puede tener contratos separados:

``` text
SPEC-MINIGPU-ISA
SPEC-MINIGPU-ABI
SPEC-MINIGPU-MEMORY-MAP
SPEC-MINIGPU-MMIO
SPEC-MINIGPU-ISA-EXTENSIONS
```

Es útil mantenerlos independientes porque:

-   evolucionan de forma diferente;
-   tienen estructuras diferentes;
-   pueden tener owners distintos;
-   pueden ser reutilizados;
-   permiten trazabilidad fina.

Al mismo tiempo, puede existir un contrato de sistema compuesto:

``` text
SPEC-MINIGPU
```

conceptualmente formado por ellos.

Entonces:

``` text
IMPL-MINIGPU-SIM --implements--> SPEC-MINIGPU
IMPL-MINIGPU-RTL --implements--> SPEC-MINIGPU
```

expresa que ambos son realizaciones del mismo modelo arquitectónico.

La semántica definitiva de la composición pertenece al metamodelo.

------------------------------------------------------------------------

## 18. Relaciones finas y globales

La relación global es útil:

``` text
IMPL-MINIGPU-RTL implements SPEC-MINIGPU
```

pero no sustituye relaciones precisas cuando aportan valor:

``` text
IMPL-MINIGPU-RTL::lsu
    implements SPEC-MINIGPU-ISA#memory

IMPL-MINIGPU-SIM::execute_ssy
    implements SPEC-MINIGPU-ISA#ssy
```

La primera responde:

> ¿Qué implementación realiza MiniGPU?

Las segundas responden:

> ¿Dónde se implementa exactamente esta parte?

Ambas granularidades pueden coexistir.

------------------------------------------------------------------------

## 19. Evolución normal de una SPEC

Durante desarrollo normal:

``` text
commit A             commit B

SPEC-MYTOOL          SPEC-MYTOOL
```

aunque el contenido cambie.

Git conserva la historia.

No se crean IDs de Artifact nuevos por cada revisión.

------------------------------------------------------------------------

## 20. Cuándo crear V1 y V2

Se crean identidades diferentes cuando necesitamos razonar
simultáneamente sobre ambas:

``` text
SPEC-MYTOOL-V1
SPEC-MYTOOL-V2
```

Por ejemplo:

-   V1 sigue desplegada;
-   tests antiguos verifican V1;
-   V2 está en desarrollo;
-   implementaciones distintas soportan versiones distintas.

Cuando V2 reemplaza V1:

``` text
SPEC-MYTOOL-V2 --supersedes--> SPEC-MYTOOL-V1
```

Esto no implica herencia de contenido.

------------------------------------------------------------------------

## 21. V2 como Work In Progress

Un flujo habitual:

``` text
SPEC-V1 accepted
       │
       ▼
SPEC-V2-WIP draft
```

El WIP puede contener inicialmente solo cambios:

``` text
+ YAML
+ configuration
Δ parser
Δ errors
```

y recibir relaciones propias:

``` text
DES-YAML
IMPL-YAML-PROTOTYPE
VER-YAML-PROTOTYPE
```

sin fingir que V2 está terminada.

------------------------------------------------------------------------

## 22. Dos destinos del WIP

### 22.1 Extensión incremental

Si V2 es realmente:

``` text
V1 + nuevas secciones
```

un futuro `extends` puede ser una representación natural.

### 22.2 Materialización

Si los cambios deben insertarse y reorganizarse por todo el documento:

``` text
V1
+
WIP
+
reorganización editorial
=
V2 completa
```

la V2 final puede ser un nuevo documento autocontenido.

El WIP es entonces un espacio de elaboración, no una plantilla textual
obligatoria para la SPEC final.

------------------------------------------------------------------------

## 23. `extends`

La metodología puede aprovechar en el futuro:

``` text
SPEC-V2 --extends--> SPEC-V1
```

para expresar herencia normativa.

Pero debe mantenerse separado de:

``` text
derived-from
supersedes
```

El uso de `extends` requiere que el metamodelo cierre primero:

-   overrides;
-   removals;
-   effective specification;
-   materialization;
-   interacción con relaciones existentes.

Hasta entonces no debe simularse con otra relación.

------------------------------------------------------------------------

## 24. Materialización

Una futura operación:

``` text
trace materialize SPEC-V2-WIP
```

podría producir una vista efectiva como ayuda.

No debería asumirse que puede realizar automáticamente toda la edición
intelectual necesaria.

Un WIP puede necesitar:

-   mover contenido;
-   fusionar secciones;
-   dividir secciones;
-   reescribir explicaciones;
-   resolver contradicciones;
-   eliminar material obsoleto.

La herramienta prepara contexto; el cierre editorial y normativo puede
requerir revisión humana.

------------------------------------------------------------------------

## 25. IDs formales durante evolución

Los IDs formales son especialmente valiosos para contenido que:

-   recibe relaciones externas;
-   será reorganizado;
-   está en WIP;
-   probablemente cambiará de título;
-   debe sobrevivir a refactors documentales.

Una sección:

``` text
SPEC-V2-WIP#yaml
```

puede mantener continuidad semántica aunque cambie su heading o
posición.

------------------------------------------------------------------------

## 26. `trace impact`

Cuando cambia una parte:

``` text
SPEC-MINIGPU-ISA#bar
```

`trace impact` puede mostrar:

``` text
implementations
verifications
requirements
decisions
dependent specifications
```

La salida significa:

> estos elementos merecen revisión

no:

> estos elementos están rotos.

------------------------------------------------------------------------

## 27. `trace diff`

Una futura comparación semántica entre revisiones:

``` text
trace diff revA revB
```

puede construir dos ProjectModels y comparar:

-   Artifacts;
-   Sections;
-   Facets;
-   Symbols;
-   relaciones;
-   metadata relevante.

Esto permite distinguir mejor cambios semánticos de simples cambios
textuales.

Después puede calcularse impacto.

------------------------------------------------------------------------

## 28. El agente como consumidor del ProjectModel

Un agente no debería comenzar leyendo indiscriminadamente todo el
repositorio.

Trace puede ofrecerle un slice contextual.

Ejemplo:

``` text
"Estudia el gap de BAR"

        ↓

ProjectModel

        ↓

SPEC relacionada
RTL symbols
simulator symbols
tests
decisions
sources
incoming/outgoing relations

        ↓

Agent
```

Esto reduce contexto y aumenta explicabilidad.

------------------------------------------------------------------------

## 29. Flujo de un agente para cerrar un gap

Un flujo recomendable:

``` text
1. localizar gap
2. identificar concepto
3. consultar relaciones
4. leer SPEC cercana
5. inspeccionar implementaciones
6. inspeccionar verificaciones
7. detectar acuerdos y contradicciones
8. producir DESIGN draft
9. señalar preguntas abiertas
10. esperar decisión cuando sea necesaria
11. proponer cambio de SPEC
12. proponer relaciones de trazabilidad
13. ejecutar trace check
```

El agente debe distinguir claramente hechos observados de propuestas.

------------------------------------------------------------------------

## 30. Qué puede automatizar un agente

Puede ayudar a:

-   localizar comportamiento no documentado;
-   resumir varias implementaciones;
-   comparar SIM y RTL;
-   encontrar tests relevantes;
-   extraer tablas de opcodes;
-   proponer estructura documental;
-   redactar DESIGN;
-   redactar una SPEC propuesta;
-   sugerir relaciones;
-   detectar posibles inconsistencias;
-   preparar una revisión.

------------------------------------------------------------------------

## 31. Qué no debe decidir silenciosamente

No debe convertir automáticamente en norma:

-   el comportamiento del RTL;
-   el comportamiento del simulador;
-   un test existente;
-   una implementación mayoritaria;
-   una suposición inferida.

Cuando existe ambigüedad:

``` text
observed A
observed B
no normative answer
```

el resultado correcto es una cuestión explícita, no una invención.

------------------------------------------------------------------------

## 32. Context packs

Una extensión útil de Trace puede ser generar paquetes de contexto para
humanos o agentes.

Conceptualmente:

``` text
trace context SPEC-MINIGPU-ISA#bar
```

podría reunir:

``` text
Target
Nearby specification
Incoming relations
Outgoing relations
Implementations
Verifications
Evidence
Decisions
Sources
Relevant locations
Diagnostics
```

No necesita ser un nuevo Artifact.

Es una vista calculada del ProjectModel.

------------------------------------------------------------------------

## 33. Cierre progresivo del proyecto

Un proyecto existente puede comenzar así:

``` text
code ███████████████████
spec ███████
test ████████████
trace ██
```

y mejorar progresivamente:

``` text
iteration 1
  documentar ISA crítica

iteration 2
  conectar RTL y simulator

iteration 3
  cubrir MMIO

iteration 4
  cerrar gaps de ABI

iteration 5
  añadir verification/evidence
```

Trace debe aportar valor desde la primera iteración.

No debe exigir una migración "big bang".

------------------------------------------------------------------------

## 34. Priorización de gaps

No todos los gaps tienen la misma importancia.

Una metodología práctica puede priorizar por:

-   comportamiento externally visible;
-   riesgo;
-   frecuencia de cambio;
-   número de implementaciones;
-   complejidad;
-   impacto;
-   criticidad;
-   discrepancias detectadas;
-   ausencia de tests.

Esta priorización es una política/query de proyecto, no semántica core.

------------------------------------------------------------------------

## 35. Uso de reglas

Cuando una zona ya está madura, una práctica inicialmente informativa
puede convertirse en regla.

Ejemplo:

Primero:

``` text
query:
  mostrar instrucciones sin SPEC
```

Más adelante:

``` text
rule:
  toda instrucción accepted debe tener sección normativa formal
```

Esto permite endurecer el proyecto gradualmente.

------------------------------------------------------------------------

## 36. De descubrimiento a enforcement

Patrón recomendado:

``` text
observe
   ↓
query
   ↓
understand
   ↓
document
   ↓
trace
   ↓
rule
   ↓
enforce
```

No empezar necesariamente por `error`.

Una query es útil para aprender el proyecto antes de convertir una
expectativa en política obligatoria.

------------------------------------------------------------------------

## 37. gendoc como vista, no como autoridad

Una vez existe ProjectModel, pueden generarse vistas:

-   tabla de instrucciones;
-   mapa MMIO;
-   coverage;
-   requirements sin implementar;
-   gaps;
-   P&R;
-   timing.

Estas vistas pueden materializarse en documentación.

Pero la salida generada no debe convertirse en la única fuente de los
datos de los que depende.

------------------------------------------------------------------------

## 38. Ejemplo MiniGPU completo

Estado inicial:

``` text
isa.md
memory-map.md
RTL
simulator
assembler
tests
```

Se descubre:

``` text
SSY
  SPEC ✓
  RTL ✓
  SIM ✓
  TEST ✓

BAR
  SPEC parcial
  RTL ✓
  SIM ✓
  TEST ✓

GETWID
  proposal ✓
  RTL prototype ?
  SIM ✓
  TEST partial
```

Proceso:

``` text
BAR
 ↓
DES-MINIGPU-BAR
 ↓
resolver semántica de participación
 ↓
DEC-MINIGPU-BAR-PARTICIPATION
 ↓
actualizar SPEC-MINIGPU-ISA#bar
 ↓
enlazar RTL/SIM
 ↓
revisar tests
 ↓
trace check
```

Para GETWID puede ocurrir otra cosa:

``` text
propuesta todavía abierta
 ↓
mantener DESIGN / SPEC proposed
 ↓
no declarar soporte accepted
```

El modelo refleja la madurez real en lugar de ocultarla.

------------------------------------------------------------------------

## 39. Ejemplo Trace sobre sí mismo

Trace puede utilizar Trace.

Podemos tener:

``` text
SPEC-TRACE-METAMODEL
SPEC-TRACE-TOOL
DES-TRACE-EXTENDS
IMPL-TRACE
VER-TRACE
```

y, cuando se estabilice la composición normativa:

``` text
SPEC-TRACE
├─ metamodel
├─ tool behavior
└─ otros contratos
```

La propia evolución del sistema sirve como prueba de que el metamodelo
soporta:

-   documentación parcial;
-   diseño WIP;
-   decisiones;
-   especificación;
-   implementación;
-   verificación;
-   evolución.

------------------------------------------------------------------------

## 40. Criterio para elegir Artifact

Una guía práctica:

### NEED

"Necesitamos..."

### REQUIREMENT

"El sistema deberá..."

### DESIGN

"Estamos estudiando...", "estas son las alternativas...", "todavía falta
resolver..."

### DECISION

"Elegimos X porque..."

### SPECIFICATION

"El sistema se comporta/debe comportarse así..."

### IMPLEMENTATION

"Esta realización concreta implementa..."

### VERIFICATION

"Comprobamos este contrato mediante..."

### EVIDENCE

"Esta ejecución/medida concreta produjo..."

### SOURCE

"Esta información procede de esta referencia externa..."

------------------------------------------------------------------------

## 41. Criterio para separar documentos

El número de archivos no determina el número de Artifacts.

La pregunta útil es:

> ¿Cuántas unidades quiero identificar, relacionar, versionar y razonar
> independientemente?

ISA, ABI y MMIO pueden ser SPECs distintas aunque conjuntamente definan
un sistema.

Dos capítulos físicos pueden pertenecer a una misma unidad lógica si el
modelo y la representación elegida lo permiten.

RESOURCE responde:

> ¿dónde está?

ARTIFACT responde:

> ¿qué entidad de ingeniería es?

------------------------------------------------------------------------

## 42. Criterio para separar metamodelo, herramienta y metodología

### Metamodelo

Cambia qué significa el ProjectModel.

Ejemplos:

-   nuevo Artifact type;
-   nueva relación;
-   semántica de `implements`;
-   reglas de identidad.

### Herramienta

Cambia lo que Trace puede hacer.

Ejemplos:

-   `trace impact`;
-   `trace diff`;
-   `trace context`;
-   `gendoc`;
-   filtros;
-   formato JSON.

### Metodología

Cambia cómo recomendamos trabajar.

Ejemplos:

-   primero crear DESIGN;
-   priorizar gaps;
-   cuándo promover una query a rule;
-   cómo usar agentes;
-   cómo cerrar una V2.

------------------------------------------------------------------------

## 43. Flujo recomendado para adopción en un proyecto existente

``` text
1. Añadir Trace sin exigir cobertura total.
2. Identificar SPECs existentes.
3. Identificar implementaciones principales.
4. Añadir relaciones globales obvias.
5. Añadir adapters/queries de dominio.
6. Ejecutar análisis de gaps.
7. Priorizar comportamiento observable y crítico.
8. Crear DESIGN para zonas ambiguas.
9. Cerrar decisiones necesarias.
10. Completar SPEC.
11. Añadir trazabilidad fina.
12. Conectar VERIFICATION.
13. Preservar EVIDENCE cuando aporte valor.
14. Convertir expectativas maduras en Rules.
15. Repetir.
```

------------------------------------------------------------------------

## 44. Objetivo final

El objetivo no es maximizar el número de relaciones.

Es conseguir que el proyecto pueda responder preguntas de ingeniería
importantes:

``` text
¿Por qué existe esto?

¿Qué contrato lo define?

¿Dónde está implementado?

¿Cómo sabemos que funciona?

¿Qué partes no están especificadas?

¿Qué está todavía en diseño?

¿Qué decisiones llevaron a este comportamiento?

¿Qué puede verse afectado si cambio esta sección?

¿Qué versión implementa este backend?

¿Dónde discrepan las realizaciones?

¿Qué información necesita un humano o un agente para cerrar este gap?
```

Trace es útil cuando esas respuestas emergen del modelo y de las fuentes
reales del proyecto, no de conocimiento tribal.

------------------------------------------------------------------------

## 45. Principio final

La trazabilidad no es un requisito previo para empezar a usar Trace.

Es un estado al que el proyecto puede aproximarse progresivamente:

``` text
conocimiento disperso
        ↓
observación
        ↓
estructura
        ↓
DESIGN
        ↓
DECISION
        ↓
SPECIFICATION
        ↓
IMPLEMENTATION + VERIFICATION
        ↓
EVIDENCE
        ↓
modelo de ingeniería cada vez más cerrado
```

Ese proceso progresivo es uno de los casos de uso centrales de Trace.
