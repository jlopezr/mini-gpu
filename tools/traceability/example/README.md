# Ejemplo mínimo conforme al metamodelo v0.3

Este directorio separa los ficheros físicos (`RESOURCE`) de los elementos del
grafo. Los comentarios `trace:artifact` declaran identidades globales y su
`type`; los enlaces Markdown normales no crean relaciones semánticas.

El grafo de ejemplo es:

```text
DEC-DEVICE-IDENTITY --addresses--> REQ-DEVICE-IDENTITY
IMPL-DEVICE-IDENTITY --implements--> SPEC-DEVICE@identity
IMPL-DEVICE-IDENTITY --satisfies--> REQ-DEVICE-IDENTITY
VER-DEVICE-IDENTITY --verifies coverage=complete--> SPEC-DEVICE#identity-register
VER-DEVICE-IDENTITY --verifies--> REQ-DEVICE-IDENTITY
SPEC-DEVICE --requires--> SRC-DEVICE-REGISTERS
IMPL-DEVICE-PROBE --implements--> SPEC-DEVICE@identity
```

Puede inspeccionarse desde la raíz del repositorio:

```bash
trace check tools/traceability/example
trace show REQ-DEVICE-IDENTITY
trace show SPEC-DEVICE#identity-register
trace show SPEC-DEVICE@identity
```

El ejemplo es también una especificación ejecutable: los tests comprueban sus
identidades, relaciones, atributos, resolución local y FACETs anidadas. La
implementación vive en `implementation.sv`: declara el ARTIFACT desde código y
materializa un SYMBOL formal mediante una anotación compacta.
`device-registers.trace.yaml` asigna identidad estable a una fuente externa y
verifica el checksum del recurso descrito.
La verificación está declarada en `validation.py`, y `probe.asm` materializa un
programa y un label MiniISA trazables con la misma gramática de anotaciones.

## Implementaciones del registro

Este bloque se materializa mediante la query registrada de `trace`; su contenido
no participa a su vez en el modelo.

<!-- gendoc:begin identity-register-implementations
generator: trace.query
query: implementations-of
arguments:
  - SPEC-DEVICE#identity-register
-->

| Identity | Type | Location | Reason |
|---|---|---|---|
| `IMPL-DEVICE-IDENTITY::identity-read` | symbol | `tools/traceability/example/implementation.sv:11` | implementa SPEC-DEVICE#identity-register |
| `IMPL-DEVICE-PROBE::read-identity` | symbol | `tools/traceability/example/probe.asm:6` | implementa SPEC-DEVICE#identity-register |

<!-- gendoc:end identity-register-implementations -->
