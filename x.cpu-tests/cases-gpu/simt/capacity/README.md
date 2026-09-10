# Límites de las pilas REGION y PATH

Casos de saturación. La propiedad clave que valida el grupo es que el simulador
comprueba **si realmente necesita reservar una entrada** antes de dar overflow,
en vez de rechazar cualquier operación con la pila llena:

```text
REGION llena + SSY distinto        => ERROR_SIMT   (ssy-region-overflow)
REGION llena + mismo SSY del top   => permitido    (ssy-region-full-reuse)

PATH llena + divergencia con push  => ERROR_SIMT   (ssy-path-overflow-depth4)
PATH llena + destino == join       => permitido    (ssy-path-full-direct-join)
```

| Caso | Qué valida |
|---|---|
| [ssy-all-paths](ssy-all-paths/) | Ocupación máxima con 8 lanes: 7 `PATH` |
| [simt-stack-overflow](simt-stack-overflow/) | Noveno `SSY` con pila de 8 |
| [ssy-region-overflow](ssy-region-overflow/) | Push de REGION con la pila llena |
| [ssy-region-full-reuse](ssy-region-full-reuse/) | REGION llena pero `SSY` reutilizable |
| [ssy-path-overflow-depth4](ssy-path-overflow-depth4/) | Push de `PATH` con la pila llena |
| [ssy-path-full-direct-join](ssy-path-full-direct-join/) | `PATH` llena pero sin necesidad de push |

Los cuatro últimos usan `simulator_options` para reducir la profundidad de las
pilas, así que solo pueden ejecutarse con `--backend gpu-simulator`.
