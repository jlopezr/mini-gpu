# Accesos de 8 y 16 bits

Esta carpeta es la 18 más seis instrucciones: `LOADB`, `LOADUB`, `STOREB`,
`LOADH`, `LOADUH` y `STOREH`. Nada más cambia de sitio; el camino de ráfagas
BL8, el subsistema de vídeo y el monitor son los de la 18 byte a byte.

## Qué no es esto

No es la ISA v0.1. La v0.1 ([`1.isa/isa.md`](../../1.isa/isa.md), §«Inmediatos
y memoria») define `LOAD` y `STORE` de exactamente cuatro bytes alineados, y
deja `0x18–0x1F` como *reservadas*. Los accesos sub-palabra aparecen por primera
vez en las propuestas, y **las dos propuestas no coinciden**:

| Opcode | `propuesta-v0.2.md` §7 | `propuesta-v0.3.md` |
|--------|------------------------|---------------------|
| `0x18` | `LOADB`                | `LOADB`             |
| `0x19` | `LOADUB`               | `LOADBU`            |
| `0x1A` | **`STOREB`**           | **`LOADH`**         |
| `0x1B` | `LOADH`                | `LOADHU`            |
| `0x1C` | `LOADUH`               | `STOREB`            |
| `0x1D` | `STOREH`               | `STOREH`            |

Aquí se sigue **el mapa de la v0.2**, y con los nombres de la v0.2
(`LOADUB`/`LOADUH`, no `LOADBU`/`LOADHU`). Al migrar a v0.3 habrá que
recodificar `0x1A`–`0x1C` y renombrar dos mnemónicos; los sitios a tocar son los
seis `localparam` de [`cpu.v`](../cpu.v), la tabla de
[`1.isa/miniisa_asm.py`](../../1.isa/miniisa_asm.py) y las dos ramas
`elif opcode in (...)` de
[`2.cpu-sim-func/minicpu_sim.py`](../../2.cpu-sim-func/minicpu_sim.py). El resto
del hardware no conoce los opcodes: solo tamaños y máscaras.

## Semántica

```
LOADB   Rd, Ra, imm16   Rd = sign_extend(mem8 [Ra + imm16])
LOADUB  Rd, Ra, imm16   Rd = zero_extend(mem8 [Ra + imm16])
LOADH   Rd, Ra, imm16   Rd = sign_extend(mem16[Ra + imm16])
LOADUH  Rd, Ra, imm16   Rd = zero_extend(mem16[Ra + imm16])
STOREB  Rs, Ra, imm16   mem8 [Ra + imm16] = Rs[7:0]
STOREH  Rs, Ra, imm16   mem16[Ra + imm16] = Rs[15:0]
```

Formato I, idéntico al de `LOAD`/`STORE`: `{opcode, Rx, Ra, imm16}`, con el
inmediato extendido con signo. Como en `STORE`, las dos escrituras toman el dato
del campo `Rd`, no de `Rb`.

Alineación: los accesos de byte admiten cualquier dirección; los de media
palabra exigen dirección par. Una dirección impar en `LOADH`/`LOADUH`/`STOREH`,
o no múltiplo de cuatro en `LOAD`/`STORE`, para la CPU con
`ERROR_MEMORY_ACCESS` (`0x02`) y deja el PC en la instrucción culpable.

## Por qué el hardware apenas cambia

El camino de datos de la 18 ya transportaba máscaras de byte de punta a punta:
`cpu.v` sacaba `dmem_write_enable[3:0]` (siempre `4'b1111`), el adaptador lo
desplazaba a una máscara de 16 bits dentro de la línea, el *fabric* la pasaba y
el controlador la convertía en DQM. Lo único que hacía falta era dejar de
escribir siempre los cuatro bytes.

**Escrituras.** El dato se replica en las cuatro posiciones de la palabra y es
la máscara la que elige el carril:

| Instrucción | `dmem_write_data`    | `dmem_write_enable`         |
|-------------|----------------------|-----------------------------|
| `STORE`     | `Rs`                 | `4'b1111`                   |
| `STOREB`    | `{4{Rs[7:0]}}`       | `4'b0001 << addr[1:0]`      |
| `STOREH`    | `{2{Rs[15:0]}}`      | `addr[1] ? 4'b1100 : 4'b0011` |

Así ni el adaptador, ni el *fabric*, ni el controlador han tenido que ensanchar
ninguna interfaz: siguen viendo una escritura de palabra con su `wmask`.

**Lecturas.** La memoria devuelve la palabra que contiene el byte pedido y la
CPU extrae y extiende en `STATE_MEMORY_WAIT`, con los dos bits bajos de la
dirección como selector. No cuesta ciclos: la latencia la sigue fijando el
*handshake* `valid`/`ready`, igual que en `LOAD`.

**Alineación.** El único cambio en `cpu_dmem_adapter.v` es quitar la exigencia
de `dmem_address[1:0] == 2'b00` para el rango de SDRAM. Esa comprobación no
podía quedarse allí porque el adaptador no sabe el tamaño del acceso; ahora la
hace `address_misaligned` en `cpu.v`, que sí lo sabe, y traps antes de tocar el
bus. La ventana de MMIO conserva la exigencia: sus registros son de 32 bits y
un acceso parcial a ellos sigue siendo un error.

## Coste

Lo que se añade al RTL es un mux de byte de 4:1 con extensión en el camino de
escritura del banco de registros, y un desplazador de máscara de cuatro bits en
el de escritura. Ambos son pequeños, pero el primero cae en un camino que esta
familia de proyectos ya vigila: conviene rebarrer semillas tras sintetizar.

```
..\tools\seed-sweep.ps1 -ProjectDir 19.fpga-cpu-hdmi-ls -Seeds (1..8)
```

## Verificación

- [`subword_ls_tb.v`](../subword_ls_tb.v) — banco de sistema completo (CPU,
  adaptador, *fabric*, controlador y modelo de SDRAM). Comprueba las ocho
  combinaciones de carga, que las escrituras parciales no tocan los bytes
  vecinos —releyéndolos por el monitor, que es el único modo de distinguir una
  máscara correcta de una que escribe la palabra entera— y las cinco trampas de
  alineación. `apio sim subword_ls_tb.v`.
- [`2.cpu-sim-func/test_minicpu_sim.py`](../../2.cpu-sim-func/test_minicpu_sim.py)
  — la clase `SubwordAccessTest` cubre lo mismo sobre el simulador funcional, de
  modo que simulador y hardware se puedan contrastar.
- [`examples/subword_demo.asm`](../examples/subword_demo.asm) — pinta una banda
  RGB565 con `STOREH`, que es el caso de uso que motiva las instrucciones.
