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
