# Barreras y divergencia

`BAR` exige que participen todas las lanes vivas del warp. Los dos casos son las
dos caras de esa regla.

| Caso | Qué valida |
|---|---|
| [ssy-bar-at-join](ssy-bar-at-join/) | `BAR` en el join: legal, se ejecuta ya reconvergida |
| [ssy-bar-partial-mask](ssy-bar-partial-mask/) | `BAR` en un camino divergente: `ERROR_BARRIER` |
