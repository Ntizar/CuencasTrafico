#!/usr/bin/env python3
"""Fusiona las ciudades nuevas en el HTML original: binario embebido + textos."""
import base64, gzip, json, os, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, "cache")

ORDER = ["jx", "jy", "jw", "lu", "lv", "lk", "tf", "tb", "lname", "gcnt", "gsx", "gsy", "gd"]
DTYPE = {"jx": "int16", "jy": "int16", "jw": "float32", "lu": "uint32", "lv": "uint32",
         "lk": "uint16", "tf": "uint16", "tb": "uint16", "lname": "uint16",
         "gcnt": "uint16", "gsx": "int16", "gsy": "int16", "gd": "int16"}
FMT = {"int16": "<h", "uint16": "<H", "uint32": "<I", "float32": "<f"}
ISZ = {"int16": 2, "uint16": 2, "uint32": 4, "float32": 4}
LIM = {"int16": (-32768, 32767), "uint16": (0, 65535), "uint32": (0, 2**32 - 1)}


def load_base(path):
    html = open(path, encoding="utf-8").read()
    m = re.search(r'<script id="citydata" type="application/octet-stream">\s*(.*?)\s*</script>', html, re.S)
    data = gzip.decompress(base64.b64decode(m.group(1)))
    n = struct.unpack_from("<I", data, 0)[0]
    header = json.loads(data[4:4 + n])
    base = 4 + n
    while base % 8:
        base += 1
    return html, header, data[base:]


def weighted_quantile(vals, weights, q):
    pairs = sorted(zip(vals, weights))
    total = sum(weights)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * total:
            return v
    return pairs[-1][0]


def city_extent(c):
    jx, jy, jw = c["raw"]["jx"], c["raw"]["jy"], c["raw"]["jw"]
    x0 = weighted_quantile(jx, jw, 0.07)
    x1 = weighted_quantile(jx, jw, 0.93)
    y0 = weighted_quantile(jy, jw, 0.07)
    y1 = weighted_quantile(jy, jw, 0.93)
    m = 0.015 * max(x1 - x0, y1 - y0)
    return [int(round(x0 - m)), int(round(y0 - m)), int(round(x1 + m)), int(round(y1 + m))]


def encode_city(c, payload):
    while len(payload) % 8:
        payload.append(0)
    arrays = []
    for key in ORDER:
        dt = DTYPE[key]
        vals = c["raw"][key]
        while len(payload) % ISZ[dt]:
            payload.append(0)
        off = len(payload)
        lo, hi = LIM.get(dt, (None, None))
        out = bytearray()
        for v in vals:
            if dt == "float32":
                out += struct.pack(FMT[dt], float(v))
            else:
                iv = int(round(v)) if isinstance(v, float) else int(v)
                if lo is not None and not (lo <= iv <= hi):
                    raise ValueError(f"{c['slug']} {key}={iv} fuera de {dt}")
                out += struct.pack(FMT[dt], iv)
        payload += out
        arrays.append([key, dt, off, len(vals)])
    meta = {k: c[k] for k in ("slug", "name", "lon0", "lat0", "nj", "nl", "nv",
                              "landmarks", "labels", "boundary", "names")}
    meta["extent"] = city_extent(c)
    meta["arrays"] = arrays
    return meta


def main():
    src = sys.argv[1]
    dst = sys.argv[2]
    slugs = sys.argv[3:]
    html, header, payload = load_base(src)
    payload = bytearray(payload)
    have = {c["slug"] for c in header["cities"]}
    for slug in slugs:
        if slug in have:
            print(f"  {slug} ya esta, se omite")
            continue
        c = json.load(open(os.path.join(CACHE, f"{slug}_built.json")))
        meta = encode_city(c, payload)
        header["cities"].append(meta)
        print(f"  + {meta['name']}: {meta['nj']} cruces, {meta['nl']} enlaces, {meta['nv']} pts")

    header["generated"] = "2026-11-12"
    header["snapshot"] = "OSM, nov 2026"
    blob = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode()
    out = bytearray(struct.pack("<I", len(blob))) + blob
    while len(out) % 8:
        out.append(0)
    out += payload
    b64 = base64.b64encode(gzip.compress(bytes(out), 9)).decode()
    print(f"  binario {len(out)/1e6:.2f} MB -> gzip {len(gzip.compress(bytes(out), 9))/1e6:.2f} MB -> b64 {len(b64)/1e6:.2f} MB")

    html2 = re.sub(r'(<script id="citydata" type="application/octet-stream">\s*).*?(\s*</script>)',
                   lambda m: m.group(1) + b64 + m.group(2), html, flags=re.S)
    # encuadre por ciudad (las ciudades alargadas no se comen el lienzo)
    old_ext = """  const mrg = 0.04 * Math.max(x1 - x0, y1 - y0);
  cc.extent = [x0 - mrg, y0 - mrg, x1 + mrg, y1 + mrg];"""
    new_ext = """  const mrg = 0.04 * Math.max(x1 - x0, y1 - y0);
  cc.extent = meta.extent || [x0 - mrg, y0 - mrg, x1 + mrg, y1 + mrg];"""
    assert old_ext in html2, "no encuentro el bloque de extent"
    html2 = html2.replace(old_ext, new_ext)
    names = [c["name"] for c in header["cities"]]
    n = len(names)
    html2 = html2.replace("<title>Cuencas urbanas — Madrid y Barcelona, calle a calle</title>",
                          f"<title>Cuencas urbanas — las {n} ciudades más grandes de España, calle a calle</title>")
    html2 = html2.replace('ctx.fillText("Cuencas urbanas · Madrid y Barcelona", PW - padX, PH - 12);',
                          f'ctx.fillText(`Cuencas urbanas · ${{HEADER.cities.length}} ciudades`, PW - padX, PH - 12);')
    open(dst, "w", encoding="utf-8").write(html2)
    print(f"  escrito {dst} ({os.path.getsize(dst)/1e6:.2f} MB), ciudades: {', '.join(names)}")


if __name__ == "__main__":
    main()
