# Trace --- Metamodelo v0.4

## 1. Propósito

Este documento define el metamodelo de trazabilidad de **Trace**. Su
objetivo es representar de forma explícita y navegable las necesidades,
requisitos, trabajo de diseño, decisiones, especificaciones,
implementaciones, verificaciones, evidencias y fuentes de un proyecto de
ingeniería.

El metamodelo es deliberadamente pequeño. No intenta modelar cada
concepto de un dominio concreto ---ISA, RTL, FPGA, software, PCB,
espacio, etc.--- sino proporcionar un núcleo sobre el que puedan
construirse vocabularios, queries, reglas y generadores específicos de
cada proyecto.

La v0.4 incorpora las conclusiones surgidas al estudiar proyectos reales
parcialmente especificados, especificaciones compuestas y evolución
incremental de especificaciones.

------------------------------------------------------------------------

## 2. Principios

1.  **La identidad lógica es independiente de la ubicación física.**
2.  **RESOURCE y ARTIFACT son conceptos diferentes.**
3.  **La estructura documental y las relaciones semánticas son
    diferentes.**
4.  **Las relaciones tienen dirección y semántica precisas.**
5.  **La información autoritativa se declara una sola vez; las vistas
    inversas se calculan.**
6.  **Git conserva la evolución temporal normal; el modelo solo
    introduce identidades diferentes cuando deben coexistir
    semánticamente.**
7.  **El modelo puede estar incompleto.** Trace debe poder utilizarse en
    proyectos existentes y ayudar a descubrir huecos, no exigir
    trazabilidad perfecta desde el primer día.
8.  **El metamodelo describe qué significa el modelo; la metodología
    describe cómo trabajar con él.**
9.  **Las inferencias deben ser explicables.** Un camino calculado no se
    convierte silenciosamente en una relación autoritativa.
10. **El ProjectModel es reconstruible desde las fuentes.** No requiere
    una base de datos persistente como fuente de verdad.

------------------------------------------------------------------------

## 3. Tipos fundamentales de Artifact

### 3.1 NEED

Representa una necesidad, objetivo o motivación.

Pregunta principal:

> ¿Por qué hacemos esto?

Ejemplo:

``` text
NEED-FAST-RENDERING
```

------------------------------------------------------------------------

### 3.2 REQUIREMENT

Representa una obligación que debe cumplirse.

Pregunta principal:

> ¿Qué debe ser cierto?

Kinds habituales:

-   `functional`
-   `performance`
-   `interface`
-   `safety`
-   `resource`
-   `timing`
-   `constraint`

Ejemplo:

``` text
REQ-FRAME-RATE
```

------------------------------------------------------------------------

### 3.3 DESIGN

`DESIGN` es nuevo en v0.4.

Representa trabajo de ingeniería todavía no normativo: exploración,
alternativas, trade-offs, propuestas incompletas, preguntas abiertas y
diseño en curso.

Pregunta principal:

> ¿Qué estamos estudiando o diseñando antes de cerrar el contrato?

Ejemplos:

``` text
DES-TRACE-EXTENDS
DES-MINIGPU-BARRIER
```

Un DESIGN puede contener:

-   descripción del problema;
-   alternativas;
-   experimentos;
-   comportamiento observado;
-   contradicciones entre implementaciones;
-   trade-offs;
-   preguntas abiertas;
-   una propuesta provisional.

Un DESIGN **no equivale a una decisión** y **no equivale a una
especificación**.

Un posible uso:

``` text
type: design
kind: exploration
status: draft
```

o:

``` text
type: design
kind: proposal
status: proposed
```

La lista de `kind` puede ampliarse por proyecto.

------------------------------------------------------------------------

### 3.4 DECISION

Representa una decisión de ingeniería y su justificación.

Pregunta principal:

> ¿Qué opción hemos elegido y por qué?

Es conceptualmente similar a un ADR generalizado.

Una DECISION puede registrar:

-   contexto;
-   alternativas consideradas;
-   decisión;
-   rationale;
-   consecuencias.

Ejemplo:

``` text
DEC-TRACE-EXTENDS
```

Diferencia fundamental:

``` text
DESIGN       razonamiento en curso
DECISION     conclusión elegida del razonamiento
SPECIFICATION contrato normativo resultante
```

------------------------------------------------------------------------

### 3.5 SPECIFICATION

Representa diseño o comportamiento normativo.

Pregunta principal:

> ¿Cómo debe comportarse o estructurarse el sistema?

Kinds habituales:

-   `architecture`
-   `interface`
-   `protocol`
-   `register`
-   `instruction`
-   `data-format`
-   `algorithm`
-   `component`

Ejemplos:

``` text
SPEC-MINIGPU-ISA
SPEC-MINIGPU-MMIO
SPEC-TRACE-CLI
```

Una SPECIFICATION puede estar en estado `draft` o `proposed`; eso
significa que existe una propuesta normativa. No debe utilizarse para
sustituir trabajo exploratorio que todavía no sabe cuál debe ser el
contrato: ese caso pertenece a DESIGN.

------------------------------------------------------------------------

### 3.6 IMPLEMENTATION

Representa una realización concreta.

Puede ser:

-   RTL;
-   software;
-   firmware;
-   PCB;
-   diseño mecánico;
-   configuración;
-   otra realización ejecutable o construible.

Ejemplos:

``` text
IMPL-MINIGPU-RTL
IMPL-MINIGPU-SIM
IMPL-TRACE
```

------------------------------------------------------------------------

### 3.7 VERIFICATION

Representa intención o método estable de verificación.

Puede ser:

-   test;
-   simulación;
-   análisis;
-   inspección;
-   review;
-   measurement;
-   formal proof.

No representa necesariamente una ejecución concreta.

Ejemplo:

``` text
VER-MINIGPU-BAR
```

------------------------------------------------------------------------

### 3.8 EVIDENCE

Representa un resultado concreto preservado.

Ejemplos:

-   resultado de tests;
-   waveform;
-   informe de síntesis;
-   informe de timing;
-   P&R;
-   medida física;
-   review record.

Ejemplo:

``` text
EVID-PNR-2026-09-21
```

------------------------------------------------------------------------

### 3.9 SOURCE

Representa una fuente externa con identidad estable.

Ejemplos:

-   datasheet;
-   estándar;
-   paper;
-   requisito externo;
-   issue;
-   meeting record;
-   manual de fabricante.

Ejemplo:

``` text
SRC-ECP5-DATASHEET
```

Una referencia documental ligera no necesita convertirse en SOURCE si no
requiere identidad ni relaciones propias.

------------------------------------------------------------------------

## 4. Clasificación

Los Artifact pueden clasificarse mediante:

-   `TYPE`: tipo fundamental;
-   `KIND`: subtipo dependiente del TYPE;
-   `SUBJECT`: dominio o parte del sistema;
-   `STATUS`: lifecycle editorial.

Los tipos fundamentales deben permanecer pequeños. Las extensiones de
dominio deben expresarse preferentemente mediante `kind`, `subject`,
queries y reglas.

------------------------------------------------------------------------

## 5. RESOURCE, ARTIFACT, SECTION, FACET y SYMBOL

### 5.1 RESOURCE

Un RESOURCE es un contenedor o ubicación física.

Ejemplos:

``` text
docs/isa.md
rtl/gpu/simt_stack.sv
tests/test_bar.py
vendor/ecp5.pdf
```

RESOURCE no es automáticamente un nodo semántico del grafo.

------------------------------------------------------------------------

### 5.2 ARTIFACT

Un ARTIFACT es una unidad lógica identificable y trazable.

Un Resource puede contener varios Artifacts.

La relación inversa no debe suponerse 1:1: una unidad lógica puede
necesitar representación distribuida. La sintaxis y reglas exactas para
Artifacts distribuidos entre varios Resources quedan por cerrar antes de
incorporarlas al formato Markdown estable.

------------------------------------------------------------------------

### 5.3 SECTION

Una SECTION es una ubicación documental direccionable dentro de un
Artifact.

En Markdown se descubre normalmente a partir de headings.

Ejemplo:

``` text
SPEC-MINIGPU-ISA#ssy
```

------------------------------------------------------------------------

### 5.4 FACET

Una FACET es una subdivisión semántica identificada dentro de un
Artifact.

No es otro Artifact.

Ejemplo:

``` text
SPEC-MINIGPU-ISA@calls
```

Puede estar representada por una SECTION.

------------------------------------------------------------------------

### 5.5 SYMBOL

Un SYMBOL es una unidad sintáctica de código que participa en
trazabilidad sin convertirse automáticamente en Artifact.

Ejemplos:

``` text
IMPL-MINIGPU-RTL::ssy
IMPL-TRACE::resolve_reference
```

Puede representar módulos, clases, funciones, métodos, procesos RTL u
otros constructos reconocidos por un adapter.

------------------------------------------------------------------------

## 6. Identidades

Ejemplos:

``` text
SPEC-ISA
SPEC-ISA#ssy
SPEC-ISA@calls
IMPL-MINIGPU::ssy
rtl/gpu/simt_stack.sv::ssy
```

Reglas:

-   Artifact IDs son globalmente únicos en el proyecto.
-   Section, Facet y Symbol IDs son locales al namespace del Artifact.
-   Los IDs son case-sensitive.
-   Los IDs formales utilizan un subconjunto ASCII práctico.
-   `#`, `@`, `:` y `/` están reservados como separadores.
-   Los IDs derivados de headings usan una función slug única y
    documentada.
-   Los IDs derivados son deliberadamente menos estables que los IDs
    formales.

Referencias relativas dentro del Artifact actual:

``` text
#ssy
@calls
::update-mask
```

No existen búsquedas heurísticas, imports implícitos, `../` ni búsqueda
automática en Artifact padre.

Resolución:

``` text
0 matches  -> error
1 match    -> valid
>1 matches -> error
```

Se permiten forward references: primero se construye el modelo completo
y después se resuelve.

------------------------------------------------------------------------

## 7. Relaciones semánticas core

### 7.1 `derived-from`

Procedencia directa.

No significa herencia normativa, dependencia genérica ni transitividad
automática.

------------------------------------------------------------------------

### 7.2 `refines`

Concretización o descomposición normativa estricta manteniendo válido el
elemento refinado.

------------------------------------------------------------------------

### 7.3 `addresses`

Respuesta intencional a otro elemento, parcial o total.

No implica por sí misma satisfacción ni implementación.

------------------------------------------------------------------------

### 7.4 `requires`

Dependencia fuerte de conformidad.

Si A `requires` B, conformar con A requiere conformar con B.

Los caminos transitivos pueden mostrarse, pero no se materializan
automáticamente como relaciones autoritativas.

------------------------------------------------------------------------

### 7.5 `implements`

Relación fuerte.

``` text
X implements Y
```

significa que X pretende realizar completamente el comportamiento
obligatorio declarado por Y.

No implica que haya sido verificado.

------------------------------------------------------------------------

### 7.6 `satisfies`

Relación fuerte entre una realización/solución y un REQUIREMENT.

No existe `satisfies` parcial en el core.

------------------------------------------------------------------------

### 7.7 `verifies`

Relaciona una VERIFICATION u otro elemento apropiado con aquello que
verifica.

Atributo:

``` text
coverage=partial|complete
```

Default:

``` text
partial
```

`complete` es relativo exactamente al target declarado.

Varias verificaciones parciales no se agregan automáticamente en una
verificación completa.

------------------------------------------------------------------------

### 7.8 `produces`

Expresa que una ejecución, proceso o elemento produce otro resultado
trazable.

Los outputs efímeros no necesitan convertirse en Artifacts.

------------------------------------------------------------------------

### 7.9 `supersedes`

Reemplazo histórico/semántico fuerte.

``` text
V2 supersedes V1
```

no significa que V2 herede el contenido de V1.

Las referencias históricas a V1 no se reescriben automáticamente.

------------------------------------------------------------------------

## 8. Relaciones reservadas/experimentales de v0.4

Las siguientes capacidades se consideran necesarias o muy prometedoras,
pero su semántica completa debe cerrarse antes de formar parte del
núcleo estable.

### 8.1 `extends`

`extends` queda reservado para **herencia normativa**.

Debe distinguirse de:

``` text
derived-from  -> procedencia
supersedes    -> reemplazo
extends       -> composición/herencia normativa entre versiones
```

Ejemplo conceptual:

``` text
SPEC-ISA-V2 --extends--> SPEC-ISA-V1
```

significaría que V2 incorpora normativamente V1 como base.

Esto permitiría una especificación efectiva:

``` text
effective(V2) = inherited(V1) + own(V2) + overrides - removals
```

Antes de estabilizar `extends` deben definirse:

1.  direccionamiento de contenido heredado;
2.  overrides;
3.  removals;
4.  múltiples niveles;
5.  ciclos;
6.  interacción con `implements`;
7.  interacción con `verifies`;
8.  materialización;
9.  migración de relaciones.

`extends` no debe simularse mediante `derived-from` o `supersedes`.

------------------------------------------------------------------------

### 8.2 Composición normativa de especificaciones

Un sistema puede estar definido por varias especificaciones
independientes:

``` text
SPEC-MINIGPU-ISA
SPEC-MINIGPU-ABI
SPEC-MINIGPU-MEMORY-MAP
SPEC-MINIGPU-MMIO
SPEC-MINIGPU-ISA-EXTENSIONS
```

y, al mismo tiempo, ser útil hablar del contrato conjunto:

``` text
SPEC-MINIGPU
```

Se reserva una relación de **composición normativa**, provisionalmente
denominada:

``` text
composed-of
```

Ejemplo conceptual:

``` text
SPEC-MINIGPU
  composed-of SPEC-MINIGPU-ISA
  composed-of SPEC-MINIGPU-ABI
  composed-of SPEC-MINIGPU-MEMORY-MAP
  composed-of SPEC-MINIGPU-MMIO
  composed-of SPEC-MINIGPU-ISA-EXTENSIONS
```

No es:

-   estructura de archivos;
-   `contains`;
-   `requires`;
-   `extends`.

Su semántica buscada es que el contrato efectivo de la SPEC compuesta
incluya normativamente sus componentes.

Así podría expresarse:

``` text
IMPL-MINIGPU-RTL implements SPEC-MINIGPU
IMPL-MINIGPU-SIM implements SPEC-MINIGPU
```

sin repetir manualmente una relación global por cada componente.

La inferencia resultante debe ser explicable; no se crearán
silenciosamente relaciones `implements` autoritativas hacia cada
componente.

Antes de estabilizar esta relación deben cerrarse:

-   nombre definitivo;
-   tipos permitidos como source/target;
-   ciclos;
-   composición anidada;
-   semántica exacta de `implements`;
-   semántica exacta de `verifies`;
-   interacción con `extends`.

------------------------------------------------------------------------

## 9. Estructura no semántica

La estructura se mantiene separada de `Relation[]`.

Ejemplos:

-   `owner_artifact`;
-   `immediate_facet`;
-   `parent_facet`;
-   `parent_symbol`;
-   Facet representada por Section;
-   miembros de una Verification compuesta.

No se utiliza una relación universal `contains`.

------------------------------------------------------------------------

## 10. Markdown

### 10.1 Artifact

``` markdown
<!-- trace:artifact SPEC-ISA
type: specification
-->

# MiniISA
```

La directiva precede al heading asociado.

El Artifact abarca el subtree del heading hasta el siguiente heading del
mismo nivel o superior.

No se requiere `trace:end`.

Los Artifacts pueden anidarse documentalmente, pero el nesting no crea
relaciones semánticas.

------------------------------------------------------------------------

### 10.2 Section

No existe `trace:section`.

Las Sections se descubren a partir de headings.

ID formal:

``` markdown
## SSY {#ssy}
```

Una Section con ID derivado puede ser target si es inequívoca.

Para actuar como source de relaciones debe tener ID formal.

------------------------------------------------------------------------

### 10.3 Facet

``` markdown
<!-- trace:facet calls
kind: capability
-->

## Calls {#calls}
```

En v0.4 se mantiene la regla de que el ID local de Facet y el ID formal
de su Section representativa coincidan.

------------------------------------------------------------------------

### 10.4 Relaciones desde Section

``` markdown
<!-- trace:relations
requires:
  - SPEC-X#foo
verifies:
  - target: SPEC-Y#bar
    coverage: complete
-->

## Something {#something}
```

Las relaciones simples usan un target string.

Las relaciones con atributos usan un objeto con `target`.

------------------------------------------------------------------------

## 11. Código

Sintaxis compacta:

``` text
[local-id] @relation target [attributes...]
```

Ejemplos:

``` sv
// @implements SPEC-ISA#ssy
module simt_stack (...);
```

``` sv
// ssy @implements SPEC-ISA#ssy
module simt_stack (...);
```

``` python
# @verifies SPEC-ISA#ssy coverage=complete
def test_ssy_conformance():
    ...
```

Identidad explícita:

``` sv
// @id ssy
module simt_stack (...);
```

Reglas:

-   la anotación se asocia al siguiente símbolo;
-   whitespace y comentarios normales pueden interponerse;
-   un elemento sintáctico real rompe la asociación;
-   anotaciones consecutivas forman un grupo;
-   máximo un ID formal por grupo;
-   un ID antes de una relación formaliza el símbolo;
-   atributos usan `key=value`;
-   atributos desconocidos son error salvo extensión registrada.

Directivas estructurales:

``` text
@id
@artifact
@within
```

No son relaciones semánticas.

------------------------------------------------------------------------

## 12. Artifact de código con scope

Ejemplo:

``` sv
// @artifact IMPL-MINIGPU type=implementation scope=directory
module minigpu (...);
```

`scope=directory` significa:

-   resource actual;
-   siblings del mismo directorio;
-   no recursivo.

Dos Artifacts reclamando el mismo directorio son error de configuración.

No se introduce `scope=tree` inicialmente.

------------------------------------------------------------------------

## 13. Adapters

Interfaz conceptual:

``` text
Adapter
  supports(resource)
  scan(resource) -> observations
```

Niveles:

1.  annotations;
2.  named symbols;
3.  hierarchy.

Nivel 1 es suficiente para considerar un lenguaje soportado.

Un adapter puede localizar un símbolo no anotado cuando una relación lo
referencia y materializarlo en el modelo. No debe construir un
inventario exhaustivo de todos los símbolos si no participan en
trazabilidad.

------------------------------------------------------------------------

## 14. Sidecars

Nombre:

``` text
<basename>.trace.yaml
```

Un sidecar es una representación alternativa de metadata, no una base de
datos y no un SOURCE por sí mismo.

Puede describir recursos que no pueden o no deben modificarse.

Puede incluir:

-   revision;
-   URL;
-   retrieval date;
-   checksum.

Las rutas relativas se resuelven respecto al Resource que contiene la
metadata.

------------------------------------------------------------------------

## 15. Referencias externas ligeras

`references` permite referencias documentales sin crear una arista del
grafo.

Ejemplo conceptual:

``` yaml
references:
  - resource: vendor/manual.pdf
    page: 42
    note: Timing requirement
```

Cuando una fuente necesita identidad estable y relaciones, debe
promoverse a SOURCE.

Los targets de relaciones semánticas nunca son rutas crudas: deben ser
nodos del modelo.

------------------------------------------------------------------------

## 16. Authority y versionado

La autoridad pertenece a la representación/fuente, no a un campo
universal del Artifact.

Conceptos como AUTHORED, GENERATED y EXTERNAL se infieren de la
representación.

Una representación generada nunca debe ser la única autoridad de los
datos necesarios para regenerarla.

No existe un `version:` universal para Artifact.

Git gestiona la evolución normal:

``` text
SPEC-X @ commit A
SPEC-X @ commit B
```

Se crean identidades distintas cuando las variantes deben coexistir en
el modelo:

``` text
SPEC-X-V1
SPEC-X-V2
```

y, si corresponde:

``` text
SPEC-X-V2 --supersedes--> SPEC-X-V1
```

------------------------------------------------------------------------

## 17. Especificaciones WIP

Una especificación en desarrollo puede tener identidad propia cuando
debe coexistir con la versión vigente.

Ejemplo:

``` text
SPEC-MINIGPU-ISA-V1       status: accepted
SPEC-MINIGPU-ISA-V2-WIP   status: draft
```

Git conserva las revisiones internas del WIP.

El WIP puede terminar de dos formas:

1.  permanecer como delta mediante un futuro `extends`;
2.  materializarse/reorganizarse en una nueva SPEC completa.

El WIP no obliga a que su estructura documental sea la estructura final
de V2.

------------------------------------------------------------------------

## 18. Verification y Evidence

VERIFICATION representa el método/intención estable.

EVIDENCE representa un resultado preservado.

No se introduce una entidad EXECUTION en el core v0.4.

Una Verification compuesta puede tener `members` como estructura
específica de Verification.

La cobertura completa nunca se deduce simplemente de sumar miembros
parciales.

------------------------------------------------------------------------

## 19. Generated blocks / gendoc

Formato:

``` markdown
<!-- gendoc:begin cpu-utilization
generator: pnr.utilization
target: IMPL-MINICPU
-->
...
<!-- gendoc:end cpu-utilization -->
```

Reglas:

-   el ID identifica el slot local;
-   begin/end repiten ID;
-   `generator:` es core;
-   el resto de campos son configuración del generator;
-   el bloque no es graph-addressable;
-   metadata Trace dentro del bloque generado se ignora al escanear
    ProjectModel;
-   no se permiten bloques anidados/solapados;
-   el contenido se materializa normalmente en Markdown y puede
    commitearse;
-   la generación debe ser determinista;
-   no se añaden timestamps automáticos.

Operaciones:

``` text
gendoc update
gendoc check
```

------------------------------------------------------------------------

## 20. Configuración raíz

`trace.yaml` define:

-   proyecto;
-   discovery;
-   configuración;
-   vocabulario del proyecto;
-   kinds;
-   subjects;
-   relaciones de extensión registradas;
-   reglas y extensiones.

No es un registro central de instancias.

Los Artifact y sus relaciones viven en Markdown, código o sidecars.

------------------------------------------------------------------------

## 21. ProjectModel

Pipeline:

``` text
trace.yaml
   ↓
Discovery
   ↓
Resources
   ↓
Adapters
   ↓
Observations
   ↓
ModelBuilder
   ↓
RawProjectModel
   ↓
Resolver
   ↓
ProjectModel immutable
   ↓
Validators + Graph + Query
                  ↓
                gendoc
```

Parsing y resolución son fases diferentes.

Los adapters producen observaciones y no mutan el grafo.

El ModelBuilder resuelve estructura, ownership, scopes e identidades,
pero no las referencias semánticas.

El Resolver actúa después de escanear todas las fuentes.

------------------------------------------------------------------------

## 22. SourceLocation y diagnostics

Toda observación lleva ubicación desde su creación:

-   resource;
-   start line;
-   opcionalmente column;
-   opcionalmente end position.

Los diagnósticos se acumulan.

Se distinguen conceptualmente:

-   build errors;
-   resolution errors;
-   semantic validation errors.

Todos se representan mediante `Diagnostic`.

Los diagnósticos deberían tener códigos estables.

------------------------------------------------------------------------

## 23. IdentityIndex

El modelo construye índices explícitos para:

-   artifacts;
-   sections;
-   facets;
-   symbols.

Internamente se prefieren objetos de identidad:

``` text
ArtifactId
SectionId(artifact, local)
FacetId(artifact, local)
SymbolId(artifact/resource, local)
```

en lugar de concatenar strings continuamente.

------------------------------------------------------------------------

## 24. Relaciones y grafo

Una Relation contiene conceptualmente:

``` text
source
kind
target
attributes
location
```

El grafo es una vista calculada.

Se pueden construir índices:

-   outgoing;
-   incoming;
-   by_type;
-   by_kind;
-   by_subject;
-   sections_by_artifact;
-   etc.

No son fuente de verdad persistente.

------------------------------------------------------------------------

## 25. Cache

La cache es opcional, descartable y exclusivamente de rendimiento.

Se cachean **observations por Resource**, no ProjectModel resuelto.

Validación rápida:

1.  `mtime_ns + size`;
2.  si cambian, calcular hash;
3.  si el hash coincide, reutilizar observations;
4.  si cambia, ejecutar adapter.

También invalidan:

-   versión del adapter;
-   versión del formato de cache.

Propiedad obligatoria:

``` text
ProjectModel(with cache) == ProjectModel(without cache)
```

No se optimiza inicialmente discovery mediante mtime de directorios.

------------------------------------------------------------------------

## 26. Queries

Las consultas son funciones sobre ProjectModel.

Python actúa como DSL.

Ejemplo conceptual:

``` python
@query
def unimplemented(model):
    return model.nodes(type="specification").without_incoming("implements")
```

Las queries pueden ser parametrizadas y reutilizadas por:

-   CLI;
-   gendoc;
-   rules;
-   UI;
-   agentes.

------------------------------------------------------------------------

## 27. Rules

Una Rule expresa una condición esperada del proyecto y produce
Diagnostics.

Ejemplo conceptual:

``` python
@rule
def accepted_requirements_are_satisfied(model):
    ...
```

Query y Rule son conceptos distintos:

``` text
Query -> pregunta
Rule  -> condición exigida
```

------------------------------------------------------------------------

## 28. Cobertura y huecos de especificación

v0.4 reconoce explícitamente que un ProjectModel puede ser parcial.

Trace puede ofrecer queries que ayuden a detectar posibles huecos, por
ejemplo:

``` text
unimplemented
unverified
not_fully_verified
unspecified
specification_gaps
```

Estas queries **no forman parte de la semántica fundamental de las
relaciones** y no deben confundir ausencia de trazabilidad con
demostración de ausencia de especificación.

Especialmente:

``` text
implementation symbol without implements
```

no implica automáticamente un error.

Muchos símbolos son detalles internos que no requieren SPEC propia.

La detección de gaps debe utilizar contexto, convenciones del proyecto,
relaciones existentes, adapters especializados y, cuando proceda, reglas
del dominio.

El metamodelo permite representar el resultado del proceso; la
metodología define cómo interpretar y cerrar esos huecos.

------------------------------------------------------------------------

## 29. Agentes

El metamodelo no define un tipo especial de agente.

Un agente puede consumir ProjectModel y sus queries para:

-   localizar contexto;
-   encontrar relaciones;
-   estudiar gaps;
-   comparar implementaciones;
-   localizar tests;
-   preparar una propuesta de DESIGN o SPECIFICATION.

Un agente no debe convertir automáticamente comportamiento observado en
contrato normativo.

Si las fuentes discrepan, la discrepancia debe mantenerse explícita
hasta que una decisión o especificación la resuelva.

Esto es una aplicación del metamodelo, no una nueva relación core.

------------------------------------------------------------------------

## 30. CLI de referencia

Operaciones previstas:

``` text
trace check
trace show <id>
trace list [filters]
trace find <text>
trace incoming <id>
trace outgoing <id>
trace tree <id>
trace impact <id>
trace path <from> <to>
trace stats

gendoc check
gendoc update
```

Queries conocidas pueden exponerse como comandos de conveniencia.

El CLI es una vista sobre la API; no debe contener semántica que no esté
disponible desde ProjectModel/query/rules.

------------------------------------------------------------------------

## 31. Extensiones de proyecto

El core no conoce:

-   ISA;
-   RTL;
-   FPGA;
-   P&R;
-   MiniGPU;
-   pytest;
-   protocolos concretos.

Un proyecto puede registrar:

-   kinds;
-   subjects;
-   relaciones adicionales con semántica definida;
-   queries;
-   rules;
-   generators;
-   adapters específicos.

No se permiten nombres de relaciones ad hoc sin registrar.

------------------------------------------------------------------------

## 32. MiniGPU como ejemplo de composición

Conceptualmente MiniGPU puede terminar modelándose como:

``` text
SPEC-MINIGPU
├─ composed-of → SPEC-MINIGPU-ISA
├─ composed-of → SPEC-MINIGPU-ABI
├─ composed-of → SPEC-MINIGPU-MEMORY-MAP
├─ composed-of → SPEC-MINIGPU-MMIO
└─ composed-of → SPEC-MINIGPU-ISA-EXTENSIONS
```

y dos realizaciones:

``` text
IMPL-MINIGPU-SIM --implements--> SPEC-MINIGPU
IMPL-MINIGPU-RTL --implements--> SPEC-MINIGPU
```

Además pueden existir relaciones finas:

``` text
IMPL-MINIGPU-RTL::lsu
    --implements--> SPEC-MINIGPU-ISA#memory
```

La relación global expresa conformidad con el contrato conjunto; las
relaciones finas permiten navegación y análisis local.

`composed-of` continúa experimental hasta cerrar su semántica exacta.

------------------------------------------------------------------------

## 33. Estado de v0.4

### Estable desde v0.3

-   tipos NEED, REQUIREMENT, DECISION, SPECIFICATION, IMPLEMENTATION,
    VERIFICATION, EVIDENCE, SOURCE;
-   RESOURCE / ARTIFACT / SECTION / FACET / SYMBOL;
-   identidades;
-   relaciones core existentes;
-   Markdown y anotaciones de código;
-   sidecars;
-   ProjectModel;
-   cache de observations;
-   queries/rules en Python;
-   gendoc.

### Incorporado en v0.4

-   DESIGN como Artifact fundamental;
-   distinción explícita DESIGN / DECISION / SPECIFICATION;
-   ProjectModel incompleto como estado legítimo;
-   gaps de especificación como problema consultable, no como error
    universal;
-   agentes como consumidores del modelo, sin convertir observación en
    norma.

### Reservado para cierre semántico

-   `extends`;
-   especificación efectiva;
-   override/removal/materialization;
-   relación de composición normativa `composed-of`;
-   Artifact lógico distribuido entre múltiples Resources y su sintaxis
    exacta.

------------------------------------------------------------------------

## 34. Regla de separación con la metodología

Una cuestión pertenece al metamodelo cuando cambia:

-   qué entidades existen;
-   qué identidad tienen;
-   qué significa una relación;
-   qué modelos son válidos;
-   qué inferencias son semánticamente legítimas.

Una cuestión pertenece a la metodología cuando describe:

-   cómo adoptar Trace;
-   en qué orden trabajar;
-   cómo detectar y cerrar gaps;
-   cómo utilizar agentes;
-   cómo evolucionar documentación incompleta;
-   cómo revisar y aprobar propuestas.

La metodología complementaria se define en `trace-methodology.md`.
