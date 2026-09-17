- ~~Revisar que el monitor del 19 tenga todos los comandos write-word, read-word, memory-monitor parece q no estan.~~
  Revisado. `read-word` y `memory-test` SI estaban; lo que fallaba era que solo
  `read-byte`/`write-byte` podian apuntar al MMIO, y el resto de comandos iba por
  un tope de 32 MiB que solo describe la SDRAM. Arreglado en 16/18/19/21
  (`parse_address`), junto con el mensaje de "hay que parar la CPU" y el texto de
  `send` que empieza por guion.
  - `write-word` IMPLEMENTADO, pero **solo en la 19** y a proposito: comando
    `0x13` en `monitor.v`, `mem_write_word`/`mem_write_word_enable` en el
    adaptador, `WordWriteMixin` en `tools/monitor_protocol.py`. Se hizo en una
    sola carpeta para probarlo antes de tocar las diez copias de `monitor.v` y
    los diez bitstreams.
    - Dos cosas que decidir antes de propagarlo:
      1. **La version no subio.** El mayor codifica el juego de comandos (1 =
         base, 2 = base+serie), asi que dos placas que contestan `2.19` pueden
         responder a comandos distintos. Mientras dure, quien lo distingue es
         la capacidad `write_word` de `tools/capabilities.json`, que mira el
         RTL. Al propagarlo habria que numerarlo bien (3 y 4).
      2. `x.tests/test_monitor_port.py` lleva la 19 fuera de la comparacion de
         copias identicas, acotada por `monitor_write_word.diff`. Al propagarlo
         se borran la excepcion, el .diff y el test que lo compara.
    - Lo que NO arregla: la velocidad de `write-block`. Medido en placa, una
      ida y vuelta cuesta **16 ms fijos** por el latency timer del FTDI (un
      `ping` de dos bytes tarda igual que un bloque de 256), y `write-block` ya
      manda sus 256 bytes en un solo viaje. Lo que baja es escribir un registro
      suelto: de cuatro viajes a uno.

- Si se quiere que `write-block` vaya de verdad mas rapido, el camino es otro y
  no es RTL: bajar el latency timer del FTDI de 16 ms a 1 ms en el driver de
  Windows (~10x directo) y subir `MAX_BLOCK_SIZE` por encima de 256 --el campo
  de longitud del protocolo ya es de 16 bits, el limite esta en el cliente y en
  el bufer de `monitor.v`.

- - -

   - Analizar los md del repositorio y ver si hay una estructura comun repetible para cada prototipo.
- Por ejemplo un README principal que explique las caracteristicas del prototipo y su implementacion.
- Dentro de docs:
    - timing.md: si se ha estado mejorando la ruta critica para mejorar el Fmax, explicar los diferentes cambios y como han afectado al timing.
    - log.md: si hay temas historicos del prototipo, dejar en README el estado final/actual (por 
    ejemplo a nadie le interesa saber ya que en algun momento R0 no estaba fijado a 0) y si la historia o evolucion es relevante, dejarla en log.md.
    - identificar si hay algun archivo comun que se repita o se pueda repetir en todos los prototipos.
- Es muy importante que el README quede interesante y entendible. No hace falta que aparezcan historias
o decisiones que se han tomado. Deberia explicar que hace y como lo hace, la vida y la obra pues si es
interesante en log.md.

--------------

Desde la raíz del repositorio, en **PowerShell**, usaría esta secuencia. No he ejecutado las pruebas ni las síntesis.

**1. Bancos de las diez carpetas y `x.tests`**

```powershell
$prototipos = @(6, 10, 12, 14, 16, 17, 18, 19, 21, 22)

foreach ($p in $prototipos) {
    & .\tools\test.ps1 --prototype $p --full
    if ($LASTEXITCODE -ne 0) { throw "Fallaron los tests del prototipo $p" }
}

& .\tools\run-tests.ps1
if ($LASTEXITCODE -ne 0) { throw "Falló x.tests" }
```

`--full` incluye el banco lento de la 22. `run-tests` ejecuta los tests unitarios y los casos con el simulador GPU por defecto. Para añadir los otros dos motores:

```powershell
.\tools\run-tests.ps1 -- --backend cpusim
.\tools\run-tests.ps1 -- --backend gpusim-cycle
```

**2. Síntesis de las diez, en segundo plano**

Lánzalas por tandas según la RAM disponible; cada comando arranca un proceso independiente:

```powershell
foreach ($p in $prototipos) {
    & .\tools\build.ps1 --prototype $p --label pre-mmio-errors --background
    if ($LASTEXITCODE -ne 0) { throw "No se pudo lanzar la síntesis de $p" }
}
```

Consultar el estado:

```powershell
foreach ($p in $prototipos) {
    & .\tools\build-status.ps1 --prototype $p
}
```

Inspeccionar una síntesis concreta:

```powershell
.\tools\build-log.ps1 --prototype 19 --lines 80
.\tools\build-log.ps1 --prototype 19 --follow
```

Antes de pasar a placa, comprueba que las diez terminaron correctamente y cumplieron timing. Que el lanzamiento en segundo plano devuelva éxito no significa que la síntesis haya pasado.

**3. Ronda de placa, secuencial**

Con la placa conectada, tras terminar las síntesis:

```powershell
foreach ($p in $prototipos) {
    & .\tools\board-upload.ps1 --prototype $p --rebuild -y
    if ($LASTEXITCODE -ne 0) { throw "Falló la carga de $p" }

    & .\tools\board-info.ps1 --prototype $p
    if ($LASTEXITCODE -ne 0) { throw "Identidad incorrecta en $p" }

    & .\tools\test-board.ps1 --prototype $p --no-upload
    if ($LASTEXITCODE -ne 0) { throw "Fallaron las pruebas de placa de $p" }
}
```

`--rebuild` fuerza `apio upload` aunque coincida la versión: necesitamos cargar el RTL actual, porque la identidad no distingue dos builds de la misma carpeta. El puerto FTDI se detecta automáticamente; puedes añadir `--port COM3` a los tres comandos si corresponde.

**Estos comandos cubren la regresión general, pero no bastan para cerrar toda la ronda específica del documento.** Quedan por comprobar expresamente en placa `SYS_ID`, `READ_WORD` en 10/16 y los cambios de la fase 3.5 —contadores, `VIDEO_CTRL` y bases de framebuffer—. No marcaría esa casilla como terminada solo porque `test-board` pase.