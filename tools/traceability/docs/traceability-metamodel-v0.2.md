# Metamodelo de trazabilidad y documentación

**Versión:** 0.2  
**Estado:** diseño conceptual  
**Ámbito inicial:** MiniGPU  
**Objetivo:** aplicable también a proyectos de CPU, FPGA, firmware, software, electrónica, sistemas embebidos y sistemas espaciales.

---

## 1. Propósito

Este documento define un metamodelo ligero para mantener documentación técnica, diseño, implementación y verificación conectados mediante trazabilidad explícita.

El problema que intenta resolver es habitual en proyectos técnicos que evolucionan rápidamente:

- la documentación deja de coincidir con la implementación;
- no queda claro por qué existe una determinada decisión;
- resulta difícil determinar qué implementa una especificación;
- resulta difícil determinar qué verifica una funcionalidad;
- los resultados de simulación, síntesis, P&R o test quedan desconectados de aquello que pretendían demostrar;
- ciertos datos se mantienen manualmente en varios sitios y terminan divergiendo;
- mover o reorganizar documentación rompe referencias conceptuales;
- la trazabilidad termina dependiendo del conocimiento personal de quien desarrolló el sistema.

El objetivo no es construir una herramienta pesada de gestión de requisitos.

El objetivo es disponer de un modelo suficientemente pequeño para poder mantenerlo cerca del código y de la documentación, pero suficientemente preciso para permitir consultas, validaciones y generación automática de documentación.

La filosofía general puede resumirse en:

> Estructurar únicamente aquello cuya identidad o semántica aporte valor.

Y:

> La documentación generada debe ser una vista de la información autoritativa, no una segunda fuente de verdad.

---

# 2. Principios de diseño

## 2.1. Identidad estable

Los elementos importantes del proyecto pueden adquirir una identidad independiente de su posición física.

Por ejemplo:

```text
SPEC-ISA
DEC-SIMT-RECONVERGENCE
VER-SSY-DIVERGENCE
```

Mover `SPEC-ISA` de un fichero Markdown a otro no cambia su identidad.

---

## 2.2. Los ficheros no son los artifacts

Un fichero es un contenedor físico.

Un artifact es una unidad lógica del proyecto.

Por ejemplo:

```text
docs/isa.md
```

puede ser un `RESOURCE` que contiene la representación de:

```text
SPEC-ISA
```

El mismo fichero podría contener varios artifacts.

De forma inversa, la información relacionada con un artifact podría estar representada mediante diferentes recursos.

---

## 2.3. No todo necesita identidad

Un heading, párrafo, tabla o bloque de código no se convierte automáticamente en artifact.

La identidad se introduce cuando permite hacer algo útil:

- referenciar;
- trazar;
- consultar;
- verificar;
- mantener lifecycle;
- expresar relaciones;
- conservar historia.

Esta regla intenta evitar que la trazabilidad introduzca una carga documental desproporcionada.

---

## 2.4. La estructura documental no es la estructura semántica

Markdown ya proporciona una estructura:

```text
documento
  sección
    subsección
      subsección
```

El metamodelo debe aprovecharla.

Sin embargo, esa estructura no implica automáticamente la creación de artifacts.

Por ejemplo:

```markdown
## Control flow

### JAL

### JALR

### JR
```

puede seguir perteneciendo completamente al artifact:

```text
SPEC-ISA
```

sin crear:

```text
SPEC-JAL
SPEC-JALR
SPEC-JR
```

---

## 2.5. Declarar cada hecho una sola vez

Una relación debe tener una única representación autoritativa.

Si:

```text
A --implements--> B
```

se declara en `A`, no debe almacenarse también manualmente:

```text
B --implemented-by--> A
```

La segunda forma es una vista derivada.

Este principio se aplica también a estados derivados, tablas generadas, índices y resúmenes.

---

## 2.6. Trazabilidad cerca del origen

Siempre que sea posible, una relación se declara junto al elemento que la origina.

Si una sección de especificación deriva de una decisión:

```text
SPEC-ISA#ssy
    --derived-from--> DEC-SIMT-RECONVERGENCE
```

la declaración debe residir junto a `SPEC-ISA#ssy`.

Las bases de datos o sidecars externos se reservan principalmente para recursos que no pueden modificarse.

---

## 2.7. El Markdown sigue siendo documentación humana

El metamodelo no pretende convertir cada documento en una base de datos.

Explicaciones, alternativas, argumentos, diagramas y razonamiento pueden continuar siendo Markdown normal.

La trazabilidad estructura aquello sobre lo que necesitamos identidad, consultas o invariantes.

---

# 3. Modelo conceptual

Las principales entidades son:

```text
RESOURCE
ARTIFACT
SECTION
FACET
RELATION
SUBJECT
GENERATED BLOCK
```

Conceptualmente:

```text
RESOURCE
   │
   └── representación de ARTIFACT
                         │
                         ├── SECTION
                         │     └── SECTION...
                         │
                         └── FACET

ARTIFACT / SECTION / FACET
            │
            └── RELATION ──────> target
```

`SECTION` representa estructura documental.

`FACET` representa estructura semántica.

---

# 4. RESOURCE

Un `RESOURCE` es un contenedor o localización física de información.

Ejemplos:

```text
docs/isa.md
rtl/gpu/simt.sv
tests/test_ssy.py
vendor/w9825g6kh.pdf
https://...
```

Un RESOURCE no es necesariamente un ARTIFACT.

Puede contener:

- uno o varios artifacts;
- secciones;
- contenido generado;
- contenido humano;
- información externa.

La localización es una propiedad de la representación, no de la identidad lógica.

Ejemplos de localización:

```text
Markdown  → file + heading/anchor
Python    → file + symbol
SV        → file + module/symbol
PDF       → file + page/section
Web       → URL + anchor
Git       → repository + commit
```

---

# 5. ARTIFACT

Un `ARTIFACT` es una unidad lógica con identidad estable y significado propio dentro del proyecto.

Ejemplos:

```text
SPEC-ISA
REQ-VIDEO-STABLE
DEC-SIMT-RECONVERGENCE
IMPL-MINIGPU
VER-SSY-DIVERGENCE
```

## 5.1. Metadata mínima

El mínimo universal necesario para declarar un ARTIFACT es:

```text
id
type
```

Por ejemplo:

```text
id: SPEC-ISA
type: specification
```

Todo lo demás es opcional, descubierto o derivado cuando sea posible.

Ejemplos:

```text
kind
status
subjects
relations
```

Mientras que otros datos pueden obtenerse de la representación:

```text
title
resource
location
sections
incoming relations
```

o calcularse mediante análisis del grafo:

```text
implemented
verified
superseded
```

---

# 6. Identidad

Los IDs de ARTIFACT son globalmente únicos dentro del proyecto.

Por ejemplo:

```text
SPEC-ISA
SPEC-VIDEO
DEC-SIMT-RECONVERGENCE
VER-SSY
```

El prefijo es una convención humana útil, pero el tipo no debe depender necesariamente de analizar el nombre.

Por ello:

```text
id: SPEC-ISA
type: specification
```

son conceptualmente dos datos diferentes.

La identidad debe sobrevivir a:

- cambios de título;
- movimientos entre ficheros;
- reorganización documental;
- cambios de heading.

La evolución histórica ordinaria del mismo artifact conserva su identidad y se gestiona mediante control de versiones.

---

# 7. Tipos de ARTIFACT

El núcleo define los siguientes tipos:

```text
NEED
REQUIREMENT
DECISION
SPECIFICATION
IMPLEMENTATION
VERIFICATION
EVIDENCE
SOURCE
```

---

# 8. NEED

Un `NEED` representa una necesidad, problema, objetivo o intención que se desea atender.

Responde principalmente a:

> ¿Por qué queremos hacer esto?

Ejemplo:

```text
NEED-SMOOTH-VIDEO
```

podría expresar:

> Queremos una salida de vídeo estable, sin artefactos visuales durante la actualización.

Un NEED:

- no tiene necesariamente forma normativa;
- no tiene por qué ser directamente verificable;
- puede originar uno o varios requisitos;
- puede ser atendido por decisiones.

Ejemplo:

```text
REQ-VIDEO-NO-TEARING
    --derived-from--> NEED-SMOOTH-VIDEO
```

y:

```text
DEC-DOUBLE-BUFFER
    --addresses--> NEED-SMOOTH-VIDEO
```

No toda motivación del proyecto necesita convertirse en NEED.

Debe adquirir identidad únicamente cuando conservar el razonamiento aporte valor.

---

# 9. REQUIREMENT

Un `REQUIREMENT` representa una obligación cuya satisfacción puede reclamarse.

Responde principalmente a:

> ¿Qué debe cumplirse?

Ejemplo:

```text
REQ-VIDEO-60HZ
```

podría establecer:

> El sistema deberá generar una salida de vídeo con una frecuencia vertical de 60 Hz.

Los requisitos se utilizan cuando una obligación necesita identidad independiente.

No toda frase normativa de una especificación debe convertirse en REQUIREMENT.

Por ejemplo, una regla como:

> R0 siempre devuelve cero.

puede permanecer simplemente dentro de:

```text
SPEC-ISA#r0
```

y ser verificada directamente:

```text
VER-R0
    --verifies--> SPEC-ISA#r0
```

Un REQUIREMENT resulta especialmente útil cuando la obligación posee:

- origen independiente;
- lifecycle propio;
- decisiones asociadas;
- varias especificaciones;
- varias implementaciones;
- verificación propia;
- evidencia propia;
- valor contractual o de sistema.

---

# 10. DECISION

Una `DECISION` representa una decisión de ingeniería que interesa conservar y referenciar.

Responde principalmente a:

> ¿Qué decidimos y por qué?

Ejemplo:

```text
DEC-SIMT-RECONVERGENCE
```

La estructura interna de una decisión no se formaliza en el metamodelo.

Alternativas, criterios, ventajas, inconvenientes y justificación pueden permanecer como Markdown humano:

```markdown
## Contexto

## Alternativas

## Decisión

## Justificación

## Consecuencias
```

No se crean artifacts independientes para cada alternativa salvo que exista una necesidad real de identidad.

---

# 11. SPECIFICATION

Una `SPECIFICATION` define comportamiento, arquitectura, interfaces, protocolos u otros aspectos normativos del diseño.

Responde principalmente a:

> ¿Cómo debe comportarse o estructurarse el sistema?

Ejemplos:

```text
SPEC-ISA
SPEC-VIDEO
SPEC-MEMORY
```

Una SPECIFICATION puede contener muchas reglas normativas sin convertir cada una en REQUIREMENT.

La especificación de la ISA, por ejemplo, puede describir:

- registros;
- encoding;
- instrucciones;
- excepciones;
- control flow;
- comportamiento SIMT;
- convenciones.

Todo ello puede continuar formando parte de un único:

```text
SPEC-ISA
```

---

# 12. IMPLEMENTATION

Una `IMPLEMENTATION` representa una realización concreta de una especificación o parte del sistema.

Ejemplos:

```text
IMPL-MINICPU
IMPL-MINIGPU
IMPL-SCANOUT
IMPL-SDRAM-CONTROLLER
```

Puede corresponder a:

- RTL;
- software;
- firmware;
- hardware;
- configuración;
- PCB;
- lógica programable;
- otros mecanismos de implementación.

Su relación principal con una SPECIFICATION es `implements`.

---

# 13. VERIFICATION

Una `VERIFICATION` representa una definición estable de cómo comprobar un comportamiento.

Ejemplos:

```text
VER-SSY-BASIC
VER-R0
VER-ISA-CONFORMANCE
```

No representa una ejecución concreta.

Por ejemplo:

```text
VER-SSY-BASIC
```

puede existir permanentemente mientras se ejecuta miles de veces en CI.

Una ejecución concreta podría producir:

```text
PASS
commit abc123
backend fpga
timestamp ...
log ...
waveform ...
```

pero esa ejecución no necesita convertirse automáticamente en ARTIFACT.

---

## 13.1. Verificaciones compuestas

Una VERIFICATION puede estar compuesta por otras verificaciones mediante estructura propia:

```text
VER-ISA-CONFORMANCE

members:
    VER-ALU
    VER-MEMORY
    VER-CALLS
    VER-SIMT
```

`members` no es una relación universal del grafo.

Es estructura específica de VERIFICATION.

La composición no implica automáticamente cobertura completa.

Aunque:

```text
VER-ISA-CONFORMANCE
    members:
        VER-ALU
        VER-MEMORY
        VER-CALLS
        VER-SIMT
```

el sistema no debe inferir:

```text
VER-ISA-CONFORMANCE
    --verifies(coverage=complete)--> SPEC-ISA
```

Esa afirmación debe ser explícita.

---

# 14. EVIDENCE

`EVIDENCE` representa un resultado concreto que se ha decidido conservar como elemento estable y trazable.

Por ejemplo:

```text
EVID-MINIGPU-1.0-ISA-CONFORMANCE
```

podría conservar:

- commit;
- configuración;
- backend;
- resultados;
- logs;
- waveforms;
- informes;
- timestamp;
- versión de herramientas.

No todas las ejecuciones producen un EVIDENCE.

La política normal es:

```text
VERIFICATION
      │
      ├── run 1    ephemeral
      ├── run 2    ephemeral
      ├── run 3    ephemeral
      │
      └── resultado relevante
                 ↓
             EVIDENCE
```

Esto evita convertir cada ejecución de CI en un artifact permanente.

---

# 15. SOURCE

Un `SOURCE` representa una fuente externa que necesita identidad dentro de la trazabilidad.

Ejemplos:

```text
SRC-W9825G6KH-DATASHEET
SRC-HDMI-SPEC
SRC-EXTERNAL-REQS
```

No todas las referencias externas necesitan SOURCE.

Puede utilizarse directamente una referencia externa ligera cuando solo se necesita citarla.

Debe promocionarse a SOURCE cuando interese:

- referenciarla desde múltiples artifacts;
- fijar versión;
- conservar identidad;
- registrar checksum;
- distinguir revisiones;
- realizar trazabilidad real.

Para un datasheet externo podría interesar almacenar:

```text
title
vendor
document revision
URL/local copy
checksum
retrieved date
```

Como el documento externo normalmente no puede modificarse, esta metadata deberá mantenerse en una representación interna del proyecto.

---

# 16. KIND

`KIND` permite especializar un TYPE sin multiplicar los tipos fundamentales.

Es un vocabulario:

- registrado;
- extensible;
- específico de cada TYPE.

Ejemplos:

```text
VERIFICATION:
    test
    simulation
    analysis
    inspection
    review
    measurement
    formal-proof
```

MiniGPU podría registrar:

```text
IMPLEMENTATION:
    rtl
    firmware
    software
```

o:

```text
SOURCE:
    datasheet
    standard
    paper
```

Los kinds no son strings libres.

El metamodelo puede proporcionar un conjunto pequeño de kinds comunes y cada proyecto puede registrar otros.

Un KIND clasifica.

No cambia automáticamente la semántica fundamental del TYPE salvo que su definición establezca explícitamente alguna regla adicional.

---

# 17. SUBJECT

`SUBJECT` permite clasificar artifacts por dominio o subsistema.

Ejemplos iniciales en MiniGPU podrían ser:

```text
isa
cpu
gpu
memory
video
toolchain
monitor
```

Por ejemplo:

```text
SPEC-ISA
subjects:
    isa
    cpu
    gpu
```

SUBJECT es un vocabulario registrado.

No es una colección libre de tags.

Puede organizarse jerárquicamente cuando resulte útil:

```text
system
├── compute
│   ├── cpu
│   └── gpu
├── memory
└── video
    ├── scanout
    └── text-overlay
```

pero la jerarquía es opcional.

Compartir SUBJECT no crea ninguna relación semántica entre artifacts.

Por ejemplo, dos artifacts clasificados como:

```text
subject: memory
```

no pasan automáticamente a depender uno del otro.

SUBJECT sirve principalmente para:

- clasificación;
- navegación;
- filtrado;
- consultas;
- generación de vistas.

---

# 18. SECTION

Una `SECTION` es una subdivisión documental descubierta a partir de la estructura del recurso.

En Markdown corresponde normalmente a un heading.

Ejemplo:

```markdown
### SSY
```

dentro de `SPEC-ISA` puede producir la dirección:

```text
SPEC-ISA#ssy
```

SECTION no es un ARTIFACT.

No obtiene automáticamente:

- TYPE;
- KIND;
- STATUS;
- SUBJECT;
- lifecycle propio.

---

## 18.1. Identidad derivada

Una sección ordinaria puede utilizar un identificador derivado de su heading:

```markdown
### SSY
```

→

```text
SPEC-ISA#ssy
```

Esto permite referenciar documentación existente con prácticamente cero metadata.

---

## 18.2. Identidad formal

Cuando se necesita identidad estable puede declararse explícitamente:

```markdown
### Instrucción SSY y reconvergencia {#ssy}
```

La dirección sigue siendo:

```text
SPEC-ISA#ssy
```

pero ahora el ID deja de depender del texto del heading.

Cambiar:

```markdown
### Instrucción SSY y reconvergencia
```

por:

```markdown
### Modelo de reconvergencia mediante SSY
```

no rompe la referencia.

---

## 18.3. Namespace de SECTION

Los IDs de SECTION son locales al ARTIFACT.

Por tanto:

```text
SPEC-ISA#ssy
```

está compuesto por:

```text
ARTIFACT = SPEC-ISA
SECTION  = ssy
```

Los IDs formales de SECTION deben ser únicos dentro del ARTIFACT.

---

## 18.4. Headings derivados duplicados

Los headings normales no necesitan ser únicos.

Por ejemplo:

```markdown
## CPU

### Estado

## GPU

### Estado
```

es perfectamente válido mientras nadie intente resolver:

```text
SPEC-ARCH#estado
```

Si se necesita referenciar ambas secciones, se introducen IDs formales:

```markdown
### Estado {#cpu-state}

### Estado {#gpu-state}
```

---

## 18.5. SECTION como target

Una SECTION puede ser destino de una relación.

Por ejemplo:

```text
IMPL-GPU-SSY
    --implements--> SPEC-ISA#ssy
```

o:

```text
VER-SSY-DIVERGENCE
    --verifies--> SPEC-ISA#ssy
```

Como target puede utilizar un ID derivado del heading mientras la resolución sea inequívoca.

---

## 18.6. SECTION como source

Una SECTION también puede originar relaciones.

Sin embargo, para hacerlo debe poseer ID formal explícito.

Por ejemplo:

```markdown
### SSY {#ssy}
```

puede declarar conceptualmente:

```text
SPEC-ISA#ssy
    --derived-from--> DEC-SIMT-RECONVERGENCE
```

La razón es que una entidad que origina relaciones está afirmando semántica propia y necesita identidad estable.

---

# 19. FACET

Una `FACET` es una subdivisión semántica identificada dentro de un ARTIFACT.

No es otro ARTIFACT.

Ejemplos para una ISA:

```text
SPEC-ISA@calls
SPEC-ISA@compare
SPEC-ISA@subword-memory
```

En MiniGPU, una capability de la ISA puede modelarse como:

```text
FACET
kind: capability
```

El concepto `capability` pertenece por tanto al dominio de MiniGPU/ISA, no al núcleo universal del metamodelo.

---

## 19.1. Namespace de FACET

Los IDs de FACET son locales al ARTIFACT.

Por ejemplo:

```text
SPEC-ISA@calls
```

está compuesto por:

```text
ARTIFACT = SPEC-ISA
FACET    = calls
```

---

## 19.2. SECTION frente a FACET

SECTION representa estructura documental:

```text
SPEC-ISA#calls
```

FACET representa identidad semántica:

```text
SPEC-ISA@calls
```

Son conceptos distintos aunque frecuentemente estén asociados.

---

## 19.3. Representación documental de FACET

Una FACET se representa normalmente mediante una SECTION Markdown identificada.

Por ejemplo:

```markdown
## Calls {#calls}

### JAL

...

### JALR

...

### JR

...
```

Semánticamente:

```text
SPEC-ISA@calls
```

puede estar anclada a:

```text
SPEC-ISA#calls
```

Las subsecciones pertenecen naturalmente a esa representación documental.

No es necesario etiquetar:

```text
#jal  → calls
#jalr → calls
#jr   → calls
```

individualmente.

Desde fuera puede utilizarse la identidad semántica:

```text
IMPL-MINICPU
    --implements--> SPEC-ISA@calls
```

mientras que, cuando se necesita precisión documental, puede utilizarse:

```text
VER-JALR
    --verifies--> SPEC-ISA#jalr
```

No se diseña por ahora un mecanismo especial para FACETs cuya representación esté dispersa por múltiples regiones del documento. Se añadirá únicamente si aparece una necesidad real.

---

## 19.4. Metadata de FACET

Una FACET puede poseer metadata ligera.

Por ejemplo:

```text
SPEC-ISA@calls

kind: capability
title: Function calls
subjects:
    isa
```

También puede participar como origen o destino de relaciones.

Sin embargo, no tiene lifecycle independiente del ARTIFACT al que pertenece.

Si una FACET comienza a necesitar:

- lifecycle independiente;
- versionado independiente;
- decisiones independientes;
- sustitución independiente;
- autonomía conceptual significativa;

debe considerarse su promoción a ARTIFACT.

La progresión conceptual es:

```text
heading
   ↓
SECTION con identidad formal
   ↓
FACET
   ↓
ARTIFACT
```

pero solo se asciende cuando la identidad adicional aporta valor.

---

# 20. Addressable Target

Las relaciones pueden dirigirse a:

```text
ARTIFACT
ARTIFACT#SECTION
ARTIFACT@FACET
```

Por ejemplo:

```text
SPEC-ISA
SPEC-ISA#ssy
SPEC-ISA@calls
```

Esto permite elegir la granularidad adecuada sin crear artifacts artificiales.

---

# 21. RELATION

Una `RELATION` es una arista semántica dirigida entre elementos identificables.

Forma conceptual:

```text
SOURCE --relation--> TARGET
```

La dirección forma parte de su significado.

Las relaciones se almacenan una sola vez, junto a su origen siempre que sea posible.

Las relaciones inversas son vistas derivadas.

---

# 22. Vocabulario de relaciones

El núcleo v0.2 define:

```text
derived-from
refines
addresses
requires
implements
satisfies
verifies
produces
supersedes
```

No forman parte del núcleo:

```text
depends-on
affects
contains
```

Las relaciones adicionales están permitidas como extensiones de proyecto, pero deben registrarse y definir su semántica.

No se permiten nombres de relación ad hoc sin registrar.

---

# 23. `derived-from`

`derived-from` expresa procedencia técnica o intelectual directa.

```text
A --derived-from--> B
```

significa que A fue obtenido, concretizado o motivado directamente a partir de B.

Ejemplos:

```text
REQ-SDRAM-TIMING
    --derived-from--> SRC-W9825G6KH-DATASHEET
```

```text
SPEC-ISA#ssy
    --derived-from--> DEC-SIMT-RECONVERGENCE
```

No es una relación genérica de dependencia.

Tampoco debe considerarse automáticamente transitiva como relación directa.

Si:

```text
A --derived-from--> B
B --derived-from--> C
```

el sistema puede mostrar el camino:

```text
A → B → C
```

pero no debe inventar:

```text
A --derived-from--> C
```

como relación explícita.

---

# 24. `refines`

`refines` expresa concreción, especialización o descomposición de significado normativo.

```text
A --refines--> B
```

significa:

> A concretiza, especializa o descompone todo o parte del significado normativo de B, mientras B continúa siendo válido.

Ejemplo:

```text
REQ-VIDEO-TIMING
    --refines--> REQ-VIDEO
```

```text
REQ-VIDEO-BUFFERING
    --refines--> REQ-VIDEO
```

`refines` no significa:

- sustitución;
- implementación;
- satisfacción;
- procedencia;
- cobertura completa.

---

# 25. `addresses`

`addresses` expresa que el origen responde intencionadamente a una necesidad, requisito o cuestión expresada por el target.

Ejemplo:

```text
DEC-SIMT-RECONVERGENCE
    --addresses--> REQ-GPU-RECONVERGENCE
```

o:

```text
DEC-VIDEO-DOUBLE-BUFFER
    --addresses--> NEED-SMOOTH-VIDEO
```

Puede responder total o parcialmente.

No implica:

- implementación;
- satisfacción;
- verificación.

No se define un atributo `coverage` para `addresses`.

---

# 26. `requires`

`requires` representa una dependencia fuerte de conformidad.

```text
A --requires--> B
```

significa:

> Implementar o conformar A requiere también disponer de una implementación conforme de B.

Ejemplo:

```text
SPEC-GPU@texture
    --requires--> SPEC-MEMORY@unaligned-loads
```

Esto permite al checker detectar situaciones como:

```text
IMPL-X implements SPEC-GPU@texture
```

pero no proporciona aquello que `@texture` requiere.

`requires` no representa pertenencia.

Por ejemplo:

```text
SPEC-ISA#jalr
    --requires--> SPEC-ISA@calls
```

sería incorrecto si JALR simplemente forma parte de la FACET `calls`.

La pertenencia documental/semántica se modela mediante estructura, no mediante `requires`.

La transitividad puede utilizarse para análisis de caminos:

```text
A requires B
B requires C
```

permite mostrar:

```text
A → B → C
```

pero no crea una relación directa autoritativa:

```text
A requires C
```

---

# 27. `implements`

`implements` posee semántica fuerte.

```text
X --implements--> Y
```

afirma:

> X pretende realizar completamente el comportamiento obligatorio definido por Y.

No significa que haya sido verificado.

Por ejemplo:

```text
IMPL-MINICPU
    --implements--> SPEC-ISA
```

afirma que MiniCPU implementa el contenido base obligatorio de `SPEC-ISA`.

No implica implementar todas sus FACETs opcionales.

Estas se declaran independientemente:

```text
IMPL-MINICPU
    --implements--> SPEC-ISA@calls
```

```text
IMPL-MINICPU
    --implements--> SPEC-ISA@compare
```

Si una implementación está incompleta, no debe utilizarse:

```text
IMPL-X --implements--> SPEC-X
```

para luego añadir un atributo ambiguo `partial`.

Debe apuntarse a objetivos más pequeños que sí implemente completamente:

```text
IMPL-X --implements--> SPEC-X#foo
IMPL-X --implements--> SPEC-X@bar
```

---

# 28. `satisfies`

`satisfies` también posee semántica fuerte.

```text
X --satisfies--> REQ-Y
```

significa:

> X es suficiente para considerar cumplida la obligación completa expresada por REQ-Y.

No existe:

```text
satisfies(partial)
```

Si varios componentes contribuyen conjuntamente a un requisito, no debe afirmarse que cada componente lo satisface individualmente.

En su lugar puede utilizarse una implementación agregada:

```text
IMPL-VIDEO-SUBSYSTEM
    --satisfies--> REQ-VIDEO-STABLE
```

La distinción principal es:

```text
implements → SPECIFICATION
satisfies  → REQUIREMENT
```

---

# 29. `verifies`

`verifies` expresa que una VERIFICATION comprueba un target.

Posee:

```text
coverage = partial | complete
```

El valor por defecto es:

```text
partial
```

Por tanto:

```text
VER-SSY-BASIC
    --verifies--> SPEC-ISA#ssy
```

equivale a:

```text
VER-SSY-BASIC
    --verifies(coverage=partial)--> SPEC-ISA#ssy
```

Significa que la verificación comprueba parte del comportamiento del target.

---

## 29.1. Cobertura completa

```text
VER-SSY-SUITE
    --verifies(coverage=complete)--> SPEC-ISA#ssy
```

significa:

> Según la estrategia de verificación del proyecto, superar esta VERIFICATION es suficiente para considerar completamente verificado exactamente ese target.

`complete` no significa necesariamente demostración matemática.

La técnica puede ser:

- simulación;
- test;
- formal;
- inspección;
- análisis;
- medición;
- combinación de métodos.

---

## 29.2. No existe propagación automática hacia arriba

Si:

```text
VER-SSY-SUITE
    --verifies(complete)--> SPEC-ISA#ssy
```

no debe inferirse:

```text
VER-SSY-SUITE
    --verifies--> SPEC-ISA
```

Para afirmar conformidad completa de la ISA debe existir una declaración explícita:

```text
VER-ISA-CONFORMANCE
    --verifies(coverage=complete)--> SPEC-ISA
```

La cobertura siempre es relativa exactamente al target declarado.

---

# 30. `produces`

`produces` es una relación general.

```text
A --produces--> B
```

significa:

> B es un resultado generado por la ejecución, realización o procesamiento de A.

Ejemplo:

```text
VER-SSY
    --produces--> EVID-SSY
```

También puede aplicarse a otros procesos cuando ambos extremos poseen identidad trazable.

Por ejemplo:

```text
PNR-MINIGPU
    --produces--> EVID-PNR-RELEASE-1
```

No debe confundirse con `derived-from`.

Por ejemplo:

```text
SPEC-ISA#ssy
    --derived-from--> DEC-SIMT-RECONVERGENCE
```

es correcto.

La decisión no “produce” la especificación en el sentido de `produces`.

Tampoco es necesario crear artifacts para todos los resultados efímeros.

---

# 31. `supersedes`

`supersedes` expresa sustitución fuerte.

```text
A --supersedes--> B
```

significa:

> A reemplaza a B como elemento vigente.

Las referencias históricas a B se conservan.

No deben reescribirse automáticamente para apuntar a A.

El estado:

```text
superseded
```

de B se deriva de la existencia de una relación entrante `supersedes`.

No debe almacenarse redundantemente:

```text
status: superseded
superseded-by: A
```

si la relación ya contiene esa información.

---

# 32. Relaciones eliminadas del núcleo

## 32.1. `depends-on`

No forma parte del núcleo.

Es demasiado fácil utilizarla como:

> Está relacionado de alguna forma con...

Cuando existe una dependencia de conformidad debe utilizarse:

```text
requires
```

y cuando existe otra semántica debe elegirse la relación correspondiente.

Podrá registrarse como extensión si aparece un caso real que justifique una semántica precisa.

---

## 32.2. `affects`

Tampoco forma parte del núcleo.

Una relación como:

```text
DEC-X --affects--> SPEC-Y
```

aporta poca información utilizable por herramientas.

Debe preferirse expresar la relación real.

---

## 32.3. `contains`

`contains` no es una relación semántica universal.

La pertenencia se representa mediante estructura del modelo.

Por ejemplo:

```text
RESOURCE → ARTIFACT
ARTIFACT → SECTION
ARTIFACT → FACET
VERIFICATION → members
```

No mediante:

```text
A --contains--> B
```

---

# 33. Registro de relaciones

El vocabulario de relaciones es extensible pero registrado.

Cada relación registrada podrá definir, cuando sea necesario:

```text
name
description
allowed source types
allowed target types
attributes
transitivity semantics
acyclicity
validation rules
```

No es necesario fijar todas estas restricciones en v0.2.

La regla fundamental es:

> Una nueva relación solo debe introducirse cuando ninguna relación existente expresa correctamente su significado.

---

# 34. Relaciones explícitas e inferencia

Debe distinguirse siempre entre:

1. relaciones declaradas;
2. caminos inferidos;
3. estados derivados.

Ejemplo:

```text
A --derived-from--> B
B --derived-from--> C
```

puede permitir mostrar:

```text
A → B → C
```

pero no transforma automáticamente ese camino en:

```text
A --derived-from--> C
```

De igual modo, una herramienta puede concluir que un artifact está relacionado indirectamente con otro sin modificar el grafo autoritativo.

Toda inferencia debe ser explicable mediante el camino que la produjo.

---

# 35. Lifecycle

Debe distinguirse entre:

- lifecycle editorial;
- estado derivado del proyecto.

## 35.1. Estado editorial almacenado

Inicialmente se contempla:

```text
proposed
accepted
deprecated
rejected
```

Estos estados expresan decisiones editoriales/humanas.

---

## 35.2. Estados derivados

No deben almacenarse manualmente estados como:

```text
implemented
verified
superseded
```

si pueden obtenerse del grafo.

Por ejemplo:

```text
superseded
```

se deriva de una relación `supersedes`.

`implemented` se deriva de relaciones `implements`.

`verified` se deriva de:

- relaciones `verifies`;
- coverage;
- resultados/evidencia;
- política de análisis correspondiente.

Esto evita estados que puedan quedar desincronizados de la realidad.

---

# 36. Versionado

La evolución histórica normal de un mismo artifact se gestiona mediante control de versiones.

Por ejemplo:

```text
SPEC-ISA
```

puede evolucionar:

```text
Git revision 1
Git revision 2
Git revision 3
...
```

sin convertirse en nuevos artifacts.

No se pretende construir un segundo sistema de versionado dentro del metamodelo.

Solo deben crearse identidades diferentes cuando varias variantes necesiten coexistir y ser referenciables independientemente.

Por ejemplo:

```text
SPEC-ISA-V1
SPEC-ISA-V2
```

podrían coexistir si realmente existen dos contratos distintos.

En ese caso podría existir:

```text
SPEC-ISA-V2
    --supersedes--> SPEC-ISA-V1
```

---

# 37. Authority y representaciones

`authority` no es metadata obligatoria de ARTIFACT.

El concepto pertenece principalmente a las representaciones o fuentes de información.

Se distinguen conceptualmente:

```text
AUTHORED
GENERATED
EXTERNAL
```

---

## 37.1. AUTHORED

Contenido mantenido intencionadamente por una persona como representación autoritativa.

Ejemplo:

```text
prosa normativa de SPEC-ISA
```

---

## 37.2. GENERATED

Contenido producido automáticamente a partir de otra fuente.

Ejemplo:

```text
tabla de opcodes generada
tabla de utilización FPGA
resumen de verificaciones
```

Una representación GENERATED nunca debe convertirse accidentalmente en la única autoridad necesaria para regenerarse a sí misma.

---

## 37.3. EXTERNAL

Información cuya autoridad reside fuera del proyecto.

Ejemplo:

```text
datasheet de SDRAM del fabricante
```

El proyecto puede almacenar una copia, checksum o metadata, pero la naturaleza de la fuente sigue siendo externa.

---

# 38. GENERATED BLOCK

Un `GENERATED BLOCK` es una región de documentación cuya representación se deriva automáticamente.

Ejemplo similar al mecanismo ya utilizado para P&R:

```markdown
<!-- BEGIN PNR:utilization -->

...contenido generado...

<!-- END PNR:utilization -->
```

El contenido situado entre los marcadores no se edita manualmente.

---

# 39. Pipeline de generación

El modelo general es:

```text
SOURCE / QUERY
       │
       ▼
GENERATOR / TRANSFORM
       │
       ▼
RENDERER
       │
       ▼
GENERATED BLOCK
```

La fuente puede ser muy diferente según el caso.

Ejemplos:

```text
P&R report
    → parser
    → utilization table
```

```text
ISA structured data
    → query
    → opcode table
```

```text
trace graph
    → analysis
    → verification status
```

```text
test provider
    → latest result
    → Markdown summary
```

---

# 40. `gendoc`

`gendoc` se concibe como una capa documental sobre información del proyecto.

No debe convertirse en el propietario de la semántica.

Conceptualmente:

```text
project data
    │
    ├── artifacts
    ├── relations
    ├── tests
    ├── P&R
    ├── synthesis
    ├── builds
    └── external sources
            │
            ▼
       graph analysis
            │
            ▼
          gendoc
            │
            ▼
         Markdown
```

---

## 40.1. Actualización

Una operación:

```text
gendoc update
```

regenera los bloques y sustituye sus representaciones.

---

## 40.2. Comprobación

Una operación:

```text
gendoc check
```

regenera conceptualmente el contenido y lo compara con el documento existente.

Si difiere, el documento está desactualizado.

Esto permite integrar la documentación en CI.

---

# 41. Consultas de GENERATED BLOCK

Un bloque generado puede utilizar consultas como:

```text
latest result
latest successful result
result for commit
result for release
all results
```

Por ejemplo:

```markdown
## Estado de verificación

<!-- BEGIN TRACE:verification-status -->

| Target | Verification | Result |
|---|---|---|
| SPEC-ISA#ssy | VER-SSY | PASS |
| SPEC-ISA#bar | VER-BAR | PASS |

<!-- END TRACE:verification-status -->
```

La tabla no es la fuente de verdad.

Es una vista generada.

---

# 42. Verificación, ejecución y evidencia

Debe mantenerse la separación:

```text
VERIFICATION
    definición estable
        │
        ▼
EXECUTION / RESULT
    ocurrencia concreta, normalmente efímera
        │
        ▼ opcional
EVIDENCE
    resultado preservado
```

`EXECUTION` no se introduce por ahora como entidad fundamental del metamodelo.

Puede existir simplemente como información suministrada por un provider:

```text
CI
simulator
test runner
formal tool
measurement system
```

Si una ejecución merece identidad permanente, puede promocionarse a EVIDENCE.

---

# 43. Ejemplo de evidencia generada

Supongamos:

```text
VER-SSY-DIVERGENCE
    --verifies(coverage=complete)--> SPEC-ISA#ssy
```

El sistema de CI ejecuta:

```text
run 1837
commit: abc123
backend: simulator
result: PASS
```

Ese run puede permanecer efímero.

`gendoc` puede consultar:

```text
latest result of VER-SSY-DIVERGENCE
```

y mostrar:

```text
SSY divergence: PASS
```

Para una release puede decidirse preservar:

```text
EVID-MINIGPU-1.0-SSY
```

y entonces:

```text
VER-SSY-DIVERGENCE
    --produces--> EVID-MINIGPU-1.0-SSY
```

---

# 44. Estado generado del proyecto

Una de las aplicaciones principales del grafo es generar automáticamente vistas de estado.

Por ejemplo:

```markdown
## Traceability status

<!-- BEGIN TRACE:status -->

...

<!-- END TRACE:status -->
```

El análisis puede detectar:

- REQUIREMENTs sin satisfacción;
- SPECIFICATIONs sin implementación;
- SPECIFICATIONs sin verificación;
- VERIFICATIONs sin resultados recientes;
- relaciones rotas;
- artifacts deprecated todavía utilizados;
- FACETs implementadas sin sus `requires`;
- referencias ambiguas;
- SECTION IDs inexistentes;
- contenido generado desactualizado.

El análisis pertenece al motor del grafo.

`gendoc` únicamente renderiza sus resultados.

Así el mismo análisis puede utilizarse desde:

```text
CLI
CI
web
IDE
gendoc
```

---

# 45. Invariantes fundamentales

## INV-001 — ID único

Todo ARTIFACT posee un ID globalmente único dentro del proyecto.

---

## INV-002 — Identidad estable

Mover o reorganizar la representación física de un ARTIFACT no cambia su ID.

---

## INV-003 — Targets válidos

Toda relación debe resolver su target.

Los targets externos deben representarse explícitamente como tales.

---

## INV-004 — Autoridad única de relaciones

Una relación se declara una sola vez, en su origen autoritativo.

Las relaciones inversas se derivan.

---

## INV-005 — Sin ciclos de autoridad generada

El contenido generado no puede constituir la única autoridad necesaria para regenerarse.

---

## INV-006 — Reproducibilidad

El contenido generado debe poder reconstruirse a partir de sus fuentes y transformaciones declaradas.

---

## INV-007 — Sincronización documental

`gendoc check` debe poder detectar bloques generados desactualizados.

---

## INV-008 — Inferencia explicable

Toda conclusión derivada del grafo debe poder explicar qué relaciones o datos la originaron.

---

## INV-009 — Estructura acíclica

Las estructuras de pertenencia que conceptualmente forman árboles o DAGs no deben contener ciclos inválidos.

---

## INV-010 — Historia preservada

La sustitución o evolución de artifacts no debe destruir referencias históricas.

---

## INV-011 — SECTION source estable

Una SECTION que origine relaciones debe poseer ID formal explícito.

---

## INV-012 — SECTION formal única

Los IDs formales de SECTION deben ser únicos dentro de su ARTIFACT.

---

## INV-013 — FACET local única

Los IDs de FACET deben ser únicos dentro de su ARTIFACT.

---

# 46. Índice global

Las herramientas pueden construir un índice global con:

```text
artifacts
sections
facets
relations
subjects
resources
locations
incoming relations
generated blocks
```

Este índice es derivado.

Debe poder eliminarse y reconstruirse completamente a partir de las fuentes autoritativas.

No debe convertirse en una base de datos cuya pérdida implique perder información conceptual del proyecto.

---

# 47. Consultas esperadas

El modelo debería permitir consultas del estilo:

```text
show SPEC-ISA
```

```text
what implements SPEC-ISA?
```

```text
what implements SPEC-ISA@calls?
```

```text
what verifies SPEC-ISA#ssy?
```

```text
why SPEC-ISA#ssy?
```

```text
what does DEC-SIMT-RECONVERGENCE address?
```

```text
what depends transitively on SPEC-MEMORY@unaligned-loads?
```

La palabra `depends` en una consulta puede significar recorrido de dependencias; no implica la existencia de una relación `depends-on`.

También:

```text
impact SPEC-ISA#ssy
```

```text
path NEED-X IMPL-Y
```

```text
orphan
```

```text
unverified
```

```text
unsatisfied
```

```text
unimplemented
```

```text
stale-generated
```

```text
broken-relations
```

---

# 48. Ejemplo MiniGPU: ISA

Podemos tener:

```text
SPEC-ISA
type: specification
subjects:
    isa
```

El documento Markdown proporciona su estructura:

```text
SPEC-ISA
│
├── #architectural-state
├── #registers
├── #instruction-format
├── #alu
├── #memory
├── #control-flow
└── #simt
      ├── #gettid
      ├── #ssy
      ├── #bar
      └── #exit
```

No se crean automáticamente artifacts para esas secciones.

---

# 49. Ejemplo MiniGPU: capabilities

Las extensiones de ISA pueden modelarse como FACETs:

```text
SPEC-ISA@subword-memory
SPEC-ISA@calls
SPEC-ISA@alu-extended
SPEC-ISA@shift-immediate
SPEC-ISA@compare
```

con:

```text
kind: capability
```

Una implementación puede declarar:

```text
IMPL-MINICPU
    --implements--> SPEC-ISA
```

y además:

```text
IMPL-MINICPU
    --implements--> SPEC-ISA@calls

IMPL-MINICPU
    --implements--> SPEC-ISA@compare
```

`implements SPEC-ISA` significa conformidad con el contenido base obligatorio.

No implica automáticamente implementar todas las FACETs opcionales.

---

# 50. Ejemplo MiniGPU: SSY

Supongamos:

```text
DEC-SIMT-RECONVERGENCE
```

que documenta la decisión de utilizar `SSY`.

La sección:

```markdown
### SSY {#ssy}
```

puede declarar:

```text
SPEC-ISA#ssy
    --derived-from--> DEC-SIMT-RECONVERGENCE
```

La implementación:

```text
IMPL-MINIGPU-SSY
    --implements--> SPEC-ISA#ssy
```

La verificación:

```text
VER-SSY-BASIC
    --verifies--> SPEC-ISA#ssy
```

y una suite más completa:

```text
VER-SSY-CONFORMANCE
    --verifies(coverage=complete)--> SPEC-ISA#ssy
```

El camino resultante permite responder:

```text
¿Por qué existe SSY?
```

mediante:

```text
SPEC-ISA#ssy
        │
        └── derived-from
                │
                ▼
       DEC-SIMT-RECONVERGENCE
```

y:

```text
¿Cómo sabemos que está implementado?
```

mediante:

```text
IMPL-MINIGPU-SSY
        │
        └── implements
                │
                ▼
          SPEC-ISA#ssy
```

y:

```text
¿Cómo sabemos que funciona?
```

mediante:

```text
VER-SSY-CONFORMANCE
        │
        └── verifies(complete)
                │
                ▼
          SPEC-ISA#ssy
```

más el resultado/evidencia correspondiente.

---

# 51. Ejemplo MiniGPU: SDRAM

Una fuente externa:

```text
SRC-W9825G6KH-DATASHEET
type: source
kind: datasheet
```

puede originar requisitos técnicos:

```text
REQ-SDRAM-TIMING
    --derived-from--> SRC-W9825G6KH-DATASHEET
```

Estos pueden refinarse:

```text
REQ-SDRAM-REFRESH
    --refines--> REQ-SDRAM-TIMING
```

La especificación del controlador puede responder a ellos y una implementación concreta realizarla.

Los resultados de timing/P&R pueden posteriormente conservarse como EVIDENCE para una determinada release.

---

# 52. Ejemplo MiniGPU: vídeo

Una necesidad:

```text
NEED-SMOOTH-VIDEO
```

puede originar:

```text
REQ-VIDEO-NO-TEARING
REQ-SCANOUT-NO-UNDERFLOW
```

Una decisión:

```text
DEC-VIDEO-DOUBLE-BUFFER
    --addresses--> NEED-SMOOTH-VIDEO
```

puede dar lugar a una especificación:

```text
SPEC-VIDEO
```

implementada por:

```text
IMPL-VIDEO-SUBSYSTEM
    --implements--> SPEC-VIDEO
```

y el sistema completo puede afirmar:

```text
IMPL-VIDEO-SUBSYSTEM
    --satisfies--> REQ-VIDEO-NO-TEARING
```

La verificación sigue siendo independiente:

```text
VER-VIDEO-SWAP
    --verifies--> REQ-VIDEO-NO-TEARING
```

Esto permite distinguir claramente:

```text
diseñado para cumplir
        ≠
comprobado experimentalmente
```

---

# 53. Ejemplo MiniGPU: P&R y gendoc

El mecanismo existente de actualización de tablas de P&R es un caso particular del modelo general.

Actualmente:

```text
P&R output
    ↓
parser
    ↓
Markdown markers
```

puede generalizarse a:

```text
provider
    ↓
structured data
    ↓
query / analysis
    ↓
renderer
    ↓
generated block
```

Por ejemplo:

```text
pnr.utilization
pnr.timing
pnr.fmax

isa.instruction-table
isa.opcode-table

mmio.register-table
memory.memory-map

trace.requirements
trace.unverified
trace.impact

tests.summary
tests.coverage

rtl.modules

build.configuration
```

Todos utilizan la misma arquitectura conceptual aunque obtengan sus datos de fuentes diferentes.

---

# 54. Qué NO intenta hacer este metamodelo

No intenta:

- sustituir Git;
- modelar cada párrafo;
- convertir cada heading en artifact;
- crear un requirement para cada frase normativa;
- almacenar todos los resultados de CI;
- definir un formato universal de test;
- modelar todas las alternativas de una decisión;
- sustituir Markdown como medio de documentación;
- obligar a que toda información sea estructurada;
- convertirse en una herramienta ALM empresarial.

---

# 55. Regla de promoción

Un principio recurrente del modelo es la promoción progresiva de identidad.

Una pieza de información puede comenzar simplemente como texto.

Si necesita ser referenciada:

```text
texto
  ↓
SECTION
```

Si necesita identidad semántica dentro de un artifact:

```text
SECTION
  ↓
FACET
```

Si necesita autonomía real:

```text
FACET
  ↓
ARTIFACT
```

De forma similar, un resultado de ejecución puede permanecer efímero:

```text
RESULT
```

y convertirse en:

```text
EVIDENCE
```

solo cuando interesa preservarlo.

La herramienta debe exigir formalización únicamente cuando exista una razón concreta.

---

# 56. Separación de capas

La arquitectura conceptual debe mantener separadas varias capas:

```text
METAMODEL
    │
    ▼
REPRESENTATION
    │
    ▼
PARSERS / PROVIDERS
    │
    ▼
DERIVED INDEX / GRAPH
    │
    ▼
ANALYSIS
    │
    ├── CLI
    ├── CI
    ├── IDE
    ├── Web
    └── GENDOC
```

## Metamodel

Define qué significa:

```text
ARTIFACT
SECTION
FACET
RELATION
VERIFICATION
...
```

## Representation

Define cómo se escribe físicamente:

```text
Markdown
Python
SystemVerilog
sidecars
...
```

## Parser/provider

Extrae información de cada representación.

## Index/graph

Construye la vista global del proyecto.

## Analysis

Aplica invariantes y consultas.

## Presentation

Muestra los resultados sin convertirse en autoridad.

---

# 57. Decisiones deliberadamente pospuestas para v0.3

La versión 0.2 define el modelo conceptual.

No fija todavía la representación física definitiva.

Quedan deliberadamente pospuestos:

## 57.1. Sintaxis de declaración de ARTIFACT en Markdown

Por ejemplo, todavía no se decide entre formas como:

```text
front matter
HTML comments
directivas
bloques especiales
atributos Markdown
```

---

## 57.2. Sintaxis física de relaciones

Todavía no se fija cómo escribir:

```text
SPEC-ISA#ssy
    --derived-from--> DEC-SIMT-RECONVERGENCE
```

dentro del Markdown.

---

## 57.3. Declaración de FACET

Debe definirse cómo indicar que:

```text
SPEC-ISA@calls
```

está asociada a:

```text
SPEC-ISA#calls
```

sin introducir ruido innecesario.

---

## 57.4. Anotaciones en código

Debe estudiarse la representación apropiada para:

```text
Python
C
SystemVerilog
Verilog
assembler
```

Por ejemplo, cómo declarar que un módulo RTL:

```text
implements SPEC-ISA#ssy
```

sin contaminar excesivamente el código.

---

## 57.5. Sidecars

Debe definirse cuándo utilizar metadata externa y qué formato emplear.

Casos claros:

- PDFs externos;
- datasheets;
- recursos de solo lectura;
- herramientas que no admiten annotations;
- artifacts distribuidos.

---

## 57.6. Restricciones exactas source/target

La semántica de las relaciones está definida, pero queda por decidir cuánto debe imponer automáticamente el checker.

Por ejemplo:

```text
implements → normalmente SPECIFICATION
satisfies  → REQUIREMENT
verifies   → target verificable
```

Debe evitarse introducir restricciones artificiales antes de tener casos reales.

---

## 57.7. Providers

Debe diseñarse la interfaz mediante la que fuentes externas proporcionan información:

```text
P&R
synthesis
test runner
CI
Git
formal tools
simulators
```

---

## 57.8. Política de resultados

Debe definirse con más detalle cómo se selecciona:

```text
latest
latest successful
for commit
for release
```

y cómo se determina si una evidencia está obsoleta.

---

# 58. Resumen del metamodelo v0.2

Las entidades principales son:

```text
RESOURCE
ARTIFACT
SECTION
FACET
RELATION
SUBJECT
GENERATED BLOCK
```

Los tipos fundamentales de ARTIFACT son:

```text
NEED
REQUIREMENT
DECISION
SPECIFICATION
IMPLEMENTATION
VERIFICATION
EVIDENCE
SOURCE
```

Las relaciones estándar son:

```text
derived-from
refines
addresses
requires
implements
satisfies
verifies
produces
supersedes
```

Las identidades addressables principales son:

```text
SPEC-ISA          ARTIFACT
SPEC-ISA#ssy      SECTION
SPEC-ISA@calls    FACET
```

El mínimo para declarar un ARTIFACT es:

```text
id
type
```

`KIND` y `SUBJECT` utilizan vocabularios registrados y extensibles.

La estructura documental se descubre en la medida de lo posible.

Las relaciones se almacenan una sola vez junto a su origen.

Los estados que pueden deducirse del grafo no se mantienen manualmente.

Las ejecuciones son efímeras por defecto.

Los resultados importantes pueden promocionarse a EVIDENCE.

El contenido generado nunca debe convertirse accidentalmente en una segunda fuente de verdad.

Y la filosofía general del sistema es:

> **Identidad cuando aporta valor, semántica explícita cuando permite razonar y generación automática cuando evita duplicar información.**

La documentación debe seguir siendo cómoda de escribir y leer por una persona, mientras que el grafo derivado permite a las herramientas comprender suficiente estructura para mantenerla coherente.
