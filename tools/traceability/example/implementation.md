<!-- trace:artifact IMPL-DEVICE-IDENTITY
type: implementation
subjects: [cpu, gpu]
implements:
  - SPEC-DEVICE#identity-register
satisfies:
  - REQ-DEVICE-IDENTITY
-->

# Implementación del registro de identidad

El RTL conecta constantes de firma y versión al camino de lectura del monitor.
