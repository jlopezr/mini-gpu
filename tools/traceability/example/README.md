# Ejemplo mínimo de trazabilidad

Este directorio es un modelo pequeño para aprender y evolucionar
`traceability` sin depender de toda la documentación de MiniGPU.

El recorrido empieza en el requisito [REQ-001](requirements.md#req-001-identidad-del-dispositivo),
continúa en la [decisión de diseño](design.md#dec-001-registro-de-identidad) y
termina en su [evidencia de validación](validation.md#test-001-lectura-de-identidad).

Se puede comprobar desde la raíz del repositorio:

```bash
trace check tools/traceability/example
trace show REQ-001
```

## Cómo leer el modelo

El adaptador convierte cada documento y encabezado en una `Identity`. Cada
enlace Markdown se convierte en una `Observation` cuyo origen es el documento
o la sección que contiene el enlace. Los encabezados que empiezan por `REQ-`,
`DEC-` o `TEST-` crean identidades tipadas. `ModelBuilder` reúne ambas
colecciones y `Resolver` comprueba destinos y cobertura: cada requisito debe
estar conectado con una decisión y una prueba, y cada decisión con una prueba.
Las relaciones conservan la dirección y reciben un nombre (`satisfies`,
`verifies`, `specified-by` o `verified-by`), por lo que `trace show REQ-001`
puede explicar el vecindario de una identidad sin leer el grafo entero.

Por ejemplo, este enlace:

```markdown
[REQ-001](requirements.md#req-001-identidad-del-dispositivo)
```

produce una observación hacia la identidad
`tools/traceability/example/requirements.md#req-001-identidad-del-dispositivo`.

Para experimentar, cambia temporalmente un nombre de fichero o el fragmento de
un enlace y vuelve a ejecutar el comando. El diagnóstico incluye el documento,
la línea y el tipo de fallo. Revierte después el cambio para conservar el
ejemplo como caso válido.
