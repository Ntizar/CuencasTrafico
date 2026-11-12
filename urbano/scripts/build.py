#!/usr/bin/env python3
"""Genera los datos (grafo vial + geometria) de una ciudad para el poster de cuencas urbanas.

Formato de salida compatible con el HTML existente: arrays tipados empaquetados
(jx, jy, jw, lu, lv, lk, tf, tb, lname, gcnt, gsx, gsy, gd) + cabecera JSON.
"""
import json, math, os, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

UA = {"User-Agent": "MastermindBot/1.0 (cuencas urbanas; davidantizar)"}
ENDPOINTS = [
    "https://z.overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
CACHE = os.path.join(os.path.dirname(__file__), "..", "cache")

HIGHWAYS = ("motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
            "living_street|pedestrian|service|motorway_link|trunk_link|primary_link|"
            "secondary_link|tertiary_link")

# velocidad por tipo (km/h) cuando no hay maxspeed
SPEED = {
    "motorway": 110, "motorway_link": 60, "trunk": 90, "trunk_link": 50,
    "primary": 70, "primary_link": 45, "secondary": 60, "secondary_link": 40,
    "tertiary": 50, "tertiary_link": 35, "unclassified": 40, "residential": 30,
    "living_street": 10, "pedestrian": 5, "service": 15,
}


def overpass(query, tries=6, tmo=150):
    last = None
    for i in range(tries):
        ep = ENDPOINTS[i % len(ENDPOINTS)]
        try:
            data = urllib.parse.urlencode({"data": query}).encode()
            req = urllib.request.Request(ep, data=data, headers=UA)
            t = time.time()
            print(f"    -> {ep.split('/')[2]} ({tmo}s max)", flush=True)
            with urllib.request.urlopen(req, timeout=tmo) as r:
                body = r.read()
            print(f"    overpass {len(body)/1e6:.1f} MB en {time.time()-t:.0f}s", flush=True)
            return json.loads(body)
        except Exception as e:  # reintento con backoff
            last = e
            print(f"    overpass fallo {type(e).__name__}: {e}; reintento", flush=True)
            time.sleep(6 * (i + 1))
    raise RuntimeError(f"overpass: {last}")


def cached(name, fetch):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if os.path.exists(p):
        return json.load(open(p))
    data = fetch()
    json.dump(data, open(p, "w"))
    return data


def nominatim(q, viewbox):
    params = {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "es",
              "viewbox": viewbox, "bounded": 1}
    req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" +
                                 urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        js = json.loads(r.read())
    time.sleep(1.1)
    return js[0] if js else None


# ---------------- geometria ----------------
def stitch_ring(members):
    segs = []
    for m in members:
        g = m.get("geometry") or []
        if len(g) < 2:
            continue
        segs.append([(p["lat"], p["lon"]) for p in g])
    rings = []
    while segs:
        cur = segs.pop(0)
        changed = True
        while changed and cur[0] != cur[-1]:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == cur[-1]:
                    cur = cur + s[1:]; segs.pop(i); changed = True; break
                if s[-1] == cur[-1]:
                    cur = cur + s[::-1][1:]; segs.pop(i); changed = True; break
                if s[-1] == cur[0]:
                    cur = s[:-1] + cur; segs.pop(i); changed = True; break
                if s[0] == cur[0]:
                    cur = s[::-1][:-1] + cur; segs.pop(i); changed = True; break
        rings.append(cur)

    def per(r):
        return sum(haversine(r[i][0], r[i][1], r[i + 1][0], r[i + 1][1]) for i in range(len(r) - 1))
    rings.sort(key=per, reverse=True)
    return rings[0]


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = math.hypot(dx, dy)
    best_i, best_d = 0, -1
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        if norm == 0:
            d = math.hypot(x - x0, y - y0)
        else:
            d = abs(dy * x - dx * y + x1 * y0 - y1 * x0) / norm
        if d > best_d:
            best_i, best_d = i, d
    if best_d > eps:
        left = rdp(pts[:best_i + 1], eps)
        right = rdp(pts[best_i:], eps)
        return left[:-1] + right
    return [pts[0], pts[-1]]


def point_in_ring(lon, lat, ring):
    inside = False
    n = len(ring)
    for i in range(n):
        lat1, lon1 = ring[i]
        lat2, lon2 = ring[(i + 1) % n]
        if (lat1 > lat) != (lat2 > lat):
            x = lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1)
            if lon < x:
                inside = not inside
    return inside


def parse_speed(tags):
    ms = (tags.get("maxspeed") or "").strip().lower()
    v = None
    if ms:
        if ms in ("walk", "foot"):
            v = 6
        elif ms in ("none",):
            v = 130
        else:
            digits = ""
            for ch in ms.replace(",", "."):
                if ch.isdigit() or ch == ".":
                    digits += ch
                elif digits:
                    break
            try:
                v = float(digits)
            except ValueError:
                v = None
        if v and ("mph" in ms):
            v *= 1.60934
    if v is None:
        v = SPEED.get(tags.get("highway"), 30)
    return max(5.0, min(130.0, v))


# ---------------- construccion ----------------
def nominatim_ring(q):
    """Limite municipal como GeoJSON desde Nominatim (sin Overpass)."""
    params = {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "es",
              "polygon_geojson": 1, "featuretype": "city"}
    req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" +
                                 urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        js = json.loads(r.read())
    time.sleep(1.1)
    if not js:
        raise RuntimeError("nominatim sin poligono")
    gj = js[0]["geojson"]
    polys = gj["coordinates"] if gj["type"] == "MultiPolygon" else [gj["coordinates"]]
    best, blen = None, -1
    for poly in polys:
        ring = [(p[1], p[0]) for p in poly[0]]
        peri = sum(haversine(ring[i][0], ring[i][1], ring[i + 1][0], ring[i + 1][1])
                   for i in range(len(ring) - 1))
        if peri > blen:
            best, blen = ring, peri
    return best


def ring_of_city(c):
    """Anillo del limite: cache, Nominatim y, si falla, Overpass."""
    p = os.path.join(CACHE, f"{c['slug']}_ring.json")
    if os.path.exists(p):
        return [tuple(x) for x in json.load(open(p))]
    try:
        ring = nominatim_ring(f"{c['name']}, España")
    except Exception as e:
        print(f"  nominatim fallo ({e}); probando overpass", flush=True)
        bnd = overpass(f"[out:json][timeout:240];rel({c['osm_rel']});out geom;")
        rel_el = bnd["elements"][0]
        ring = stitch_ring([m for m in rel_el["members"] if m["type"] == "way" and m.get("role") != "inner"])
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    json.dump(ring, open(p, "w"))
    return ring


def poly_filter(ring, maxpts=220):
    """Anillo simplificado para la clausula poly: de Overpass."""
    pts = rdp(ring, 25.0)
    tol = 25.0
    while len(pts) > maxpts:
        tol *= 1.5
        pts = rdp(ring, tol)
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return " ".join(f"{a:.5f} {b:.5f}" for a, b in pts)


def build(city):
    slug, name, rel = city["slug"], city["name"], city["osm_rel"]
    print(f"== {name} (rel {rel})")
    ring = ring_of_city(city)
    print(f"  anillo: {len(ring)} pts")

    lon0 = round(sum(p[1] for p in ring) / len(ring), 4)
    lat0 = round(sum(p[0] for p in ring) / len(ring), 4)
    cos0 = math.cos(math.radians(lat0))

    def project(lat, lon):
        return ((lon - lon0) * 111320 * cos0, (lat - lat0) * 110574)

    poly = poly_filter(ring)
    datas = cached(f"{slug}_ways.json", lambda: overpass(f"""[out:json][timeout:300];
way(poly:"{poly}")["highway"~"^({HIGHWAYS})$"]->.w;
.w out body;
node(w.w)->.n;
.n out skel qt;"""))
    ways = [e for e in datas["elements"] if e["type"] == "way"]
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in datas["elements"] if e["type"] == "node"}
    print(f"  {len(ways)} vias, {len(nodes)} nodos")

    # nodos de cruce
    cnt = Counter()
    for w in ways:
        ns = w["nodes"]
        for nid in ns:
            cnt[nid] += 1
        cnt[ns[0]] += 1
        cnt[ns[-1]] += 1
    is_j = {nid for nid, c in cnt.items() if c >= 2}
    print(f"  cruces: {len(is_j)}")

    jidx, jx, jy = {}, [], []

    def jn(nid):
        if nid not in jidx:
            lat, lon = nodes[nid]
            x, y = project(lat, lon)
            jidx[nid] = len(jx)
            jx.append(x); jy.append(y)
        return jidx[nid]

    names, name_idx = [], {}
    lu, lv, lk, tf, tb, lname, gcnt, gsx, gsy, gd = ([] for _ in range(10))
    nv = 0
    skipped_long = 0

    for w in ways:
        tags = w["tags"]
        ns = [n for n in w["nodes"] if n in nodes]
        if len(ns) < 2:
            continue
        hw = tags.get("highway")
        if hw not in SPEED:
            continue
        if hw == "service" and tags.get("service") in ("parking_aisle", "driveway"):
            continue
        nm = (tags.get("name") or tags.get("ref") or "").strip()
        if nm and nm not in name_idx:
            name_idx[nm] = len(names); names.append(nm)
        nidx = name_idx.get(nm, 65535) if nm else 65535
        oneway = (tags.get("oneway") or "").lower()
        if tags.get("junction") == "roundabout":
            oneway = "yes"
        speed = parse_speed(tags)

        # partir en cruces
        chain = [ns[0]]
        for nid in ns[1:]:
            chain.append(nid)
            if nid in is_j:
                if len(chain) >= 2:
                    seg = chain
                    if oneway in ("-1", "reverse"):
                        seg = seg[::-1]
                    pts = []
                    for a, b in zip(seg[:-1], seg[1:]):
                        la, lo = nodes[a]; lb, lob = nodes[b]
                        if a == seg[0]:
                            pts.append(project(la, lo))
                        pts.append(project(lb, lob))
                    length = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
                    if length >= 1 and len(pts) >= 2:
                        simp = rdp(pts, 8.0)
                        xi = [int(round(p[0])) for p in simp]
                        yi = [int(round(p[1])) for p in simp]
                        u, v = jn(seg[0]), jn(seg[-1])
                        t = max(0, round(length / (speed / 3.6)))
                        lu.append(u); lv.append(v)
                        lk.append(min(65535, int(round(length))))
                        if oneway in ("yes", "1", "true"):
                            tf.append(min(65535, t)); tb.append(0)
                        else:
                            tf.append(min(65535, t)); tb.append(min(65535, t))
                        lname.append(nidx)
                        gcnt.append(len(xi))
                        gsx.append(xi[0]); gsy.append(yi[0])
                        for i in range(1, len(xi)):
                            gd.append(xi[i] - xi[i - 1]); gd.append(yi[i] - yi[i - 1])
                        nv += len(xi)
                chain = [nid]

    # longitud > uint16: partir no implementado; informar
    print(f"  enlaces {len(lu)}, puntos geo {nv}, nombres {len(names)}")

    # pesos por cruce: mitad de la longitud de los enlaces adyacentes (km)
    jw = [0.0] * len(jx)
    for i in range(len(lu)):
        half = lk[i] / 2 / 1000
        jw[lu[i]] += half; jw[lv[i]] += half
    print(f"  km de calle: {sum(jw):.0f}")

    # etiquetas de distrito
    xs = [p[0] for p in (project(la, lo) for la, lo in ring[:-1])]
    ys = [p[1] for p in (project(la, lo) for la, lo in ring[:-1])]
    pad = 0.01
    bbox = f"{min(p[0] for p in ring)-pad},{min(p[1] for p in ring)-pad},{max(p[0] for p in ring)+pad},{max(p[1] for p in ring)+pad}"
    labels = []
    try:
        labs = cached(f"{slug}_districts.json", lambda: overpass(f"""[out:json][timeout:120];
rel({bbox})["boundary"="administrative"]["admin_level"="9"];
out tags center;"""))
        cand = []
        for e in labs["elements"]:
            c = e.get("center")
            nm2 = (e["tags"].get("name") or "").strip()
            if not c or not nm2:
                continue
            if not point_in_ring(c["lon"], c["lat"], ring[:-1]):
                continue
            x, y = project(c["lat"], c["lon"])
            cand.append({"name": nm2.upper(), "x": int(round(x)), "y": int(round(y))})
        labels = cand
    except Exception as e:
        print(f"  sin etiquetas: {e}")
    print(f"  etiquetas {len(labels)}")

    # hitos
    viewbox = f"{min(p[1] for p in ring)},{max(p[0] for p in ring)},{max(p[1] for p in ring)},{min(p[0] for p in ring)}"
    landmarks = []
    for lm in city["landmarks"]:
        try:
            r = nominatim(f"{lm}, {name}, España", viewbox)
        except Exception as e:
            print(f"  hito {lm}: error {e}"); continue
        if not r:
            print(f"  hito {lm}: no encontrado"); continue
        lat, lon = float(r["lat"]), float(r["lon"])
        x, y = project(lat, lon)
        best, bd = 0, 1e18
        for i in range(len(jx)):
            d = (jx[i] - x) ** 2 + (jy[i] - y) ** 2
            if d < bd:
                bd, best = d, i
        landmarks.append({"name": lm.split(",")[0], "lat": round(lat, 5), "lon": round(lon, 5),
                          "snap_m": int(round(math.sqrt(bd)))})
    print(f"  hitos {len(landmarks)}: " + ", ".join(f"{l['name']}({l['snap_m']}m)" for l in landmarks))

    # limite simplificado
    rp = [project(la, lo) for la, lo in ring]
    simp = rdp(rp, 40.0)
    boundary = [[int(round(x)), int(round(y))] for x, y in simp]
    print(f"  limite {len(boundary)} pts")

    return {
        "slug": slug, "name": name, "lon0": lon0, "lat0": lat0,
        "nj": len(jx), "nl": len(lu), "nv": nv,
        "landmarks": landmarks, "labels": labels, "boundary": boundary,
        "names": names,
        "raw": {"jx": jx, "jy": jy, "jw": jw, "lu": lu, "lv": lv, "lk": lk, "tf": tf,
                "tb": tb, "lname": lname, "gcnt": gcnt, "gsx": gsx, "gsy": gsy, "gd": gd},
    }


if __name__ == "__main__":
    import importlib
    cfg = importlib.import_module("cities")
    wanted = sys.argv[1:] or [c["slug"] for c in cfg.CITIES]
    force = "--force" in wanted
    for c in cfg.CITIES:
        if c["slug"] not in wanted:
            continue
        p = os.path.join(CACHE, f"{c['slug']}_built.json")
        if os.path.exists(p) and not force:
            print(f"== {c['name']}: ya construida, se omite")
            continue
        try:
            out = build(c)
        except Exception as e:
            print(f"!! {c['name']} fallo: {type(e).__name__}: {e}")
            continue
        json.dump(out, open(p, "w"))
        print(f"  -> {p}")
