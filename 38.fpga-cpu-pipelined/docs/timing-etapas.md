# Timing de la CPU segmentada por etapas

Medido el 9 de noviembre de 2026 sobre el build
`reports/20261109-121743-511820-timing-stages` (RTL del commit `e57475c`, más el
cambio de comentarios de `register_file.v`). Reloj de la CPU: 25 MHz exigidos
(periodo de 40 ns), **50,30 MHz alcanzados** (camino crítico de 19,88 ns).

La pregunta es si las etapas del pipeline están equilibradas, antes de tocar la
estructura de `cpu.v`.

Las secciones 1–5 y la matriz son esa medida del 9 de noviembre, con el RTL de
entonces. Lo que cambió después, y cómo queda ahora, está en
[Estado actual](#estado-actual-11-de-noviembre) al final.

## Cómo se ha medido

El informe detallado de nextpnr (`--detailed-timing-report`, ya activo en
`apio.ini`) da, para cada entrada de cada flip-flop, cuándo llega la señal
contando desde el flanco de reloj. `timing-wall --by-register --ports` traduce
cada celda a su registro de `cpu.v` con el `hardware.json` de Yosys y separa las
entradas:

- **DATO**: entrada de dato (DI/M). Lo que el registro calcula.
- **ENABLE**: entrada CE. La decisión de si el registro se actualiza este ciclo.
- **OTRAS**: aquí siempre LSR, que Yosys usa para los «poner a 0» condicionales.
- **LLEGADA**: la mayor de las tres. Es la que cuenta para el reloj.
- **LIMITA**: cuál de las tres da la llegada.

Todos los tiempos están en ns e incluyen el clk-to-q (~0,5 ns) y el ruteo desde
el registro de origen. El informe solo da dónde acaba cada camino, no dónde
empieza: son aproximaciones del trabajo de cada etapa, no cortes exactos.

### Cómo leer las tablas

Los registros `x_*` guardan la instrucción **mientras está** en la etapa X, pero
los **escribe la lógica de la etapa anterior**: `ex_result` lo calcula ID
(`exec_result`) y EX lo guarda durante su ciclo. Cada tabla dice qué lógica
escribe sus registros.

El reparto de registros por etapa es manual, por lo que hace cada uno en
`cpu.v`; la herramienta no lo deduce del circuito.

## 1. `if_*` + PC del fetch — escritos por la lógica de IF (fetch)

| Registro | DATO | ENABLE | OTRAS | LLEGADA | LIMITA |
|---|---|---|---|---|---|
| fetch_request_pc | 19,88 | 7,83 | 4,70 | **19,88** | dato |
| imem_address | 19,64 | 18,59 | 4,47 | 19,64 | dato |
| if_instruction | 2,76 | 19,42 | 4,41 | 19,42 | enable |
| imem_valid | 18,97 | – | 4,32 | 18,97 | dato |
| if_pc | 2,69 | 18,92 | 4,45 | 18,92 | enable |
| if_valid | 17,68 | – | 8,24 | 17,68 | dato |

## 2. `id_*` — escritos al pasar de IF a ID

| Registro | DATO | ENABLE | OTRAS | LLEGADA | LIMITA |
|---|---|---|---|---|---|
| id_instruction | 2,47 | 19,46 | 4,39 | **19,46** | enable |
| id_pc | 2,78 | 19,09 | 4,44 | 19,09 | enable |
| id_valid | 18,92 | – | 8,17 | 18,92 | dato |

## 3. `ex_*` + petición a memoria — escritos por la lógica de ID (+EX)

| Registro | DATO | ENABLE | OTRAS | LLEGADA | LIMITA |
|---|---|---|---|---|---|
| ex_result | 18,77 | 15,22 | 4,62 | **18,77** | dato |
| ex_next_pc | 18,69 | 15,57 | 4,41 | 18,69 | dato |
| ex_valid | 15,67 | – | 7,30 | 15,67 | dato |
| ex_pc | 2,61 | 15,35 | 4,40 | 15,35 | enable |
| ex_error_code | 15,29 | 14,83 | 4,10 | 15,29 | dato |
| ex_class | 15,17 | – | – | 15,17 | dato |
| ex_store_data | 11,59 | 15,08 | 4,70 | 15,08 | enable |
| ex_store_mask | 13,09 | 14,88 | 4,09 | 14,88 | enable |
| ex_load_signed | 4,23 | 14,88 | 4,09 | 14,88 | enable |
| ex_halt_after_retire | 9,44 | 14,88 | 4,09 | 14,88 | enable |
| ex_rd | 2,39 | 14,76 | 4,42 | 14,76 | enable |
| ex_reg_write | 14,45 | 14,76 | 3,83 | 14,76 | enable |
| mem_request_sent | 13,23 | – | 7,30 | 13,23 | dato |
| ex_load_size | 13,18 | – | – | 13,18 | dato |
| dmem_address | 2,63 | 8,85 | 4,41 | 8,85 | enable |
| dmem_write_data | 2,57 | 8,47 | 4,70 | 8,47 | enable |
| dmem_write_enable | 5,87 | – | 7,34 | 7,34 | otras |
| dmem_valid | 3,90 | – | 7,32 | 7,32 | otras |

## 4. `wb_*` — escritos por la lógica de EX (=MEM)

| Registro | DATO | ENABLE | OTRAS | LLEGADA | LIMITA |
|---|---|---|---|---|---|
| wb_pc | 10,36 | 7,28 | 4,45 | **10,36** | dato |
| wb_next_pc | 10,06 | 6,99 | 4,68 | 10,06 | dato |
| wb_rd | 9,72 | 6,73 | 4,41 | 9,72 | dato |
| wb_result | 9,12 | 6,96 | 4,65 | 9,12 | dato |
| wb_halt_after_retire | 8,97 | 6,42 | 4,28 | 8,97 | dato |
| wb_error_code | 8,71 | 6,44 | 4,38 | 8,71 | dato |
| wb_valid | 7,46 | – | 7,85 | 7,85 | otras |
| wb_error | 7,22 | 6,76 | 4,43 | 7,22 | dato |
| wb_reg_write | 6,92 | 6,42 | 4,34 | 6,92 | dato |

## 5. `register_write_*` — escritos por la lógica de WB

| Registro | DATO | ENABLE | OTRAS | LLEGADA | LIMITA |
|---|---|---|---|---|---|
| register_write_data | 2,52 | 12,01 | – | **12,01** | enable |
| register_write_address | 2,12 | 11,76 | – | 11,76 | enable |
| register_write_enable | 2,01 | – | 10,39 | 10,39 | otras |

Fuera de las etapas: el control (`running`, `halted`, `step_active`…, 7–9 ns),
el PC arquitectónico y el error (`debug_pc`, `error`, ~9,3 ns) y el banco de
registros (`registers`, 6,5 ns). `timing-wall` nombra el PC como `debug_pc`
porque `assign debug_pc = architectural_pc` comparte sus bits.

## Resumen: trabajo propio de cada etapa

El trabajo propio es la columna DATO de lo que cada etapa calcula, sin las
señales que solo esperan una decisión de otra etapa.

| Etapa real | De → a | Trabajo propio | % de 40 ns |
|---|---|---|---|
| IF | buffer → `if_instruction`, `if_pc` | ~2,7 | 7 % |
| ID (+EX) | `id_*` → `ex_result`, `ex_next_pc`… | ~18,8 (19,9 hasta el PC del salto) | 47–50 % |
| EX (=MEM) | `ex_*` + memoria → `wb_*` | ~9–10 | 23–26 % |
| WB | `wb_*` → `register_write_*`, PC, error | ~2–4 | 5–9 % |

```text
IF   ██ 3
ID   ███████████████████ 19
MEM  █████████ 9–10
WB   ███ 3
```

## Conclusiones

1. **No está equilibrado.** Casi todo el trabajo está en ID, que en un solo
   ciclo decodifica, lee el banco, adelanta el valor pendiente, calcula la ALU o
   compara y decide el salto. Con las etapas repartidas por igual (~8 ns cada
   una) el reloj podría pasar de 100 MHz; ahora el límite es 50.
2. **IF e ID no son lentas: esperan a ID.** Sus datos llegan en menos de 3 ns;
   lo que llega a ~19 ns es el ENABLE, que sale de `id_redirects_fetch` y
   `raw_hazard`. Simplificar IF no acelera nada.
3. **El camino crítico** (`timing-wall --path`, 19,88 ns, 69 % ruteo):

   ```text
   id_instruction → ¿es salto? (cpu.v:181) → register_b_address → lectura del banco
   → id_live_operand_b (adelanto, cpu.v:192) → comparación de 33 bits (cpu.v:342)
   → salto tomado → id_redirects_fetch → fetch_request_pc
   ```

4. **EX (=MEM) va a la mitad que ID.** La limita el DATO: la selección de byte
   de las cargas y el multiplexor entre el camino normal y el de memoria, que se
   asignan en dos sitios del RTL.
5. **`register_write_*` no es una etapa** (ya eliminado, ver
   [Estado actual](#estado-actual-11-de-noviembre)). No tiene `valid` ni `pc`, no puede
   parar ni se vacía; es un buffer de escritura heredado de la CPU multiciclo de
   la 35. Su DATO es una copia (~2,5 ns) y lo que tarda es la decisión de
   retirar (~12 ns). Obliga a tener el adelanto `id_live_operand_*`, que está en
   el camino crítico.
6. **A 25 MHz sobra margen** (unos 20 ns por ciclo). Nada de esto obliga a
   cambiar el RTL. Importa si se quiere subir el reloj: lo primero sería partir
   la decisión de salto de ID, por ejemplo registrándola y pagando un ciclo más
   en los saltos tomados.

## Caminos entre etapas (matriz, 9 de noviembre)

Las tablas de arriba solo dicen dónde **acaba** cada camino. Para saber de dónde
**sale**, `timing-wall --stage-matrix` sigue el netlist de Yosys hacia atrás desde
cada entrada de cada registro hasta los registros de origen, contando las LUT. La
etapa de cada registro sale del prefijo (`if_*`…) o del atributo
`(* pipeline_stage = "..." *)` que llevan en `cpu.v` los demás; `_WR` es el buffer
de escritura y `_CTL` el control global, que no son etapas.

Build `reports/20261109-161957-904878-stage-attrs` (el mismo RTL con los
atributos; la colocación cambia y alguna llegada se mueve unas décimas respecto
a las tablas de arriba). Cada casilla es `LUT máximas / peor llegada del
destino`; `<` es un camino hacia atrás, `=` dentro de la misma etapa.

**DATO** (lo que el registro calcula):

| origen \ destino | IF | ID | EX | WB | _WR | _CTL |
|---|---|---|---|---|---|---|
| IF | 11/19,9 = | 11/18,9 | **14/18,8** | · | · | · |
| ID | **11/19,9 <** | 11/18,9 = | **14/18,8** | · | · | · |
| EX | 7/19,9 < | 7/18,9 < | 8/15,7 = | 6/10,4 | · | · |
| WB | 7/19,9 < | 7/18,9 < | 8/15,7 < | 7/10,4 = | 0/2,5 | 3/7,2 |
| _WR | 9/19,9 | 9/18,9 | **12/18,8** | · | · | · |
| _CTL | 7/19,9 | 6/18,9 | 8/15,7 | 7/10,4 | · | 3/7,2 |
| _RAM (banco) | 8/19,9 | 8/18,9 | 11/18,8 | · | · | · |

**CONTROL** (CE/LSR: si el registro se actualiza o se pone a cero):

| origen \ destino | IF | ID | EX | WB | _WR | _CTL |
|---|---|---|---|---|---|---|
| IF | 10/19,4 = | 10/19,5 | · | · | · | · |
| ID | **10/19,4 <** | 11/19,5 = | 10/15,6 | · | · | · |
| EX | 6/19,4 < | 7/19,5 < | 6/15,6 = | · | · | · |
| WB | 6/19,4 < | 7/19,5 < | 6/15,6 < | 2/9,4 = | 4/12,0 | 3/7,7 |
| _WR | 8/19,4 | 8/19,5 | · | · | · | · |
| _CTL | 5/19,4 | 7/19,5 | 6/15,6 | 3/9,4 | 5/12,0 | 3/8,7 |
| _RAM (banco) | 7/19,4 | 7/19,5 | · | · | · | · |

Las LUT son de cada par; la llegada es del destino (nextpnr no da tiempos por
par), así que todas las casillas de una columna que llegan al mismo registro
comparten la cifra. Las LUT no cuentan el ruteo, que aquí es ~70 % del camino.

### Lo que añade la matriz

1. **La lógica de ID es la más profunda: 14 LUT de ID a EX** (la ALU y el salto).
   De EX a WB son 6, y de WB a `_WR`, 0: una copia.
2. **ID manda hacia atrás a IF con 10–11 LUT**, por el dato (el destino del
   salto en `fetch_request_pc`/`imem_address`) y por el control (el enable de
   `if_*`). Confirma, ahora con el origen, que IF llega tarde por ID.
3. **EX y WB también mandan hacia atrás a ID e IF** (6–7 LUT): son `ex_rd`,
   `wb_rd`, `*_valid`… de la detección de riesgos (`hazard_ex`, `hazard_wb`).
4. **`_WR` entra en el cálculo de EX con 12 LUT**: es el adelanto
   `id_live_operand_*` desde `register_write_*`. Es el camino hacia atrás más
   profundo de la lista y confirma que el buffer de escritura alarga el camino
   crítico.
5. **IF entra en EX con 14 LUT**, cuando IF no debería alimentar la ALU: es el
   multiplexor `id_valid ? id_src : if_src` de las direcciones de lectura del
   banco (`cpu.v`, `register_a_address`/`register_b_address`), que sobra con un
   banco de lectura combinacional.

## Estado actual (11 de noviembre)

Después de esta medida se reorganizó `cpu.v`: un `always` por etapa, con un
único dueño para cada registro, y el control en una sola sección. Además:

1. **Sin buffer `_WR`.** WB escribe el banco directamente
   (`register_write_enable = ctl_retire && wb_reg_write`).
2. **Sin adelanto `id_live_operand_*`.** Ahora vendría de WB y no se usaría
   nunca: siempre que un operando coincide con `wb_rd`, `hazard_wb` ya para ID, y
   al ciclo siguiente el banco tiene el valor. El rendimiento es el mismo.
3. **Sin el multiplexor `id_valid ? id_src : if_src`.** El banco se lee con
   `id_src_a`/`id_src_b`; la lectura es combinacional y no hacía falta.
4. **Código muerto fuera**: `ALU_FAST_PATH`, `ctl_halt_pending` (nunca se ponía
   a 1), `ctl_running` (siempre valía `!halted`) y `ex_instruction` (no se leía).

El primer refactor, sin 1–4 pero ya sin `_WR`, bajó a 38,55 MHz: la escritura en
el banco y el adelanto pasaban a depender de `wb_commit`, que mezcla
`halt_request`, `halted` y `ctl_running`. Con 1–4:

| Build | CPU | `clk_mem` | FF | LUT |
|---|---|---|---|---|
| `20261109-161957-904878-stage-attrs` (antes) | 50,30 MHz | 101,3 MHz | — | — |
| `20261111-161933-410949-revisar-refactor` | 38,55 MHz | 95,2 MHz (falla) | — | — |
| `20261111-163257-732443-pasos-1-4` | 54,84 MHz | 116,8 MHz | 12 860 | 17 931 |
| `20261111-165312-596391-paso-5` (solo orden y comentarios) | 51,76 MHz | 110,4 MHz | 12 860 | 17 789 |

Entre los dos últimos la lógica es la misma: la diferencia es lo que mueve
cambiar el orden del fuente en la síntesis y en la colocación con una sola
semilla.

### Por etapa (build `paso-5`)

| Etapa | Antes | Ahora | DATO | ENABLE | Qué domina |
|---|---|---|---|---|---|
| IF | 19,88 | 19,17 | 19,17 | 18,13 | PC siguiente tras salto (dato) y stall (enable) |
| ID | 19,46 | 19,32 | 18,60 | 19,32 | stall (enable de `id_instruction`/`id_pc`) |
| EX | 18,77 | 17,48 | 17,48 | 12,38 | la ALU y el salto (dato de `ex_result`/`ex_next_pc`) |
| WB | 10,36 | 10,69 | 9,55 | 10,69 | — |
| `_CTL` | 8,68 | 9,54 | 7,14 | 9,54 | — |

Lo que mejora de verdad es EX: su ENABLE baja de 15,6 a 12,4 ns y su DATO de
18,8 a 17,5. IF e ID siguen esperando la misma decisión de salto o riesgo.

### Camino crítico (19,32 ns, 70 % ruteo)

```text
id_instruction → ¿es salto? (id_src_a, cpu.v:383) → lectura del banco
→ comparación de 33 bits (id_compare_difference, cpu.v:478) → salto tomado
→ id_redirects_fetch / raw_hazard → enable de id_instruction
```

Es el de antes sin el adelanto: ya no acaba en el PC del fetch sino en el
enable de ID, pero es la misma decisión.

### Matriz (build `paso-5`)

**DATO**:

| origen \ destino | IF | ID | EX | WB | _CTL |
|---|---|---|---|---|---|
| IF | 5/19,2 = | 1/18,6 | · | · | · |
| ID | **12/19,2 <** | 13/18,6 = | **13/17,5** | · | · |
| EX | 7/19,2 < | 7/18,6 < | 8/14,6 = | 4/9,6 | · |
| WB | 8/19,2 < | 8/18,6 < | 9/14,6 < | 4/9,6 = | 2/6,0 |
| _CTL | 6/19,2 | · | 6/14,6 | 4/9,6 | 4/7,1 |
| _RAM (banco) | 8/19,2 | 10/18,6 | 10/17,5 | · | · |

**CONTROL**:

| origen \ destino | IF | ID | EX | WB | _CTL |
|---|---|---|---|---|---|
| IF | 3/18,1 = | · | · | · | · |
| ID | **11/18,1 <** | 13/19,3 = | 9/12,4 | · | · |
| EX | 7/18,1 < | 7/19,3 < | 5/12,4 = | 4/10,7 | · |
| WB | 8/18,1 < | 8/19,3 < | 6/12,4 < | 5/10,7 = | 4/9,5 |
| _CTL | 4/18,1 | 4/19,3 | 3/12,4 | 5/10,7 | 5/9,5 |
| _RAM (banco) | 8/18,1 | 10/19,3 | · | · | · |

Respecto a la del 9 de noviembre:

1. **IF ya no entra en EX** (antes 14 LUT, por el multiplexor de direcciones):
   ahora IF solo alimenta a IF y a ID.
2. **ID → EX baja de 14 a 13 LUT**, y el banco → EX de 11 a 10: es el adelanto
   que ya no está.
3. **Lo que queda hacia atrás es lo propio del diseño**: ID → IF con 11–12 LUT
   (la decisión de salto) y EX/WB → ID/IF con 7–9 (la detección de riesgos).
   Acortarlo pide partir ID en dos (decode + lectura | ALU + salto), que a
   25 MHz no hace falta.

## Cómo repetirlo

```bash
export PATH="$PWD/tools:$PATH"
build --prototype 38 --background                     # o reutilizar el último build
timing-wall -p 38 --clock clk_25mhz --filter cpu_i. --by-register --ports --top 60
timing-wall -p 38 --clock clk_25mhz --filter cpu_i. --stages --ports
timing-wall -p 38 --clock clk_25mhz --filter cpu_i. --stages --stage-matrix
timing-wall -p 38 --clock clk_25mhz --path
```

Después de cambiar `cpu.v`, `timing-wall <build-viejo> --compare <build-nuevo>
--by-register` compara registro a registro. Las cifras cambian con la semilla
de colocación: para conclusiones finas, mirar varias semillas de un
`build-sweep`.
