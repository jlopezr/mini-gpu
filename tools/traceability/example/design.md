<!-- trace:artifact DEC-DEVICE-IDENTITY
type: decision
subjects: [cpu, gpu]
addresses:
  - REQ-DEVICE-IDENTITY
-->

# Registro de identidad

Se utiliza un registro de solo lectura con una firma del diseño y una versión
del protocolo del monitor.

<!-- trace:artifact SPEC-DEVICE
type: specification
kind: interface
subjects: [cpu, gpu]
requires:
  - SRC-DEVICE-REGISTERS
-->

## Interfaz de identidad

<!-- trace:facet identity
kind: capability
-->

### Identidad {#identity}

#### Registro de identidad {#identity-register}

La lectura devuelve la firma en los bits altos y la versión en los bajos.

<!-- trace:facet versioning
kind: capability
-->

#### Versionado {#versioning}

La versión permite rechazar un bitstream incompatible antes de ejecutar código.
