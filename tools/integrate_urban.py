#!/usr/bin/env python3
"""Integra el modo «calle a calle» (7 ciudades) dentro de la app nacional.

Idempotente: si el marcador ya existe, no vuelve a insertar. Aplica ediciones
puntuales sobre index.html y añade el bloque de JS del modo urbano.
"""

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
DATA = Path("/home/nan/Projects/CuencasUrbanas/out/urbandata.b64")
BLOCK = Path("/tmp/urban_block.js")

html = INDEX.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global html
    n = html.count(old)
    assert n == count, f"esperaba {count} coincidencias, hay {n}: {old[:70]!r}"
    html = html.replace(old, new)


# ---------------------------------------------------------------- 1. datos
if 'id="urbandata"' not in html:
    b64 = DATA.read_text().strip()
    anchor = 'type="application/octet-stream">'
    i = html.index(anchor) + len(anchor)
    j = html.index("</script>", i)
    html = html[:j] + "</script>\n" + '<script id="urbandata" type="application/octet-stream">' + b64 + html[j:]
    print(f"  datos urbanos inyectados: {len(b64)/1e6:.2f} MB b64")

# ---------------------------------------------------------------- 2. botón
sub(
    '<button type="button" data-v="interstate" aria-pressed="false">Efecto autovía</button>',
    '<button type="button" data-v="interstate" aria-pressed="false">Efecto autovía</button>\n'
    '        <button type="button" data-v="urban" aria-pressed="false">Calle a calle</button>',
)

# ---------------------------------------------------------------- 3. controles
URBAN_UI = """    <div class="group" id="urban-controls" hidden>
      <span class="label" id="lbl-ucity">Ciudad</span>
      <div class="seg grid2" role="group" aria-labelledby="lbl-ucity" id="ucity"></div>
      <span class="label" id="lbl-uref">Punto de referencia</span>
      <div class="seg grid2" role="group" aria-labelledby="lbl-uref" id="uref"></div>
      <p class="hint">Cada calle se tiñe del punto al que llega antes. Toca el mapa para moverlo.</p>
    </div>
"""
sub('    <div class="group" id="route-group">', URBAN_UI + '    <div class="group" id="route-group">')

# ---------------------------------------------------------------- 4. estado
sub('const S = { kind: "one",', 'const S = { kind: "one", ucity: null, uref: {},')

# ---------------------------------------------------------------- 5. compute
sub(
    '  const isI = S.kind === "interstate", mode = isI ? "time" : S.mode;',
    '  const urban = S.kind === "urban";\n'
    '  const isI = S.kind === "interstate", mode = isI ? "time" : S.mode;',
)
sub(
    '  const wsrc = S.weight === "pop" ? A.jpop : A.jarea;\n  const W = new Float64Array(NJ);',
    '  const wsrc = urban || S.weight !== "pop" ? A.jarea : A.jpop;\n  const W = new Float64Array(NJ);',
)
sub(
    '    let ok = dist[i] < Infinity;\n'
    '    if (S.scope === "state") ok = ok && A.jstate[i] === S.destState;\n'
    '    else if (S.scope === "reach") ok = ok && dist[i] <= reachCost;',
    '    let ok = dist[i] < Infinity;\n'
    '    if (!urban) {\n'
    '      if (S.scope === "state") ok = ok && A.jstate[i] === S.destState;\n'
    '      else if (S.scope === "reach") ok = ok && dist[i] <= reachCost;\n'
    '    }',
)
sub(
    '  R = { W, col, inScope, info, total, half, far, farD, maxW: 0 };',
    '  R = { W, col, inScope, info, total, half, far, farD, maxW: 0 };\n'
    '  if (urban && CUR) R.extent = CUR.extent;',
)

# ---------------------------------------------------------------- 6. dibujo
sub(
    '  if (R.meet || R.inter) drawModeText(ctx, st, F, FM, padX, footer);',
    '  if (CUR && R.extent && !R.meet && !R.inter) drawUrbanText(ctx, st, F, FM, padX, footer);\n'
    '  else if (R.meet || R.inter) drawModeText(ctx, st, F, FM, padX, footer);',
)
sub(
    '    else {\n'
    '      const dxp = px(JX[S.dest]), dyp = py(JY[S.dest]);',
    '    else {\n'
    '      if (CUR) drawTowns(ctx, st, F, px, py, [map.x, map.y, map.x + map.w, map.y + map.h], 14,\n'
    '        [[px(JX[S.dest]) - 12, py(JY[S.dest]) - 12, px(JX[S.dest]) + 12, py(JY[S.dest]) + 12]]);\n'
    '      const dxp = px(JX[S.dest]), dyp = py(JY[S.dest]);',
)

# ---------------------------------------------------------------- 7. UI sync
sub(
    '  document.getElementById("route-group").hidden = k === "interstate";',
    '  document.getElementById("route-group").hidden = k === "interstate";\n'
    '  document.getElementById("urban-controls").hidden = k !== "urban";\n'
    '  if (k === "urban") { if (!CUR) useUrban(S.ucity || (URB[0] && URB[0].slug)); }\n'
    '  else if (CUR) useNational();',
)
sub(
    '  document.querySelectorAll(".one-only").forEach(el => el.hidden = k !== "one");',
    '  document.querySelectorAll(".one-only").forEach(el => el.hidden = !(k === "one" || k === "urban"));',
)
sub(
    '  document.getElementById("weight-group").hidden = k === "meet";',
    '  document.getElementById("weight-group").hidden = k === "meet" || k === "urban";',
)
sub(
    '  interstate: "Colorea cada carretera según el tiempo que las autovías ahorran en el viaje hasta un lugar.",',
    '  interstate: "Colorea cada carretera según el tiempo que las autovías ahorran en el viaje hasta un lugar.",\n'
    '  urban: "El mismo árbol de rutas, pero a escala de calle: elige ciudad y punto de referencia.",',
)

# ---------------------------------------------------------------- 8. guardas
sub(
    '  if (!M || ((S.kind === "one" || S.kind === "interstate") && S.dest == null)) return;',
    '  if (!M || ((S.kind === "one" || S.kind === "interstate") && S.dest == null)) return;\n'
    '  if (S.kind === "urban" && !CUR) return;',
)

# ---------------------------------------------------------------- 9. clic
sub(
    '    if (S.kind === "meet") {\n      const T = S.travelers;',
    '    if (S.kind === "urban") {\n'
    '      if (!CUR) return;\n'
    '      S.dest = nearestJunction(x, y); S.destLabel = streetAt(S.dest);\n'
    '      S.uref[CUR.slug] = -1; routedKey = ""; drawUrbanChips(); update(); return;\n'
    '    }\n'
    '    if (S.kind === "meet") {\n      const T = S.travelers;',
)

# ---------------------------------------------------------------- 10. init
sub('  await loadData();', '  await loadData();\n  await loadUrban();')

# ---------------------------------------------------------------- 11. bloque JS
block = BLOCK.read_text(encoding="utf-8")
marker = "// ---------- modo urbano: la misma app, a escala de calle ----------"
if marker not in html:
    end = html.rindex("})();")
    html = html[:end] + block + "\n" + html[end:]
    print("  bloque JS del modo urbano insertado")

INDEX.write_text(html, encoding="utf-8")
print(f"  index.html: {len(html)/1e6:.2f} MB")
