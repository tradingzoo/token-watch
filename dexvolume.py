"""DEX volume season: which weeks of the year usually see more on-chain trading, and what that suggests
for this month and next.

Source: DefiLlama, total DEX volume across all chains, one number per day
(https://api.llama.fi/overview/dexs, the same data as https://defillama.com/?dexsVolume=true).
Fetched at most every 12 hours into data/dex_volume.json; the page is rebuilt from that file every run.

The maths, in plain words (user, 6 Nov 2026: volume has grown a lot, keep old years relevant):
  1. Add the days up into full weeks, Monday to Sunday.
  2. Compare each week with the typical week in the 6 months either side of it (a centred 53-week
     average, taken on a log scale so one huge week doesn't drag its neighbours up). 1.20 = that week was
     20% busier than normal for that time. This removes the long-term growth, so a 2021 week and a
     2025 week can be compared even though 2025 volume is far bigger.
  3. For each week of the year, take the middle value (median) across the years, then smooth over 3 weeks.
     That is the "typical week" shape.
  4. Forecast = recent level (last 8 full weeks with the season taken out) x the typical shape ahead.
     Range = the quieter-year and busier-year (25th / 75th percentile) values for those weeks.
  5. Backtest: the same forecast made in the past, using only data known at the time, checked against
     what happened, next to the plain guess "the next month looks like the last 8 weeks".
Years start at 2021: in 2020 DEX volume grew about 100x, so "normal for that time" means nothing there.
"""
import datetime as dt, json, math, os, statistics as st, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "dex_volume.json")
URL = "https://api.llama.fi/overview/dexs?excludeTotalDataChartBreakdown=true&dataType=dailyVolume"
REFETCH_HOURS = 12
FIRST_YEAR = 2021
HALF = 26          # weeks either side for "normal"
LOOKBACK = 8       # weeks of recent level used for the forecast
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def refresh(log=print):
    """Fetch the daily series if the saved copy is older than REFETCH_HOURS. Never raises."""
    old = None
    try:
        old = json.load(open(CACHE, encoding="utf-8"))
        if time.time() - old.get("fetched", 0) < REFETCH_HOURS * 3600:
            return old
    except Exception:
        pass
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "token-watch"})
        d = json.load(urllib.request.urlopen(req, timeout=60))
        daily = [[int(t), round(float(v))] for t, v in d["totalDataChart"]]
        if len(daily) < 1000:
            raise ValueError(f"only {len(daily)} days")
        new = {"fetched": time.time(), "source": URL, "daily": daily}
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        json.dump(new, open(CACHE, "w", encoding="utf-8"), separators=(",", ":"))
        log(f"dex volume: {len(daily)} days, last {dt.datetime.fromtimestamp(daily[-1][0], dt.UTC):%Y-%m-%d}")
        return new
    except Exception as ex:
        log(f"dex volume fetch failed: {ex}")
        return old


# ---------- maths ----------

def _weeks(daily):
    """[(monday, total, days_in_week)] from the daily series."""
    wk = {}
    for t, v in daily:
        d = dt.datetime.fromtimestamp(t, dt.UTC).date()
        m = d - dt.timedelta(d.weekday())
        s = wk.setdefault(m, [0, 0])
        s[0] += v; s[1] += 1
    return sorted((m, s[0], s[1]) for m, s in wk.items())


def _woy(monday):
    """Week of the year 1-52 (ISO week; the odd week 53 counts as 52)."""
    return min(52, monday.isocalendar()[1])


def _year_of(monday):
    return (monday + dt.timedelta(3)).year


# US presidential cycle, by year % 4 (user, 6 Nov 2026: toggle by cycle year; 2026 is a midterm year)
CYCLE = {0: "Election year", 1: "Post-election year", 2: "Midterm year", 3: "Pre-election year"}


EVENTS = {2021: "Nov 2021 was the top of the bull run.", 2022: "Nov 2022 was the FTX collapse, which drove that month.",
          2024: "Nov 2024 was the US election itself."}


def _phase(y):
    return CYCLE[y % 4]


def _month_of(monday):
    return (monday + dt.timedelta(3)).month  # the month its Thursday falls in


def _q(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo = math.floor(k)
    return xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (k - lo)


def _index(full):
    """{monday: week volume / normal for that time}, centred log average, full weeks only."""
    logs = [math.log(max(v, 1)) for _, v, _ in full]
    out = {}
    for i, (m, v, _) in enumerate(full):
        if i < HALF or i + HALF >= len(full) or m.year < FIRST_YEAR - 1:
            continue
        w = logs[i - HALF:i + HALF + 1]
        out[m] = math.exp(logs[i] - st.mean(w))
    # re-centre so the typical week since FIRST_YEAR is exactly 1 (0%), otherwise growth curves tilt it up a bit
    c = math.exp(st.mean(math.log(x) for m, x in out.items() if m.year >= FIRST_YEAR))
    return {m: x / c for m, x in out.items()}


def _profile(idx, known_before=None, years=None, min_n=2):
    """Typical shape by week of year: {woy: (median, p25, p75, years_above, years)}, 3-week smoothed.
    known_before: only use weeks whose whole 'normal' window had happened by then (for the backtest)."""
    by = {w: [] for w in range(1, 53)}
    for m, x in idx.items():
        if m.year < FIRST_YEAR:
            continue
        if known_before and m + dt.timedelta(weeks=HALF + 1) > known_before:
            continue
        if years and _year_of(m) not in years:
            continue
        by[_woy(m)].append(x)
    if min(len(v) for v in by.values()) < min_n:
        return None
    raw = {w: (st.median(v), _q(v, .25), _q(v, .75), sum(x > 1 for x in v), len(v)) for w, v in by.items()}
    sm = {}
    for w in range(1, 53):
        nb = [raw[(w - 2) % 52 + 1], raw[w], raw[w % 52 + 1]]
        sm[w] = (st.mean(r[0] for r in nb), st.mean(r[1] for r in nb), st.mean(r[2] for r in nb), raw[w][3], raw[w][4])
    return sm


def _level(full, prof, before):
    """Recent level with the season taken out: geometric mean of the last LOOKBACK full weeks / their typical shape."""
    last = [(m, v) for m, v, _ in full if m + dt.timedelta(7) <= before][-LOOKBACK:]
    if len(last) < LOOKBACK:
        return None, None
    lv = math.exp(st.mean(math.log(v / prof[_woy(m)][0]) for m, v in last))
    plain = math.exp(st.mean(math.log(v) for _, v in last))
    return lv, plain


def _month_weeks(y, mo):
    """Mondays of the weeks whose Thursday is in that month."""
    d = dt.date(y, mo, 1)
    m = d - dt.timedelta(d.weekday())
    out = []
    while True:
        if _month_of(m) == mo and (m + dt.timedelta(3)).year == y:
            out.append(m)
        elif out:
            return out
        m += dt.timedelta(7)


def _backtest(full, idx):
    """For every month from 2023 on: forecast the month's weekly volume from the 8 weeks before it, using only what
    was known then. Returns rows (label, forecast, plain, actual)."""
    vol = {m: v for m, v, _ in full}
    rows = []
    for y in range(FIRST_YEAR + 2, full[-1][0].year + 1):
        for mo in range(1, 13):
            wks = _month_weeks(y, mo)
            if not all(w in vol for w in wks):
                continue
            start = wks[0]
            prof = _profile(idx, known_before=start)
            if not prof:
                continue
            lv, plain = _level(full, prof, start)
            if not lv:
                continue
            fc = sum(lv * prof[_woy(w)][0] for w in wks)
            rows.append((f"{MONTHS[mo - 1]} {y}", fc, plain * len(wks), sum(vol[w] for w in wks)))
    return rows


def analyse(data, today=None):
    today = today or dt.datetime.now(dt.UTC).date()
    cut = dt.datetime(today.year, today.month, today.day, tzinfo=dt.UTC).timestamp()
    data = dict(data, daily=[x for x in data["daily"] if x[0] < cut])  # today's number is still filling in
    wks = _weeks(data["daily"])
    full = [w for w in wks if w[2] == 7]
    idx = _index(full)
    last_day = dt.datetime.fromtimestamp(data["daily"][-1][0], dt.UTC).date()
    nm = (today.year + (today.month == 12), today.month % 12 + 1)
    # month table: each year's average index for the month
    mtab = {}
    for m, x in idx.items():
        if m.year >= FIRST_YEAR:
            mtab.setdefault(_month_of(m), {}).setdefault(_year_of(m), []).append(x)
    # log-scale average, so one spike week doesn't make a whole month look busy
    mtab = {mo: {y: math.exp(st.mean(map(math.log, v))) for y, v in ys.items()} for mo, ys in mtab.items()}
    base = {"full": full, "wks": wks, "idx": idx, "mtab": mtab, "last_day": last_day, "this": (today.year, today.month), "next": nm}
    allp = group(base, None)
    return dict(base, **allp, bt=_backtest(full, idx), fetched=data.get("fetched", 0))


def group(base, years):
    """Typical shape + forecast using only the given years (None = all)."""
    full, idx, last_day = base["full"], base["idx"], base["last_day"]
    allp = _profile(idx)
    prof = allp if years is None else _profile(idx, years=years, min_n=1)
    if years is not None:
        # with only 1-2 years in a group there is no real spread, so borrow the all-years spread around this group's value
        prof = {w: (p[0], p[0] * allp[w][1] / allp[w][0], p[0] * allp[w][2] / allp[w][0], p[3], p[4]) for w, p in prof.items()}
    lv, plain = _level(full, prof, last_day + dt.timedelta(1))
    vol = {m: (v, n) for m, v, n in base["wks"]}
    ahead = []
    for y, mo in (base["this"], base["next"]):
        for w in _month_weeks(y, mo):
            p = prof[_woy(w)]
            got = vol.get(w)
            ahead.append({"monday": w, "month": mo, "fc": lv * p[0], "lo": lv * p[1], "hi": lv * p[2],
                          "actual": got[0] if got and got[1] == 7 else None,
                          "so_far": got if got and got[1] < 7 else None})
    return {"prof": prof, "level": lv, "plain": plain, "ahead": ahead}


# ---------- page ----------

def _b(v):
    return f"${v / 1e9:,.1f}B" if v >= 1e9 else f"${v / 1e6:,.0f}M"


def _pct(x):
    return f"{(x - 1) * 100:+.0f}%"


def _season_svg(prof, focus, e):
    """52 bars, % busier or quieter than normal, around a 0 line. This month and next drawn full strength."""
    W, H, P, B, T = 720, 220, 40, 24, 10
    vals = [prof[w][0] - 1 for w in range(1, 53)]
    top = max(0.05, max(abs(v) for v in vals)) * 1.15
    mid = T + (H - B - T) / 2
    y = lambda v: mid - (H - B - T) / 2 * v / top
    step = (W - P - 6) / 52
    bw = step - 2
    out = [f"<svg viewBox='0 0 {W} {H}' role='img' class='chart season' aria-label='Typical DEX volume by week of the year, % vs normal'>"]
    for g in (-top / 1.15 / 2, top / 1.15 / 2):
        out.append(f"<line x1='{P}' x2='{W}' y1='{y(g):.1f}' y2='{y(g):.1f}' class='grid'/>"
                   f"<text x='{P - 6}' y='{y(g) + 4:.1f}' class='ax' text-anchor='end'>{g * 100:+.0f}%</text>")
    out.append(f"<line x1='{P}' x2='{W}' y1='{mid:.1f}' y2='{mid:.1f}' class='target'/>"
               f"<text x='{P - 6}' y='{mid + 4:.1f}' class='ax' text-anchor='end'>0%</text>")
    ref = dt.date(2025, 1, 1)
    for i, v in enumerate(vals):
        w = i + 1
        monday = dt.date.fromisocalendar(2025, w, 1)
        mo = _month_of(monday)
        x = P + 3 + i * step
        y0, y1 = sorted((y(0), y(v)))
        p = prof[w]
        tip = (f"Week {w} (around {monday + dt.timedelta(3):%d %b}): {_pct(p[0])} vs normal. "
               f"Busier than normal in {p[3]} of {p[4]} years. Quiet year {_pct(p[1])}, busy year {_pct(p[2])}.")
        out.append(f"<g class='bar{' on' if mo in focus else ''}'><rect x='{x:.1f}' y='{y0:.1f}' width='{bw:.1f}' height='{max(1.5, y1 - y0):.1f}' rx='2'/>"
                   f"<rect x='{x - 1:.1f}' y='{T}' width='{step:.1f}' height='{H - B - T}' class='hit'><title>{e(tip)}</title></rect></g>")
    for mo in range(1, 13):
        d = dt.date(2025, mo, 15)
        i = (d - ref).days / 7
        out.append(f"<text x='{P + 3 + i * step:.1f}' y='{H - 6}' class='ax{' fx' if mo in focus else ''}' text-anchor='middle'>{MONTHS[mo - 1]}</text>")
    return "".join(out) + "</svg>"


def _forecast_svg(full, ahead, plain, e):
    """Last 12 full weeks (actual) then the weeks of this month and next (forecast with range)."""
    past = [(m, v) for m, v, _ in full if m < ahead[0]["monday"]][-12:]
    items = [("past", m, v, None, None, None) for m, v in past]
    for a in ahead:
        items.append(("done" if a["actual"] else "fc", a["monday"], a["actual"] or a["fc"], a["lo"], a["hi"], a))
    W, H, P, B, T = 720, 220, 48, 24, 10
    top = max(max(i[2] for i in items), max(i[4] or 0 for i in items)) * 1.1
    y = lambda v: H - B - (H - B - T) * v / top
    n = len(items)
    step = (W - P - 6) / n
    bw = max(4, min(26, step - 4))
    out = [f"<svg viewBox='0 0 {W} {H}' role='img' class='chart fcast' aria-label='Weekly DEX volume, recent weeks and forecast'>"]
    for g in (top / 1.1 / 2, top / 1.1):
        out.append(f"<line x1='{P}' x2='{W}' y1='{y(g):.1f}' y2='{y(g):.1f}' class='grid'/>"
                   f"<text x='{P - 6}' y='{y(g) + 4:.1f}' class='ax' text-anchor='end'>{_b(g)}</text>")
    for i, (kind, m, v, lo, hi, a) in enumerate(items):
        x = P + 3 + i * step + (step - bw) / 2
        h = max(1.5, (H - B) - y(v))
        if kind == "fc":
            tip = f"Week of {m:%d %b}: forecast {_b(v)} (range {_b(lo)} to {_b(hi)})"
            if a["so_far"]:
                tip += f". So far: {_b(a['so_far'][0])} in {a['so_far'][1]} of 7 days"
            body = (f"<rect x='{x:.1f}' y='{y(v):.1f}' width='{bw:.1f}' height='{h:.1f}' rx='2' class='f'/>"
                    f"<line x1='{x + bw / 2:.1f}' x2='{x + bw / 2:.1f}' y1='{y(hi):.1f}' y2='{y(lo):.1f}' class='rng'/>")
            if a["so_far"]:
                sv = a["so_far"][0]
                body += f"<rect x='{x:.1f}' y='{y(sv):.1f}' width='{bw:.1f}' height='{max(1.5, (H - B) - y(sv)):.1f}' rx='2' class='sf'/>"
        else:
            tip = f"Week of {m:%d %b %Y}: {_b(v)} (actual)"
            if a:
                tip += f"; forecast was {_b(a['fc'])}"
            body = f"<rect x='{x:.1f}' y='{y(v):.1f}' width='{bw:.1f}' height='{h:.1f}' rx='2' class='a'/>"
        out.append(f"<g class='bar'>{body}<rect x='{P + 3 + i * step:.1f}' y='{T}' width='{step:.1f}' height='{H - B - T}' class='hit'><title>{e(tip)}</title></rect></g>")
    x0 = P + 3 + len(past) * step
    out.append(f"<line x1='{x0:.1f}' x2='{W}' y1='{y(plain):.1f}' y2='{y(plain):.1f}' class='plain'><title>Plain guess: {_b(plain)} a week (the last {LOOKBACK} weeks carry on)</title></line>"
               f"<text x='{x0 + 2:.1f}' y='{y(plain) + 14:.1f}' class='ax pl'>plain guess {_b(plain)}</text>")
    for i in sorted({0, len(past), n - 1}):
        out.append(f"<text x='{P + 3 + i * step + step / 2:.1f}' y='{H - 6}' class='ax' text-anchor='middle'>{items[i][1]:%d %b}</text>")
    return "".join(out) + "</svg>"


CSS = """
svg.chart.season .bar rect:first-child{fill:var(--chart);opacity:.32} svg.chart.season .bar.on rect:first-child{opacity:1}
svg.season .ax.fx{fill:var(--ink);font-weight:650}
svg.chart.fcast .bar rect.a{fill:var(--chart)} svg.chart.fcast .bar rect.f{fill:none;stroke:var(--chart);stroke-width:1.5;stroke-dasharray:3 2}
svg.fcast .ax.pl{fill:var(--ink);font-weight:600} svg.fcast .plain{stroke:var(--mid);stroke-width:2;stroke-dasharray:6 4} svg.chart.fcast .bar rect.sf{fill:var(--chart);opacity:.6} svg.fcast .rng{stroke:var(--ink);stroke-width:1.5;opacity:.5}
svg.chart .bar:hover rect{opacity:.75}
.lgd{display:flex;flex-wrap:wrap;gap:var(--s3);font-size:13px;color:var(--mute);margin:0 0 var(--s2)}
.lgd i{display:inline-block;width:12px;height:12px;border-radius:2px;vertical-align:-1px;margin-right:4px;background:var(--chart)}
.lgd i.f{background:none;border:1.5px dashed var(--chart)} .lgd i.sf{opacity:.55} .lgd i.o{opacity:.32} .lgd i.pl{height:0;border-top:2px dashed var(--mid);border-radius:0;background:none;vertical-align:3px}
.dvbar{display:flex;gap:var(--s1);flex-wrap:wrap;margin:var(--s1) 0 var(--s3);padding:var(--s1);background:var(--soft);border-radius:10px;width:fit-content}
.dvbar button{border:0;background:none;color:var(--mute);border-radius:6px;padding:6px 12px;cursor:pointer;font:inherit;font-size:14px;font-weight:550}
.dvbar button.on{background:var(--card);color:var(--ink);box-shadow:var(--shadow)} .dvbar button small{font-weight:400;opacity:.75}
table.sum th small{display:block;font-weight:400;font-size:11px} table.sum td.off{opacity:.35}
table.sum tr.fx td{font-weight:650} table.sum td.up{color:var(--hi)} table.sum td.dn{color:var(--lo)}
"""


def _view(r, years, e):
    """Tiles, both charts, forecast table and month table for one group of years (None = all years)."""
    g = group(r, years)
    prof, ahead, mtab = g["prof"], g["ahead"], r["mtab"]
    (ty, tm), (ny, nmo) = r["this"], r["next"]
    focus = {tm, nmo}
    all_years = sorted({y for v in mtab.values() for y in v})
    use = [y for y in all_years if years is None or y in years]

    def mrow(mo):
        ys = mtab.get(mo, {})
        vals = [ys[y] for y in use if y in ys]
        med = st.median(vals) if vals else None
        cells = "".join((f"<td class='{'up' if ys[y] > 1 else 'dn'}{'' if y in use else ' off'}'>{_pct(ys[y])}</td>" if y in ys else "<td>–</td>")
                        for y in all_years)
        return (f"<tr class='{'fx' if mo in focus else ''}'><td>{MONTHS[mo - 1]}</td><td>{_pct(med) if vals else '–'}</td>"
                f"<td>{sum(v > 1 for v in vals)} of {len(vals)}</td>{cells}</tr>"), med, sum(v > 1 for v in vals), len(vals)

    rows = {mo: mrow(mo) for mo in range(1, 13)}
    tiles = []
    for y, mo in ((ty, tm), (ny, nmo)):
        _, med, up, n = rows[mo]
        a = [x for x in ahead if x["month"] == mo]
        fc, lo, hi = (sum(x[f] for x in a) / len(a) for f in ("fc", "lo", "hi"))
        yrs = "year" if n == 1 else "years"
        tiles.append(f"<div class='tile'><span>{MONTHS[mo - 1]} usually</span><b>{_pct(med) if med else '–'}</b><small>vs a normal month · busier in {up} of {n} {yrs}</small></div>")
        tiles.append(f"<div class='tile'><span>{MONTHS[mo - 1]} {y} forecast</span><b>{_b(fc)}/wk</b><small>range {_b(lo)} to {_b(hi)} a week</small></div>")
    tiles.append(f"<div class='tile'><span>Last 8 weeks</span><b>{_b(g['plain'])}/wk</b><small>typical week, all chains = the plain guess</small></div>")

    def got(a):
        if a["actual"]:
            return _b(a["actual"])
        if a["so_far"]:
            return f"{_b(a['so_far'][0])} ({a['so_far'][1]} of 7 days)"
        return "–"

    ahead_rows = "".join(
        f"<tr class='{'fx' if a['actual'] or a['so_far'] else ''}'><td>{a['monday']:%d %b}</td><td>{_b(a['fc'])}</td><td>{_b(a['lo'])} to {_b(a['hi'])}</td><td>{_b(g['plain'])}</td>"
        f"<td>{got(a)}</td></tr>" for a in ahead)
    head_years = "".join(f"<th>{y}<small>{_phase(y).split()[0]}</small></th>" for y in all_years)
    shape = "middle value across the years" if years is None else " and ".join(str(y) + (" so far" if y == all_years[-1] else "") for y in use) + " only"
    return f"""<div class="tiles">{''.join(tiles)}</div>
<h3>Typical week of the year</h3>
<p class="lgd"><span><i></i>{MONTHS[tm - 1]} and {MONTHS[nmo - 1]}</span><span><i class="o"></i>other weeks</span><span>{shape}, smoothed over 3 weeks · hover a bar for each week</span></p>
{_season_svg(prof, focus, e)}
<h3>{MONTHS[tm - 1]} and {MONTHS[nmo - 1]}, week by week</h3>
<p class="lgd"><span><i></i>actual</span><span><i class="sf"></i>this week so far</span><span><i class="f"></i>forecast</span><span>thin line = range (quiet year to busy year)</span><span><i class="pl"></i>plain guess</span></p>
{_forecast_svg(r['full'], ahead, g['plain'], e)}
<details class="tv"><summary>Forecast table</summary><table class="sum"><tr><th>Week of</th><th>Season forecast</th><th>Range</th><th>Plain guess</th><th>Actual</th></tr>{ahead_rows}</table></details>
<h3>Every month, every year</h3>
<p class="muted">Each month's weeks vs normal for that time. Green = busier than normal, red = quieter.{'' if years is None else ' Faded columns are years outside this view.'}</p>
<table class="sum"><tr><th>Month</th><th>Usually</th><th>Busier in</th>{head_years}</tr>{''.join(rows[mo][0] for mo in range(1, 13))}</table>"""


# The toggle. Clicks are caught on the document, so they keep working after the page swaps in a fresh copy every
# few minutes; the chosen view is remembered for the visit and put back after each swap (TW_INIT runs after it).
DV_JS = """<script>
(()=>{const K='tw-dexvol-view';
const show=v=>{document.querySelectorAll('#dexvol .dvbar button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
document.querySelectorAll('#dexvol .dvview').forEach(d=>d.hidden=d.dataset.v!==v);};
const saved=()=>{try{return sessionStorage.getItem(K)}catch(e){return null}};
document.addEventListener('click',ev=>{const b=ev.target.closest('#dexvol .dvbar button');if(!b)return;
try{sessionStorage.setItem(K,b.dataset.v)}catch(e){}show(b.dataset.v);});
const re=()=>{const v=saved();if(v&&document.querySelector('#dexvol .dvview[data-v="'+v+'"]'))show(v);};
re();addEventListener('load',()=>{const o=window.TW_INIT;if(o&&!o.dv){window.TW_INIT=function(){o.apply(this,arguments);re();};window.TW_INIT.dv=1;}});})();
</script>"""


def html(e, log=print):
    try:
        data = refresh(log)
        if not data:
            return "<p>DEX volume data not fetched yet (DefiLlama). It appears after the next scan.</p>"
        r = analyse(data)
        all_years = sorted({y for v in r["mtab"].values() for y in v})
        now_phase = _phase(r["this"][0])
        views = [("all", "All years", None)]
        for k in (2, 3, 0, 1):  # midterm (now) first, then the order they come in
            views.append((CYCLE[k].split()[0].lower().replace("-", ""), CYCLE[k], {y for y in all_years if y % 4 == k}))
        blocks = {v: _view(r, ys, e) for v, _, ys in views}
    except Exception as ex:
        log(f"dex volume page failed: {ex}")
        return f"<p>DEX volume section failed this run: {e(str(ex))}</p>"
    (ty, tm), (ny, nmo) = r["this"], r["next"]
    bt = r["bt"]
    bt_html = ""
    if bt:
        err_s = st.median(abs(f / a - 1) for _, f, _, a in bt)
        err_p = st.median(abs(p / a - 1) for _, _, p, a in bt)
        wins = sum(abs(f / a - 1) < abs(p / a - 1) for _, f, p, a in bt)
        dir_ok = sum((f > p) == (a > p) for _, f, p, a in bt)
        fm = [x for x in bt if x[0].split()[0] in (MONTHS[tm - 1], MONTHS[nmo - 1])]
        bt_rows = "".join(f"<tr><td>{e(l)}</td><td>{_b(f)}</td><td>{_b(p)}</td><td>{_b(a)}</td><td>{'season' if abs(f / a - 1) < abs(p / a - 1) else 'plain guess'}</td></tr>" for l, f, p, a in fm)
        verdict = ("<b>So far the season pattern has not helped predict the next month.</b> " if err_s >= err_p or wins * 2 < len(bt)
                   else "<b>So far the season pattern has helped a little.</b> ")
        bt_html = (f"<p class='answer'>{verdict}Tested on {len(bt)} past months (2023 on, each using only data known at the time, all years): "
                   f"the season forecast was off by <b>{err_s * 100:.0f}%</b> on a typical month, the plain guess (&quot;next month = last 8 weeks&quot;) by <b>{err_p * 100:.0f}%</b>. "
                   f"Season was closer in <b>{wins} of {len(bt)}</b> months, and called up-or-down vs the last 8 weeks right in <b>{dir_ok} of {len(bt)}</b> (a coin toss gets about {len(bt) // 2}).</p>"
                   f"<details class='tv'><summary>Past {MONTHS[tm - 1]} and {MONTHS[nmo - 1]} forecasts vs what happened</summary>"
                   f"<table class='sum'><tr><th>Month</th><th>Season forecast</th><th>Plain guess</th><th>Actual</th><th>Closer</th></tr>{bt_rows}</table></details>")
    buttons, divs = [], []
    for v, label, ys in views:
        yl = "" if ys is None else " " + ", ".join(str(y) + ("*" if y == all_years[-1] else "") for y in sorted(ys))
        now = " (now)" if label == now_phase else ""
        buttons.append(f"<button data-v='{v}' class='{'on' if v == 'all' else ''}'>{label if ys is None else label.replace(' year', '')}{now}<small>{yl}</small></button>")
        note = ""
        if ys is not None:
            full_y = [y for y in sorted(ys) if y != all_years[-1]]
            note = (f"<p class='answer'><b>{label}s only: {len(full_y)} full year{'s' if len(full_y) != 1 else ''} of data "
                    f"({', '.join(map(str, full_y))}){' plus ' + str(all_years[-1]) + ' so far' if all_years[-1] in ys else ''}.</b> "
                    f"DefiLlama's useful DEX data starts in 2021, so this is one or two years, not a pattern. "
                    f"It can't be tested either: there's no earlier {label.lower()} in the data to check it against. "
                    f"The quiet/busy range is borrowed from all years."
                    + "".join(f" {EVENTS[y]}" for y in sorted(ys) if y in EVENTS) + "</p>")
        divs.append(f"<div class='dvview' data-v='{v}'{'' if v == 'all' else ' hidden'}>{note}{blocks[v]}</div>")
    fetched = dt.datetime.fromtimestamp(r["fetched"], dt.UTC)
    return f"""<h2 style="margin:22px 0 6px">DEX volume season: when on-chain trading usually picks up</h2>
<p class="top">Total DEX volume across all chains from <a href="https://defillama.com/?dexsVolume=true">DefiLlama</a> (data to {r['last_day']:%d %b %Y}, fetched {fetched:%d %b %H:%M} UTC), added up into weeks (Mon to Sun).
Volume has grown a lot since 2021, so each week is compared with the <b>typical week in the 6 months either side of it</b>: +20% means 20% busier than normal for that time. That way 2021 and 2025 count the same. Years used: {all_years[0]} to {all_years[-2]}, plus {all_years[-1]} so far ({ty} is a {now_phase.lower()} in the US presidential cycle).</p>
{bt_html}
<p class="muted" style="margin-bottom:0">Show the pattern from:</p>
<div class="dvbar">{''.join(buttons)}</div>
{''.join(divs)}
<p class="muted">* = so far this year. Read with care: there are only {len(all_years) - 1} full years, and the big months were mostly big events (Nov 2021 top of the bull run, Nov 2022 FTX collapse, Nov 2024 US election). A "season" built from a handful of events can repeat or not. Forecast = last {LOOKBACK} weeks' level with the season taken out, times the typical shape ahead. This tab is all chains, not Robinhood Chain alone. Method: dexvolume.py.</p>
{DV_JS}"""
