#!/usr/bin/env python3
"""Ventana de pantalla de un simulador: lo que saldría por HDMI, y la entrada.

Es un proceso aparte, por lo mismo que `fb_window.py`: Tk quiere su bucle de
eventos en el hilo principal y cerrar la ventana no puede tumbar al simulador ni
al depurador. Lo usan los dos.

    screen_window.py FUENTE.hex [--input] [--scale N]
    screen_window.py --panel --input [--scale N]

Por `stdin`, una línea JSON por refresco (el framebuffer en Base64):

    {"screen": {"mode": 2, "fb": "YQhhCGE...", "text": [..2400..], "palette": [..256..]},
     "title": "PC=0x40 instr=120"}

`tools/screen.py` explica qué se dibuja según `mode`, `fb` y `text`. Por
`stdout`, un JSON por línea:

    {"event": "keys", "pressed": [4, 225]}              con --input: teclas pulsadas
    {"event": "mouse", "buttons": 1, "dx": 3, "dy": -2}  con --input: botones y movimiento
    {"event": "interrupt"}                               F12
    {"event": "error", "message": "..."}

`keys` y `mouse` son reports de estado completo, los de `InputDevice`: la
traducción de Tk a teclas físicas HID está en `tools/host_input.py`. Con
`--input` las teclas van al programa; sin él, la ventana solo muestra.

Con `--panel` no hay pantalla que dibujar --no hace falta fuente-- sino un panel
informativo que captura teclado y ratón igual que la ventana normal. Es lo que
usa `monitor.py input`: la imagen la enseña el HDMI de la placa, y leer el
framebuffer por UART costaría ~1,5 s por frame. Por `stdin` acepta
`{"panel": "texto"}` para cambiar lo que dice el panel.
"""
from __future__ import annotations

import argparse
import base64
import json
import queue
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

POLL_MS = 10            # muestreo de modificadores y ratón
REFRESH_MS = 30         # cuánto tarda en pintar lo último recibido


def emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("font", type=Path, nargs="?")
    parser.add_argument("--panel", action="store_true",
                        help="sin pantalla: un panel que solo captura la entrada")
    parser.add_argument("--input", action="store_true",
                        help="captura teclado y ratón y los manda como reports")
    parser.add_argument("--scale", type=int, default=1)
    args = parser.parse_args()

    import tkinter as tk

    from tools import host_input, screen

    if args.panel:
        compositor = None
    else:
        if args.font is None:
            parser.error("falta la fuente (o usa --panel)")
        from PIL import Image, ImageTk

        from tools import console_render

        compositor = screen.Compositor(console_render.load_font(args.font))
    scancode_of = host_input.default_scancode_of()

    requests: queue.Queue = queue.Queue()

    def read_stdin():
        for line in sys.stdin:
            line = line.strip()
            if line:
                try:
                    requests.put(json.loads(line))
                except json.JSONDecodeError:
                    pass
        requests.put(None)

    threading.Thread(target=read_stdin, daemon=True).start()

    root = tk.Tk()
    root.title("mini-gpu")
    root.configure(background="#101010")
    root.resizable(False, False)
    state = {"photo": None, "title": ""}
    if args.panel:
        panel_size = (screen.SCREEN_SIZE[0] * args.scale, screen.SCREEN_SIZE[1] * args.scale)
        view = tk.Canvas(root, width=panel_size[0], height=panel_size[1],
                         background="#101820", highlightthickness=0)
        view.pack()
        panel_text = view.create_text(
            panel_size[0] // 2, panel_size[1] // 2, fill="#9fb4c7", justify="center",
            width=panel_size[0] - 40, font=("Segoe UI", 12),
            text="Capturando teclado y raton hacia la placa.\n\nF12 para salir.")
        root.title("mini-gpu  ·  F12 sale  ·  entrada hacia la placa")
    else:
        view = tk.Label(root, background="#000000", borderwidth=0)
        view.pack()

    def show(snap: dict, title: str | None) -> None:
        if snap.get("fb"):
            snap["fb"] = base64.b64decode(snap["fb"])
        image = compositor.compose(snap)
        if args.scale != 1:
            image = image.resize((image.width * args.scale, image.height * args.scale),
                                 Image.NEAREST)
        # Tk pierde la imagen si nadie guarda la referencia.
        state["photo"] = ImageTk.PhotoImage(image)
        view.configure(image=state["photo"])
        if title is not None:
            state["title"] = title
            root.title(f"mini-gpu  ·  F12 interrumpe  ·  {title}"
                       if args.input else f"mini-gpu  ·  {title}")

    def pump() -> None:
        latest = None
        try:
            while True:
                message = requests.get_nowait()
                if message is None:
                    root.destroy()          # el simulador cerró la tubería
                    return
                if args.panel and "panel" in message:
                    view.itemconfigure(panel_text, text=message["panel"])
                latest = message if "screen" in message and not args.panel else latest
                if "screen" not in message and "title" in message:
                    root.title(f"mini-gpu  ·  {message['title']}")
        except queue.Empty:
            pass
        if latest is not None:
            try:
                show(latest["screen"], latest.get("title"))
            except Exception as error:           # no tumbar la ventana por un frame malo
                emit({"event": "error", "message": f"pantalla: {error}"})
        root.after(REFRESH_MS, pump)

    if args.input:
        keyboard = host_input.HostKeyboard(
            lambda pressed: emit({"event": "keys", "pressed": sorted(pressed)}))
        # El ratón se supone al principio en el centro de la ventana.
        width = screen.SCREEN_SIZE[0] * args.scale
        height = screen.SCREEN_SIZE[1] * args.scale
        mouse = host_input.HostMouse(origin=(width // 2, height // 2),
                                     bounds=(width, height))
        sent = {"buttons": 0}

        def sync_modifiers() -> None:
            if sys.platform == "win32":
                keyboard.set_modifiers(host_input.windows_modifiers())

        def key_event(down: bool):
            def handler(event):
                if event.keysym == "F12":
                    if down:
                        emit({"event": "interrupt"})
                    return "break"
                if event.keycode in host_input.MODIFIER_VKS:
                    if sys.platform == "win32":
                        sync_modifiers()
                    else:
                        usage = host_input.usage_from_keysym(event.keysym)
                        if usage is not None:
                            (keyboard.press(usage, event.time) if down
                             else keyboard.release(usage))
                    return "break"
                usage = host_input.host_usage(event.keycode, event.state, event.keysym,
                                              scancode_of=scancode_of)
                if usage is not None:
                    keyboard.press(usage, event.time) if down else keyboard.release(usage)
                return "break"
            return handler

        def send_mouse() -> None:
            report = mouse.drain(sent["buttons"])
            if report is not None:
                sent["buttons"] = report[0]
                emit({"event": "mouse", "buttons": report[0], "dx": report[1], "dy": report[2]})

        def poll() -> None:
            if root.focus_displayof() is not None:
                sync_modifiers()
            send_mouse()
            root.after(POLL_MS, poll)

        def lost_focus(_event=None) -> None:
            keyboard.release_all()
            mouse.release_all()
            send_mouse()

        root.bind("<KeyPress>", key_event(True))
        root.bind("<KeyRelease>", key_event(False))
        root.bind("<FocusOut>", lost_focus)
        view.bind("<Enter>", lambda e: mouse.enter(e.x, e.y))
        view.bind("<Leave>", lambda e: mouse.leave(e.x, e.y))
        view.bind("<Motion>", lambda e: mouse.motion(e.x, e.y))
        for number in (1, 2, 3):
            view.bind(f"<ButtonPress-{number}>",
                      lambda e, n=number: mouse.button(n, True))
            view.bind(f"<ButtonRelease-{number}>",
                      lambda e, n=number: mouse.button(n, False))
        root.after(POLL_MS, poll)
    else:
        root.bind("<F12>", lambda e: emit({"event": "interrupt"}))

    if args.panel:
        # Centrada en el monitor: es una ventana de captura que se usa con el
        # ratón, y que salga en una esquina obliga a buscarla.
        # `geometry` coloca el marco EXTERIOR, así que hay que contar la barra
        # de título y los bordes: se miden tras mostrarla una vez.
        root.update()
        border = root.winfo_rootx() - root.winfo_x()
        title = root.winfo_rooty() - root.winfo_y()
        width = root.winfo_width() + 2 * border
        height = root.winfo_height() + title + border
        left = (root.winfo_screenwidth() - width) // 2
        top = (root.winfo_screenheight() - height) // 2
        root.geometry(f"+{max(left, 0)}+{max(top, 0)}")

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.after(REFRESH_MS, pump)
    root.focus_force()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
