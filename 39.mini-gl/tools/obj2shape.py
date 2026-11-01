#!/usr/bin/env python3
"""Convierte un modelo Wavefront OBJ en un PShape de MiniProcessing (processing3d.h): un .h con las
posiciones (x, y, z en float por vértice, el formato POSITION_F32_XYZ de mgl_create_mesh_copy), los
triángulos como índices u16 y los grupos de triángulos seguidos del mismo color.

No hay texturas en el renderer: cada cara recibe el color medio de la textura bajo su polígono UV (o el
de --color si no hay textura) y esos colores se reducen a --colors por k-means, para que el sketch dibuje
un tramo de índices por color (un SET_COLOR y un DRAW_INDEXED cada uno), como el cubo de colores.

El modelo se centra y se escala para que quepa en [-1, 1] (el sketch lo escala con scale()), y pasa de
y hacia arriba (OBJ, Blender) a y hacia abajo (Processing) con un giro de 180° en x: (x, -y, -z). Así
no cambia de quiralidad y lo que mira a -z en Blender (su "adelante") mira al espectador.

Solo la biblioteca estándar: el PNG (8 bits RGB/RGBA, sin entrelazar) se decodifica aquí mismo.

Uso: obj2shape.py modelo.obj [--texture tex.png] [--colors 8] [--name tie_fighter] -o modelo.h
"""

import argparse
import struct
import sys
import zlib
from pathlib import Path


def read_png(path):
    """(ancho, alto, filas): cada fila, lista de (r, g, b) con el alfa ya aplicado sobre negro."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit(f"{path}: no es un PNG")
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or ctype not in (2, 6) or interlace:
                sys.exit(f"{path}: solo PNG de 8 bits RGB o RGBA sin entrelazar")
            bpp = 4 if ctype == 6 else 3
        elif kind == b"IDAT":
            idat += body
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows, prev = [], bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
        for i in range(stride):  # los cinco filtros de PNG
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        if bpp == 4:
            rows.append([(line[i] * line[i + 3] // 255, line[i + 1] * line[i + 3] // 255,
                          line[i + 2] * line[i + 3] // 255) for i in range(0, stride, 4)])
        else:
            rows.append([tuple(line[i : i + 3]) for i in range(0, stride, 3)])
    return w, h, rows


def read_obj(path):
    """Posiciones, coordenadas UV y caras (listas de (v, vt), índices desde 0; vt puede ser None)."""
    vs, vts, faces = [], [], []
    for line in Path(path).read_text().splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "v":
            vs.append(tuple(float(c) for c in p[1:4]))
        elif p[0] == "vt":
            vts.append((float(p[1]), float(p[2])))
        elif p[0] == "f":
            face = []
            for ref in p[1:]:
                ids = ref.split("/")
                v = int(ids[0])
                t = int(ids[1]) if len(ids) > 1 and ids[1] else None
                face.append((v - 1 if v > 0 else len(vs) + v,
                             None if t is None else t - 1 if t > 0 else len(vts) + t))
            faces.append(face)
    return vs, vts, faces


def face_color(uvs, tex, samples=24):
    """Color medio de la textura dentro del polígono UV: una rejilla de hasta samples x samples puntos
    sobre su caja (solo los que caen dentro); si no cae ninguno, el del centroide."""
    w, h, rows = tex
    pts = [(u * w, (1.0 - v) * h) for u, v in uvs]  # v hacia arriba en OBJ, fila 0 arriba en el PNG
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    def inside(x, y):  # par/impar: vale para polígonos no convexos
        c, n = False, len(pts)
        for i in range(n):
            (ax, ay), (bx, by) = pts[i], pts[i - 1]
            if (ay > y) != (by > y) and x < ax + (bx - ax) * (y - ay) / (by - ay):
                c = not c
        return c

    def texel(x, y):
        return rows[min(h - 1, max(0, int(y)))][min(w - 1, max(0, int(x)))]

    nx = max(1, min(samples, int(x1 - x0)))
    ny = max(1, min(samples, int(y1 - y0)))
    acc, n = [0, 0, 0], 0
    for j in range(ny):
        y = y0 + (j + 0.5) * (y1 - y0) / ny
        for i in range(nx):
            x = x0 + (i + 0.5) * (x1 - x0) / nx
            if inside(x, y):
                for k, c in enumerate(texel(x, y)):
                    acc[k] += c
                n += 1
    if not n:
        return texel(sum(xs) / len(xs), sum(ys) / len(ys))
    return tuple(round(c / n) for c in acc)


def kmeans(colors, weights, k, rounds=30):
    """Reduce los colores a k como mucho. Arranque determinista: el más pesado y luego, cada vez, el
    más lejano a los ya elegidos."""
    distinct = sorted(set(colors))
    if len(distinct) <= k:
        return distinct, [distinct.index(c) for c in colors]

    def d2(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b))

    total = {}
    for c, wt in zip(colors, weights):
        total[c] = total.get(c, 0.0) + wt
    centers = [max(total, key=total.get)]
    while len(centers) < k:
        centers.append(max(distinct, key=lambda c: min(d2(c, m) for m in centers)))
    centers = [tuple(float(x) for x in c) for c in centers]
    for _ in range(rounds):
        label = [min(range(len(centers)), key=lambda m: d2(c, centers[m])) for c in colors]
        acc = [[0.0, 0.0, 0.0, 0.0] for _ in centers]
        for c, wt, m in zip(colors, weights, label):
            for i in range(3):
                acc[m][i] += c[i] * wt
            acc[m][3] += wt
        new = [tuple(a[i] / a[3] for i in range(3)) if a[3] else centers[m] for m, a in enumerate(acc)]
        if new == centers:
            break
        centers = new
    used = sorted(set(label))
    remap = {m: i for i, m in enumerate(used)}
    return ([tuple(round(x) for x in centers[m]) for m in used], [remap[m] for m in label])


def area(a, b, c):
    ux, uy, uz = (b[i] - a[i] for i in range(3))
    vx, vy, vz = (c[i] - a[i] for i in range(3))
    return 0.5 * ((uy * vz - uz * vy) ** 2 + (uz * vx - ux * vz) ** 2 + (ux * vy - uy * vx) ** 2) ** 0.5


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("obj")
    ap.add_argument("--texture", help="PNG del que sacar el color de cada cara (por su UV)")
    ap.add_argument("--color", default="200,200,200", help="r,g,b de todas las caras si no hay textura")
    ap.add_argument("--colors", type=int, default=8, help="como mucho tantos colores (grupos)")
    ap.add_argument("--credit", help="autor y licencia del modelo, para el comentario del .h")
    ap.add_argument("--cull", action="store_true",
                    help="no dibujar las caras traseras (comprueba que la orientación es coherente)")
    ap.add_argument("--name", help="nombre del PShape en C (por defecto, el del fichero)")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    vs, vts, faces = read_obj(args.obj)
    if len(vs) > 65535:
        sys.exit(f"{args.obj}: {len(vs)} vértices, más de los que caben en índices u16")
    tex = read_png(args.texture) if args.texture else None
    fixed = tuple(int(c) for c in args.color.split(","))

    # Centrar en la caja, escalar a [-1, 1] y (x, y, z) -> (x, -y, -z).
    lo = [min(v[i] for v in vs) for i in range(3)]
    hi = [max(v[i] for v in vs) for i in range(3)]
    mid = [(lo[i] + hi[i]) / 2 for i in range(3)]
    s = 2.0 / max(hi[i] - lo[i] for i in range(3))
    pos = [((v[0] - mid[0]) * s, -(v[1] - mid[1]) * s, -(v[2] - mid[2]) * s) for v in vs]

    # Triángulos en abanico (las caras de un OBJ suelen ser convexas), con el color de su cara.
    tris, colors, weights = [], [], []
    for face in faces:
        if len(face) < 3:
            continue
        if tex and all(t is not None for _, t in face):
            color = face_color([vts[t] for _, t in face], tex)
        else:
            color = fixed
        for i in range(1, len(face) - 1):
            tri = (face[0][0], face[i][0], face[i + 1][0])
            tris.append(tri)
            colors.append(color)
            weights.append(area(*(pos[v] for v in tri)))

    if args.cull:
        # Coherente: dos triángulos que comparten una arista la recorren en sentidos opuestos. Se
        # comparan posiciones, no índices, porque el OBJ repite vértices en las costuras de la UV.
        weld, seen = {}, set()
        ids = [weld.setdefault(tuple(round(c, 5) for c in p), len(weld)) for p in pos]
        for a, b, c in tris:
            for e in ((ids[a], ids[b]), (ids[b], ids[c]), (ids[c], ids[a])):
                if e in seen:
                    sys.exit(f"{args.obj}: orientación incoherente (arista {e} dos veces en el mismo "
                             "sentido): --cull dejaría caras sin dibujar")
                seen.add(e)

    palette, label = kmeans(colors, weights, args.colors)
    # Grupos de más oscuro a más claro; dentro de cada uno, el orden del OBJ.
    order = sorted(range(len(palette)), key=lambda m: sum(palette[m]))
    rank = {m: i for i, m in enumerate(order)}
    tris_sorted = sorted(range(len(tris)), key=lambda t: rank[label[t]])
    ends, n = [], 0
    for m in order:
        n += 3 * sum(1 for t in label if t == m)
        ends.append(n)

    name = args.name or Path(args.output).stem
    guard = name.upper() + "_SHAPE_H"
    out = [f"/* Generado por tools/obj2shape.py a partir de {Path(args.obj).name}"
           + (f" y {Path(args.texture).name}" if tex else "") + ": no editar a mano.",
           *([f"   {args.credit}"] if args.credit else []),
           f"   {len(pos)} vértices, {len(tris)} triángulos, {len(palette)} colores. */",
           f"#ifndef {guard}", f"#define {guard}", "", '#include "processing3d.h"', ""]
    out.append(f"static const float {name}_positions[{len(pos)} * 3] = {{")
    for x, y, z in pos:
        out.append(f"    {x:.6f}f, {y:.6f}f, {z:.6f}f,")
    out.append("};")
    out.append(f"static const unsigned short {name}_indices[{len(tris)} * 3] = {{")
    for i in range(0, len(tris_sorted), 6):
        out.append("    " + " ".join(f"{a}, {b}, {c}," for a, b, c in (tris[t] for t in tris_sorted[i : i + 6])))
    out.append("};")
    out.append(f"static const PShapeGroup {name}_groups[{len(palette)}] = {{")
    for m, end in zip(order, ends):
        r, g, b = palette[m]
        out.append(f"    {{{r}, {g}, {b}, {end}}},")
    out.append("};")
    out.append(f"static const PShape {name} = {{{name}_positions, {len(pos)}, {name}_indices, "
               f"{3 * len(tris)}, {name}_groups, {len(palette)}, {int(args.cull)}}};")
    out += ["", "#endif", ""]
    Path(args.output).write_text("\n".join(out))
    print(f"{args.output}: {len(pos)} vértices, {len(tris)} triángulos, colores:",
          " ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in (palette[m] for m in order)))


if __name__ == "__main__":
    main()
