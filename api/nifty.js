/**
 * GET /api/nifty?since=YYYY-MM-DD  → sessions after `since`, for topping up a baseline
 * GET /api/nifty?full=1            → the whole verified series, in the page's encoded form
 *
 * Exists because Yahoo's chart API sends no CORS header, so a browser cannot call it
 * directly. The hosted copy of the page ships without an embedded dataset and asks for
 * ?full=1; the downloadable copy has the data baked in and only ever uses ?since=.
 *
 * PATCH below is the set of real NSE sessions the bulk feed is missing or has blank —
 * every value taken from the exchange's own end-of-day index file
 * (nsearchives.nseindia.com/content/indices/ind_close_all_<DDMMYYYY>.csv). Three of them
 * are the first trading day of their year, so without this table 2016, 2018 and 2019 would
 * report the wrong starting price. The rest are Diwali Muhurat and Union Budget weekend
 * sessions plus a few weekdays Yahoo simply dropped.
 */

const START = '2007-09-17'; // first session Yahoo has for ^NSEI
const DAY = 86400000;

const PATCH = [
  ['2013-01-01', 5937.65, 5963.9, 5935.2, 5950.85],
  ['2013-11-03', 6332.05, 6342.95, 6311.15, 6317.35],
  ['2014-01-01', 6323.8, 6327.2, 6298.25, 6301.65],
  ['2014-02-17', 6057.1, 6080.65, 6038.3, 6073.3],
  ['2014-03-22', 6497.8, 6502.65, 6481.35, 6494.9],
  ['2014-10-23', 8027.7, 8031.75, 8008.85, 8014.55],
  ['2015-01-01', 8272.8, 8294.7, 8248.75, 8284.0],
  ['2015-02-28', 8913.05, 8941.1, 8751.35, 8901.85],
  ['2015-04-15', 8844.75, 8844.8, 8722.4, 8750.2],
  ['2015-11-11', 7838.8, 7847.95, 7819.1, 7825.0],
  ['2016-01-01', 7938.45, 7972.55, 7909.8, 7963.2],
  ['2016-08-12', 8605.45, 8684.3, 8604.45, 8672.15],
  ['2016-10-30', 8672.35, 8678.25, 8616.25, 8625.7],
  ['2018-01-01', 10531.7, 10537.85, 10423.1, 10435.55],
  ['2019-01-01', 10881.7, 10923.6, 10807.1, 10910.1],
  ['2019-02-13', 10870.55, 10891.65, 10772.1, 10793.65],
  ['2019-03-29', 11625.45, 11630.35, 11570.15, 11623.9],
  ['2019-10-27', 11662.25, 11672.4, 11604.6, 11627.15],
  ['2020-02-01', 11939.0, 12017.35, 11633.3, 11661.85],
  ['2020-11-14', 12823.35, 12828.7, 12749.45, 12780.25],
  ['2023-11-12', 19547.25, 19547.25, 19510.25, 19525.55],
  ['2026-02-01', 25333.75, 25440.9, 24571.75, 24825.45],
  ['2026-08-28', 24122.6, 24188.3, 24076.85, 24175.65],
  ['2026-09-01', 24077.55, 24143.15, 23952.55, 24055.8],
];

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/126.0 Safari/537.36';

function isoOf(ms) {
  const d = new Date(ms);
  return (
    d.getUTCFullYear() +
    '-' + String(d.getUTCMonth() + 1).padStart(2, '0') +
    '-' + String(d.getUTCDate()).padStart(2, '0')
  );
}

async function yahoo(fromSec) {
  const to = Math.floor(Date.now() / 1000) + 86400;
  const url =
    'https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI' +
    '?period1=' + fromSec + '&period2=' + to + '&interval=1d';
  const r = await fetch(url, { headers: { 'User-Agent': UA, Accept: '*/*' } });
  if (!r.ok) throw new Error('upstream ' + r.status);
  const j = await r.json();
  const res = j && j.chart && j.chart.result && j.chart.result[0];
  if (!res || !res.timestamp) throw new Error('unexpected upstream payload');
  const off = (res.meta.gmtoffset || 0) * 1000;
  const q = res.indicators.quote[0];
  const rows = new Map();
  for (let i = 0; i < res.timestamp.length; i++) {
    const o = q.open[i], h = q.high[i], l = q.low[i], c = q.close[i];
    if (o == null || h == null || l == null || c == null) continue;
    rows.set(isoOf(res.timestamp[i] * 1000 + off), [
      +o.toFixed(2), +h.toFixed(2), +l.toFixed(2), +c.toFixed(2),
    ]);
  }
  return rows;
}

/** Same base-36 delta encoding the offline build produces, so the page decodes either identically. */
function encode(sorted) {
  const p = (x) => Math.round(x * 100);
  const base = Date.parse(START + 'T00:00:00Z');
  const d = [], c = [], o = [], h = [], l = [];
  let prevDay = null, prevC = 0;
  for (const [iso, v] of sorted) {
    const day = Math.round((Date.parse(iso + 'T00:00:00Z') - base) / DAY);
    d.push((prevDay === null ? day : day - prevDay).toString(36));
    prevDay = day;
    const cc = p(v[3]);
    c.push((cc - prevC).toString(36));
    prevC = cc;
    o.push((p(v[0]) - cc).toString(36));
    h.push((p(v[1]) - cc).toString(36));
    l.push((p(v[2]) - cc).toString(36));
  }
  return {
    base: START, n: sorted.length,
    d: d.join(','), c: c.join(','), o: o.join(','), h: h.join(','), l: l.join(','),
  };
}

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');
  if (req.method === 'OPTIONS') return res.status(204).end();

  const q = req.query || {};
  const full = q.full === '1' || q.full === 'true';
  const since = String(q.since || '').slice(0, 10);

  if (!full && !/^\d{4}-\d{2}-\d{2}$/.test(since)) {
    return res.status(400).json({ error: 'pass ?full=1 or ?since=YYYY-MM-DD' });
  }

  try {
    if (full) {
      const rows = await yahoo(Math.floor(Date.parse(START + 'T00:00:00Z') / 1000) - 14 * 86400);
      for (const [iso, o, h, l, c] of PATCH) rows.set(iso, [o, h, l, c]); // NSE wins
      const sorted = [...rows.entries()]
        .filter(([iso]) => iso >= START)
        .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
      if (sorted.length < 4000) throw new Error('series too short: ' + sorted.length);
      res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=86400');
      return res.status(200).json(encode(sorted));
    }

    // Re-fetch a fortnight before `since` so a partially-written last session is corrected.
    const rows = await yahoo(Math.floor((Date.parse(since + 'T00:00:00Z') - 14 * DAY) / 1000));
    for (const [iso, o, h, l, c] of PATCH) if (iso > since) rows.set(iso, [o, h, l, c]);
    const out = [...rows.entries()]
      .filter(([iso]) => iso > since)
      .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
      .map(([iso, v]) => [iso, v[0], v[1], v[2], v[3]]);
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=86400');
    return res.status(200).json({ last: out.length ? out[out.length - 1][0] : since, rows: out });
  } catch (err) {
    res.setHeader('Cache-Control', 'no-store');
    return res.status(502).json({ error: String((err && err.message) || err), rows: [] });
  }
};
