# Modelo de ciclos del SM

Modelo de microarquitectura para explorar cambios en el cauce de `gpu_sm.v`
**sin escribir RTL**. Carpeta aparte a propósito: `11.gpu-sim-func` es un
simulador funcional, hace su trabajo y no se toca. Este importa aquel para
ejecutar la ISA y solo decide **qué warp avanza y cuánto cuesta**.

## Para qué

Las preguntas que dejó abiertas `22.fpga-gpu-bl8/profiling.md` son todas de
parámetros, y en RTL cada una cuesta una reescritura más diez minutos de
simulación:

- ¿cuántos warps hacen falta para llenar un cauce de N etapas sin burbujas?
- ¿cuál es la ocupación real de la etapa de ejecución, que fija el techo?
- ¿cuánto ganaría de verdad la propuesta de `22.fpga-gpu-bl8/sm-pipeline.md`?

## El contrato: validar antes de predecir

**Un modelo que no reproduce el diseño actual no puede decir nada creíble sobre
uno que no existe.** `validate.py` lo contrasta contra las cifras medidas en
RTL, y mientras no cuadren, los números del modo `pipelined` son ficción.

```
python validate.py                 # contra el diseno actual
python validate.py --model pipelined
```

No es una precaución retórica. En esta misma línea de trabajo, un generador de
tráfico sintético dio +37% donde el cliente real daba +29%, y un banco de
pruebas "verificaba" el vídeo sin comprobar a qué dirección leía.

## Estado: validado

Contra `gpu_calib_tb.v` sobre `examples/plasma_nommio.asm`, un frame:

| Magnitud | Modelo | RTL | Error |
| --- | --- | --- | --- |
| `retired` | 151 880 | 151 880 | **exacto** |
| `lane_ops` | 1 215 040 | 1 214 976 | +0,005% |
| `lsu_tx` | 9 600 | 9 600 | **exacto** |
| `cycles` | 2 480 048 | 2 678 274 | −7,4% |

El flujo de instrucciones y el modelo de coalescencia salen exactos. Los ciclos
quedan **un 7,4% optimistas**, así que las predicciones hay que leerlas con ese
sesgo: el modelo va a decir siempre algo mejor de lo que dará el RTL.

El 1,3 ciclos por instrucción que faltan son, por orden de sospecha: las
vueltas extra de `RECON` al desapilar, el ciclo de `PICK` que consume cada
respuesta de la LSU, y el coste del `BAR`.

### Dos trampas que costó descubrir

1. **El programa tiene que ser el mismo en los dos lados.** `plasma.asm` accede
   al MMIO y el simulador funcional no tiene esa ventana —ni debe tenerla—, así
   que el modelo abortaba con `ERROR_MEMORY_ACCESS` en `pc=0xdc` y medía un
   recorrido distinto. **Fallaba produciendo números en vez de un error**, que
   es la peor manera. De ahí `plasma_nommio.asm`.

2. **Calibrar no es ajustar.** La primera versión suponía 3 ciclos de ejecución
   y daba −30%. En vez de subir la constante hasta que cuadrara, conté los
   estados de `gpu_lane.v` desde `step_request`:
   `HALTED → FETCH_REQUEST → FETCH_WAIT → DECODE → EXECUTE → RETIRE`, seis. Con
   el número derivado del RTL el error bajó a −7,4%.

## Lo que ya ha dicho

`python validate.py --model pipelined`, sobre la propuesta de
`22.fpga-gpu-bl8/sm-pipeline.md`:

| | Actual | Segmentado | |
| --- | --- | --- | --- |
| Ciclos/frame | 2 211 672 | 721 750 | **3,1×** |
| Ciclos por instrucción | 14,56 | 4,75 | |
| Utilización de las ALU | 6,87% | 21,04% | |
| Burbujas sin warp | 0 | 38 ciclos | |
| Ocupación de `X` | — | **77,0%** | |

Dos conclusiones que no se veían sin medir:

- **Son ~3×, no el 5-6× que se estimó a ojo.** Con el front-end segmentado el
  cuello pasa a `X`, ocupada el 77%, porque dura 4 ciclos: los de la lane. El
  fetch redundante que tenía dentro **ya está quitado** (predicho −11,9%,
  medido en RTL −11,2%), y el siguiente paso —colapsar `HALTED` y `RETIRE`,
  que duplican etapas del propio cauce— llevaría `X` a 2 y el CPI a 2,82.
  Razonado instrucción a instrucción en `22.fpga-gpu-bl8/sm-pipeline.md`.
- **Ocho warps sobran.** 38 ciclos de burbuja en todo un frame. No hace falta
  subir el número de warps, que era una de las preguntas abiertas.

La columna "Actual" está **validada contra la placa**: `profile.py` mide 15,6
ciclos por instrucción y el modelo predijo 15,66.

## Limitación conocida

El simulador funcional ejecuta los accesos a memoria al instante, así que este
modelo les pone la latencia **por encima**, sin modelar el reordenamiento real
entre warps. Para cargas donde cada hilo escribe sus propias palabras —todas
las que hay hoy— da igual. Para un programa con warps que se pisen en memoria,
no serviría.