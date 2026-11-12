#!/usr/bin/env python3
"""Convierte las ciudades urbanas al esquema de datos de la app nacional.

La app nacional (CuencasTrafico/index.html) y la urbana usan el mismo modelo de
grafo, pero con convenciones de empaquetado distintas:

  nacional: jx/jy uint16 * Q + x0, lt (segundos, float32), lk (metros, float32),
            jarea/jpop float32, gd deltas int16 ...
  urbana:   jx/jy float metros, tf/tb (segundos, uint16), lk (metros, uint16),
            jw (km de calle), gd deltas int en metros.

Este script reescribe cada ciudad en la convención nacional y las empaqueta todas
en un único binario gzip+base64, con el mismo formato que usa loadData():
  [u32 longitud_json][json][padding a 8][arrays...]  por ciudad, en secuencia.

Uso:  python scripts/to_national.py out/urbandata.b64
"""

import base64
import gzip
import json
import math
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
BASE_HTML = ROOT / "data" / "original.html"

CHUNK = struct.Struct("<I")
Q_TARGET = 65000  # unidades disponibles en uint16


def _read_blob_cities(path):
    """Ciudades ya empaquetadas dentro de un HTML con <script id="citydata">."""
    html = path.read_text(encoding="utf-8")
    m = re.search(r'<script id="citydata"[^>]*>\s*(.*?)\s*</script>', html, re.S)
    if not m:
        return []
    raw = gzip.decompress(base64.b64decode(m.group(1)))
    n = CHUNK.unpack_from(raw, 0)[0]
    meta = json.loads(raw[4:4 + n])
    base = 4 + n
    while base % 8:
        base += 1
    out = []
    for city in meta["cities"]:
        arrays = {}
        for key, dt, off, size in city["arrays"]:
            fmt = {"uint16": "H", "int16": "h", "uint8": "B",
                   "uint32": "I", "float32": "f"}[dt]
            width = struct.calcsize(fmt)
            vals = struct.unpack_from("<" + fmt * size, raw, base + off)
            arrays[key] = list(vals)
        rec = dict(city)
        rec["arrays"] = arrays
        out.append(rec)
    return out


def _read_cache_cities():
    out = []
    for path in sorted(CACHE.glob("*_built.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        raw = d["raw"]
        rec = {
            "slug": d["slug"], "name": d["name"],
            "lon0": d["lon0"], "lat0": d["lat0"],
            "nj": d["nj"], "nl": d["nl"], "nv": d["nv"],
            "names": d["names"], "landmarks": d["landmarks"],
            "labels": d["labels"], "boundary": d["boundary"],
            "arrays": raw,
        }
        out.append(rec)
    return out


def _project(city, lat, lon):
    cos0 = math.cos(math.radians(city["lat0"]))
    return ((lon - city["lon0"]) * 111320 * cos0, (lat - city["lat0"]) * 110574)


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def convert(city):
    A = city["arrays"]
    jx, jy = A["jx"], A["jy"]
    nj, nl, nv = city["nj"], city["nl"], city["nv"]

    x0 = min(jx)
    y0 = min(jy)
    span = max(max(jx) - x0, max(jy) - y0)
    q = max(0.25, math.ceil(span / Q_TARGET * 100) / 100)

    jxi = [int(round((x - x0) / q)) for x in jx]
    jyi = [int(round((y - y0) / q)) for y in jy]

    # geometría: la fuente guarda gsx/gsy (primer punto, absoluto) y gd (deltas en metros)
    gsx_i, gsy_i, gd_new = [], [], []
    gcnt = A["gcnt"]
    g_off = 0
    for l in range(nl):
        px, py = A["gsx"][l], A["gsy"][l]
        gsx_i.append(int(round((px - x0) / q)))
        gsy_i.append(int(round((py - y0) / q)))
        # la convención nacional aplica el delta antes de guardar: el primer par
        # es (0,0) para que el punto inicial sea exactamente gsx/gsy
        gd_new.append(0)
        gd_new.append(0)
        for _ in range(gcnt[l] - 1):
            x = px + A["gd"][2 * g_off]
            y = py + A["gd"][2 * g_off + 1]
            g_off += 1
            dx = int(round((x - px) / q))
            dy = int(round((y - py) / q))
            gd_new.append(max(-32767, min(32767, dx)))
            gd_new.append(max(-32767, min(32767, dy)))
            px, py = x, y

    # las ciudades del HTML base no traen 'jw': se sintetiza con el largo de calle
    jw = A.get("jw")
    if jw is None:
        jw = [0.0] * nj
        for l in range(nl):
            km = A["lk"][l] / 1000.0
            jw[A["lu"][l]] += km / 2
            jw[A["lv"][l]] += km / 2

    lt = []
    for l in range(nl):
        tf = A["tf"][l]
        tb = A.get("tb", A["tf"])[l]
        lt.append((min(tf, tb) if tb else tf) / 60.0)  # la nacional mide en minutos

    extent_src = []
    for x, y in zip(jx, jy):
        extent_src.append(x)
    sx = sorted(jx)
    sy = sorted(jy)
    ex0 = _quantile(sx, 0.07)
    ex1 = _quantile(sx, 0.93)
    ey0 = _quantile(sy, 0.07)
    ey1 = _quantile(sy, 0.93)
    mx = (ex1 - ex0) * 0.015
    my = (ey1 - ey0) * 0.015
    extent = [ex0 - mx, ey0 - my, ex1 + mx, ey1 + my]

    def world(v, o):
        return o + (v - o)  # identidad: se recalcula sobre el espacio convertido

    def to_world_x(v):
        return x0 + (v - x0)

    # puntos auxiliares en el espacio nacional
    def conv_pt(p):
        return [int(round((p[0] - x0) / q)), int(round((p[1] - y0) / q))]

    marks = []
    for lm in city.get("landmarks", []):
        if "lat" not in lm:
            continue
        x, y = _project(city, lm["lat"], lm["lon"])
        best, bd = 0, float("inf")
        for i in range(nj):
            d = (jx[i] - x) ** 2 + (jy[i] - y) ** 2
            if d < bd:
                bd, best = d, i
        marks.append([lm["name"], best])

    labels = []
    for lb in city.get("labels", []):
        labels.append([lb["name"], int(round((lb["x"] - x0) / q)),
                       int(round((lb["y"] - y0) / q))])

    boundary = [conv_pt(p) for p in city.get("boundary", [])]

    arrays = [
        ("jx", "uint16", jxi),
        ("jy", "uint16", jyi),
        ("jstate", "uint8", [0] * nj),
        ("jarea", "float32", [float(v) for v in jw]),
        ("jpop", "float32", [0.0] * nj),
        ("lu", "uint32", A["lu"]),
        ("lv", "uint32", A["lv"]),
        ("lt", "float32", lt),
        ("lk", "float32", [float(v) for v in A["lk"]]),
        ("lname", "uint16", A["lname"]),
        ("gcnt", "uint16", gcnt),
        ("gsx", "uint16", gsx_i),
        ("gsy", "uint16", gsy_i),
        ("gd", "int16", gd_new),
    ]

    header = {
        "slug": city["slug"], "name": city["name"],
        "x0": x0, "y0": y0, "Q": q,
        "nj": nj, "nl": nl, "nv": nv,
        "extent": [int(round((extent[0] - x0) / q)), int(round((extent[1] - y0) / q)),
                   int(round((extent[2] - x0) / q)), int(round((extent[3] - y0) / q))],
        "marks": marks, "labels": labels, "boundary": boundary,
        "names": city["names"],
    }
    return header, arrays


FMT = {"uint16": "H", "int16": "h", "uint8": "B", "uint32": "I", "float32": "f"}


def pack(header, arrays):
    spec = []
    blob = b""
    for key, dt, vals in arrays:
        while len(blob) % 8:  # los Float32Array exigen offsets múltiplos de 4
            blob += b"\0"
        data = struct.pack("<" + FMT[dt] * len(vals), *vals)
        spec.append([key, dt, len(blob), len(vals)])
        blob += data
    header = dict(header, arrays=spec)
    js = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode()
    head = CHUNK.pack(len(js)) + js
    while len(head) % 8:
        head += b"\0"
    chunk = head + blob
    while len(chunk) % 8:  # que cada ciudad empiece alineada
        chunk += b"\0"
    return CHUNK.pack(len(chunk)) + chunk


def main():
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out" / "urbandata.b64"
    cities = _read_blob_cities(BASE_HTML) + _read_cache_cities()
    seen, ordered = set(), []
    for c in cities:
        if c["slug"] in seen:
            continue
        seen.add(c["slug"])
        ordered.append(c)

    parts = []
    for city in ordered:
        header, arrays = convert(city)
        parts.append(pack(header, arrays))
        print(f"  + {header['name']:<10} nj={header['nj']:>6} nl={header['nl']:>6} "
              f"Q={header['Q']} marcas={len(header['marks'])}")

    raw = b"".join(parts)
    gz = gzip.compress(raw, 9, mtime=0)
    b64 = base64.b64encode(gz)
    dest.write_bytes(b64)
    print(f"  binario {len(raw)/1e6:.2f} MB -> gzip {len(gz)/1e6:.2f} MB -> b64 {len(b64)/1e6:.2f} MB")
    print(f"  escrito {dest}  ({len(ordered)} ciudades)")


if __name__ == "__main__":
    main()
