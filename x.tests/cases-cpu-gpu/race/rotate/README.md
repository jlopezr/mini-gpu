# rotate

Una textura que gira y se acerca (un gather por celda), en ensamblador (`rotate.asm`) y en C (`rotate.c`).

## C frente a ensamblador

`compare_race.py rotate` ejecuta los seis (tres métodos × C y ensamblador) con los mismos datos y comprueba
que cada uno dibuja la imagen del modelo en Python. Los kernels de GPU se lanzan sin programa de CPU y
la CPU se ejecuta hasta `HALT`:

| Método | Cuenta | Ensamblador | C | C / ens. |
|---|---|---:|---:|---:|
| CPU | instrucciones de CPU | 233.806 | 285.439 | 1,22 |
| GPU inocente | instrucciones de warp | 29.426 | 42.231 | 1,44 |
| GPU buena | instrucciones de warp | 30.864 | 44.664 | 1,45 |

Aquí sí hay diferencia, a diferencia de los kernels de sistema. El bucle de celdas son **20
instrucciones en C contra 14 en ensamblador**, y las seis de más son de tres clases, las tres de
sacar del bucle lo que no cambia en él:

- **`MOVI` + desplazamiento** (dos veces por celda): la GPU no tiene `SHLI`, y la constante (7, 2) se
  vuelve a cargar en cada vuelta. En ensamblador está en un registro desde antes del bucle.
- **`p += cstep` escalado a cada vuelta:** un `MOVI`, un `SHL` y un `ADD` donde el ensamblador tiene un
  `ADDI`, aunque `cstep` no cambia dentro del bucle.
- **Una copia del texel** (`ADD R28,R15,R0`) y **la constante 160 cargada antes de cada `BLT`**.

Dos cosas que importan de cara a escribir C para esta máquina:

- **lcc reparte los registros por orden de declaración.** Con 14 registros preservados y 18 variables,
  declarar primero las frías (`blk`, `fb`, `u00`...) dejaba a `u`, `v` y `texel` en la pila, y el bucle
  de celdas leía y escribía la pila en cada vuelta. En `rotate_body.h` las variables se declaran de la más
  caliente a la más fría.
- **Una pila en la GPU es cara.** Cada lane tiene su porción, a 512 bytes de la siguiente, así que un
  acceso a la pila de los ocho lanes son ocho transacciones. `mini-opt` ya quita los guardados y
  restauraciones de registros preservados aunque el kernel tenga locales, pero no los locales.

Esa brecha es la que cierra el pase `licm` de `mini-opt`: los números de arriba son los de antes de él, y con
todos los pases la rotación queda en 1,00 / 1,00 / 1,01 veces el ensamblador (CPU, GPU inocente, GPU buena; ver
[compare](../../../../32.cpu-gpu-func-sim/compare/README.md)).
