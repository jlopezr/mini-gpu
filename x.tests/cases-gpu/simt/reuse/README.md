# Reutilización del SSY

Reejecutar el `SSY` que ya está en el top de la pila reutiliza la REGION en vez
de empujar otra. Es la regla que permite poner un `SSY` dentro de un bucle.

| Caso | Qué valida |
|---|---|
| [ssy-loop-reuse](ssy-loop-reuse/) | Bucle que vuelve al mismo `SSY` |
| [ssy-reuse-reduced-mask](ssy-reuse-reduced-mask/) | El `entry_mask` original no se sustituye |
| [ssy-reuse-with-pending-path](ssy-reuse-with-pending-path/) | La reutilización no pierde un `PATH` pendiente |
| [ssy-same-join-different-pc](ssy-same-join-different-pc/) | Mismo join pero otro PC: no es reutilización |
| [simt-unused-ssy-loop](simt-unused-ssy-loop/) | Reejecución sin divergencia alguna |

`ssy-region-full-reuse`, en [capacity](../capacity/), prueba la misma regla con
la pila deliberadamente llena.
