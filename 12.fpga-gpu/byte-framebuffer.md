# Framebuffer de bytes en la GPU: análisis y plan

Contexto: hacer caber el mandelbrot de 320×240 en los 128 KiB de BRAM de la GPU, y
usarlo como banco de pruebas para medir el efecto de la coalescencia de accesos.

El plan es implementar **las dos versiones** y compararlas:

1. **Software** — empaquetar 4 píxeles por palabra en el kernel, sin tocar el hardware.
2. **Hardware** — añadir `LOADB`/`STOREB` al ISA y a la ruta de datos.

Las cifras de este documento están medidas sobre el repo salvo donde se indique
lo contrario.

---

## 1. El presupuesto de memoria

`gpu_bram.v` son 8 bancos × 4096 palabras × 32 bits = **128 KiB**, con el espacio
de direcciones `0x00000`–`0x1FFFF`.

| Elemento                     | Tamaño      | Notas                                                   |
|------------------------------|-------------|---------------------------------------------------------|
| Programa mandelbrot          | **220 B**   | 55 instrucciones, ensamblado con `1.isa/miniisa_asm.py` |
| Framebuffer, 1 palabra/píxel | **300 KiB** | 320×240×4 = 307200 B. **No cabe**: 2.3× la BRAM entera  |
| Framebuffer, 1 byte/píxel    | **75 KiB**  | 320×240 = 76800 B. Cabe, con 53 KiB libres              |

El programa es irrelevante en espacio. El problema es exclusivamente el framebuffer.

### Dos cosas que hay que arreglar en cualquier caso

**El rango de valores no cabe en un byte.** Analizando `expected.bin`: mínimo 1,
máximo **256**, con 17206 píxeles a 256 (los del interior del conjunto, porque
`R4 = 256` iteraciones). Un truncamiento a byte convierte 256 en 0, y como el 0
no aparece nunca el resultado es reversible *por accidente*. Preferible saturar
a 255 de forma explícita: es una instrucción y no depende de una coincidencia.

**La base del framebuffer está fuera del mapa.** El kernel usa `0x00100000`
(1 MiB) y la BRAM acaba en `0x1FFFF`. Hay que reubicarla independientemente del
formato que se elija.

---

## 2. El mapa de bancos y por qué importa

En `gpu_bram.v` / `gpu_lsu.v` la dirección se descompone así:

```
addr[16:5]  ->  fila dentro del banco (4096 filas)
addr[4:2]   ->  banco (0..7)
addr[1:0]   ->  byte dentro de la palabra (hoy: debe ser 0)
```

Las palabras consecutivas están **entrelazadas entre bancos**. Eso hace que un
warp de 8 lanes con direcciones de palabra consecutivas toque los 8 bancos:

| Patrón                  | `addr[4:2]` de los 8 lanes | Bancos distintos | Oleadas |
|-------------------------|----------------------------|------------------|---------|
| 8 palabras consecutivas | 0,1,2,3,4,5,6,7            | 8                | **1**   |
| 8 bytes consecutivos    | 0,0,0,0,1,1,1,1            | 2                | **4**   |
| 8 bytes con paso 4      | 0,1,2,3,4,5,6,7            | 8                | **1**   |

El router del LSU concede **como máximo un lane por banco y oleada**
(`gpu_lsu.v:99`, `else if (!route_valid[bank])`). Los lanes que chocan no se
pierden: siguen en `pending[selected]` y entran en la siguiente oleada
(`gpu_lsu.v:148`).

### Consecuencias

- **Funcionalmente es correcto.** El conflicto de bancos ya está resuelto por
  construcción. Con byte enables, cuatro lanes escribiendo cuatro bytes de la
  misma palabra en cuatro oleadas distintas no se pisan; no hace falta
  read-modify-write.
- **Es solo rendimiento**, y solo para bytes. Las palabras no pierden nada.
- **No es inherente a los bytes, es del patrón de acceso.** Es exactamente la
  penalización por acceso no coalescido que se estudia en CUDA, reproducible y
  medible aquí.

Para este kernel el coste es despreciable de todos modos: 76800 stores sobre
10.255.708 instrucciones ejecutadas es el **0.75%** del total.

---

## 3. Versión A — empaquetado por software

Cada lane calcula 4 píxeles y los empaqueta él mismo en una palabra de 32 bits
con shifts y ORs, seguido de un único `STORE` alineado.

- Cero cambios en el hardware.
- Mantiene la distribución perfecta entre los 8 bancos (1 oleada por store).
- El framebuffer ocupa los mismos 75 KiB.

Implementado en `examples/mandelbrot.asm` (64 instrucciones, 256 B), base del
framebuffer en `0x4000`. Verificado contra `expected.bin` saturado a 255: los
76800 píxeles coinciden.

### Coste real medido: +17.6%, y no por el empaquetado

|                           | Instrucciones de warp | Por píxel |
|---------------------------|-----------------------|-----------|
| Original, 1 palabra/píxel | 10.255.708            | 133.5     |
| Versión A, empaquetado    | **12.062.200**        | **157.1** |

La estimación previa de este documento decía "aproximadamente un 1%" y **era
incorrecta**. Contaba solo la aritmética de empaquetado, que efectivamente sale
casi gratis: +8 instrucciones por píxel de empaquetado y saturación, menos ~5
que se ahorran al hacer un `STORE` por cada 4 píxeles en vez de uno por píxel.
Eso son unas +3 por píxel, no +23.6.

El resto es **divergencia SIMT**, y viene del cambio de mapeo lane→píxel:

- Antes, los 8 lanes de un warp trabajaban sobre 8 píxeles **adyacentes**.
- Ahora, como un lane tiene que poseer los 4 píxeles de una palabra, en cada
  paso `k` los 8 lanes trabajan sobre píxeles separados **de 4 en 4**.

El warp itera hasta que escapa el último lane, así que lo que importa es el
máximo de iteraciones entre los 8. Píxeles más separados están menos
correlacionados y ese máximo sube: de ~70 a ~82 iteraciones por paso
(descontando el coste fijo), un +17% que explica prácticamente toda la
diferencia.

Es un resultado interesante por sí mismo: el coste de empaquetar en software no
está en las instrucciones de empaquetado, sino en la **localidad que se pierde
al reorganizar el trabajo**. Y es una restricción estructural de esta versión:
mientras una palabra deba contener 4 píxeles consecutivos y no haya intercambio
entre lanes, un lane está obligado a poseer 4 píxeles consecutivos.

Esto le da a la versión B un argumento que no tenía al escribir el plan: con
`STOREB` cada lane vuelve a poseer **un** píxel, se recupera la adyacencia y se
recuperan esas ~12 iteraciones de divergencia por paso. La comparación deja de
ser "software gratis contra hardware con 4 oleadas" y pasa a ser un intercambio
real entre divergencia y conflictos de banco.

Tareas:

- [x] Reubicar la base del framebuffer dentro de `0x00000`–`0x1FFFF`
- [x] Saturar la cuenta de iteraciones a 255 (sin ramificar: `iter - (iter>>8)`)
- [x] Bucle de 4 píxeles por lane con empaquetado y `STORE` único
- [ ] Actualizar `expected.bin` y el caso de test a formato empaquetado

---

## 4. Versión B — `LOADB` / `STOREB` en hardware

### Qué hay que tocar

| Cambio                                                   | Dónde                          | Dificultad |
|----------------------------------------------------------|--------------------------------|------------|
| Opcodes nuevos (`0x18`–`0x1f` libres)                    | `gpu_lane.v`                   | Trivial    |
| Permitir `addr[1:0] != 0` según el tamaño                | `gpu_lsu.v:97`                 | Trivial    |
| Llevar el tamaño en la petición del LSU                  | `gpu_lsu.v` puerto `req_*`     | Medio      |
| Byte strobes en el puerto A: `bank_write` de 8 → 32 bits | `gpu_lsu.v`, `gpu_bram.v`      | **Medio**  |
| Extraer y extender el byte en la respuesta               | `gpu_lsu.v` (`response_lanes`) | Medio      |

Notas de implementación:

- El **puerto aux de la BRAM ya tiene byte enables** (`gpu_bram.v:64-67`,
  `aux_strobe[0..3]`). El patrón ya está escrito en el fichero; el puerto A solo
  tiene que replicarlo.
- La comprobación de alineación tiene que pasar a depender del tamaño del
  acceso: las palabras deben seguir exigiendo `addr[1:0] == 0`, los bytes no.
  Hoy `req_write` es un único bit y no lleva información de tamaño.
- El LSU ya conserva las direcciones completas en `addresses[selected]`,
  incluidos los bits `[1:0]`, así que la extracción del byte en la respuesta no
  necesita estado adicional.
- Decidir si `LOADB` extiende con ceros o con signo (o ambos opcodes).

Tareas:

- [ ] Contador de oleadas en el LSU para instrumentar la comparación
- [ ] Opcodes y decodificación en `gpu_lane.v`
- [ ] Campo de tamaño en la petición del LSU
- [ ] Byte strobes en el puerto A de `gpu_bram.v`
- [ ] Extracción/extensión en la ruta de respuesta
- [ ] Testbench de LSU con conflictos de banco provocados
- [ ] Variante del kernel con `STOREB` directo

---

## 5. Qué esperamos medir

Con el contador de oleadas, las dos versiones deberían dar:

|                         | Instrucciones      | Oleadas por store | Bytes de framebuffer |
|-------------------------|--------------------|-------------------|----------------------|
| Original (no cabe)      | 10.255.708         | 1                 | 300 KiB              |
| A: empaquetado software | 12.062.200 medido  | 1                 | 75 KiB               |
| B: `STOREB` directo     | ~10.4 M esperado   | 4                 | 75 KiB               |

La hipótesis inicial era que **A ganaría pese a ejecutar más instrucciones**,
porque B paga 4 oleadas por store. Medida la versión A, esa hipótesis se debilita
bastante: A ejecuta 1.8 M de instrucciones de más por divergencia, mientras que
las 4 oleadas de B afectan solo a los 76800 stores, el 0.75% de las
instrucciones. Salvo que una oleada extra cueste muchísimo, **B debería ganar**.

Lo que decidirá la comparación es cuánto cuesta realmente una oleada del LSU
frente a una instrucción de warp — que es exactamente lo que el contador de
oleadas tiene que medir.

Un kernel con menos aritmética por píxel (por ejemplo un simple relleno o una
copia) debería mostrar la diferencia mucho más marcada. Puede valer la pena
añadir ese caso como segundo punto de medida.

---

## 6. Estado de las afirmaciones

- **Medido**: tamaño del programa (55 instrucciones / 220 B), tamaño y rango de
  valores de `expected.bin` (min 1, max 256, 17206 píxeles a 256), capacidad de
  la BRAM, número de instrucciones ejecutadas del kernel original (del
  `test.json`), y el coste y la corrección de la versión A (12.062.200
  instrucciones, 76800 píxeles idénticos a la referencia saturada, ejecutado en
  el simulador funcional de `11.gpu-sim-func`).
- **Derivado del código, no medido**: el número de oleadas por patrón de acceso,
  y por tanto la penalización 4×. Sale de la descomposición de direcciones y de
  la lógica de `route_valid`, pero no se ha ejecutado. El contador de oleadas de
  la versión B es precisamente lo que lo convertirá en un dato.
