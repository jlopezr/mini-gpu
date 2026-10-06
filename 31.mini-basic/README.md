# mini-basic

Un BASIC con interfaz tipo QBasic: el intérprete de `../28.basic` y la TUI de
`../z.tui`, sin copiar nada de ellos.

```text
 File  Run
┌───────────────────── Untitled ─────────────────────┐
│10 REM Guess the number                             │   programa (editor)
│...                                                 │
├──────────────────── Immediate ─────────────────────┤
│Your guess: 37                                      │   salida de la ejecución
│Got it in 3 tries                                   │
│PRINT N*2                                           │
│6                                                   │
│                                                    │   línea para escribir
└────────────────────────────────────────────────────┘
 F5 Run  F6 Window  F10 Exit                  Ln 1, Col 1
```

- **F5** (o `RUN` en la ventana inmediata): el texto del editor se carga entero
  (`mb_program_load_text`) y se ejecuta. Si una línea no compila, el cursor salta
  a ella; si falla al ejecutarse, salta a la línea del programa con ese número.
- **Esc** para un programa en marcha.
- **F6** pasa del editor a la línea de la ventana inmediata y viceversa.
- La línea inmediata ejecuta sentencias sueltas contra las variables del último
  `RUN` (`PRINT N*2`), más `NEW` y `LIST`. Las líneas con número solo valen en el
  editor.
- `INPUT` pide la respuesta en esa misma línea.
- F10 sale.

## Cómo cede tiempo el intérprete

El bucle principal alterna `mb_run_step(..., 200)` (200 sentencias) con
`tui_poll_event` (mira el teclado sin esperar) y `tui_draw_pending` (repinta solo
lo que cambió). Un `GOTO 10` infinito no congela nada. Un `INPUT` sin respuesta
devuelve `MB_WAITING_INPUT`, y entonces el bucle espera de verdad a una tecla.
Detalles en el README de `28.basic`.

## Compilar

Desde un entorno de MSVC (consola VT de Windows):

```powershell
nmake /f Makefile.msvc
.\mini-basic.exe
```

## Probar sin terminal

`test/console_script.c` es un backend de consola con teclas guionizadas
(`MB_SCENARIO=1..3`): corre la aplicación, y al agotarse las teclas imprime la
pantalla. Cubre ejecución con `INPUT`, Esc y un error con su línea.

- F1 (menú Help) abre la ventana About; OK o Esc la cierran.

## MiniCPU (prototipo 30)

```powershell
nmake /f Makefile.msvc mini       # con vcvars32.bat; deja _build\mb_mini.bin
nmake /f Makefile.msvc mini-run   # la sube a la placa
```

`mb_unity_mini.c` agrupa la TUI, la consola MMIO, el intérprete y la aplicación
en una unidad (mini-lcc no enlaza). El `.bin` ocupa unos 149 KB, sobre todo por
los buffers estáticos (que van como ceros dentro del fichero), y la RAM de la 30
sobra. El teclado es el de INPUT (`monitor.py input`): por la UART no llegan
F5/F6/F10. `test/mini_input_guess.txt` es un guion para `cpusim --keyboard
--input-script` que pulsa F5 y responde al `INPUT`; en el simulador el programa
de ejemplo se ejecuta entero, con el scroll de la ventana de salida.

## Pendiente

- Abrir/guardar ficheros.
- Medir en la placa cuánto cuesta el repintado y qué `SLICE` conviene.
- Números de línea opcionales (cuando se toque el intérprete).
