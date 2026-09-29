# Traceability Metamodel

**Version:** 0.1  
**Status:** Draft

## 1. Purpose

This document defines a generic metamodel for engineering traceability.

The model is intended to support projects involving hardware, software, firmware, systems engineering, verification, documentation, external specifications, and generated engineering data.

The metamodel deliberately does **not** define:

- the storage format;
- the Markdown syntax used to annotate artifacts;
- the implementation of the indexer;
- the database representation;
- the user interface;
- the command-line interface.

Those are representations and implementations of the model described here.

The model should remain usable independently of any particular project, programming language, documentation system, or engineering discipline.

---

# 2. Design principles

## 2.1 Stable identity

Engineering entities that need to participate in traceability have stable identities.

Their identity must not depend on their physical location.

Moving an artifact from one file to another must not change its identity.

For example:

```text
SPEC-ISA-SSY
```

may initially be located at:

```text
docs/isa.md#ssy
```

and later at:

```text
docs/isa/simt.md#ssy
```

without becoming a different artifact.

---

## 2.2 Traceability belongs close to its source

Whenever possible, traceability metadata should be stored together with the authoritative artifact.

For example:

- relations concerning a Markdown artifact should normally live in that Markdown;
- relations concerning source code may live in annotations or comments associated with the relevant symbol;
- metadata for an external immutable PDF may live in a sidecar file.

A separate global traceability database should not normally be the authoritative source of information.

Such a database may be generated as an index.

---

## 2.3 Store facts once

A fact should have one authoritative representation.

In particular, a relation is stored in one direction only.

Its inverse is calculated by tooling.

For example, if the authoritative relation is:

```text
IMPL-042 --implements--> SPEC-017
```

the following information is derived:

```text
SPEC-017 <--implemented-by-- IMPL-042
```

The inverse relation must not also be independently maintained.

---

## 2.4 Human-authored and generated information are different

The system distinguishes between information maintained by a human and information derived from another authoritative source.

Generated information may appear inside human-authored documents, but it is not independently authoritative.

---

## 2.5 Files are not artifacts

A physical resource and an engineering artifact are different concepts.

One resource may contain:

- no artifacts;
- one artifact;
- many artifacts;
- nested artifacts;
- generated blocks.

An artifact may move between resources without changing identity.

---

## 2.6 Not every piece of documentation needs identity

Normal explanatory documentation does not need to become an artifact.

A fragment should normally receive artifact identity only when there is value in independently:

- referencing it;
- relating it;
- verifying it;
- implementing it;
- superseding it;
- classifying it;
- tracking its impact.

Traceability should not require annotating every paragraph.

---

# 3. Core model

The core entities are:

```text
RESOURCE
ARTIFACT
RELATION
SUBJECT
GENERATED BLOCK
```

Conceptually:

```text
                     RESOURCE
                        |
                     contains
                        |
                        v
                    ARTIFACT
                   /    |    \
                  /     |     \
          contains   classified  RELATION
              |          by         |
              v          |          v
          ARTIFACT    SUBJECT    ARTIFACT


                     RESOURCE
                        |
                     contains
                        |
                        v
                 GENERATED BLOCK
                        |
                    derives
                        |
                        v
                generated content
```

---

# 4. Resource

A **Resource** is a physical or externally addressable container in which engineering information exists.

Examples include:

```text
Markdown file
Python file
SystemVerilog file
YAML file
PDF
datasheet
web page
Git commit
test report
synthesis report
PnR result
```

A Resource is primarily concerned with **location**, not engineering meaning.

Possible resource identifiers include:

```text
docs/isa.md
rtl/gpu/control.sv
tests/test_simt.py
datasheets/W9825G6KH.pdf
https://example.org/specification
git:<commit>
```

Resources do not necessarily require globally stable engineering IDs.

Artifacts do.

---

# 5. Artifact

An **Artifact** is the fundamental logical unit of traceability.

An artifact represents an engineering entity with stable identity.

Minimum conceptual properties are:

```text
id
type
```

Common optional properties include:

```text
kind
title
status
subjects
authority
location
```

Example:

```text
id: REQ-0047
type: requirement
kind: functional
title: SIMT divergence support
status: accepted
subject: GPU/SIMT
authority: authored
```

The representation shown above is illustrative only. It does not define a storage format.

---

# 6. Artifact types

The initial model defines eight fundamental artifact types.

## 6.1 NEED

A need describes a goal, capability, motivation, or stakeholder expectation.

It primarily answers:

> Why is something needed?

A need does not necessarily have to be directly verifiable.

Example:

```text
The system needs to execute programs containing divergent
SIMT control flow.
```

---

## 6.2 REQUIREMENT

A requirement describes a property or constraint that the system must satisfy.

It primarily answers:

> What must be true?

Possible kinds include:

```text
functional
performance
interface
timing
resource
safety
constraint
```

The list of kinds is extensible.

---

## 6.3 DECISION

A decision records an engineering choice and its rationale.

It primarily answers:

> Why was this solution selected?

A decision will commonly contain:

```text
context
alternatives
decision
rationale
consequences
```

Architecture Decision Records are instances of this artifact type.

A decision is distinct from both a requirement and a specification.

For example:

```text
Requirement:
    Indirect function calls shall be supported.

Decision:
    Indirect calls will use a JALR instruction.

Specification:
    JALR writes the return address to rd and transfers
    control to the address calculated from its operands.
```

---

# 6.4 SPECIFICATION

A specification describes the defined behavior, structure, interface, protocol, format, or architecture of some part of the system.

It primarily answers:

> How is this supposed to work?

Possible kinds include:

```text
architecture
interface
protocol
instruction
register
memory-map
data-format
algorithm
component
```

The list is extensible.

---

# 6.5 IMPLEMENTATION

An implementation represents a concrete realization of some part of the system.

Examples include:

```text
RTL module
software module
function
class
firmware component
PCB design
mechanical component
configuration
```

Possible kinds include:

```text
rtl
software
firmware
hardware
mechanical
pcb
configuration
```

An implementation artifact does not have to correspond to an entire file.

For example:

```text
rtl/gpu/control.sv
```

may be a Resource containing several implementation artifacts.

---

# 6.6 VERIFICATION

A verification artifact defines how some engineering claim is established.

It primarily answers:

> How do we establish that this is correct?

Verification is intentionally broader than testing.

Possible kinds include:

```text
test
simulation
analysis
inspection
review
measurement
formal-proof
```

A verification artifact may verify a requirement, specification, implementation property, or other appropriate artifact.

---

# 6.7 EVIDENCE

Evidence is a concrete result supporting an engineering claim or verification activity.

Examples include:

```text
test result
simulation result
waveform
synthesis report
PnR report
timing report
resource utilization report
measurement
review record
```

A verification procedure and its execution result are therefore different artifacts.

For example:

```text
VER-043
    |
    | produces
    v
EVID-20260920-017
```

---

# 6.8 SOURCE

A source represents authoritative or relevant information originating outside the immediate engineering model.

Examples include:

```text
datasheet
standard
paper
external requirement
interface control document
manual
issue
meeting record
external specification
```

Sources are particularly useful for distinguishing:

```text
"we decided this"
```

from:

```text
"this is imposed by an external source"
```

---

# 7. Artifact kinds

`type` represents fundamental semantics.

`kind` provides domain-specific specialization.

For example:

```text
type: specification
kind: instruction
```

or:

```text
type: implementation
kind: rtl
```

New kinds may be introduced without changing the fundamental metamodel.

This allows the same metamodel to be used for projects involving:

```text
CPU
GPU
FPGA
embedded systems
space systems
software
ASIC
robotics
mechanical systems
```

without introducing fundamental artifact types for every engineering domain.

---

# 8. Artifact containment

Artifacts may contain other artifacts.

For example:

```text
SPEC-ISA
 |
 +-- SPEC-ISA-ARITHMETIC
 |      |
 |      +-- SPEC-ISA-ADD
 |      +-- SPEC-ISA-SUB
 |
 +-- SPEC-ISA-CONTROL
 |      |
 |      +-- SPEC-ISA-BRA
 |      +-- SPEC-ISA-JAL
 |
 +-- SPEC-ISA-SIMT
        |
        +-- SPEC-ISA-SSY
        +-- SPEC-ISA-BAR
```

Containment represents logical structure.

It must not be confused with physical containment in a Resource.

For example:

```text
docs/isa.md
```

may physically contain all the artifacts above.

The logical hierarchy remains valid if some of them are later moved into different files.

---

# 9. Location

An artifact may have a location describing where its authoritative representation currently exists.

Examples:

```text
Markdown:
    file + anchor/section

Source code:
    file + symbol

PDF:
    file + page/section

Web:
    URL + anchor

Git:
    repository + commit

External document:
    document identifier + section
```

Location is mutable.

Artifact identity is stable.

Therefore:

```text
artifact identity != artifact location
```

---

# 10. Subject

A **Subject** represents a component, subsystem, domain, or area to which artifacts apply.

Subjects provide classification independently of artifact identity.

Example:

```text
System
 |
 +-- CPU
 |    +-- ALU
 |    +-- LSU
 |
 +-- GPU
 |    +-- SIMT
 |    +-- Scheduler
 |
 +-- Memory
 |
 +-- Video
 |
 +-- Toolchain
```

An artifact may belong to zero, one, or several subjects.

For example:

```text
REQ-0047

subjects:
    GPU/SIMT
    ISA
```

Artifact IDs therefore do not need to encode the complete classification hierarchy.

---

# 11. Relation

A **Relation** is a directed semantic connection between two artifacts.

Conceptually:

```text
SOURCE ARTIFACT
       |
       | relation type
       v
TARGET ARTIFACT
```

A relation minimally consists of:

```text
source
type
target
```

For example:

```text
DEC-027 --addresses--> REQ-047
```

---

# 12. Relation storage

A relation has exactly one authoritative stored direction.

Inverse relationships are derived.

For example, storing:

```text
IMPL-082 --implements--> SPEC-ISA-SSY
```

allows tooling to expose:

```text
SPEC-ISA-SSY <--implemented-by-- IMPL-082
```

without storing the inverse relation.

This prevents two representations of the same fact from diverging.

---

# 13. Initial relation vocabulary

The initial vocabulary is intentionally small.

## 13.1 contains

Expresses logical containment.

```text
A --contains--> B
```

Example:

```text
SPEC-ISA-SIMT --contains--> SPEC-ISA-SSY
```

---

## 13.2 refines

Expresses a more detailed formulation of another artifact.

```text
A --refines--> B
```

Typical example:

```text
REQ-SUBSYSTEM-012 --refines--> REQ-SYSTEM-003
```

---

## 13.3 derived-from

Expresses provenance.

```text
A --derived-from--> B
```

Example:

```text
REQ-SDRAM-021 --derived-from--> SRC-W9825G6KH
```

It primarily answers:

> Where did this come from?

---

## 13.4 addresses

Expresses that an artifact responds to or resolves another artifact.

Typical use:

```text
DEC-027 --addresses--> REQ-047
```

---

## 13.5 affects

Expresses that an artifact has consequences for another artifact without implying implementation or verification.

Example:

```text
DEC-027 --affects--> SPEC-ISA-SSY
```

---

## 13.6 implements

Expresses concrete realization.

```text
IMPL-082 --implements--> SPEC-ISA-SSY
```

---

## 13.7 satisfies

Expresses that an artifact contributes to satisfying a requirement.

Example:

```text
IMPL-082 --satisfies--> REQ-047
```

This relation may be used when linking directly from implementation to requirements is useful.

The model does not require every trace to pass through every possible intermediate artifact.

---

## 13.8 verifies

Expresses verification of another artifact.

```text
VER-043 --verifies--> REQ-047
```

or:

```text
VER-044 --verifies--> SPEC-ISA-SSY
```

---

## 13.9 produces

Expresses production of an output or evidence.

```text
VER-043 --produces--> EVID-017
```

---

## 13.10 depends-on

Expresses a general dependency not better represented by a more specific relation.

```text
A --depends-on--> B
```

`depends-on` should not be used when a more semantically precise relation exists.

---

## 13.11 supersedes

Expresses historical replacement.

```text
DEC-043 --supersedes--> DEC-017
```

The superseded artifact remains part of engineering history.

It is not deleted merely because it is no longer current.

---

# 14. Explicit and inferred relations

The model distinguishes between:

```text
explicit relations
inferred relations
```

An explicit relation is authoritatively declared.

An inferred relation is calculated from other facts.

For example:

```text
DEC-003 --affects--> SPEC-SIMT

SPEC-SIMT --contains--> SPEC-SSY
```

Tooling may report that `SPEC-SSY` is indirectly affected by `DEC-003`.

However, it must distinguish this from an explicitly declared relation:

```text
DEC-003 --affects--> SPEC-SSY
```

The graph must therefore preserve provenance for inferred relationships.

A tool should be able to explain the path:

```text
DEC-003
   |
 affects
   v
SPEC-SIMT
   |
 contains
   v
SPEC-SSY
```

rather than presenting the inferred relation as an independently authored fact.

---

# 15. Relation semantics

Relations may have different graph properties.

These properties must eventually be defined explicitly for every relation type.

Relevant properties include:

```text
symmetric
asymmetric
transitive
acyclic
hierarchical
inheritance-producing
```

For example, containment is naturally hierarchical and should normally be acyclic.

`supersedes` should also normally be acyclic.

Not every relation should be considered transitive.

For example:

```text
A implements B
B implements C
```

must not automatically imply:

```text
A implements C
```

unless the semantics explicitly justify it.

Tools must therefore not perform arbitrary graph closure.

---

# 16. Authority

Every engineering fact has an authoritative source.

Three broad authority modes are initially defined.

## 16.1 Authored

The artifact is directly maintained at its declared location.

Example:

```text
DEC-027 in decisions.md
```

---

## 16.2 Generated

The representation is derived from another authoritative source.

It must not be independently edited.

Example:

```text
ISA opcode table generated from instruction definitions
```

---

## 16.3 External

The authoritative information exists outside the locally editable model.

Examples:

```text
vendor datasheet
standard
external ICD
```

Local metadata may describe and reference an external artifact without becoming authoritative for its actual contents.

---

# 17. Generated Block

A **Generated Block** is a region inside a Resource whose content is derived automatically.

It is conceptually described by:

```text
source/query
transform
renderer
generated content
```

For example:

```text
PnR results
    |
    | query utilization
    v
transform
    |
    | Markdown table renderer
    v
generated block in architecture.md
```

Generated Blocks allow derived engineering information to appear where it is useful to human readers without creating duplicate authoritative information.

---

# 18. Generated Block lifecycle

A generated block has two distinct parts:

```text
generator declaration
generated content
```

The declaration is authoritative.

The generated content is not.

Conceptually:

```text
BEGIN GENERATED BLOCK

    generator: pnr.utilization
    source: build/top.json

    --------------------------
    generated content
    --------------------------

END GENERATED BLOCK
```

The exact syntax is outside the scope of this metamodel.

---

# 19. Generated Blocks and artifacts

A Generated Block is not inherently an Artifact.

It is primarily a view.

However, generated content may represent artifacts whose authority exists elsewhere.

For example, an automatically generated ISA table may display:

```text
SPEC-ISA-ADD
SPEC-ISA-SUB
SPEC-ISA-SSY
```

without becoming the authoritative definition of those artifacts.

Tooling must be able to distinguish:

```text
artifact
```

from:

```text
representation of artifact
```

---

# 20. Generated queries

Generated Blocks may eventually operate over the traceability graph itself.

Examples include:

```text
all instructions
all requirements
unverified requirements
implementations of REQ-047
incoming relations of SPEC-ISA-SSY
PnR utilization
timing results
test results
```

This enables documentation to contain automatically maintained views such as traceability matrices.

Example:

```text
Requirement      Implementation       Verification
---------------------------------------------------
REQ-001          IMPL-023             VER-009
REQ-002          IMPL-031             VER-014
REQ-003          IMPL-044             -
```

Such tables are views of authoritative information, not separate sources of truth.

---

# 21. Lifecycle

Artifacts may have lifecycle states.

The exact state vocabulary may depend on artifact type, but an initial generic set is:

```text
proposed
accepted
implemented
verified
deprecated
superseded
rejected
```

Not every state necessarily applies to every artifact type.

Lifecycle state is distinct from artifact existence.

A superseded or rejected decision remains part of the engineering record.

---

# 22. Historical continuity

The model favors preserving engineering history.

When an artifact is replaced conceptually, the preferred operation is:

```text
NEW --supersedes--> OLD
```

rather than deleting `OLD`.

This allows questions such as:

```text
Why was this originally designed this way?

What replaced this decision?

Which implementation corresponds to the old architecture?

When did this requirement change?
```

Git history may complement this information but does not replace semantic engineering history.

Git records that text changed.

Traceability records what that change means.

---

# 23. Invariants

A conforming repository should eventually enforce the following invariants.

## INV-001 — Unique identity

Artifact IDs are globally unique within the traceability domain.

---

## INV-002 — Stable identity

Moving or renaming the physical representation of an artifact does not change its ID.

---

## INV-003 — Valid relation targets

Every local relation target must resolve to a known artifact.

References to intentionally external artifacts must be explicitly representable as such.

---

## INV-004 — Single relation authority

A relation is authoritatively stored once.

Inverse relations are derived.

---

## INV-005 — No generated authority

Generated content must not become the sole authoritative source of information required to regenerate itself.

Generation dependencies must not form an authority cycle.

---

## INV-006 — Reproducible generated content

Given the same authoritative inputs and generator version, generated content should be reproducible.

---

## INV-007 — Generated content synchronization

Tooling must be able to determine whether committed generated content matches its authoritative inputs.

Conceptually:

```text
docgen check
```

must be capable of failing when generated documentation is stale.

---

## INV-008 — Explainable inference

Every inferred relationship must be explainable through a path of explicit relations and defined inference rules.

---

## INV-009 — Acyclic containment

Artifact containment must not contain cycles.

---

## INV-010 — Historical preservation

Superseding an artifact must not require deleting the superseded artifact from the engineering record.

---

# 24. Index

Implementations may build a derived global index.

For example:

```text
authoritative resources
        |
        v
      indexer
        |
        v
+------------------+
| artifact index   |
| relation graph   |
| resource map     |
+------------------+
        |
        +------> CLI
        |
        +------> HTML
        |
        +------> generated Markdown
        |
        +------> CI checks
        |
        +------> traceability reports
```

The index is disposable.

Deleting it must not destroy authoritative engineering information.

It must be possible to reconstruct it from authoritative resources.

---

# 25. Expected queries

The metamodel should eventually support questions such as:

```text
show ARTIFACT

what implements ARTIFACT?

what verifies ARTIFACT?

where did ARTIFACT come from?

why does ARTIFACT exist?

what does ARTIFACT depend on?

what depends on ARTIFACT?

what is affected if ARTIFACT changes?

what superseded ARTIFACT?

what did ARTIFACT supersede?

which requirements have no verification?

which requirements have no implementation?

which artifacts are orphaned?

show the path from NEED-X to EVIDENCE-Y
```

The ability to answer these questions is a design objective of the metamodel.

---

# 26. Example abstract trace

A typical trace may look like:

```text
SOURCE
   |
   | derived-from
   v
REQUIREMENT
   ^
   | addresses
   |
DECISION
   |
   | affects
   v
SPECIFICATION
   ^
   | implements
   |
IMPLEMENTATION


REQUIREMENT
   ^
   | verifies
   |
VERIFICATION
   |
   | produces
   v
EVIDENCE
```

Another valid trace may omit some intermediate artifacts:

```text
REQUIREMENT
     ^
     |
  satisfies
     |
IMPLEMENTATION
```

The metamodel should support useful engineering traceability without forcing artificial artifacts merely to complete a predefined chain.

---

# 27. Physical representation

This metamodel intentionally does not prescribe how artifacts and relations are encoded.

Possible representations include:

```text
Markdown metadata
Markdown annotations
YAML
source-code comments
language annotations
sidecar files
external tool adapters
```

Different Resource types may use different representations while participating in the same graph.

For example:

```text
Markdown artifact
       |
       |
       v
       GRAPH <------- SystemVerilog annotation
       ^
       |
       +------------- Python test annotation
       ^
       |
       +------------- PDF sidecar metadata
```

---

# 28. Separation of concerns

The architecture should preserve the following separation:

```text
METAMODEL
    |
    | defines semantics
    v
REPRESENTATION
    |
    | defines encoding
    v
PARSER / ADAPTERS
    |
    | discover artifacts
    v
INDEX / GRAPH
    |
    | enables queries
    v
TOOLS
    |
    +-- CLI
    +-- CI
    +-- doc generation
    +-- reports
    +-- visualization
```

Changing the Markdown syntax should not require changing the metamodel.

Changing the graph database should not require changing artifact semantics.

Adding support for a new Resource type should require an adapter, not a new traceability model.

---

# 29. Open questions for v0.2

The following questions are intentionally unresolved.

### Q1 — Artifact identity namespace

Should IDs be globally flat:

```text
REQ-0047
DEC-0027
SPEC-0081
```

or optionally hierarchical:

```text
REQ-SIMT-0047
SPEC-ISA-SSY
```

---

### Q2 — Relation attributes

Should relations themselves support metadata such as:

```text
rationale
status
confidence
created
source
```

If so, relations begin to behave partially like artifacts.

This needs careful consideration.

---

### Q3 — Artifact versions

Should artifact versioning be explicitly modeled, or should Git plus `supersedes` be sufficient?

---

### Q4 — Containment semantics

Which relations, if any, propagate through logical containment?

For example:

```text
DEC-X --affects--> SPEC-SIMT
SPEC-SIMT --contains--> SPEC-SSY
```

Should tooling report that `DEC-X` indirectly affects `SPEC-SSY`?

If so, this must be an explicitly defined inference rule.

---

### Q5 — Requirement refinement

Should `refines` be generic for all artifact types or should requirement decomposition have a more specific relation?

---

### Q6 — Generated Block language

How expressive should generated queries be?

A simple provider model:

```text
generator: pnr.utilization
```

may be sufficient initially.

A later implementation could support generic graph queries.

---

### Q7 — External artifact identity

How should external artifacts be identified reliably across repositories and organizations?

---

### Q8 — Evidence retention

Should transient CI/test results become artifacts automatically, or only selected/baselined results?

Creating an artifact for every test invocation may produce excessive traceability data.

---

# 30. Non-goals

The metamodel is not intended to:

- replace Git;
- replace source code;
- require every paragraph to be annotated;
- require every implementation symbol to become an artifact;
- force a specific development methodology;
- force all projects to use the same artifact kinds;
- make every possible dependency explicit;
- duplicate information that can be reliably derived;
- turn documentation into a database disguised as Markdown.

The goal is to provide enough semantic structure to preserve engineering intent, provenance, implementation, verification, and history while keeping the authoritative information close to the artifacts engineers actually work with.

---

# 31. Summary

The fundamental model is:

```text
RESOURCE
   |
   +-- contains physical representations
   |
   +--> ARTIFACT
   |       |
   |       +--> ARTIFACT
   |             via semantic RELATION
   |
   +--> GENERATED BLOCK
           |
           +--> derived view of authoritative information


ARTIFACT
   |
   +-- stable identity
   +-- type
   +-- optional kind
   +-- lifecycle
   +-- authority
   +-- location
   +-- subjects
   +-- outgoing relations


ARTIFACT TYPES
   |
   +-- NEED
   +-- REQUIREMENT
   +-- DECISION
   +-- SPECIFICATION
   +-- IMPLEMENTATION
   +-- VERIFICATION
   +-- EVIDENCE
   +-- SOURCE


CORE RELATIONS
   |
   +-- contains
   +-- refines
   +-- derived-from
   +-- addresses
   +-- affects
   +-- implements
   +-- satisfies
   +-- verifies
   +-- produces
   +-- depends-on
   +-- supersedes
```

The authoritative engineering information remains distributed close to its natural sources.

A derived index reconstructs the global graph.

Generated Blocks allow views of that graph and other engineering data to be embedded back into human-readable documentation without introducing additional sources of truth.
