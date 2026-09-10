# Push de REGION con la pila llena

## Objetivo

Comprueba que abrir una REGION nueva con la pila llena produce `ERROR_SIMT`
(código 6) antes de modificar el estado.

## Comportamiento esperado

- Con `simt_region_depth = 1`, el primer `SSY` deja la pila llena.
- El segundo `SSY` está en otro PC, luego no es reutilización y necesita push.
- Debe fallar sin commit parcial.

## Qué comprueba el `test.json`

- `error_code = 6`.
- `fault.pc = 8` y `warp[0].pc = 8`: el PC no avanzó más allá del `SSY` que falló.
- `active_mask = 255` intacta.

## Notas

Usa `simulator_options.simt_region_depth = 1`. Contrapunto de
`ssy-region-full-reuse`: misma pila llena, pero aquí sí hace falta push.
