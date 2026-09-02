"""
Harvest NSE's public daily bhavcopy into a local end-of-day database.

One file per trading day, containing every listed security. Two formats exist:
  legacy (to ~Jun 2024): /content/historical/EQUITIES/<YYYY>/<MON>/cm<DDMONYYYY>bhav.csv.zip
  current (from ~Jul 2024): /content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip
Both are parsed by column NAME, not position, so a column order change cannot
silently shift prices into the wrong field.

Output is a SQLite database, which keeps memory flat across ~7M rows and gives
per-symbol lookups for free. Zips are cached on disk and completed days are
recorded, so the run is fully resumable.

Usage: python build_bhavcopy.py [START_ISO] [END_ISO]
"""
import csv, io, os, sqlite3, sys, time, zipfile, datetime
import urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "bhav_cache")
DB = os.path.join(HERE, "nse_eod.sqlite")
os.makedirs(CACHE, exist_ok=True)

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
EPOCH = datetime.date(1970, 1, 1)
GAP = 0.28                      # ~2.2 req/s, the rate nsearchives sustained cleanly
NEW_FROM = datetime.date(2024, 7, 1)

START = datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.date(2007, 9, 17)
END = datetime.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else datetime.date(2026, 9, 2)

_last = [0.0]


def urls_for(d):
    """Preferred format first, the other as fallback — the changeover is not razor sharp."""
    legacy = ("https://nsearchives.nseindia.com/content/historical/EQUITIES/%d/%s/cm%02d%s%dbhav.csv.zip"
              % (d.year, MON[d.month - 1], d.day, MON[d.month - 1], d.year))
    new = ("https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_%s_F_0000.csv.zip"
           % d.strftime("%Y%m%d"))
    return [new, legacy] if d >= NEW_FROM else [legacy, new]


def fetch(d):
    """Return the day's zip bytes, or None if NSE has no file (i.e. not a trading day)."""
    cp = os.path.join(CACHE, d.isoformat() + ".zip")
    if os.path.exists(cp):
        with open(cp, "rb") as f:
            return f.read() or None
    miss = os.path.join(CACHE, d.isoformat() + ".none")
    if os.path.exists(miss):
        return None

    for url in urls_for(d):
        delay = 2.0
        for _ in range(5):
            wait = GAP - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
            try:
                r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60)
                b = r.read()
                if b[:2] == b"PK":
                    with open(cp, "wb") as f:
                        f.write(b)
                    return b
                break                                   # served something that is not a zip
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break                               # try the other format
                if e.code in (403, 429, 500, 502, 503, 504):
                    time.sleep(delay); delay = min(delay * 2, 90); continue
                raise
            except Exception:
                time.sleep(delay); delay = min(delay * 2, 90); continue
    open(miss, "wb").close()
    return None


def parse(zbytes):
    """-> list of (symbol, o, h, l, c) for the regular equity series only."""
    z = zipfile.ZipFile(io.BytesIO(zbytes))
    name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
    if not name:
        return []
    text = z.read(name).decode("utf-8", "replace")
    rdr = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().upper() for h in next(rdr)]
    except StopIteration:
        return []
    idx = {h: i for i, h in enumerate(header)}

    def col(*names):
        for n in names:
            if n in idx:
                return idx[n]
        return None

    c_sym = col("TCKRSYMB", "SYMBOL")
    c_ser = col("SCTYSRS", "SERIES")
    c_o = col("OPNPRIC", "OPEN")
    c_h = col("HGHPRIC", "HIGH")
    c_l = col("LWPRIC", "LOW")
    c_c = col("CLSPRIC", "CLOSE")
    c_typ = col("FININSTRMTP")                          # current format carries derivatives too
    if None in (c_sym, c_ser, c_o, c_h, c_l, c_c):
        raise RuntimeError("unrecognised bhavcopy columns: %s" % header[:18])

    out = []
    for row in rdr:
        if len(row) <= max(c_sym, c_ser, c_o, c_h, c_l, c_c):
            continue
        if (row[c_ser] or "").strip().upper() != "EQ":
            continue
        if c_typ is not None and (row[c_typ] or "").strip().upper() not in ("STK", ""):
            continue
        try:
            o, h, l, c = (float(row[c_o]), float(row[c_h]), float(row[c_l]), float(row[c_c]))
        except ValueError:
            continue
        if not (c > 0 and l <= c <= h and l <= o <= h):
            continue
        out.append(((row[c_sym] or "").strip().upper(), o, h, l, c))
    return out


db = sqlite3.connect(DB)
db.execute("PRAGMA journal_mode=OFF")
db.execute("PRAGMA synchronous=OFF")
db.execute("CREATE TABLE IF NOT EXISTS px(sym TEXT, d INT, o REAL, h REAL, l REAL, c REAL,"
           " PRIMARY KEY(sym,d)) WITHOUT ROWID")
db.execute("CREATE TABLE IF NOT EXISTS days(d INT PRIMARY KEY, n INT)")
db.commit()
done = {r[0] for r in db.execute("SELECT d FROM days")}

dates = []
cur = START
while cur <= END:
    # weekdays always; weekends only in the months NSE holds special sessions
    if cur.weekday() < 5 or cur.month in (2, 10, 11):
        dates.append(cur)
    cur += datetime.timedelta(1)
todo = [d for d in dates if (d - EPOCH).days not in done]

print("[bhavcopy] %s -> %s | %d candidate days, %d already done, %d to fetch"
      % (START, END, len(dates), len(dates) - len(todo), len(todo)), flush=True)

t0 = time.time()
rows_total = 0
trading = 0
for i, d in enumerate(todo, 1):
    di = (d - EPOCH).days
    try:
        z = fetch(d)
    except Exception as e:
        print("  ! %s fetch failed: %s" % (d, e), flush=True)
        continue
    if z is None:
        db.execute("INSERT OR REPLACE INTO days(d,n) VALUES(?,0)", (di,))
    else:
        try:
            recs = parse(z)
        except Exception as e:
            print("  ! %s parse failed: %s" % (d, e), flush=True)
            continue
        if recs:
            db.executemany("INSERT OR REPLACE INTO px VALUES(?,?,?,?,?,?)",
                           [(s, di, o, h, l, c) for (s, o, h, l, c) in recs])
            trading += 1
            rows_total += len(recs)
        db.execute("INSERT OR REPLACE INTO days(d,n) VALUES(?,?)", (di, len(recs)))
    if i % 100 == 0 or i == len(todo):
        db.commit()
        el = time.time() - t0
        print("  %5d/%d  %s  %d trading days, %s rows  |  %.0fs elapsed, ~%.0fs left"
              % (i, len(todo), d, trading, format(rows_total, ","), el, el / i * (len(todo) - i)),
              flush=True)
db.commit()

db.execute("CREATE INDEX IF NOT EXISTS px_sym ON px(sym)")
db.commit()

nsym = db.execute("SELECT COUNT(DISTINCT sym) FROM px").fetchone()[0]
nrow = db.execute("SELECT COUNT(*) FROM px").fetchone()[0]
ndays = db.execute("SELECT COUNT(*) FROM days WHERE n>0").fetchone()[0]
lo, hi = db.execute("SELECT MIN(d),MAX(d) FROM px").fetchone()
print("\n[bhavcopy] DONE  %s symbols | %s rows | %d trading days | %s -> %s | db %.0f MB"
      % (format(nsym, ","), format(nrow, ","), ndays,
         EPOCH + datetime.timedelta(lo or 0), EPOCH + datetime.timedelta(hi or 0),
         os.path.getsize(DB) / 1e6), flush=True)
print("[bhavcopy] top by session count:", flush=True)
for s, n in db.execute("SELECT sym,COUNT(*) c FROM px GROUP BY sym ORDER BY c DESC LIMIT 5"):
    print("    %-14s %d" % (s, n), flush=True)
