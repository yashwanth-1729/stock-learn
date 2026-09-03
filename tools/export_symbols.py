"""
Turn the harvested bhavcopy database into per-symbol series the page can consume.

Emits the same base-36 delta encoding index.html already decodes, so the front end
needs no changes to read exchange-sourced data instead of the bulk feed.

Bhavcopy publishes prices AS TRADED, so a chart drawn straight from it shows a 2:1
split as a 50% crash. Factors derived by tools/derive_adjustments.py are applied here,
covering splits, bonuses, rights issues and demergers alike. Without that file the
output is raw and is labelled so.

Usage: python export_symbols.py [OUT_DIR] [--min-days N] [--adjust FILE]
"""
import datetime, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "nse_eod.sqlite")
EPOCH = datetime.date(1970, 1, 1)
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"

args = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = args[0] if args else os.path.join(HERE, "export")
MIN_DAYS = 250
ADJ = {}
if "--min-days" in sys.argv:
    MIN_DAYS = int(sys.argv[sys.argv.index("--min-days") + 1])
_adj_path = os.path.join(HERE, "..", "data", "adjustments.json")
if "--adjust" in sys.argv:
    _adj_path = sys.argv[sys.argv.index("--adjust") + 1]
if os.path.exists(_adj_path):
    with open(_adj_path, encoding="utf-8") as f:
        ADJ = json.load(f)

os.makedirs(os.path.join(OUT, "eq"), exist_ok=True)


def b36(n):
    if n == 0:
        return "0"
    sign = "-" if n < 0 else ""
    n = abs(n)
    s = ""
    while n:
        n, r = divmod(n, 36)
        s = DIGITS[r] + s
    return sign + s


def adjust(rows, sym):
    """Apply the derived factor timeline: adjusted(d) = astraded(d) / factor_on(d).

    Steps are [effective_from, factor] with the factor holding until the next entry,
    and the final entry is 1.0 — so present-day prices pass through untouched.
    """
    rec = ADJ.get(sym) or ADJ.get(sym.replace(".NS", "")) or {}
    steps = rec.get("steps") or []
    if not steps:
        return rows, 0
    marks = [((datetime.date.fromisoformat(d) - EPOCH).days, float(f)) for d, f in steps]
    marks.sort()
    out = []
    for d, o, h, l, c in rows:
        f = 1.0
        for md, mf in marks:
            if d >= md:
                f = mf
            else:
                break
        if f <= 0:
            f = 1.0
        out.append((d, o / f, h / f, l / f, c / f))
    return out, len([m for m in marks if abs(m[1] - 1) > 1e-9])


db = sqlite3.connect(DB)
syms = [r[0] for r in db.execute(
    "SELECT sym FROM px GROUP BY sym HAVING COUNT(*) >= ? ORDER BY sym", (MIN_DAYS,))]
print("exporting %d symbols with >= %d sessions -> %s" % (len(syms), MIN_DAYS, OUT), flush=True)

index = []
total = 0
adjusted = 0
for i, sym in enumerate(syms, 1):
    rows = list(db.execute("SELECT d,o,h,l,c FROM px WHERE sym=? ORDER BY d", (sym,)))
    if len(rows) < 2:
        continue
    rows, nsp = adjust(rows, sym)
    if nsp:
        adjusted += 1

    base = EPOCH + datetime.timedelta(rows[0][0])
    dd, cc, oo, hh, ll = [], [], [], [], []
    prev_day = None
    prev_c = 0
    for d, o, h, l, c in rows:
        off = d - rows[0][0]
        dd.append(b36(off if prev_day is None else off - prev_day))
        prev_day = off
        ci = int(round(c * 100))
        cc.append(b36(ci - prev_c))
        prev_c = ci
        oo.append(b36(int(round(o * 100)) - ci))
        hh.append(b36(int(round(h * 100)) - ci))
        ll.append(b36(int(round(l * 100)) - ci))

    doc = {"symbol": sym + ".NS", "source": "NSE bhavcopy",
           "adjusted": bool(nsp), "first": base.isoformat(),
           "last": (EPOCH + datetime.timedelta(rows[-1][0])).isoformat(),
           "series": {"base": base.isoformat(), "n": len(rows),
                      "d": ",".join(dd), "c": ",".join(cc),
                      "o": ",".join(oo), "h": ",".join(hh), "l": ",".join(ll)}}
    path = os.path.join(OUT, "eq", sym + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    total += os.path.getsize(path)
    index.append({"symbol": sym + ".NS", "n": len(rows),
                  "first": doc["first"], "last": doc["last"]})
    if i % 250 == 0:
        print("  %d/%d  %.0f MB so far" % (i, len(syms), total / 1e6), flush=True)

with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
    json.dump({"count": len(index), "symbols": index}, f, separators=(",", ":"))

print("\nexported %d symbols | %.1f MB total | %.0f KB average"
      % (len(index), total / 1e6, total / max(1, len(index)) / 1e3))
print("corporate-action adjusted: %d symbols (%s)"
      % (adjusted, ("factors from %s" % os.path.basename(_adj_path)) if ADJ
         else "no factors file - output is AS TRADED"))
