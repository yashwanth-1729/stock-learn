"""
Turn the harvested bhavcopy database into per-symbol series the page can consume.

Emits the same base-36 delta encoding index.html already decodes, so the front end
needs no changes to read exchange-sourced data instead of the bulk feed.

Note on splits: bhavcopy publishes prices AS TRADED. A chart drawn straight from it
shows a 2:1 split as a 50% crash. Adjustment factors are therefore applied from a
splits file if one is supplied (--splits splits.json, mapping SYMBOL -> [[iso, "2:1"], ...]);
without it the output is raw and is labelled as such.

Usage: python export_symbols.py [OUT_DIR] [--min-days N] [--splits FILE]
"""
import datetime, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "nse_eod.sqlite")
EPOCH = datetime.date(1970, 1, 1)
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"

args = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = args[0] if args else os.path.join(HERE, "export")
MIN_DAYS = 250
SPLITS = {}
if "--min-days" in sys.argv:
    MIN_DAYS = int(sys.argv[sys.argv.index("--min-days") + 1])
if "--splits" in sys.argv:
    with open(sys.argv[sys.argv.index("--splits") + 1], encoding="utf-8") as f:
        SPLITS = json.load(f)

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


def ratio(txt):
    """'2:1' -> 2.0 — the factor pre-split prices must be divided by."""
    try:
        a, b = str(txt).split(":")
        return float(a) / float(b)
    except Exception:
        return 1.0


def adjust(rows, sym):
    """Scale pre-split prices so the series is continuous, newest prices untouched."""
    sp = SPLITS.get(sym) or SPLITS.get(sym + ".NS") or []
    if not sp:
        return rows, 0
    events = sorted(((datetime.date.fromisoformat(d) - EPOCH).days, ratio(r)) for d, r in sp)
    out = []
    for d, o, h, l, c in rows:
        f = 1.0
        for ed, er in events:
            if d < ed:
                f *= er
        out.append((d, o / f, h / f, l / f, c / f))
    return out, len(events)


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
print("split-adjusted: %d symbols (%s)"
      % (adjusted, "splits file supplied" if SPLITS else "no splits file - output is AS TRADED"))
