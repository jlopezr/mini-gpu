# Mehjorar plasma
1. jMrar desplazamientos?

M
. plasma.asm hace por palabra: SHL por 11 (×2 píxeles), por 5 (×2) y por 16 = 48 ciclos solo desplazando. Fue mala elección mía, escribí el efecto como si los 
shifts fueran de un 2. ciclo.

Per2. o seamos honestos con la aritmética: 48 ciclos repartidos entre ~34 instrucciones son 1,4 de los 20,5 ciclos por instrucción. No es el término dominante. 
El resto sale de la estructura: la lane recorre FETCH_REQUEST → FETCH_WAIT → DECODE → EXECUTE → RETIRE, y mi gpu_imem_buffer añade su propio ida y vuelta 
(S_IDLE → S_FETCH → S_RESP) incluso cuando el buffer acierta. Eso son ~9-10 ciclos por instrucción antes de ejecutar nada. Los otros ~10 no los tengo 
desglosados — no te los voy a inventar; haría falta instrumentar el SM.
3. Homogeneizar contadores de rendimiento
4.Homogeneizar MMIO: 