# Semántica de la ALU

Casos cortos y sin bucles, cada uno centrado en una regla que `1.isa/isa.md`
fija explícitamente y que es fácil implementar mal.

| Caso | Regla que valida |
|---|---|
| [logic-immediates](logic-immediates/) | `ANDI`/`XORI`/`ORI` extienden el inmediato con **ceros**, no con signo |
| [shift-amount](shift-amount/) | `SHL`/`SHR`/`SAR` usan solo los **cinco bits bajos** de `Rb`; `SAR` replica el signo y `SHR` no |
| [unsigned-branches](unsigned-branches/) | `BLTU`/`BGEU` comparan **sin signo**, al contrario que `BLT`/`BGE` |
| [multiply](multiply/) | `MUL` básico |

Los tres primeros están construidos para que un error de signo cambie el
resultado: usan `0xFFFFFFFF`, `0x80000000` y desplazamientos de 32 y 33, es
decir los valores donde las dos interpretaciones posibles divergen.
