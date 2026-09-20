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
-->

## Interfaz de identidad

### Registro de identidad {#identity-register}

La lectura devuelve la firma en los bits altos y la versión en los bajos.
