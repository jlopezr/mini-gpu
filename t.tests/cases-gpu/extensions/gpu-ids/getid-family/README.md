# Familia GETID: identidades de lane y de warp

## Objetivo

Comprueba que `GETTID`, `GETLANE`, `GETWARP`, `GETLWARP` y `GETARG` devuelven lo
que dice `isa.md`, y que `logical_warp_id` y `arg` del `warps.json` llegan al
kernel.

## Comportamiento esperado

- Dos warps con `warp_size = 4`: el slot físico 0 (id lógico 7, argumento
  `0x1000`) y el slot 3 (id lógico 2, argumento `0x2000`). El id lógico no
  coincide con el slot a propósito.
- `GETTID = warp * 4 + lane`, `GETLANE = lane`, `GETWARP = slot físico`.
- Todas las lanes de un warp ven el mismo `GETLWARP` y el mismo `GETARG`.

## Qué comprueba el `test.json`

- Terminación sin error, 6 instrucciones por warp.
- Las cinco identidades en las lanes 0 y 3 del warp 0 y en las lanes 0 y 1 del
  warp 3.

## Notas

- `requires: ["gpu_ids"]`: solo los simuladores (11 y 25) la declaran. El RTL
  solo tiene `GETTID`, así que en la placa el caso se omite.
