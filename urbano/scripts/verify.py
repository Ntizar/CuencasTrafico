#!/usr/bin/env python3
"""Verifica el HTML generado en chrome-headless-shell: carga, cambia de ciudad y mide el canvas."""
import json, os, re, subprocess, sys, html as H

CHROME = os.path.expanduser("~/.cache/chrome/chrome-headless-shell-linux64/chrome-headless-shell")
PROBE = r"""
<script>
(() => {
  const out = {errors: [], cities: []};
  window.addEventListener('error', e => out.errors.push(String(e.message)));
  window.addEventListener('unhandledrejection', e => out.errors.push('rejection: ' + e.reason));
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  function pixels() {
    const c = document.getElementById('poster');
    const g = c.getContext('2d');
    const d = g.getImageData(0, 0, c.width, c.height).data;
    const seen = new Set(); let nonwhite = 0;
    for (let i = 0; i < d.length; i += 4 * 37) {
      const k = (d[i] >> 3) + ',' + (d[i+1] >> 3) + ',' + (d[i+2] >> 3);
      seen.add(k);
      if (d[i] < 245 || d[i+1] < 245 || d[i+2] < 245) nonwhite++;
    }
    return {colores: seen.size, tinta: +(nonwhite / (d.length / (4*37))).toFixed(3)};
  }
  (async () => {
    for (let i = 0; i < 400 && !document.querySelector('#cityChips .chip'); i++) await sleep(100);
    const chips = [...document.querySelectorAll('#cityChips .chip')];
    out.nChips = chips.length;
    out.chips = chips.map(c => c.textContent.trim());
    for (const ch of chips) {
      ch.click();
      await sleep(1500);
      const st = document.getElementById('liveStat');
      out.cities.push({ciudad: ch.textContent.trim(), stat: st ? st.textContent.trim() : null, ...pixels()});
    }
    const loading = document.getElementById('loading');
    out.loading = loading ? getComputedStyle(loading).display : 'ausente';
    const pre = document.createElement('pre');
    pre.id = 'probe'; pre.textContent = JSON.stringify(out);
    document.body.appendChild(pre);
  })();
})();
</script>
"""


def main():
    src, dst = sys.argv[1], sys.argv[2]
    h = open(src, encoding="utf-8").read()
    h = h.replace("</body>", PROBE + "</body>")
    tmp = "/tmp/verify_page.html"
    open(tmp, "w", encoding="utf-8").write(h)
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = os.path.expanduser("~/.cache/chrome/libs") + ":" + os.path.expanduser("~/.chrome-libs/usr/lib/x86_64-linux-gnu")
    cmd = [CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
           "--hide-scrollbars", "--window-size=1280,900", "--virtual-time-budget=60000",
           "--dump-dom", "file://" + tmp]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    dom = p.stdout
    m = re.search(r'<pre id="probe">(.*?)</pre>', dom, re.S)
    if not m:
        print("SIN PROBE. stderr:", p.stderr[-1500:])
        print("dom bytes", len(dom))
        return 1
    data = json.loads(H.unescape(m.group(1)))
    print(json.dumps(data, ensure_ascii=False, indent=1))
    open(dst, "w").write(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
