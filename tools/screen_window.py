#!/usr/bin/env python3
"""Ventana de pantalla de un simulador: lo que saldría por HDMI, y la entrada.

Es un proceso aparte, por lo mismo que `fb_window.py`: Tk quiere su bucle de
eventos en el hilo principal y cerrar la ventana no puede tumbar al simulador ni
al depurador. Lo usan los dos.

    screen_window.py FUENTE.hex [--input] [--scale N]

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
    parser.add_argument("font", type=Path)
    parser.add_argument("--input", action="store_true",
                        help="captura teclado y ratón y los manda como reports")
    parser.add_argument("--scale", type=int, default=1)
    args = parser.parse_args()

    import tkinter as tk

    from PIL import Image, ImageTk

    from tools import console_render, host_input, screen

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
    view = tk.Label(root, background="#000000", borderwidth=0)
    view.pack()
    state = {"photo": None, "title": ""}

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
                latest = message if "screen" in message else latest
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
        mouse = host_input.HostMouse(origin=(screen.SCREEN_SIZE[0] * args.scale // 2,
                                             screen.SCREEN_SIZE[1] * args.scale // 2))
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

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.after(REFRESH_MS, pump)
    root.focus_force()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
