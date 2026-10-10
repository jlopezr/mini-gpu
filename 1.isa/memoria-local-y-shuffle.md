# Memoria local por lane y shuffle: ideas para aprovechar la EBR de la 37

Notas de diseño, no un contrato. Nada de esto está implementado: los opcodes de
`gpu_lane.v` llegan hasta `GETTID` (0x30) y los de la propuesta v0.4b que aquí se
citan no existen en el RTL de `37.fpga-cpu-gpu-mk2`.

## 1. Punto de partida

Cada lane tiene un `gpu_register_file` (`words[0:255]`, 8 warps × 32 registros ×
32 bits = 1 KiB). Cabe en una sola EBR (18 Kib, 16 Kib útiles a 32 bits) y el
resto queda libre: unas 256 palabras por lane. El inventario
(`../inventario-recursos-37.md`, fila «GPU: registros por carril») lo marca con
mejora «Baja» y un uso del 22 %.

Ese hueco no es gratis del todo: los puertos del banco ya están ocupados (dos
lecturas compartidas entre I y D, y una escritura compartida entre X y las
respuestas del LSU). Usarlo exige robar ciclos a esos puertos o poner una EBR
aparte.

## 2. Memoria local y compartida por lane

Dos espacios sobre el mismo hueco:

- **Local**: privado por lane. Dirección interna `{warp, offset}`. La misma
  dirección da datos distintos en cada lane. Sirve para spills, pila local y
  arrays pequeños por hilo.
- **Compartido**: el contenido está replicado en las 8 lanes y cada una lee su
  copia, así que 8 consultas distintas ocurren a la vez (tablas de seno, paletas,
  gamma). Dirección interna `offset`, sin warp.

Las lecturas de ambos son locales y sin conflicto. Las escrituras difieren:
local escribe en paralelo; compartido tiene que llegar a las 8 copias, necesita
una regla de conflictos (p. ej. gana la lane activa más baja) y, si las lanes
escriben a direcciones distintas, se serializa (hasta 8 ciclos). Por eso lo
compartido sirve para datos que se escriben poco, como tablas cargadas por la
CPU con la GPU parada, y no para que las lanes se comuniquen entre sí.

### Dos formas de acceder

| | Ventana de direcciones (`LW`/`SW`) | Opcodes propios |
|---|---|---|
| ISA | no cambia | `LDL/STL`, `LDS/STS` (hay huecos: 0x18-0x1f, 0x28-0x2b, 0x31-0x3d) |
| Decisión | por lane, con los bits altos de `d_rf_a + d_immediate` (gpu_sm.v:330) | por opcode, en decodificación |
| Caso mixto en un warp | las lanes fuera de la ventana siguen al LSU quitándolas de `lsu_mask` | no existe |
| Punteros genéricos | sí | no |
| Herramientas | simulador y decodificador | ensamblador, simulador, depurador, monitor, tests, mini-lcc |
| LSU | se toca la máscara | no se toca |

Preferencia provisional: opcodes propios, para no cargar el LSU, que ya es el
punto de mayor convergencia (1.220 bits de puertos). Se puede probar primero con
ensamblador y simulador antes de enseñárselo a mini-lcc.

No verificado: cómo encaja la lectura/escritura local en las etapas I/D/X/W, ni
cuántos ciclos libres de lectura hay con carga real (hay contadores para medirlo).

### Otras opciones descartadas o aplazadas

- **Más registros virtuales** (banco por warp): la ISA codifica 5 bits y el
  compilador casi no lo aprovecharía. Valor bajo.
- **Estructuras de warp** (descriptores, pila SIMT): son del SM, no de la lane, y
  pesan <1 % del chip. Valor bajo.
- **16 warps**: el banco cabe en la misma EBR, pero el estado por warp está en
  flip-flops (~+2.600 FF), los mux pasan a 16:1 y la pila SIMT duplica sus DPR.
  Solo con datos de `no_warp_stall` que lo justifiquen.
- **Cola de vértices**: EBR dedicada, no el hueco. Con un vértice por lane
  encajaría en la memoria local, pero depende de que ésta exista.

## 3. Shuffle

### Lo que ya había en el repositorio

- `propuesta-v0.3.md` (§ SHFL, 0x35, y ejemplo §15.10): solo la forma
  **indexada**, `SHFL Rd, Ra, Rb`; no propone variantes XOR, up ni down. Deja
  pendiente el tratamiento del índice fuera del warp y de una fuente inactiva.
- `propuesta-v0.4b.md` § 6.2: cierra ese pendiente. Un índice fuera del warp o una
  fuente inactiva produce cero, sin wrap. Captura máscara, `Ra` y `Rb` antes de
  escribir; no es barrera ni reconverge; solo escriben las lanes activas.
  Capability `warp_shuffle`.
- `minigpu_fuego_warps.md` § 8: caso de uso `SHFL_UP`/`SHFL_DOWN` en el kernel de
  propagación de calor. Pasaría de 3 lecturas por píxel a 1 (no implica 3× de
  velocidad), y no resuelve los bordes entre warps: el borde necesita un
  `LOADUB` extra. Este documento no fija encoding.
- `minigpu_fuego_warps.md` también dice que MiniISA v0.1 no tiene `SHFL` ni
  `BALLOT`, a propósito, para medir primero sin ellos.

### Qué aporta esta nota

1. **La memoria local/compartida no sustituye al shuffle.** Con `LDL/STL` una
   lane solo ve su memoria. Con `LDS/STS` se puede emular (cada lane escribe en
   `compartida[i]` y lee `compartida[(i+1)%8]`), pero la escritura se serializa:
   hasta 8 ciclos de escritura más 1 de lectura.
2. **El hardware ya tiene los datos juntos.** `d_rf_a`/`x_rf_a` son
   `reg [255:0]` (8 lanes × 32 bits, gpu_sm.v:161 y :169). Un shuffle es un mux
   sobre ese vector, sin memoria ni EBR, con latencia de ALU y escribiendo por
   el puerto normal del banco.
3. **Coste según la variante:**
   - vecino (`up`/`down` con delta 1): un desplazamiento fijo del vector, casi gratis;
   - `xor` con máscara fija: reducciones en árbol (con 8 lanes, máscaras 1, 2 y 4
     cubren una reducción completa en 3 pasos);
   - indexado (`SHFL` de v0.3/v0.4b): 8 mux 8:1 de 32 bits con el índice de
     origen por lane. Es la forma ya propuesta.
4. **Falta decidir** si, además del indexado, merece la pena una forma fija de
   vecino (más barata y la que pide el kernel de calor), y qué recibe la lane 0 en
   `up` y la 7 en `down`. v0.4b ya dice cero para fuera de rango.

### Nombres de referencia en otras GPU

- NVIDIA: `__shfl_sync`, `__shfl_up_sync`, `__shfl_down_sync`, `__shfl_xor_sync`;
  votos `__ballot_sync`, `__any_sync`, `__all_sync`, `__match_sync`,
  `__reduce_add_sync`.
- AMD: DPP (`row_shl`, `row_shr`, `quad_perm`: opera con el vecino sin una
  instrucción aparte), `ds_swizzle`, `ds_bpermute`, `v_readlane`,
  `v_readfirstlane`, `v_writelane`.
- Vulkan/GLSL: `subgroupShuffle`, `subgroupShuffleUp/Down/Xor`,
  `subgroupBroadcast`, `subgroupBallot`, `subgroupAdd`.
- Gráficos: `quadSwapHorizontal/Vertical`, base de las derivadas (`dFdx`, `dFdy`).

## 4. Pendiente

- Diseñar el recorrido de `LDL/STL/LDS/STS` por las etapas del SM y medir los
  ciclos de lectura libres.
- Medir antes con `no_warp_stall` y los contadores si falta algo de esto.
- Medir área y timing de la ruta de shuffle entre lanes (lo pide v0.3).
