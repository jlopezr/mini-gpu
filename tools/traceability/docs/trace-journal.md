# Trace Journal

**Version:** 0.1  
**Status:** Draft

## 1. Purpose

The traceability methodology distinguishes between the current engineering knowledge of a project and the process by which that knowledge was reached.

Artifacts should primarily describe knowledge that is relevant **now**: requirements, designs, decisions, specifications, implementations, verification evidence, and their relationships.

During engineering work, however, additional information is continuously generated:

- approaches that were attempted and later discarded;
- implementation problems encountered along the way;
- intermediate solutions;
- observations made during simulation, synthesis, testing, or review;
- explanations of why an artifact evolved in a particular direction;
- contextual information that may be useful when revisiting the same problem in the future.

This information can be valuable, but keeping it indefinitely in the main artifact makes that artifact progressively harder to read and maintain.

A **journal** provides a place for this historical engineering context.

The fundamental distinction is:

> **An artifact describes the engineering knowledge that is relevant now. A journal records useful context about how that artifact reached its current state.**

A journal is therefore neither a replacement for an artifact nor a replacement for Git.

---

## 2. Three different kinds of history

The methodology distinguishes three related but different forms of information.

### 2.1 Current engineering knowledge

This belongs in traceable artifacts.

Examples include:

- what the system must do;
- how a subsystem is designed;
- an architectural decision and its rationale;
- an interface contract;
- the implementation corresponding to a specification;
- verification evidence.

This information participates in the traceability graph.

### 2.2 Engineering history

This is the purpose of the journal.

It answers questions such as:

- What did we try before arriving at the current solution?
- What unexpected problem appeared during implementation?
- Why did the design evolve in this direction?
- What alternative implementation was tested?
- What useful observation was made but is no longer part of the current design?

This information is historical and contextual rather than normative.

### 2.3 Mechanical history

Git records the mechanical evolution of project files.

It answers questions such as:

- Which lines changed?
- When did they change?
- In which commit?
- Who made the change?
- What did the previous version contain?

The journal should not duplicate information that Git already records adequately.

The resulting separation is:

```text
Artifact                 Journal                  Git
────────                 ───────                  ───
what is true now         how we got here          what changed

engineering              engineering              mechanical
knowledge                context                  history
```

---

## 3. Journal and traceability

A journal is associated with an artifact but is **not itself a traceability artifact**.

For example:

```text
DES-SDRAM-BURST
      │
      └── journal
           └── DES-SDRAM-BURST.log.md
```

The journal does not normally:

- receive an artifact ID of its own;
- participate in `@trace` relationships;
- satisfy requirements;
- verify specifications;
- become a normative source;
- require lifecycle management equivalent to normal artifacts.

The relationship between an artifact and its journal should preferably be established by **convention rather than explicit metadata**.

For example:

```text
DES-SDRAM-BURST.md
DES-SDRAM-BURST.log.md
```

or, if journals are stored separately:

```text
design/
    DES-SDRAM-BURST.md

history/
    DES-SDRAM-BURST.log.md
```

The exact repository layout is a tooling concern and does not need to become part of the core metamodel.

A journal is optional. An artifact without useful historical context does not need an empty journal.

---

## 4. What belongs in a journal

A journal should contain information about the development process that may have future engineering value.

Typical examples include:

### Failed or discarded approaches

```text
The first implementation used an eight-word burst.

This increased the time for which scanout could hold the SDRAM
controller and complicated arbitration with other clients.

A four-word burst was subsequently tested.
```

### Unexpected implementation findings

```text
During implementation it was discovered that ACK becomes visible
one cycle later than originally assumed by the client.
```

### Useful experimental observations

```text
The eight-entry FIFO failed timing at the target frequency.
Reducing it to four entries allowed timing closure.
```

### Intermediate solutions

```text
The first version serialized all lane stores. This was useful for
validating semantics but was later replaced with lane arbitration.
```

### Context for future work

```text
A wider request queue was considered but not implemented because
the current SDRAM controller cannot exploit the additional
parallelism.
```

The journal should preserve information because it may help future engineering work, not merely because it happened.

A useful test is:

> **If someone revisits this subsystem six months from now and asks "why did this end up this way?", would this information help?**

If the answer is yes, it is a good journal candidate.

---

## 5. What does not belong in a journal

The journal must not become a dump of development activity.

Information such as the following normally has no lasting value:

```text
Opened controller.v.

Changed signal foo.

Ran the test.

Test failed.

Changed foo again.

Ran the test again.
```

This is activity logging, not engineering memory.

Similarly, information that remains part of the current engineering knowledge should not be moved into the journal merely because it originated during development.

For example:

```text
The SDRAM controller uses four-word bursts.
```

If this is part of the current contract, it belongs in the appropriate artifact.

The journal may explain how that value was reached, but it must not become the only place where the current value is documented.

---

## 6. Journal, DESIGN and DECISION

The journal must not replace `DESIGN` or `DECISION`.

These concepts have different purposes.

### DESIGN

`DESIGN` contains active engineering reasoning:

- alternatives currently under consideration;
- trade-offs;
- incomplete proposals;
- open questions;
- design exploration that remains relevant.

### DECISION

`DECISION` captures a durable engineering decision:

- what was selected;
- relevant alternatives;
- why it was selected;
- rationale that should remain part of project knowledge.

### JOURNAL

The journal contains historical context about the process:

- what happened while exploring or implementing;
- intermediate attempts;
- useful failures;
- observations that explain the evolution of the artifact.

For example, during development a DESIGN might accumulate:

```text
We initially implemented burst=8.

Synthesis showed that this complicated arbitration with scanout.

Burst=4 was then tested and behaved better.

We therefore intend to use burst=4.
```

After the engineering knowledge stabilizes, this information may be distributed.

The DESIGN may retain the relevant trade-off:

```text
Longer bursts improve SDRAM efficiency but increase the time for
which a client occupies the controller.
```

A DECISION may capture:

```text
Use four-word SDRAM bursts.

Rationale:
This provides a compromise between SDRAM efficiency and arbitration
latency.
```

The journal may retain:

```text
The first implementation used burst=8. During synthesis and testing
this was found to interact poorly with scanout arbitration.

A second implementation using burst=4 was subsequently evaluated.
```

Thus, moving information to the journal is not necessarily the same as removing it from project knowledge.

One development observation can produce:

- current design knowledge;
- a formal decision;
- historical context.

---

## 7. Information lifecycle

Development information can be classified according to its future value.

```text
                     development information
                              │
                              ▼
                   Is it currently relevant?
                       /             \
                     yes              no
                     │                │
                     ▼                ▼
               ARTIFACT        Does it explain
                               an important choice?
                                  /          \
                                yes           no
                                │             │
                                ▼             ▼
                            DECISION      Is the history
                                         useful later?
                                           /      \
                                         yes       no
                                         │         │
                                         ▼         ▼
                                      JOURNAL     DROP
```

This diagram is intentionally simplified.

For example, a piece of information may remain in a DESIGN while also contributing to the rationale of a DECISION.

The important principle is:

> **Consolidation does not attempt to preserve everything that happened. It attempts to preserve each piece of engineering knowledge in the place where it remains useful.**

---

# 8. Greenfield workflow

Projects adopting the methodology from the beginning should avoid accumulating historical commentary in artifacts unnecessarily.

The preferred workflow is to classify information as it is generated.

## 8.1 Normal development

When working on an artifact, a developer or agent should ask:

**Does this describe the current artifact?**

If yes, update the artifact.

**Is this a durable engineering decision?**

If yes, create or update the appropriate `DECISION`.

**Is this useful historical context about how we got here?**

If yes, append it to the artifact journal.

**Is it merely transient development activity?**

If yes, do not preserve it.

---

## 8.2 Journals are created lazily

A journal should not be created automatically for every artifact.

Initially:

```text
DES-017.md
```

If useful historical information appears:

```text
DES-017.md
DES-017.log.md
```

This avoids repositories containing large numbers of empty or meaningless journal files.

---

## 8.3 Prefer direct journal writing

In a greenfield project, developers and agents should preferably write historical observations directly to the journal instead of first contaminating the artifact and cleaning it later.

The desired workflow is:

```text
                   engineering work
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
          Artifact      Decision     Journal
```

rather than:

```text
engineering work
       │
       ▼
dirty artifact
       │
       ▼
cleanup
```

Cleanup remains useful as a safety mechanism, but it should not be the primary workflow.

---

# 9. Agent workflow

Agents are particularly likely to generate valuable but verbose implementation commentary.

Without an explicit policy, this commentary tends to accumulate inside proposals and design documents.

An agent working on an artifact should therefore know:

1. which artifact is the current work context;
2. whether that artifact has a journal;
3. where journal entries should be written;
4. the distinction between current knowledge and historical context.

A suitable agent instruction is conceptually:

```text
Work on DES-017.

Keep DES-017 as a description of current engineering knowledge.

Record useful development history in its journal, including:
- alternatives actually attempted;
- significant failed approaches;
- unexpected implementation findings;
- deviations from the original approach;
- context that may explain the final result later.

Do not journal routine activity.

If an observation represents a durable engineering decision,
propose or update a DECISION rather than leaving the decision
only in the journal.
```

The journal therefore acts as **long-term engineering memory**, not as an agent transcript.

---

# 10. Append-oriented history

Journals should normally be append-oriented.

Once an entry describes something that happened, later development does not make that event cease to have happened.

For example:

```markdown
## 2026-09-22 — Burst length experiment

The first implementation used eight-word bursts.

This produced excessive arbitration latency for scanout, so a
four-word implementation was evaluated.
```

If later work returns to eight-word bursts, the old entry should normally remain.

A new entry can explain the new development.

This differs from normal artifacts, which should be updated to describe current knowledge.

Append-oriented does not mean immutable. Errors can be corrected, and journals may occasionally be reorganized for readability. However, rewriting historical entries merely to make them agree with the current design should be avoided.

Git remains the authoritative mechanical history of changes to the journal itself.

---

# 11. Journal structure

Journal syntax should remain deliberately lightweight.

A minimal journal might be:

```markdown
# Journal — DES-SDRAM-BURST

## 2026-09-22 — Initial burst implementation

The first implementation used burst=8.

During testing...

## 2026-09-23 — Arbitration

...
```

No complex annotation language is required initially.

Optional lightweight categories may eventually be useful:

```text
@observation
@experiment
@issue
@rejected
```

However, these should only be introduced if tooling demonstrates a concrete need for them.

The journal should remain easy to write manually and easy to read as ordinary Markdown.

---

# 12. Legacy projects

A different problem exists when the methodology is introduced into an existing project.

Existing documentation may already combine:

- current design;
- old design;
- implementation commentary;
- decisions;
- abandoned alternatives;
- debugging notes;
- outdated conclusions;
- useful historical observations;
- irrelevant development noise.

This is not a normal journal workflow problem.

It is a **migration problem**.

---

# 13. Legacy migration

Legacy migration should transform mixed documentation into the normal methodology.

Conceptually:

```text
                 existing document
                        │
                        ▼
                   classification
                        │
       ┌────────────────┼─────────────────┐
       │                │                 │
       ▼                ▼                 ▼
 current knowledge    history         decisions
       │                │                 │
       ▼                ▼                 ▼
    Artifact          Journal          DECISION

                 irrelevant material
                        │
                        ▼
                       DROP
```

The goal is not merely to make the document shorter.

The goal is to identify what kind of engineering knowledge each piece represents.

---

## 13.1 Migration classification

A migration tool or agent should classify candidate content into at least:

### KEEP

Still-valid content belonging in the current artifact.

### JOURNAL

Historical information useful for understanding development.

### DECISION CANDIDATE

Information describing an engineering choice whose rationale deserves durable representation.

### OTHER ARTIFACT CANDIDATE

Information that actually belongs in another traceable artifact, such as a SPEC or REQUIREMENT.

### DROP

Information with no meaningful future engineering value.

### UNCERTAIN

Content that cannot safely be classified automatically.

Uncertain content should not be silently moved or deleted.

---

## 13.2 Review before modification

Legacy migration is inherently interpretive.

For that reason, tooling should preferably present a proposed transformation before modifying files.

Conceptually:

```text
$ trace migrate DES-017 --dry-run

KEEP
  34 blocks

JOURNAL
  12 blocks

DECISION CANDIDATES
  3 blocks

OTHER ARTIFACT CANDIDATES
  1 block

DROP
  7 blocks

UNCERTAIN
  2 blocks
```

The exact command-line interface is not normative at this stage.

The important methodological requirement is that ambiguous historical cleanup should remain reviewable.

---

# 14. After migration

Legacy migration is temporary.

Once an existing artifact has been cleaned, it follows the same workflow as an artifact created in a greenfield project.

```text
LEGACY PROJECT
      │
      ▼
   migration
      │
      ▼
normal artifact + optional journal
      │
      ▼
GREENFIELD WORKFLOW
```

Therefore, the methodology does not maintain two permanent classes of project.

There are simply:

- artifacts already following the journal discipline;
- artifacts that still need migration.

---

# 15. Tooling model

Journal support should be implemented as tooling around ordinary Markdown rather than as a new core traceability model.

Possible operations include:

```text
trace journal <artifact>
```

Display the journal associated with an artifact.

```text
trace journal <artifact> add
```

Append an entry using an editor or agent workflow.

```text
trace migrate <artifact>
```

Analyze legacy documentation and propose a migration.

```text
trace migrate <artifact> --dry-run
```

Show the proposed classification without modifying the repository.

Additional commands may emerge from implementation experience.

The methodology should not depend on a particular CLI syntax.

---

# 16. Automation boundaries

Some journal operations can be deterministic.

For example:

- locating the journal corresponding to an artifact;
- creating it on first use;
- appending an entry;
- checking naming conventions;
- finding orphan journals.

Other operations require semantic interpretation:

- deciding whether a paragraph is historical;
- determining whether an observation represents a durable decision;
- deciding whether old commentary still describes current behavior;
- deciding whether information has enough future value to preserve.

These operations are appropriate for agents or human review.

Tooling should therefore distinguish between:

```text
deterministic tooling
        +
semantic assistance
        +
human review when necessary
```

Automation should not turn historical commentary silently into normative engineering knowledge.

---

# 17. Relationship with Git

Journals complement Git rather than duplicate it.

Git should remain responsible for exact historical reconstruction.

The journal should not normally contain:

- commit hashes for every change;
- line-by-line modification history;
- complete diffs;
- exhaustive lists of modified files;
- routine timestamps already available from Git.

A journal entry may reference a commit when doing so is genuinely useful, but this should not be required.

A useful distinction is:

```text
Git:
    What changed?

Journal:
    What happened that is worth remembering?

Artifact:
    What should I believe now?
```

---

# 18. Relationship with artifact evolution

Journal history is separate from artifact identity.

If an artifact evolves while retaining the same conceptual identity, its ID remains stable and Git records its revisions.

Its journal can continue accumulating relevant historical context.

If a new artifact supersedes the old one, the traceability model should represent that relationship independently of the journal.

For example:

```text
DES-001 ── superseded-by ──> DES-014
```

The journal of `DES-001` remains historical context for `DES-001`.

The journal must not be used as a substitute for explicit semantic relationships between artifacts.

---

# 19. Design principles

Journal support should follow these principles.

**Current knowledge stays visible.**  
A reader should not need to inspect the journal to determine current system behavior.

**History should not pollute current documentation.**  
Useful historical context deserves preservation, but not at the cost of readability.

**Not everything deserves preservation.**  
The journal is engineering memory, not an activity log.

**Important rationale should be promoted.**  
A durable engineering decision belongs in `DECISION`, even if the events leading to it are also described in a journal.

**Git and journals solve different problems.**  
Git records mechanical history; journals preserve selected engineering context.

**Journals remain lightweight.**  
They should not acquire the lifecycle and annotation burden of normal artifacts without a demonstrated need.

**Greenfield and legacy are different workflows.**  
New projects should classify information as it is generated. Existing mixed documentation requires explicit migration.

**Agents assist rather than silently redefine knowledge.**  
Semantic cleanup and promotion should remain reviewable whenever interpretation can change project meaning.

---

# 20. Summary

The traceability system distinguishes four complementary concerns:

```text
Artifact
    current engineering knowledge

Trace graph
    semantic relationships between engineering artifacts

Journal
    selected historical context explaining artifact evolution

Git
    exact mechanical history of repository changes
```

The journal fills the gap between current engineering documentation and raw version-control history.

For greenfield work, it provides a destination for useful development context as that context is generated.

For legacy work, migration extracts historical material from documents that have accumulated current knowledge, decisions, commentary, and obsolete information in the same place.

The objective is not to preserve every step of development.

The objective is to make current engineering knowledge easy to understand **without losing the parts of its history that may help engineers understand why it became that way**.