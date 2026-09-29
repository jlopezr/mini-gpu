# Modelo de trazabilidad y documentación — v0.3

## 1. Propósito

Este documento define un modelo ligero de documentación, trazabilidad y generación documental para proyectos técnicos.

El objetivo es disponer de un sistema suficientemente pequeño para utilizarse cómodamente en proyectos como MiniGPU, pero suficientemente general para proyectos de CPU, FPGA, software embebido, electrónica, sistemas espaciales u otros sistemas de ingeniería.

El modelo busca conectar explícitamente:

- necesidades;
- requisitos;
- decisiones;
- especificaciones;
- implementación;
- verificación;
- evidencia;
- fuentes externas;
- documentación generada.

La intención no es construir una herramienta ALM pesada ni sustituir Git, Markdown, los lenguajes de implementación o los sistemas de build.

El principio fundamental es:

> La información debe mantenerse cerca de su fuente de autoridad y las vistas documentales deben poder derivarse de ella.

---

# 2. Principios

## 2.1. Una única fuente de verdad

Un hecho estructurado debe tener una fuente autoritativa.

Las tablas, resúmenes, matrices y vistas derivadas pueden aparecer en muchos documentos, pero deben poder regenerarse desde esa fuente.

---

## 2.2. Trazabilidad explícita

Las relaciones importantes entre elementos del proyecto deben expresarse explícitamente.

No deben inferirse relaciones semánticas únicamente porque dos elementos estén próximos en un documento, compartan directorio o tengan nombres similares.

---

## 2.3. Pocas entidades fundamentales

El modelo mantiene deliberadamente pequeño el número de conceptos fundamentales.

La especialización se realiza preferentemente mediante `kind`, `subject` y extensiones registradas.

---

## 2.4. Identidad independiente de ubicación

La identidad semántica de un elemento no debe depender necesariamente del archivo donde se encuentre.

Por ejemplo:

```text
SPEC-ISA
SPEC-ISA#ssy
SPEC-ISA@calls
IMPL-MINIGPU::update-mask
```

son identidades lógicas.

El archivo y posición donde aparecen son propiedades de su representación.

---

## 2.5. Git como historial

El versionado ordinario de artifacts se delega a Git.

No se introduce un sistema paralelo de versiones salvo cuando varias variantes deban coexistir simultáneamente como entidades diferentes.

---

## 2.6. El grafo es independiente de la documentación generada

El modelo de proyecto y su grafo de trazabilidad deben poder construirse sin ejecutar `gendoc`.

`gendoc` consume el modelo.

El modelo no consume el resultado generado por `gendoc`.

---

# 3. Capas del sistema

Conceptualmente existen cuatro capas:

```text
Fuentes físicas
      │
      ▼
Adaptadores
      │
      ▼
Project Model / Trace Graph
      │
      ├──────────► consultas / CI / análisis
      │
      ▼
    gendoc
      │
      ▼
Documentación derivada
```

Las fuentes físicas incluyen Markdown, código, sidecars, informes externos y configuración.

Los adaptadores interpretan cada representación.

El Project Model contiene las identidades, estructura y relaciones.

`gendoc` genera vistas documentales a partir de ese modelo o de otras fuentes autoritativas.

---

# 4. RESOURCE

Un `RESOURCE` es un contenedor o ubicación física.

Ejemplos:

```text
docs/isa.md
rtl/gpu/simt_stack.sv
sim/simulator.py
vendor/w9825g6kh.pdf
build/pnr.json
```

Un RESOURCE no es por sí mismo una entidad semántica del grafo.

Puede contener ARTIFACTS, SECTIONs, FACETs o SYMBOLs.

Una ruta física no debe utilizarse como sustituto de una identidad semántica cuando se necesita trazabilidad estable.

---

# 5. ARTIFACT

Un `ARTIFACT` es una unidad lógica identificable y trazable.

Todo ARTIFACT tiene como mínimo:

```yaml
id: ...
type: ...
```

El `type` no se infiere del prefijo del ID.

Los IDs de ARTIFACT son globalmente únicos dentro del proyecto.

Ejemplo:

```text
SPEC-ISA
REQ-GPU-RECONVERGENCE
DEC-SIMT-RECONVERGENCE
IMPL-MINIGPU
VER-SSY-DIVERGENCE
```

---

# 6. Tipos fundamentales

## 6.1. NEED

Representa una necesidad, objetivo, problema o intención.

Responde principalmente a:

> ¿Por qué queremos hacer esto?

No constituye necesariamente una obligación verificable.

---

## 6.2. REQUIREMENT

Representa una obligación cuya satisfacción puede reclamarse.

Responde principalmente a:

> ¿Qué debe cumplirse?

Ejemplos de `kind` posibles:

- functional;
- performance;
- interface;
- safety;
- resource;
- timing;
- constraint.

No todo enunciado normativo de una especificación debe convertirse automáticamente en REQUIREMENT.

Solo se crea un REQUIREMENT independiente cuando esa obligación necesita identidad y trazabilidad propias.

---

## 6.3. DECISION

Representa una decisión de ingeniería.

Responde principalmente a:

> ¿Qué opción se eligió y por qué?

Las alternativas, ventajas, inconvenientes y razonamiento pueden permanecer como Markdown normal dentro del artifact.

No es necesario convertir cada parte de un ADR en entidades estructuradas.

---

## 6.4. SPECIFICATION

Describe cómo debe comportarse o estructurarse algo.

Ejemplos de `kind`:

- architecture;
- interface;
- protocol;
- register;
- instruction;
- data-format;
- algorithm;
- component.

---

## 6.5. IMPLEMENTATION

Representa una implementación con identidad semántica propia.

Puede corresponder a:

- RTL;
- software;
- firmware;
- PCB;
- mecánica;
- configuración;
- otros elementos implementativos.

No toda función, módulo o región de código necesita convertirse en IMPLEMENTATION.

Para granularidad interna existe SYMBOL.

---

## 6.6. VERIFICATION

Representa una definición estable de cómo se pretende verificar algo.

Ejemplos:

- test;
- simulation;
- analysis;
- inspection;
- review;
- measurement;
- formal-proof.

Una VERIFICATION no representa cada ejecución individual de un test.

---

## 6.7. EVIDENCE

Representa un resultado concreto preservado que puede utilizarse como evidencia.

Ejemplos:

- resultado de tests;
- waveform;
- informe de síntesis;
- informe de timing;
- informe P&R;
- medida física;
- registro de revisión.

Las ejecuciones efímeras no necesitan convertirse automáticamente en EVIDENCE.

---

## 6.8. SOURCE

Representa una fuente externa que necesita identidad estable dentro del grafo.

Ejemplos:

- datasheet;
- estándar;
- paper;
- requisito externo;
- issue;
- acta;
- manual.

Una simple referencia documental no necesita convertirse automáticamente en SOURCE.

---

# 7. KIND

`KIND` especializa un TYPE.

Los kinds se registran por TYPE y pueden extenderse por proyecto.

Ejemplo:

```yaml
kinds:
  specification:
    - architecture
    - interface
    - protocol

  verification:
    - test
    - simulation
    - analysis
```

Un KIND no constituye por sí mismo una nueva entidad fundamental.

---

# 8. SUBJECT

`SUBJECT` clasifica artifacts por dominio o materia.

Ejemplos:

```text
isa
cpu
gpu
video
memory
compiler
simulator
```

Los SUBJECT pueden organizarse jerárquicamente si el proyecto lo desea.

La pertenencia a un SUBJECT no implica relaciones semánticas.

---

# 9. STATUS

El estado editorial almacenado inicialmente es:

```text
proposed
accepted
deprecated
rejected
```

Estados como:

```text
implemented
verified
superseded
```

no se almacenan necesariamente como lifecycle editorial.

Pueden derivarse del grafo y de la evidencia disponible.

---

# 10. SECTION

Una `SECTION` es estructura documental addressable dentro de un ARTIFACT Markdown.

No es un ARTIFACT.

Ejemplo:

```text
SPEC-ISA#ssy
```

Una SECTION puede ser target de relaciones.

Puede ser source de relaciones cuando dispone de ID formal.

---

## 10.1. ID derivado

Un heading puede generar un ID derivado:

```markdown
### SSY
```

puede producir:

```text
SPEC-ISA#ssy
```

Los IDs derivados son deliberadamente inestables frente a renombrados.

---

## 10.2. ID formal

Cuando una SECTION necesita identidad estable se utiliza un ID Markdown explícito:

```markdown
### Instrucción SSY y reconvergencia {#ssy}
```

que produce:

```text
SPEC-ISA#ssy
```

El ID permanece estable aunque cambie el título, nivel o posición.

Los IDs formales de SECTION deben ser únicos dentro del ARTIFACT.

No existen aliases automáticos ni seguimiento de renombres.

---

# 11. FACET

Una `FACET` es una subdivisión semántica identificada dentro de un ARTIFACT.

No tiene lifecycle independiente.

Ejemplo:

```text
SPEC-ISA@calls
SPEC-ISA@compare
```

Una capability de MiniISA puede modelarse como un KIND de FACET, pero `capability` no forma parte necesariamente del metamodelo universal.

---

## 11.1. FACET frente a ARTIFACT

Una FACET es adecuada mientras el elemento:

- dependa conceptualmente del artifact;
- no necesite lifecycle independiente;
- no necesite identidad global;
- no necesite autonomía documental.

Cuando esa autonomía aparece, debe promoverse a ARTIFACT.

---

## 11.2. Representación Markdown

Una FACET se asocia normalmente a una SECTION con ID formal.

```markdown
<!-- trace:facet calls
kind: capability
-->

## Function calls {#calls}
```

Esto crea simultáneamente:

```text
SPEC-ISA@calls
SPEC-ISA#calls
```

En v0.3 el ID local de la FACET y el ID formal de su SECTION deben coincidir.

---

## 11.3. Alcance

El alcance documental de una FACET es el subtree del heading al que está asociada.

Termina:

- al encontrar un heading del mismo nivel o superior;
- al cruzar una frontera de ARTIFACT.

No existe `facet:end`.

---

## 11.4. FACETs anidadas

Las FACET pueden anidarse estructuralmente.

Ejemplo:

```text
SPEC-ISA
└── @calls
    └── @indirect-calls
```

La FACET hija conserva identidad plana:

```text
SPEC-ISA@indirect-calls
```

y dispone estructuralmente de:

```text
parent-facet: SPEC-ISA@calls
```

`parent-facet` no es una relación semántica.

No implica `requires`, `refines` ni ninguna otra relación.

---

## 11.5. SECTION dentro de FACET

El Project Model conserva qué SECTION pertenece inmediatamente a qué FACET.

Una SECTION situada dentro de varias FACETs anidadas almacena únicamente su FACET inmediata.

La pertenencia a FACETs ancestras se obtiene mediante `parent-facet`.

---

# 12. SYMBOL

Un `SYMBOL` es una unidad sintáctica de código que participa en trazabilidad sin necesidad de convertirse en ARTIFACT.

Puede corresponder, por ejemplo, a:

- módulo SystemVerilog;
- función;
- clase;
- método;
- bloque `always_ff`;
- bloque `always_comb`;
- generate block;
- otra unidad reconocible por el adapter.

Un SYMBOL puede incluso corresponder a una construcción sin nombre propio si se le asigna un ID formal.

---

## 12.1. Materialización

Los adapters pueden reconocer la estructura del lenguaje, pero no deben crear un inventario completo de todos los símbolos del proyecto.

Un SYMBOL se materializa en el Project Model cuando participa en trazabilidad.

Esto ocurre, por ejemplo, si:

- contiene una anotación;
- es source de una relación;
- es target de una relación.

---

## 12.2. Target no anotado

Un SYMBOL no necesita estar previamente anotado para ser target.

Por ejemplo:

```text
IMPL-MINIGPU::simt_stack
```

puede resolverse contra:

```systemverilog
module simt_stack (...);
```

Si el adapter puede identificarlo inequívocamente.

---

## 12.3. Identidad derivada

Un SYMBOL puede obtener identidad derivada de su nombre y contexto.

Ejemplo:

```text
IMPL-MINIGPU::simt_stack
```

Los IDs derivados son deliberadamente sensibles a renombres.

---

## 12.4. Identidad formal

Puede asignarse un ID local estable:

```systemverilog
// @id update-mask
always_ff @(posedge clk) begin
    ...
end
```

que produce:

```text
IMPL-MINIGPU::update-mask
```

El ID formal permanece estable aunque cambie la construcción concreta o su nombre en el lenguaje.

---

## 12.5. Jerarquía

Cuando el adapter conoce la jerarquía del lenguaje, la identidad derivada puede reflejarla:

```text
IMPL-SIMULATOR::Simulator.execute_ssy
```

El modelo puede conservar `parent-symbol`.

No todos los adapters están obligados a descubrir jerarquía.

Un ID formal sigue siendo local directamente al ARTIFACT:

```text
IMPL-SIMULATOR::ssy-execution
```

y no depende de la jerarquía sintáctica.

---

## 12.6. Localización

Todo SYMBOL trazable debe disponer al menos de una localización inicial.

La localización final es opcional.

Si el adapter puede determinar fácilmente el rango completo, puede conservarlo.

La semántica de trazabilidad nunca depende de conocer el final del SYMBOL.

---

# 13. Espacios de identidad

Los ARTIFACT tienen identidad global:

```text
SPEC-ISA
IMPL-MINIGPU
```

Los elementos internos tienen identidad local al ARTIFACT:

```text
SPEC-ISA#ssy
SPEC-ISA@calls
IMPL-MINIGPU::update-mask
```

La sintaxis es:

```text
ARTIFACT
ARTIFACT#SECTION
ARTIFACT@FACET
ARTIFACT::SYMBOL
```

---

# 14. SYMBOL sin ARTIFACT lógico

Cuando un SYMBOL pertenece a un ARTIFACT se prefiere:

```text
IMPL-MINIGPU::ssy
```

Si no existe ARTIFACT contenedor puede utilizarse el RESOURCE como namespace:

```text
rtl/gpu/simt_stack.sv::ssy
```

Esto proporciona distintos grados de estabilidad.

La identidad bajo ARTIFACT puede sobrevivir tanto al renombrado del símbolo como al movimiento de archivo si utiliza ID formal.

---

# 15. Gramática de IDs

Los IDs formales utilizan una gramática deliberadamente restringida.

Se permiten:

```text
A-Z
a-z
0-9
_
-
```

Los siguientes caracteres quedan reservados para composición de identidades:

```text
#
@
:
/
```

Las identidades son case-sensitive.

No se realiza normalización silenciosa de IDs formales.

Los IDs derivados utilizan una única función de slug documentada y determinista.

---

# 16. Relaciones

El vocabulario core es deliberadamente pequeño.

Las relaciones fundamentales son:

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

Cada relación tiene dirección canónica.

Solo se almacena la relación outgoing autoritativa.

Las vistas inversas se calculan.

---

# 17. derived-from

```text
A --derived-from--> B
```

Indica procedencia conceptual directa.

No significa dependencia genérica.

No debe utilizarse como sustituto de `requires`, `refines`, etc.

No se considera automáticamente transitiva.

---

# 18. refines

```text
A --refines--> B
```

A concreta o descompone normativamente B manteniendo B válido.

---

# 19. addresses

```text
A --addresses--> B
```

A constituye una respuesta intencional a B.

Puede ser parcial o total.

No implica satisfacción, implementación ni verificación.

No tiene atributo de coverage.

---

# 20. requires

```text
A --requires--> B
```

A necesita conformidad con B para ser válido o implementarse correctamente.

Es una dependencia fuerte de conformidad.

No representa pertenencia estructural.

Los caminos transitivos pueden mostrarse en análisis, pero no se crean automáticamente relaciones authored adicionales.

---

# 21. implements

```text
A --implements--> B
```

A pretende implementar completamente el comportamiento obligatorio de B.

Es una relación fuerte.

No tiene atributo `partial`.

No implica que la implementación haya sido verificada.

Normalmente:

```text
IMPLEMENTATION --implements--> SPECIFICATION
```

Implementar el artifact base no implica implementar automáticamente sus FACETs opcionales.

---

# 22. satisfies

```text
A --satisfies--> B
```

A es suficiente para cumplir completamente la obligación representada por B.

Es siempre fuerte.

No existe `partial satisfies`.

Normalmente:

```text
... --satisfies--> REQUIREMENT
```

Una implementación agregada puede satisfacer un requisito aunque internamente varios componentes contribuyan a ello.

---

# 23. verifies

```text
A --verifies--> B
```

Indica intención de verificación.

Tiene:

```text
coverage=partial
coverage=complete
```

El valor por defecto es:

```text
partial
```

`complete` se interpreta exclusivamente respecto al target exacto declarado.

Verificar completamente:

```text
SPEC-ISA#ssy
```

no implica verificar completamente:

```text
SPEC-ISA
```

No existe propagación ascendente automática.

---

# 24. produces

```text
A --produces--> B
```

Indica que B es resultado de ejecutar o procesar A.

Ambos extremos deben tener identidad trazable cuando se utiliza la relación.

Los resultados efímeros no necesitan convertirse en artifacts.

---

# 25. supersedes

```text
A --supersedes--> B
```

A sustituye formalmente a B.

El estado superseded de B puede derivarse de esta relación.

Las referencias históricas hacia B no se reescriben.

---

# 26. Relaciones eliminadas del core

No forman parte del vocabulario core:

```text
depends-on
affects
contains
```

`depends-on` resulta demasiado genérico.

`affects` resulta demasiado ambiguo.

`contains` pertenece normalmente a estructura, no a semántica del grafo.

---

# 27. Extensiones de relaciones

Un proyecto puede añadir relaciones propias.

Deben registrarse en `trace.yaml`.

Una relación registrada debe definir su semántica.

No se permiten nombres de relación ad hoc introducidos directamente en documentos.

---

# 28. Targets válidos

Las relaciones semánticas pueden dirigirse a elementos semánticos addressable:

```text
ARTIFACT
ARTIFACT#SECTION
ARTIFACT@FACET
ARTIFACT::SYMBOL
```

Un RESOURCE físico no es target semántico.

Si un recurso externo necesita participar en el grafo debe adquirir identidad mediante un ARTIFACT, por ejemplo SOURCE.

---

# 29. Referencias locales

Dentro del contexto de un ARTIFACT se permiten:

```text
#ssy
@calls
::update-mask
```

equivalentes a:

```text
SPEC-ISA#ssy
SPEC-ISA@calls
SPEC-ISA::update-mask
```

si el ARTIFACT actual es `SPEC-ISA`.

Las referencias relativas solo resuelven dentro del ARTIFACT actual.

No existe:

```text
../
```

ni búsqueda automática en artifacts documentalmente padres.

Para referirse a otro ARTIFACT se exige identidad absoluta:

```text
SPEC-ISA@calls
```

---

# 30. Resolución de referencias

La resolución es estricta.

Una referencia debe resolver exactamente a una identidad.

```text
0 resultados  → error
1 resultado   → válido
>1 resultados → error
```

No se utilizan heurísticas para adivinar la intención.

Las forward references están permitidas.

El sistema construye primero el modelo completo y después resuelve y valida relaciones.

---

# 31. Representación Markdown de ARTIFACT

Se utiliza un comentario HTML inmediatamente anterior al heading:

```markdown
<!-- trace:artifact SPEC-ISA
type: specification
subjects: [isa, cpu, gpu]
-->

# MiniCPU / MiniGPU ISA
```

La cabecera tiene forma:

```text
trace:<element-type> <id>
```

El cuerpo es YAML.

El ID aparece en la cabecera.

La metadata aparece en YAML.

---

# 32. ARTIFACT Markdown y headings

En v0.3 un `trace:artifact` Markdown debe asociarse siempre a un heading.

No existe el caso especial:

```text
ARTIFACT = RESOURCE completo
```

sin heading.

---

# 33. Alcance de ARTIFACT en Markdown

El alcance del ARTIFACT es el subtree del heading asociado.

Termina al encontrar un heading del mismo nivel o superior.

No se necesita `trace:end`.

---

# 34. ARTIFACTS anidados

Los ARTIFACT pueden estar documentalmente anidados.

Un ARTIFACT interior captura su subtree.

Las SECTION interiores pertenecen únicamente al ARTIFACT más cercano.

Ejemplo conceptual:

```text
SPEC-GPU
├── #alu
└── SPEC-SIMT
    ├── #stack
    ├── #push
    └── #pop
```

No se crean simultáneamente:

```text
SPEC-GPU#push
SPEC-SIMT#push
```

El nesting documental no crea una relación semántica entre los ARTIFACTS.

---

# 35. ARTIFACT como frontera semántica local

Un ARTIFACT establece una frontera para:

- SECTION;
- FACET;
- SYMBOL.

Una FACET no atraviesa un ARTIFACT anidado.

Las estructuras ligeras pertenecen a un único ARTIFACT propietario.

---

# 36. Relaciones desde ARTIFACT

Las relaciones outgoing del ARTIFACT se incluyen en su metadata:

```markdown
<!-- trace:artifact DEC-SIMT-RECONVERGENCE
type: decision
subjects: [gpu, isa]
addresses:
  - REQ-GPU-RECONVERGENCE
-->
```

---

# 37. Relaciones desde FACET

Se incluyen en la declaración de FACET:

```markdown
<!-- trace:facet texture
kind: capability
requires:
  - SPEC-MEMORY@unaligned-loads
-->

## Texture {#texture}
```

---

# 38. Relaciones desde SECTION

Una SECTION utiliza `trace:relations`.

Debe tener ID formal para actuar como source.

```markdown
<!-- trace:relations
derived-from:
  - DEC-SIMT-RECONVERGENCE
-->

### SSY {#ssy}
```

---

# 39. Relaciones con atributos

La forma simple es:

```yaml
verifies:
  - SPEC-ISA#ssy
```

equivalente a `coverage=partial`.

La forma extendida es:

```yaml
verifies:
  - target: SPEC-ISA#ssy
    coverage: complete
```

---

# 40. Anotaciones de código

La forma compacta general es:

```text
[local-id] @relation target [key=value ...]
```

Ejemplo:

```systemverilog
// @implements SPEC-ISA#ssy
module simt_stack (...);
```

Sin ID explícito se utiliza identidad derivada del SYMBOL.

---

# 41. ID formal + relación

Puede escribirse:

```systemverilog
// update-mask @implements SPEC-SIMT#active-mask
always_ff @(posedge clk) begin
    ...
end
```

`update-mask` formaliza automáticamente la identidad local.

Es equivalente conceptualmente a:

```systemverilog
// @id update-mask
// @implements SPEC-SIMT#active-mask
always_ff @(posedge clk) begin
    ...
end
```

---

# 42. ID sin relación

Para asignar únicamente identidad:

```systemverilog
// @id update-mask
always_ff @(posedge clk) begin
    ...
end
```

La forma elegida es:

```text
@id update-mask
```

y no:

```text
update-mask @id
```

---

# 43. Grupos de anotaciones

Las anotaciones consecutivas asociadas a la misma unidad sintáctica forman un grupo.

Ejemplo:

```systemverilog
// update-mask @implements SPEC-SIMT#active-mask
// @requires SPEC-ISA#ssy
always_ff @(posedge clk) begin
    ...
end
```

Ambas relaciones tienen como source el mismo SYMBOL.

Un grupo puede establecer como máximo un ID formal.

Esto es error:

```systemverilog
// update-mask @implements SPEC-SIMT#active-mask
// mask-writer @requires SPEC-ISA#ssy
always_ff ...
```

v0.3 no soporta aliases de SYMBOL.

---

# 44. Binding de anotaciones

Un grupo de anotaciones se asocia al siguiente elemento sintáctico reconocido.

Entre anotación y elemento se permiten:

- whitespace;
- comentarios normales.

Un elemento sintáctico real intermedio rompe la asociación.

Por ejemplo, una directiva de preprocesador puede romperla.

---

# 45. Atributos de relaciones en código

Los atributos utilizan únicamente:

```text
key=value
```

Ejemplo:

```python
# test-ssy @verifies SPEC-ISA#ssy coverage=complete
def test_ssy():
    ...
```

v0.3 no define arrays, objetos ni una sintaxis compleja de valores dentro de comentarios de código.

---

# 46. ARTIFACT declarado desde código

Un ARTIFACT puede declararse:

```systemverilog
// @artifact IMPL-MINIGPU type=implementation
module minigpu (...);
```

Si un grupo contiene `@artifact`, las relaciones del mismo grupo tienen como source ese ARTIFACT:

```systemverilog
// @artifact IMPL-MINIGPU type=implementation
// @implements SPEC-ISA
module minigpu (...);
```

produce:

```text
IMPL-MINIGPU --implements--> SPEC-ISA
```

Sin `@artifact`, las relaciones tienen como source el SYMBOL asociado.

---

# 47. Scope de ARTIFACT de código

Un ARTIFACT puede declarar:

```systemverilog
// @artifact IMPL-MINIGPU type=implementation scope=directory
module minigpu (...);
```

`scope=directory` incluye:

- el RESOURCE actual;
- los resources hermanos del mismo directorio.

No es recursivo.

No existe `scope=tree` en v0.3.

---

# 48. Conflictos de scope

Dos ARTIFACTS no pueden reclamar simultáneamente:

```text
scope=directory
```

sobre el mismo directorio.

Es un error de configuración.

---

# 49. @within

Para excepciones puede declararse explícitamente:

```text
@within IMPL-MINIGPU
```

Esto permite incorporar un RESOURCE a un contexto de ARTIFACT aunque quede fuera de su scope ordinario.

`@within` es metadata estructural.

No es una relación semántica.

---

# 50. Colisiones de SYMBOL

Los IDs de SYMBOL addressable dentro del namespace de un ARTIFACT deben ser únicos.

Si dos símbolos derivados producen el mismo ID y ambos participan en trazabilidad:

```text
IMPL-MINIGPU::foo
```

se produce un error.

La solución es proporcionar IDs formales.

No se incorporan automáticamente rutas de RESOURCE para resolver la colisión.

---

# 51. Niveles de adapters de código

Un adapter puede proporcionar distintos niveles de capacidad.

### Nivel 1 — annotations

Puede asociar anotaciones al siguiente elemento.

### Nivel 2 — named symbols

Reconoce elementos nombrados como:

- module;
- function;
- class;
- def;
- etc.

### Nivel 3 — hierarchy

Conoce relaciones padre/hijo entre símbolos.

El core no depende de disponer de AST completo.

Un adapter mínimo puede ser útil únicamente con Nivel 1.

---

# 52. Sidecars

Para resources que no pueden o no deben modificarse se utiliza:

```text
<basename>.trace.yaml
```

Ejemplo:

```text
vendor/
├── w9825g6kh.pdf
└── w9825g6kh.trace.yaml
```

Contenido:

```yaml
artifact: SRC-W9825G6KH-DATASHEET
type: source
kind: datasheet

resource:
  file: w9825g6kh.pdf
  revision: "Rev. A"
  sha256: "..."
```

---

# 53. Sidecar no implica SOURCE

Un sidecar es únicamente otra representación de metadata.

Puede describir:

- PDF;
- RTL de vendor;
- hoja de cálculo;
- binario;
- informe;
- cualquier otro RESOURCE.

No implica automáticamente:

```text
type: source
```

---

# 54. Metadata externa opcional

Un sidecar puede almacenar cuando resulte útil:

```text
revision
url
retrieval-date
sha256
```

Los checksums son útiles pero no obligatorios universalmente.

---

# 55. References ligeras

Para referencias documentales que no necesitan identidad semántica se utiliza `references`.

Forma corta:

```yaml
references:
  - vendor/foo.pdf
```

Forma estructurada:

```yaml
references:
  - resource: vendor/foo.pdf
    page: 23
    note: SDRAM timing
```

`references` no crea edges del grafo.

Si una referencia necesita:

- múltiples relaciones;
- identidad estable;
- versionado explícito;
- checksum;
- análisis de impacto;

debe promoverse a SOURCE.

---

# 56. Paths relativos

Todos los paths relativos presentes en metadata se resuelven respecto al RESOURCE que contiene esa metadata.

Ejemplo sidecar:

```yaml
resource:
  file: w9825g6kh.pdf
```

se resuelve respecto al directorio del sidecar.

Ejemplo gendoc:

```yaml
report: ../build/pnr.json
```

se resuelve respecto al Markdown que contiene el bloque.

Internamente la herramienta puede normalizarlos respecto a la raíz del proyecto.

---

# 57. Composite VERIFICATION

Una VERIFICATION compuesta puede declarar:

```yaml
type: verification
kind: test-suite
members:
  - VER-ALU
  - VER-CALLS
```

`members` es estructura específica de VERIFICATION compuesta.

No es una relación semántica universal.

La coverage de una VERIFICATION padre no se infiere automáticamente de sus miembros.

---

# 58. Ejecuciones y resultados

El modelo distingue:

```text
VERIFICATION
    definición estable

execution
    ocurrencia concreta potencialmente efímera

EVIDENCE
    resultado preservado y trazable
```

v0.3 no introduce `EXECUTION` como entidad core.

Las herramientas pueden consultar ejecuciones sin incorporarlas necesariamente al grafo persistente.

---

# 59. GENERATED BLOCK

Un bloque generado es una vista documental derivada embebida en Markdown.

Ejemplo:

```markdown
<!-- gendoc:begin cpu-utilization
generator: pnr.utilization
target: IMPL-MINICPU
-->

...contenido generado...

<!-- gendoc:end cpu-utilization -->
```

---

# 60. Identidad del bloque generado

`cpu-utilization` identifica el slot documental concreto.

No identifica al generador.

El mismo generador puede utilizarse en varios bloques.

Los IDs de bloques son locales al documento.

---

# 61. Configuración de gendoc

La cabecera sigue el mismo principio:

```text
gendoc:begin <id>
```

seguida de YAML.

`generator` es propiedad core:

```yaml
generator: pnr.utilization
```

Las demás propiedades pueden pertenecer al generador concreto.

---

# 62. Fuentes de gendoc

Los generators deben consumir preferentemente el Project Model o sus APIs de consulta cuando la información pertenece al modelo.

También pueden consumir directamente fuentes específicas externas cuando sea apropiado.

Ejemplo:

```text
P&R report → pnr.utilization → Markdown
```

No es obligatorio convertir todo input de generación en ARTIFACT.

---

# 63. Materialización

El contenido generado se materializa dentro del Markdown.

Normalmente se commitea a Git.

Esto permite:

- leer documentación sin ejecutar herramientas;
- revisar cambios documentales en diffs;
- publicar Markdown directamente;
- detectar desactualización en CI.

---

# 64. gendoc update

```text
gendoc update
```

regenera los bloques y sustituye su contenido.

---

# 65. gendoc check

```text
gendoc check
```

regenera conceptualmente en memoria y compara con el contenido materializado.

No modifica archivos.

Si existe diferencia, termina con error.

---

# 66. Determinismo

Los generators deben ser deterministas cuando sus inputs lo sean.

No se introducen timestamps automáticos.

Dos ejecuciones consecutivas de:

```text
gendoc update
```

sin cambios en inputs deben producir diff vacío.

---

# 67. Bloques anidados

Los bloques `gendoc` no pueden anidarse ni solaparse en v0.3.

Cada `gendoc:begin` debe cerrarse antes de abrir otro.

---

# 68. Trazabilidad dentro de gendoc

Todo contenido situado dentro de:

```text
gendoc:begin
...
gendoc:end
```

es derivado.

Las directivas `trace:*` que aparezcan dentro se ignoran al construir el Project Model.

Esto evita ciclos:

```text
model
  ↓
gendoc
  ↓
Markdown
  ↓
model
```

---

# 69. GENERATED BLOCK no es elemento del grafo

El ID de un bloque `gendoc` existe únicamente para gestionar la vista documental.

No puede ser:

- source de relaciones;
- target de relaciones.

Si un resultado generado necesita identidad trazable debe representarse mediante un ARTIFACT, normalmente EVIDENCE.

---

# 70. Autoridad

v0.3 no introduce un campo universal:

```text
authority:
```

La autoridad se deriva normalmente de la representación.

Conceptualmente existen:

```text
AUTHORED
GENERATED
EXTERNAL
```

pero no son estados obligatorios almacenados en ARTIFACT.

Un contenido generado nunca puede ser la única autoridad necesaria para regenerarse a sí mismo.

---

# 71. trace.yaml

La raíz del proyecto puede contener:

```text
trace.yaml
```

Ejemplo:

```yaml
project: minigpu
version: 1

scan:
  - docs/**/*.md
  - rtl/**/*.sv
  - sim/**/*.py
  - tests/**/*.py
  - "**/*.trace.yaml"

exclude:
  - build/**
  - .git/**
```

---

# 72. Función de trace.yaml

`trace.yaml` define:

- proyecto;
- configuración;
- discovery;
- vocabulario extendido.

No es un registro central de ARTIFACTS.

Los artifacts y relaciones permanecen junto a sus fuentes.

---

# 73. Extensiones de proyecto

`trace.yaml` puede registrar:

- kinds;
- subjects;
- relaciones específicas del proyecto.

Los TYPE core y relaciones core no necesitan repetirse.

Las relaciones adicionales deben incluir una definición semántica.

---

# 74. Construcción del modelo

El Project Model se reconstruye desde las fuentes en cada ejecución.

No se necesita una base de datos persistente para corrección.

Puede añadirse posteriormente una cache, pero debe ser:

- descartable;
- reconstruible;
- no autoritativa;
- normalmente ignorada por Git.

---

# 75. trace check

```text
trace check
```

valida, entre otras cosas:

- IDs globales únicos;
- IDs locales únicos;
- referencias resolubles;
- relaciones registradas;
- atributos válidos;
- kinds registrados;
- subjects registrados;
- scopes;
- sidecars;
- formal IDs;
- colisiones de SYMBOL;
- estructura Markdown;
- checksums cuando se soliciten.

---

# 76. Metadata desconocida

Los campos pertenecientes al lenguaje core deben ser conocidos.

Un typo como:

```yaml
subjets:
```

no debe ignorarse silenciosamente.

Debe producir error.

Las extensiones pueden añadir metadata únicamente mediante mecanismos registrados.

---

# 77. Atributos desconocidos de relaciones

Un atributo desconocido de una relación es error.

Por ejemplo:

```text
coverage=foo
```

es inválido para `verifies`.

Las relaciones extendidas pueden definir explícitamente sus propios atributos.

---

# 78. Relaciones duplicadas

El grafo semántico se considera un conjunto de edges.

Dos declaraciones idénticas de la misma relación no representan dos relaciones diferentes.

`trace check` debe señalar la duplicación para que pueda eliminarse de la fuente.

---

# 79. Orden

El orden documental puede conservarse para:

- renderizado;
- diagnósticos;
- experiencia de usuario.

Pero no modifica la semántica de:

- relaciones;
- subjects;
- members;
- otras colecciones semánticas.

---

# 80. Versionado

El historial normal pertenece a Git.

No existe un campo universal obligatorio:

```text
version:
```

para todos los ARTIFACTS.

Cuando dos variantes deben coexistir:

```text
SPEC-ISA-V2 --supersedes--> SPEC-ISA-V1
```

pueden tener identidades distintas.

Los resources externos pueden declarar `revision`.

---

# 81. Invariantes principales

El sistema debe mantener al menos los siguientes invariantes.

### I1

Todo ARTIFACT tiene `id` y `type`.

### I2

Los IDs de ARTIFACT son globalmente únicos.

### I3

SECTION, FACET y SYMBOL tienen identidad local a un ARTIFACT cuando existe contexto de ARTIFACT.

### I4

Los IDs locales addressable deben ser inequívocos.

### I5

Las relaciones almacenadas tienen dirección canónica.

### I6

Las relaciones inversas se calculan y no se duplican.

### I7

Toda relación utiliza un nombre core o registrado.

### I8

Todo target semántico debe resolver inequívocamente.

### I9

Los RESOURCE no son targets semánticos.

### I10

La estructura documental no implica relaciones semánticas.

### I11

Un ARTIFACT es frontera de ownership para sus elementos locales.

### I12

Un bloque generado no participa en la construcción del grafo.

### I13

El contenido generado nunca es la única autoridad necesaria para regenerarse.

### I14

`implements`, `satisfies` y `coverage=complete` conservan su semántica fuerte.

### I15

Las inferencias estructurales o caminos transitivos nunca se convierten silenciosamente en relaciones authored.

---

# 82. Ejemplo MiniGPU

Podríamos tener:

```text
NEED-GPU-PARALLELISM
        │
        ▼
REQ-GPU-RECONVERGENCE
        ▲
        │ satisfies
        │
IMPL-MINIGPU
        │
        │ implements
        ▼
SPEC-ISA#ssy
        ▲
        │ verifies coverage=complete
        │
VER-SSY-DIVERGENCE
        │
        │ produces
        ▼
EVID-SSY-DIVERGENCE-42
```

y simultáneamente:

```text
DEC-SIMT-RECONVERGENCE
        │
        ├── addresses → REQ-GPU-RECONVERGENCE
        │
        └── derived-from / refines según corresponda
```

El documento ISA puede contener:

```text
SPEC-ISA
├── @subword-memory
├── @calls
│   └── @indirect-calls
├── @alu-extended
├── @shift-immediate
└── @compare
```

sin convertir cada capability en un ARTIFACT independiente.

---

# 83. Consultas esperables

El modelo debe permitir preguntas como:

```text
¿Qué requisitos no están satisfechos?

¿Qué especificaciones no tienen implementación?

¿Qué elementos no tienen verificación?

¿Qué verificaciones tienen solo coverage parcial?

¿Qué artifacts dependen de esta decisión?

¿Qué se ve afectado si cambia SPEC-ISA#ssy?

¿Qué FACETs implementa MiniCPU?

¿Qué SECTION pertenecen a SPEC-ISA@calls?

¿Qué SYMBOL implementa SPEC-ISA#ssy?

¿Qué evidencia existe para una release o commit?

¿Qué artifacts están superseded?

¿Qué documentación generada está stale?
```

Las respuestas pueden utilizar:

- relaciones directas;
- estructura;
- relaciones inversas calculadas;
- caminos explicables.

Las inferencias deben poder mostrar siempre de dónde proceden.

---

# 84. No objetivos de v0.3

v0.3 no intenta resolver:

- base de datos central;
- servidor obligatorio;
- UI web;
- workflow empresarial;
- control de acceso;
- aliases automáticos;
- seguimiento automático de renombres;
- AST completo para todos los lenguajes;
- regiones arbitrarias begin/end en código;
- `scope=tree`;
- EXECUTION como entidad core;
- perfiles complejos de capabilities;
- semántica distribuida de FACET;
- nesting de gendoc;
- inferencia automática de relaciones semánticas.

Estos elementos pueden añadirse posteriormente si aparecen necesidades reales.

---

# 85. Regla de promoción

Cuando un elemento ligero empieza a necesitar:

- identidad estable independiente;
- lifecycle propio;
- relaciones propias significativas;
- versionado independiente;
- reutilización transversal;
- ownership independiente;

debe considerarse su promoción a ARTIFACT.

Esto permite comenzar ligero y añadir estructura únicamente cuando aporta valor.

---

# 86. Resumen de identidades

```text
SPEC-ISA
│
├── SPEC-ISA#ssy             SECTION
│
├── SPEC-ISA@calls           FACET
│
└── SPEC-ISA@indirect-calls  FACET
```

Código:

```text
IMPL-MINIGPU
│
├── IMPL-MINIGPU::simt_stack
└── IMPL-MINIGPU::update-mask
```

Representación física:

```text
RESOURCE
├── ARTIFACT
│   ├── SECTION
│   ├── FACET
│   └── SYMBOL
│
└── GENERATED BLOCK
```

El GENERATED BLOCK pertenece a la representación documental, no al grafo semántico.

---

# 87. Modelo mental final

El sistema puede resumirse en cuatro preguntas:

### ¿Qué cosas tienen identidad?

ARTIFACT y, localmente, SECTION, FACET y SYMBOL.

### ¿Cómo se conectan?

Mediante un vocabulario pequeño y explícito de relaciones semánticas.

### ¿Dónde vive la verdad?

Junto a la fuente autoritativa: Markdown, código, sidecars, fuentes externas o resultados preservados.

### ¿Cómo obtenemos documentación útil?

Construyendo primero un Project Model y generando después vistas mediante consultas y `gendoc`.

La consecuencia práctica es:

```text
autoría humana / herramientas
            │
            ▼
       fuentes reales
            │
            ▼
       Project Model
        /     |      \
       /      |       \
 trace check  |       análisis
              |
            gendoc
              |
              ▼
     documentación Markdown
```

La documentación deja así de ser una copia manual del estado del proyecto y pasa a ser, donde resulte conveniente, una vista reproducible del mismo.

---

# 88. Estado de v0.3

Con v0.3 quedan definidos:

- metamodelo fundamental;
- tipos de artifact;
- relaciones core;
- SECTION;
- FACET;
- SYMBOL;
- namespaces;
- ownership;
- resolución de referencias;
- representación Markdown;
- representación compacta en código;
- sidecars;
- resources externos;
- scopes;
- estructura de verificación;
- autoridad;
- versionado;
- configuración de proyecto;
- validación;
- bloques generados;
- funcionamiento conceptual de `gendoc`.

El siguiente paso ya no necesita ampliar el metamodelo.

El siguiente paso natural es implementar un **vertical slice mínimo**:

```text
trace.yaml
   ↓
scanner Markdown
   ↓
scanner de un lenguaje de código
   ↓
Project Model
   ↓
trace check
   ↓
query
   ↓
gendoc
```

y utilizar MiniGPU como proyecto piloto.

Cualquier ampliación posterior debería justificarse por un caso real que v0.3 no pueda representar limpiamente.
