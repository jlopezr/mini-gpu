# Minitour práctico de `trace`

## 1. Declarar un artefacto

En Markdown:

```markdown
<!-- trace:artifact REQ-DEVICE-IDENTITY
type: requirement
status: accepted
subjects: [cpu, gpu]
-->

# Identificación del dispositivo
```

Esto crea una identidad global:

```text
REQ-DEVICE-IDENTITY
```

El archivo Markdown es el `RESOURCE`; el requisito es el `ARTIFACT`.

## 2. Crear secciones y facets

Una sección normal pertenece al artefacto:

```markdown
## Registro de identidad {#identity-register}
```

Produce:

```text
REQ-DEVICE-IDENTITY#identity-register
```

Una facet representa una parte semántica reutilizable:

```markdown
<!-- trace:facet identity-register
kind: capability
-->

## Registro de identidad {#identity-register}
```

Produce:

```text
REQ-DEVICE-IDENTITY@identity-register   # facet
REQ-DEVICE-IDENTITY#identity-register   # sección
```

## 3. Relacionar artefactos

Desde otro artefacto:

```markdown
<!-- trace:artifact SPEC-DEVICE
type: specification
status: accepted
implements:
  - REQ-DEVICE-IDENTITY
-->

# Especificación del dispositivo
```

Las relaciones se escriben solo en su dirección canónica. `trace` calcula la vista inversa al consultar.

## 4. Anotar implementación

En Python:

```python
# @artifact IMPL-DEVICE type=implementation
# @implements SPEC-DEVICE
class Device:
    pass
```

Un símbolo concreto:

```python
# @id read_identity
# @implements SPEC-DEVICE#identity-register
def read_identity():
    ...
```

Crea:

```text
IMPL-DEVICE
IMPL-DEVICE::read_identity
```

La misma gramática funciona en SystemVerilog:

```systemverilog
// @artifact IMPL-GPU type=implementation
// @implements SPEC-GPU
module gpu;
```

Y ensamblador:

```asm
; @artifact IMPL-PROBE type=implementation
; @id read_identity
; @implements SPEC-DEVICE#identity-register
read_identity:
```

## 5. Usar un sidecar

Para archivos que no quieres o no puedes modificar:

```yaml
artifact: SRC-DATASHEET
type: source
kind: datasheet

resource:
  file: device.pdf
  revision: "Rev. A"
  sha256: abc123...
```

Normalmente se guarda como:

```text
device.trace.yaml
```

El checksum garantiza que el recurso externo sea exactamente la versión esperada.

## 6. Validar el proyecto

```powershell
.\tools\trace check
```

Comprueba:

- Sintaxis y metadata.
- Identidades duplicadas.
- Referencias inexistentes.
- Relaciones inválidas.
- Checksums.
- Reglas activadas en `trace.yaml`.

Para ignorar la caché:

```powershell
.\tools\trace check --no-cache
```

## 7. Explorar el grafo

Ver una identidad:

```powershell
.\tools\trace show SPEC-DEVICE
```

Listar artefactos:

```powershell
.\tools\trace list --type specification
.\tools\trace list --kind capability
```

Ver relaciones:

```powershell
.\tools\trace incoming SPEC-DEVICE
.\tools\trace outgoing IMPL-DEVICE
```

Ver estructura:

```powershell
.\tools\trace tree SPEC-DEVICE
```

Encontrar un camino:

```powershell
.\tools\trace path REQ-DEVICE-IDENTITY IMPL-DEVICE
```

Analizar impacto:

```powershell
.\tools\trace impact SPEC-DEVICE
.\tools\trace impact docs\design.md --depth 2
```

Casi todos admiten:

```powershell
--format json
```

## 8. Ejecutar queries

Inventario:

```powershell
.\tools\trace query list
```

Consultas útiles:

```powershell
.\tools\trace query unimplemented
.\tools\trace query unverified
.\tools\trace query not-fully-verified
.\tools\trace query unsatisfied
```

Consultas parametrizadas:

```powershell
.\tools\trace query implementations-of SPEC-DEVICE
.\tools\trace query verifications-of SPEC-DEVICE
```

## 9. Aplicar reglas

En `trace.yaml`:

```yaml
rules:
  - accepted-requirements-satisfied
  - accepted-specifications-implemented
  - accepted-targets-fully-verified
```

Ver las reglas disponibles:

```powershell
.\tools\trace rule list
```

Las reglas se evalúan durante:

```powershell
.\tools\trace check
```

## 10. Generar documentación

Un bloque declarativo:

```markdown
<!-- gendoc:begin missing-implementations
generator: trace.query
query: unimplemented
arguments: []
-->

Aquí aparecerá la tabla.

<!-- gendoc:end missing-implementations -->
```

Generarlo:

```powershell
.\tools\generate-docs
```

Comprobar sin escribir:

```powershell
.\tools\generate-docs --check
```

Listar generadores:

```powershell
.\tools\generate-docs --list-generators
```

Actualmente están registrados:

```text
trace.query
prototype-summary
cpu-matrix
gpu-matrix
synthesis-table
```

## 11. La caché

Se guarda localmente en:

```text
.trace/cache-v1.json
```

No se versiona. Conserva los fragmentos parseados y las declaraciones `gendoc`.

El ciclo normal queda así:

```text
fuentes anotadas
      ↓
  trace check
      ↓
modelo + grafo cacheado
      ↓
queries / rules / impacto
      ↓
 generate-docs
      ↓
Markdown materializado
```

Para verlo todo funcionando junto, el mejor punto de entrada es:

```text
tools/traceability/example/
```