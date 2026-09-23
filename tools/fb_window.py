#!/usr/bin/env python3
"""Ventana que enseña uno o dos framebuffers RGB565, y se va refrescando.

Es un proceso aparte del depurador, y no por capricho: `mini-dbg` tiene el
terminal ocupado con la TUI, y Tk quiere su propio bucle de eventos en el hilo
principal. Separarlos evita esa pelea y además hace que cerrar la ventana no
pueda tumbar la sesión de depuración.

El protocolo de entrada es una línea JSON por refresco, por `stdin`; los
buffers contienen RGB565 codificado en Base64:

    {"front": "YQhhCGEI...", "back": null, "title": "PC=0x40 instr=120"}

Cada clave que venga con datos se repinta; una clave ausente deja su panel como
estaba. Por `stdout`, la ventana devuelve `{"event": "interrupt"}` al pulsar
`Esc`; cerrar con la X termina el proceso, y el depurador se entera solo la
próxima vez que intenta refrescar.

Tk y no pygame: viene con Python, y aquí no hace falta nada más que enseñar un
mapa de bits y ampliarlo.
"""
from __future__ import annotations

import importlib.util
import base64
import json
import queue
import struct
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Escalas de ampliación permitidas con + y -. La 2 es la del scanout real.
ESCALAS = (1, 2, 3, 4)


def _expandir():
    """La conversión RGB565 -> RGB888 canónica, la de `frame-to-image.py`.

    Se carga del fichero porque su nombre lleva guion y no se puede importar.
    Duplicar aquí los cuatro desplazamientos sería tener dos definiciones del
    color: sin replicar los bits altos, 0b11111 da 0xF8 y el blanco sale gris.
    """
    ruta = ROOT / "tools" / "frame-to-image.py"
    spec = importlib.util.spec_from_file_location("frame_to_image", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.expandir


def build_lookup():
    """Los 65536 colores posibles, precalculados una vez.

    Convertir píxel a píxel en Python cuesta más que leer el frame; con la
    tabla, un framebuffer de 320x240 se convierte en unos milisegundos, que es
    lo que hace falta para que esto parezca una ventana y no un visor.
    """
    expandir = _expandir()
    return [bytes(expandir(valor)) for valor in range(65536)]


LOOKUP = None


def rgb_bytes(data: bytes) -> bytes:
    global LOOKUP
    if LOOKUP is None:
        LOOKUP = build_lookup()
    valores = struct.unpack(f"<{len(data) // 2}H", data)
    return b"".join([LOOKUP[v] for v in valores])


def main() -> int:
    import tkinter as tk

    from PIL import Image, ImageTk

    ancho, alto = 320, 240
    if len(sys.argv) > 1:
        ancho, alto = (int(v) for v in sys.argv[1].lower().split("x"))

    peticiones: queue.Queue = queue.Queue()

    def leer_stdin():
        for linea in sys.stdin:
            linea = linea.strip()
            if linea:
                try:
                    peticiones.put(json.loads(linea))
                except json.JSONDecodeError:
                    pass
        peticiones.put(None)

    threading.Thread(target=leer_stdin, daemon=True).start()

    raiz = tk.Tk()
    raiz.title("mini-dbg: framebuffer")
    raiz.configure(background="#101010")

    estado = {"escala": 2, "imagenes": {}, "fotos": {}}

    contenedor = tk.Frame(raiz, background="#101010")
    contenedor.pack(padx=8, pady=(8, 0))

    paneles = {}
    for indice, nombre in enumerate(("front", "back")):
        marco = tk.Frame(contenedor, background="#101010")
        etiqueta = tk.Label(marco, text=nombre.upper(), fg="#b0b0b0",
                            bg="#101010", font=("Consolas", 10))
        etiqueta.pack()
        lienzo = tk.Label(marco, background="#202020")
        lienzo.pack()
        paneles[nombre] = {"marco": marco, "lienzo": lienzo, "columna": indice}

    barra = tk.Label(raiz, text="esperando frame...", fg="#909090",
                     bg="#101010", font=("Consolas", 9), anchor="w")
    barra.pack(fill="x", padx=8, pady=(4, 6))

    def recolocar():
        for nombre, panel in paneles.items():
            panel["marco"].grid_forget()
        visibles = [n for n in ("front", "back") if n in estado["imagenes"]]
        for columna, nombre in enumerate(visibles):
            paneles[nombre]["marco"].grid(row=0, column=columna, padx=6)

    def repintar():
        escala = estado["escala"]
        for nombre, imagen in estado["imagenes"].items():
            mostrada = imagen if escala == 1 else imagen.resize(
                (imagen.width * escala, imagen.height * escala),
                Image.NEAREST)  # NEAREST: un pixel es un pixel, sin inventar
            foto = ImageTk.PhotoImage(mostrada)
            # La referencia se guarda o Tk se la come con el recolector y la
            # imagen sale en blanco. Es el clásico de tkinter.
            estado["fotos"][nombre] = foto
            paneles[nombre]["lienzo"].configure(image=foto)
        recolocar()

    def aplicar(peticion: dict) -> None:
        for nombre in ("front", "back"):
            if nombre not in peticion:
                continue
            contenido = peticion[nombre]
            if contenido is None:
                estado["imagenes"].pop(nombre, None)
                estado["fotos"].pop(nombre, None)
                continue
            try:
                datos = base64.b64decode(contenido, validate=True)
                estado["imagenes"][nombre] = Image.frombytes(
                    "RGB", (ancho, alto), rgb_bytes(datos))
            except (OSError, ValueError, MemoryError) as exc:
                print(json.dumps({
                    "event": "error",
                    "message": f"framebuffer {nombre}: {exc}",
                }), flush=True)
                continue
        if peticion.get("title"):
            barra.configure(text=peticion["title"])
        repintar()

    def bombear():
        acumulada = {}
        try:
            while True:
                peticion = peticiones.get_nowait()
                if peticion is None:
                    # El depurador cerró la tubería: se acabó la sesión.
                    raiz.destroy()
                    return
                # El simulador puede completar frames más deprisa que Tk los
                # convierte en PhotoImage. Se combinan todas las peticiones
                # pendientes y se pinta solo la más reciente, conservando un
                # frame anterior si después llegó únicamente un título.
                acumulada.update(peticion)
        except queue.Empty:
            pass
        if acumulada:
            aplicar(acumulada)
        raiz.after(50, bombear)

    def zoom(paso: int):
        def manejar(_evento=None):
            actual = ESCALAS.index(estado["escala"])
            estado["escala"] = ESCALAS[
                min(max(actual + paso, 0), len(ESCALAS) - 1)]
            repintar()
        return manejar

    raiz.bind("<plus>", zoom(1))
    raiz.bind("<KP_Add>", zoom(1))
    raiz.bind("<minus>", zoom(-1))
    raiz.bind("<KP_Subtract>", zoom(-1))

    def interrumpir(_evento=None):
        print(json.dumps({"event": "interrupt"}), flush=True)
        return "break"

    def enviar_tecla(evento):
        # `char` conserva la R mayúscula; para cursores y PageUp se necesita
        # `keysym`. Zoom y Escape tienen su binding específico.
        if evento.keysym in {"plus", "KP_Add", "minus", "KP_Subtract",
                             "Escape"}:
            return
        key = evento.char or evento.keysym
        print(json.dumps({"event": "key", "key": key}), flush=True)

    raiz.bind("<Escape>", interrumpir)
    raiz.bind("<KeyPress>", enviar_tecla, add="+")

    raiz.after(50, bombear)
    raiz.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
