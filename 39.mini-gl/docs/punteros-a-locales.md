# Punteros a variables locales en código de kernel: `clip_edge` y sus alternativas

En V2, `raster.c` se compila también como parte del kernel de la GPU (`gpu_renderer.c` lo incluye con
`MGL_RASTER_LANES`). Al hacerlo apareció un problema con una función de apariencia inocente, `clip_edge`, que
recibía punteros a dos variables locales. Este documento explica qué pasaba, por qué, cómo se resolvió y qué otras
soluciones hay.

## El código original

`sw_triangle` rellena cada fila con un tramo `[from, to]` que recorta con las tres aristas del triángulo:

```c
static void clip_edge(long v, long d, int left, int *from, int *to) {
    long x;
    if (d > 0) {
        if (v >= 0) return;
        x = left + (-v + d - 1) / d; /* la primera x con v + d * (x - left) >= 0 */
        if (x > *from) *from = x > *to ? *to + 1 : (int)x;
    } else if (d < 0) {
        if (v < 0) {
            *to = *from - 1;
            return;
        }
        x = left + v / -d; /* la última */
        if (x < *to) *to = (int)x;
    } else if (v < 0)
        *to = *from - 1;
}

/* en sw_triangle, por cada fila: */
clip_edge(a, by - y0, left, &from, &to);
clip_edge(b, cy - by, left, &from, &to);
clip_edge(c, y0 - cy, left, &from, &to);
```

En la CPU (V0, V1) funcionaba bien. En el kernel de V2, la GPU paraba con `ERROR_SIMT`.

## Qué pasaba

El problema no son los punteros en general (`j`, `j->framebuffer` o el de un sprite son normales), sino los
**punteros a variables locales**: `&from` y `&to`.

1. **La variable se va a la pila.** Una variable cuya dirección se toma no puede vivir en un registro: lcc la pone
   en la pila, calcula su dirección (`ADDI R3, R30, 8`) y la usa como puntero. Cada uso de `from` o `to` pasa a ser
   un `LOAD` o un `STORE`. En la GPU, además, cada lane tiene su propia pila, así que esos accesos van a direcciones
   separadas y no se coalescen.

2. **mini-opt deja de poder seguir la pila.** Varios pases de mini-opt necesitan saber qué hay en cada hueco de la
   pila. Si la dirección de un hueco está en un registro, cualquier `STORE` por un puntero podría estar escribiendo
   en cualquier hueco, así que esos pases suponen lo peor. El que más sufre es `ssy`, el que coloca los `SSY` para la
   divergencia SIMT: da por variable entre lanes todo lo que se lee de la pila. Como lcc guarda en la pila
   parámetros, derrames y registros preservados, casi cualquier salto del kernel parece depender de la lane.

3. **Expandir la llamada no lo arregla.** La GPU de la 36, para la que se compilan los kernels, no tiene `JAL`, y
   el pase `kernelcalls` copia el cuerpo de `clip_edge` dentro del kernel. Pero `&from` sigue ahí: se calcula con
   `ADDI` y se usa como base de los accesos. mini-opt no tiene ningún pase que vea que ese puntero solo apunta a un
   hueco fijo.

Como el kernel incluye todo el raster expandido, el efecto de un solo `&local` alcanza a **todo el kernel**:

| | Con `clip_edge(&from, &to)` | Con `CLIP_EDGE` (macro) |
|---|---|---|
| Saltos que `ssy` trata como divergentes | 242 | 19 |
| Resultado en la GPU | `ERROR_SIMT`: más de 8 regiones anidadas | correcto, profundidad 2 |
| V0 (CPU), `shapes`, 2 frames | 591 000 instrucciones | 587 000 instrucciones |

La GPU tiene una pila de **8 regiones** SIMT (cada `SSY` abre una). Con tantos saltos marcados como divergentes, las
regiones anidadas superaban ese límite.

## La solución elegida: una macro

`CLIP_EDGE` hace lo mismo, pero sobre las variables de quien la llama, sin tomar su dirección:

```c
#define CLIP_EDGE(V, D, LEFT, FROM, TO)                                 \
    do {                                                                \
        long v_ = (V), d_ = (D), x_;                                    \
        if (d_ > 0) {                                                   \
            if (v_ < 0) {                                               \
                x_ = (LEFT) + (-v_ + d_ - 1) / d_; /* la primera */     \
                if (x_ > (FROM)) (FROM) = x_ > (TO) ? (TO) + 1 : (int)x_; \
            }                                                           \
        } else if (d_ < 0) {                                            \
            if (v_ < 0)                                                 \
                (TO) = (FROM) - 1;                                      \
            else {                                                      \
                x_ = (LEFT) + v_ / -d_; /* la última */                 \
                if (x_ < (TO)) (TO) = (int)x_;                          \
            }                                                           \
        } else if (v_ < 0)                                              \
            (TO) = (FROM) - 1;                                          \
    } while (0)

CLIP_EDGE(a, by - y0, left, from, to);
```

Cambios respecto a la función:

- `*from` y `*to` pasan a ser `FROM` y `TO`: la macro escribe directamente en `from` y `to`.
- Los dos `return` se convierten en `if` anidados, porque en una macro un `return` saldría de `sw_triangle`.
- `v_`, `d_` y `x_` son locales del bloque `do { … } while (0)`: cada argumento se evalúa una sola vez y los nombres
  no chocan con los de quien llama.

La lógica es la misma caso por caso. El fuzz de triángulos contra la versión original y el de V2 contra V0
(`tests/test_fuzz_v2.c`) dan idéntico.

Es el mismo recurso que ya usa `WALK_RUN` en `segment`, por un motivo parecido: lcc no expande funciones ni deja en
registros lo que va por un puntero.

**Ventajas:** no hay que tocar mini-opt; también mejora la CPU, porque `from` y `to` quedan en registros.

**Inconvenientes:** una macro de varias líneas es más incómoda de leer, depurar y mantener que una función (barras
al final de cada línea, sin comprobación de tipos, cuidado con los paréntesis y con evaluar los argumentos una sola
vez).

## Alternativas

### 1. Devolver valores en vez de escribir por punteros

Una función que no toma direcciones es C normal y se puede expandir sin problemas. Aquí habría que separar lo que
`clip_edge` hace a la vez:

```c
from = clip_from(a, by - y0, left, from, to);   /* solo puede subir from */
to   = clip_to(a, by - y0, left, from, to);     /* solo puede bajar to   */
```

O devolver un único valor que codifique los dos (por ejemplo, `from` y `to` en las dos mitades de un entero de 32
bits), lo que funciona porque las coordenadas caben en 16 bits.

- **Ventajas:** sigue siendo una función; se lee y se depura como C normal.
- **Inconvenientes:** hay que repartir la lógica en dos funciones o empaquetar y desempaquetar, y repetir parte del
  cálculo. Devolver una estructura no sirve: lcc la devuelve a través de memoria, otra vez con una dirección de la
  pila.

### 2. Arreglarlo en mini-opt: accesos directos a los huecos cuya dirección se toma

Un pase nuevo que reconozca este patrón:

```
ADDI  R3, R30, 8        ; R3 = &from
...
LOAD  R7, R3, 0         ; lee from
STORE R9, R3, 0         ; escribe from
```

Si el registro con la dirección (`R3`) solo se usa como base de `LOAD`/`STORE` con desplazamiento constante (no se
guarda en memoria, no se suma con algo desconocido y no se pasa a una llamada que no se expanda), cada acceso es en
realidad un acceso al hueco `R30+8`. El pase los cambiaría por `LOAD R7, R30, 8` y similares, y el `ADDI`
desaparecería. A partir de ahí la pila vuelve a poder seguirse, y `forward`/`stackslots` podrían incluso pasar el
hueco a un registro.

Es una optimización conocida en compiladores (sustituir variables cuya dirección se toma por accesos directos o por
registros), de tamaño medio en mini-opt: hay que seguir el valor del puntero a través de copias y de los marcos de las
funciones expandidas, y con un solo uso que no se entienda hay que renunciar.

- **Ventajas:** el código C se puede escribir de forma natural (`&local` deja de ser peligroso en un kernel), y
  mejora también cualquier otro kernel y el código de CPU.
- **Inconvenientes:** es trabajo en el compilador, con sus tests; y no cubre todos los casos (si el puntero se guarda
  en memoria o se pasa a código de otra unidad, sigue sin poder seguirse).

### 3. Mejorar los análisis para que una dirección escapada no lo invalide todo

En lugar de dar por perdida toda la pila en cuanto se escapa una dirección, los análisis (`ssy`, `noalias`,
`forward`) podrían dar por perdidos solo los huecos cuya dirección se ha tomado y seguir el resto. En C, un puntero a
`from` solo puede acceder a `from`.

- **Ventajas:** reduce mucho el daño: el resto del kernel se analizaría bien.
- **Inconvenientes:** `from` y `to` seguirían en la pila (más accesos a memoria), y el cambio se repartiría por
  varios pases. La alternativa 2 resuelve más con un solo pase.

## Recomendación

- **Para el código de hoy**, la macro: ya está hecha, validada y es lo más rápido en CPU y GPU.
- **Como regla al escribir código que acabe en un kernel:** nada de `&variable_local`. Si una función tiene que
  devolver más de un valor, mejor una macro (como `WALK_RUN` y `CLIP_EDGE`) o varios valores devueltos.
- **A medio plazo**, la alternativa 2 en mini-opt, si aparecen más casos. Eliminaría la regla anterior y dejaría
  escribir el raster como C normal.

Mientras tanto, mini-opt no deja pasar el problema en silencio: el pase `ssy` comprueba al compilar que ningún
`SSY` puede superar las 8 regiones anidadas y, si pasa, da un error que dice de qué función expandida viene el salto.
