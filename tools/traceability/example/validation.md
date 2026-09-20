<!-- trace:artifact VER-DEVICE-IDENTITY
type: verification
kind: test
subjects: [cpu, gpu]
verifies:
  - target: SPEC-DEVICE#identity-register
    coverage: complete
  - REQ-DEVICE-IDENTITY
-->

# Lectura de identidad

El test lee el registro después del reset y compara firma y versión con los
valores esperados.
