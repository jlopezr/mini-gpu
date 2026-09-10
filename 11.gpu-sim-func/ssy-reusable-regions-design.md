# SSY: regiones reutilizables y dos pilas SIMT

## Estado y alcance

Propuesta de semántica e implementación para MiniGPU, basada en lo acordado
durante el análisis de Mandelbrot. **Este documento no modifica el simulador
ni el RTL.** Describe una variante de la semántica 3: regiones reutilizables,
cierre automático y almacenamiento separado de regiones y caminos pendientes.

No añade instrucciones a la ISA. En particular, no necesita SYNC. Sí cambia
el significado de SSY y el tratamiento de las divergencias respecto al código
actual, que reserva una entrada en cada SSY y permite una divergencia por entrada.

La regla central es:

> SSY establece una región de reconvergencia. Reejecutar el SSY de la región
> abierta más interna la reutiliza. Las divergencias pueden añadir caminos
> pendientes, pero las lanes que llegan directamente al join solo esperan.

**Una región ocupa almacenamiento incluso si ninguna rama diverge.** La regla
«solo reservar cuando hay divergencia» se aplica a PATH, no a REGION. Además,
una divergencia con salida directa al join tampoco necesita PATH.

## 1. Modelo de ejecución

Cada warp tiene un único PC compartido. Solo las lanes de `active_mask`
ejecutan la instrucción de ese PC. `live_mask` indica las lanes que no han
terminado mediante EXIT o HALT de la ISA.

Una lane aparcada en un join no tiene un PC independiente ni ejecuta código
allí: está desactivada hasta la reconvergencia. Sus registros permanecen intactos.

Hay dos clases de estado pendiente:

- **REGION:** recuerda dónde y con qué lanes reconverger.
- **PATH:** recuerda instrucciones que todavía debe ejecutar un subconjunto.

El orden de ejecución es en profundidad. Cuando ambos caminos de una rama
divergente tienen trabajo antes del join, se ejecuta primero el fall-through
y se guarda el camino tomado.

## 2. Estructuras por warp

Se consideran PCs completos de 32 bits y ocho lanes por warp. Las pilas se
dimensionan por separado; para concretar el diseño se proponen ocho posiciones
en cada una. Esto no equivale a ocho posiciones compartidas.

### Estado activo

| Campo | Bits | Significado |
|---|---:|---|
| `pc` | 32 | PC compartido actual |
| `active_mask` | 8 | Lanes que ejecutan la instrucción actual |
| `live_mask` | 8 | Lanes que todavía no han terminado |
| `region_count` | 4 | Número de regiones, de 0 a 8 |
| `path_count` | 4 | Número de caminos pendientes, de 0 a 8 |

### Pila de regiones

| Campo de REGION | Bits | Significado |
|---|---:|---|
| `ssy_pc` | 32 | Dirección del SSY que abrió la región |
| `join_pc` | 32 | Dirección donde reunir sus lanes |
| `entry_mask` | 8 | Máscara activa original al abrirla |
| `path_base` | 4 | Profundidad de caminos en el momento de apertura |

Son **76 bits por región**. No hay campo `used`: la región admite múltiples
divergencias. Reutilizarla no cambia ninguno de sus cuatro campos.

### Pila de caminos

| Campo de PATH | Bits | Significado |
|---|---:|---|
| `pending_pc` | 32 | PC por el que empezar el camino pendiente |
| `pending_mask` | 8 | Lanes que deben ejecutarlo |

Son **40 bits por camino**. No guarda un join ni un identificador de región:
el anidamiento y `path_base` proporcionan esa asociación.

Al abrir una región interior, todos los PATH ya existentes quedan por debajo
de su `path_base`. Solo los añadidos por encima pertenecen a su ejecución.
La región interior se cierra antes de atender los caminos de la exterior.

### Capacidad conceptual

```text
8 REGION × 76 bits = 608 bits
8 PATH   × 40 bits = 320 bits
Pilas             = 928 bits por warp
Dos contadores    =   8 bits por warp
```

Se añaden el PC, las máscaras activas y el resto del estado ya existente del
warp. Estos son bits lógicos, no una estimación de recursos físicos sintetizados.
Con profundidad parametrizable, los contadores y `path_base` necesitan
`ceil(log2(capacidad + 1))` bits, cada uno según la pila que cuenta.

## 3. Semántica de SSY

El destino mantiene la codificación actual: desplazamiento signed de 26 bits
en palabras desde PC+4, con resultado arquitectónico de 32 bits.

1. Calcular y validar el destino, incluida alineación y memoria accesible.
2. Si existe una región superior y su `ssy_pc` coincide con el PC actual,
   **reutilizarla sin hacer push**.
3. En otro caso, comprobar capacidad y añadir una REGION con la máscara activa
   y la profundidad de caminos actuales.
4. Avanzar PC y normalizar antes de ejecutar otra instrucción.

La reutilización conserva la máscara original, incluso si ahora solo hay una
lane activa. También conserva `path_base` y todos los caminos pendientes.
Es válida aunque la pila de regiones esté llena: no necesita otra posición.

### Qué significa «la misma región»

La identidad es el **PC del SSY de la región abierta más interna**. No basta
con tener el mismo join. Tampoco se busca una coincidencia más abajo en la pila.

- Mismo SSY que el top: reutilización.
- SSY distinto, aunque comparta join: nueva región.
- Mismo SSY que una región exterior, con otra región todavía encima: no reutiliza
  la exterior; aplica la regla de apertura nueva, sujeta al contrato estructurado.

Esta es una definición de la ISA, no una inferencia de la intención del programa.
Reentrar en el SSY superior no puede usarse para pedir otro nivel recursivo de
la misma región. Ese uso necesitaría otra forma de expresar la apertura.

Para cerrar el caso de código modificado durante una región abierta, se propone
rechazar con error SIMT una reutilización cuyo destino ya no coincida con el
`join_pc` guardado. Nunca se cambia el join de una región en curso.

## 4. Semántica de branches

La uniformidad se mide sobre las lanes activas. Otras lanes pueden estar
aparcadas o pendientes. Una sola lane activa no puede divergir.

La decisión se toma por **PC siguiente efectivo**: si el destino de la rama
es PC+4, no existe divergencia aunque los predicados difieran.

### Branch uniforme

Actualizar PC al único destino efectivo. No abrir, cerrar ni reservar entradas
por el hecho de evaluar el branch. Después normalizar: si ese destino es el
join actual, puede atender pendientes o cerrar regiones.

Un branch uniforme no necesita una región. BRA tampoco necesita SSY.

### Branch divergente

Debe existir una región abierta; de lo contrario se produce error SIMT.
Se usa el join `J` de la región superior. Sean `T` la máscara tomada y `F`
la máscara fall-through, ambas no vacías:

| Destinos | Acción |
|---|---|
| Destino tomado = J | Aparcar T; continuar en PC+4 con F; no añadir PATH |
| PC+4 = J | Aparcar F; continuar en destino tomado con T; no añadir PATH |
| Ningún destino = J | Añadir PATH con destino tomado y T; continuar en PC+4 con F |

El caso en que ambos destinos son J ya es uniforme y se resuelve antes.

Aparcar una máscara significa retirarla del estado activo. No cambia
`live_mask` y no necesita una lista separada de llegadas: `entry_mask` permite
recuperar esas lanes cuando se cierre la región.

La omisión de PATH para una salida directa al join forma parte del contrato,
incluida la capacidad observable. No es una optimización opcional del RTL.

## 5. Cuándo se añaden y se eliminan entradas

### Regiones

| Evento | Acción sobre la pila de regiones |
|---|---|
| SSY distinto del SSY superior, o pila vacía | Push REGION |
| Repetición del SSY superior | Ninguna; reutilizar sin reiniciar |
| Branch uniforme o divergente | Ninguna reserva REGION |
| Llegada al join con PATH propios pendientes | Conservar REGION |
| Llegada al join sin PATH propios pendientes | Pop REGION; restaurar su máscara viva |
| Camino activo agotado por EXIT, con PATH propios pendientes | Conservar REGION y activar pendiente |
| Camino activo agotado por EXIT, sin PATH propios pendientes | Pop REGION; restaurar su máscara viva en el join |
| Todas las lanes terminadas | Vaciar ambas pilas |

### Caminos

| Evento | Acción sobre la pila de caminos |
|---|---|
| Branch uniforme | Ninguna |
| Divergencia con uno de sus destinos directamente en el join | Ninguna; aparcar esas lanes |
| Divergencia con trabajo en ambos caminos | Push PATH para el tomado |
| Camino activo alcanza el join y queda PATH de esa región | Pop PATH; empezar a ejecutarlo |
| Camino activo termina mediante EXIT y queda PATH de esa región | Pop PATH; empezar a ejecutarlo |

**Eliminar un PATH significa seleccionarlo para ejecutarlo**, no haber terminado
su trabajo. Su PC y su máscara pasan al estado activo del warp.

## 6. Normalización y reconvergencia

Se normaliza después del commit de una instrucción y antes del siguiente fetch.
La instrucción del join no se ejecuta hasta terminar esa normalización.

Para la región superior:

```text
path_count > REGION.path_base
    Hay un camino pendiente de esta región.
    Retirarlo y cargar su PC y su máscara filtrada por live_mask.

path_count == REGION.path_base
    No quedan caminos pendientes de esta región.
    Retirarla, ir a su join y restaurar entry_mask & live_mask.
```

Solo se inicia este proceso al llegar al join actual o al quedar vacía la
máscara activa. Se repite si aparecen máscaras vacías o joins coincidentes.
No se cierra una región simplemente porque no tenga PATH: todavía puede estar
ejecutándose su camino activo.

EXIT y HALT de la ISA retiran las lanes activas de `live_mask`. No deben volver
a activarse al restaurar una región. Si no queda ninguna lane viva, se vacían
ambas pilas y se termina el warp; para este diseño el PC final conserva el
PC siguiente de la instrucción que retiró las últimas lanes.

BAR mantiene su regla de máscara completa respecto a `live_mask`. En un join
se normaliza antes de evaluar BAR. SSY no es una barrera entre warps.

## 7. Pseudocódigo del controlador

Pseudocódigo independiente del formato físico de RAM. `R` y `P` son pilas
LIFO; `top`, `push` y `pop` operan sobre su extremo superior. Las comprobaciones
que puedan fallar se realizan antes del commit de la instrucción.

```text
execute_ssy(offset):
    J = u32(pc + 4 + sign_extend(offset, 26) * 4)
    validate_address(J)

    if not R.empty() and R.top.ssy_pc == pc:
        require(R.top.join_pc == J, ERROR_SIMT)
        # No modificar entry_mask, path_base ni P.
    else:
        require(R.count < REGION_DEPTH, ERROR_SIMT)
        R.push(REGION(pc, J, active_mask, P.count))

    pc = u32(pc + 4)
    retire_instruction()
    normalize()


execute_branch(taken_mask, target):
    F_pc = u32(pc + 4)
    T = taken_mask & active_mask
    F = active_mask & ~T

    if target == F_pc or T == 0 or F == 0:
        pc = target if T != 0 else F_pc
    else:
        require(not R.empty(), ERROR_SIMT)
        J = R.top.join_pc

        if target == J:
            pc = F_pc
            active_mask = F
        elif F_pc == J:
            pc = target
            active_mask = T
        else:
            require(P.count < PATH_DEPTH, ERROR_SIMT)
            P.push(PATH(target, T))
            pc = F_pc
            active_mask = F

    retire_instruction()
    normalize()


normalize():
    if live_mask == 0:
        R.clear()
        P.clear()
        active_mask = 0
        finish_warp()
        return

    while not R.empty():
        region = R.top

        if active_mask != 0 and pc != region.join_pc:
            return

        assert P.count >= region.path_base

        if P.count > region.path_base:
            path = P.pop()
            pc = path.pending_pc
            active_mask = path.pending_mask & live_mask
        else:
            region = R.pop()
            pc = region.join_pc
            active_mask = region.entry_mask & live_mask

    assert P.empty()
    require(active_mask != 0, ERROR_SIMT)
```

La validación de codificación y direcciones de branch sigue la ISA y no se
repite completa en este pseudocódigo. Las aserciones representan invariantes
internos: no sustituyen una comprobación de capacidad antes de un push.

## 8. Esquema de implementación RTL

Por warp se necesitan los arrays REGION y PATH y dos contadores. No hace falta
un registro de preparación SSY ni una búsqueda asociativa por toda la pila.
La comparación de reutilización consulta solo `R[region_count-1].ssy_pc`.

Una división sencilla del controlador sería:

1. **RECON:** comprobar terminación, máscara vacía y join del top. Hacer como
   máximo un pop por ciclo y permanecer aquí mientras haya que normalizar.
2. **FETCH/DECODE:** obtener y validar la instrucción. Para SSY, decidir si
   reutiliza o necesita capacidad REGION antes de escribir.
3. **EXEC:** obtener resultados o máscaras del branch, sin commit prematuro.
4. **COMMIT:** aplicar el cambio validado, reservar PATH si corresponde y
   retirar la instrucción. Volver a RECON antes de ejecutar otra instrucción.

Si las pilas se implementan en memoria síncrona, las lecturas del top requieren
los estados de espera correspondientes. No se presupone acceso combinacional
ni que una normalización completa quepa en un ciclo.

Los pops de reconvergencia no cuentan como instrucciones retiradas. En pausa
o depuración se conservan ambos contadores, las pilas y el estado activo; el
avance paso a paso debe resolver RECON antes de ejecutar la siguiente instrucción.

## 9. Ejemplos de estado

### Bucle con SSY interior y dos lanes

```asm
    GETTID R1
    ADDI   R1, R1, 100
    MOVI   R2, 0
    MOVI   R4, 128

loop:
    SSY    done
    BGE    R2, R4, done
    BGE    R2, R1, done
    ADDI   R2, R2, 1
    BRA    loop

done:
    ADDI   R3, R2, 0
    EXIT
```

Un warp con solo lanes 0 y 1 activas comienza con máscara `11`:

| Momento | Máscara activa | Regiones | Caminos | Acción |
|---|---|---:|---:|---|
| Primer SSY | 11 | 1 | 0 | Capturar `entry_mask=11`, `path_base=0` |
| Vueltas uniformes | 11 | 1 | 0 | Reutilizar el mismo SSY |
| R2=100: sale lane 0 | 10 | 1 | 0 | Destino directo a done; aparcar lane 0 |
| SSY de la siguiente vuelta | 10 | 1 | 0 | Conservar `entry_mask=11`, no sustituirla por 10 |
| R2 de lane 1=101: sale lane 1 | 10 | 1 | 0 | Branch uniforme hacia done |
| Normalización en done | 11 | 0 | 0 | Pop REGION y reunión |

La copia a R3 produce `[100, 101]`. El ejemplo del Mandelbrot original se
beneficia de las mismas reglas: sus salidas apuntan directamente al join y
reejecuta el SSY de la región más interna.

### If/else con trabajo en ambos caminos

```text
Tras SSY:             R=[exterior(base=0)]      P=[]
Tras divergencia:     R=[exterior(base=0)]      P=[B]
Ejecutando A:         R=[exterior(base=0)]      P=[B]
A llega al join:      R=[exterior(base=0)]      P=[]    ejecutar B
B llega al join:      R=[]                     P=[]    reunir
```

### Región anidada mientras B está pendiente

```text
Exterior ejecuta A:   R=[exterior(base=0)]                P=[B]
A abre interior:     R=[exterior(base=0), interior(base=1)] P=[B]
Interior diverge:    R=[exterior(base=0), interior(base=1)] P=[B, D]
```

Al llegar al join interior, se ejecuta D. Cuando vuelve a ese join,
`P.count == 1 == interior.path_base`: se cierra la interior, **sin ejecutar B**.
B solo se selecciona cuando la ejecución exterior alcanza su propio join.

## 10. Casos límite y restricciones

| Caso | Regla |
|---|---|
| Pila REGION llena y SSY reutilizable | Permitido; no hay push |
| Pila REGION llena y apertura nueva | Error SIMT antes de modificar estado |
| Pila PATH llena y branch uniforme | Permitido |
| Pila PATH llena y salida directa al join | Permitido; no necesita PATH |
| Pila PATH llena y dos caminos con trabajo | Error SIMT antes de cambiar PC, máscaras o pila |
| Divergencia sin región | Error SIMT |
| Dos SSY distintos con el mismo join | Dos regiones; no se fusionan |
| Joins interiores y exteriores iguales | Normalización repetida, en orden LIFO |
| SSY con join en PC+4 | Abrir y cerrar antes del siguiente fetch; una apertura nueva exige capacidad igualmente |
| Región uniforme que nunca alcanza el join | Permanece abierta; repetir su SSY no la cierra |
| Todas las lanes hacen EXIT | Vaciar pilas y terminar sin reactivar lanes |
| Destino SSY inválido y pila llena | Validar destino primero, para una prioridad de fallo determinista |

Los caminos deben llegar al join de su región o finalizar sus lanes, respetando
las regiones interiores. Un salto al join exterior no descarta automáticamente
una región interior abierta. Un continue puede usar la cola común de la vuelta;
un break interior puede expresarse con una marca y comprobarse después del
cierre interior.

Sin metadatos de control, no se garantiza detectar inmediatamente todos los
saltos que violen estas restricciones. Los programas fuera de ese contrato no
tienen garantizada una reconvergencia correcta. Tampoco se garantiza progreso
si un camino no termina ni llega a su join.

## 11. Invariantes y validación para una implementación futura

Invariantes que conviene comprobar en el simulador y mediante assertions RTL:

- `active_mask` siempre es subconjunto de `live_mask`.
- La ejecución activa pertenece a la máscara de entrada viva de la región superior.
- Cada `path_base` es menor o igual que `path_count`; las bases de regiones
  anidadas son no decrecientes.
- Sin regiones no quedan PATH pendientes.
- Las máscaras de caminos pendientes vivos son disjuntas entre sí y de la activa.
- Reutilizar SSY nunca reemplaza la máscara original ni pierde pendientes.
- Un pop PATH no cierra por sí mismo una REGION.
- Ningún push que desborde produce commit parcial.

Casos mínimos de validación:

1. Bucle anterior con límites 100 y 101: una REGION, cero PATH y resultados correctos.
2. Repetir SSY con máscara reducida: al cerrar se recuperan las lanes aparcadas.
3. If/else con ambos caminos útiles: un PATH, recorrido fall-through primero.
4. Dos divergencias antes del mismo join, con destinos pendientes diferentes.
5. Región interior con pendientes exteriores: comprobar la frontera `path_base`.
6. Dos SSY distintos que comparten join, y repetición del SSY superior con PATH pendientes.
7. Fall-through igual al join y branch cuyo destino coincide con PC+4.
8. EXIT en primer camino, en pendiente, en ambos y dentro de una región interior.
9. Overflow separado de REGION y PATH, y reutilización o salida directa con pila llena.
10. BAR en join, máscara parcial y terminación completa del warp.
11. Comparación de simulador y RTL con ambos Mandelbrot y sus framebuffers esperados.

Estos son criterios de aceptación propuestos, **no pruebas ya ejecutadas de
esta semántica**. La implementación requerirá actualizar simulador, RTL,
documentación ISA, diagnóstico de pilas y tests de conformidad conjuntamente.
