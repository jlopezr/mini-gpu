# `fb-desalineada`

## Objetivo

Una base de framebuffer desalineada es **error**, no se trunca (`mmio.md` §9.2).

## Comportamiento esperado

- El programa escribe en `FB_BACK` una dirección alineada a 4 pero **no** a 16:
  justo la diferencia que la v1 se tragaba en la CPU y la GPU no.
- Existe porque la comprobación se le cayó a dos casos a la vez. En la v1,
  `video-registers` y `shared-double-buffer` escribían `FB_BACK` con los dos bits
  bajos a uno y comprobaban que el hardware los ignoraba. La v2 convirtió esa
  escritura en un fallo de acceso, y un programa no puede comprobar su propio
  fallo: al quitarla de los dos, el alineamiento se quedaba sin probar.
- Merece caso propio porque el truncamiento silencioso **no** era igual en las dos
  familias (4 bytes en la CPU, 16 en la GPU), así que el mismo programa dibujaba
  bien en una placa y torcido en la otra sin que nada lo dijera. De ahí que corra
  en las dos.

## Qué comprueba el `test.json`

- Parada con error: `error_code = 0x02`, sin `underflow`.
- `requires: ["video"]`.

Contexto: [README de la categoría](../../README.md).
