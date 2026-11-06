"""Active vs resting tokens, launch/graduation times, the run log and the daily study (user, 6 Nov 2026).

Why: every listed token used to be fully checked every scan, so scans grew with the list (39 min on 6 Nov, for
a 15-minute schedule). Now:
  ACTIVE  = shown on the page (61+), a 30-day test token, launched in the last 2 days, graduated in the last
            2 days, or woken in the last 2 days. Checked every scan (price, status, X), as before.
  RESTING = everything else (hidden and older). Nothing is deleted: each one gets a price, Pons-stage and X check
            once a day, spread across the scans (a small slice each run), so the load stays flat.
  WAKE    = a resting token goes back to active if it graduates, reaches $25k, or doubles from its value when it
            started resting.
Data behind the 2 days (6 Nov study, notes/2026-11-06_tracking_study.md): of our listed Pons tokens 2+ days old,
77% of those that graduated did so within 6 hours; the late ones (ZOKI after 7.9 days, MORROW after 14.7) took days,
so a daily check catches them within a day.

Files: data/tiers.json (times, resting, woken), data/runs.csv (one row per scan), data/studies/<date>.json (daily).
"""
import csv, datetime, json, math, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "data", "tiers.json")
RUNS = os.path.join(HERE, "data", "runs.csv")
STUDIES = os.path.join(HERE, "data", "studies")
ACTIVE_DAYS = 2
WAKE_VALUE = 25_000
WAKE_X = 2.0
TIMES_PER_RUN = 25  # Pons pages fetched per run for launch/graduation times (a one-off backfill, then new tokens)
RUN_FIELDS = ["time", "minutes", "active", "resting", "resting_checked", "rescored", "woken", "listed"]


def load():
    db = json.load(open(FILE, encoding="utf-8")) if os.path.exists(FILE) else {}
    for k in ("times", "resting", "woken"):
        db.setdefault(k, {})
    return db


def save(db):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    tmp = FILE + ".tmp"
    json.dump(db, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, FILE)


def _iso(s):
    return datetime.datetime.fromisoformat(s) if s else None


def _days(now, ts):
    return (now - ts).total_seconds() / 86400 if ts else None


def record_times(db, addr, o, now):
    """o = a token's own Pons page data (createdAt, graduatedAt, stage). Saves launch and graduation times."""
    if not o or not o.get("createdAt"):
        return
    t = db["times"].setdefault(addr, {})
    t.update({"pons": True, "created": int(o["createdAt"]), "stage": o.get("stage"), "checked": now.isoformat(timespec="seconds")})
    if o.get("graduatedAt"):
        t["graduated"] = int(o["graduatedAt"])


def launched_at(db, addr, r):
    t = db["times"].get(addr)
    if t and t.get("created"):
        return datetime.datetime.fromtimestamp(t["created"], datetime.timezone.utc)
    return _iso(r.get("launched") or r.get("first_seen"))


def is_active(db, addr, r, now, keep, show_at):
    if r["scoring"]["score"] >= show_at or addr in keep:
        return True
    age = _days(now, launched_at(db, addr, r))
    if age is None or age < ACTIVE_DAYS:
        return True
    g = db["times"].get(addr, {}).get("graduated")
    if g and _days(now, datetime.datetime.fromtimestamp(g, datetime.timezone.utc)) < ACTIVE_DAYS:
        return True
    w = db["woken"].get(addr)
    return bool(w and _days(now, _iso(w["at"])) < ACTIVE_DAYS)


def split(db, rows, now, keep, show_at, pdb):
    """(active addresses, resting addresses). Keeps db['resting'] in step: new resters get their starting value."""
    active, resting = set(), set()
    for r in rows:
        a = r["address"].lower()
        (active if is_active(db, a, r, now, keep, show_at) else resting).add(a)
    for a in resting:
        if a not in db["resting"]:
            db["resting"][a] = {"since": now.isoformat(timespec="seconds"),
                                "value": (pdb.get(a) or {}).get("now_mcap"), "checked": None}
    for a in [a for a in db["resting"] if a not in resting]:
        db["resting"].pop(a)
    return active, resting


def due_resting(db, resting, now, runs_per_day=60):
    """The slice of resting tokens to check this run: not checked in the last 24 hours, oldest first.
    Size = enough to get through all of them in a day at ~60 runs a day (at least 10)."""
    per_run = max(10, math.ceil(len(resting) / runs_per_day))
    due = [a for a in resting if not db["resting"][a].get("checked")
           or _days(now, _iso(db["resting"][a]["checked"])) >= 1]
    due.sort(key=lambda a: db["resting"][a].get("checked") or "")
    return due[:per_run]


def wake(db, a, why, m, now, symbols):
    rest = db["resting"].pop(a, None) or {}
    db["woken"][a] = {"at": now.isoformat(timespec="seconds"), "why": why, "symbol": symbols.get(a, "?"),
                      "value_rest": rest.get("value"), "value_woken": m}


def wake_check(db, resting, slice_checked, pdb, now, symbols):
    """Every run, for every resting token priced this run (exchange prices come in one cheap batch for all of them):
    wake it if it graduated, reached $25k or doubled. 6 Nov: PRIORS and ORBIO graduated after 5-6 days and passed
    $500k within a day, so waking must not wait for the daily slice. Returns the woken addresses."""
    woke = []
    for a in slice_checked:
        if a in db["resting"]:
            db["resting"][a]["checked"] = now.isoformat(timespec="seconds")
    for a in list(resting):
        rest = db["resting"].get(a)
        if not rest:
            continue
        p = pdb.get(a) or {}
        if p.get("now_at") != now.isoformat(timespec="seconds"):
            continue  # not priced this run
        m = p.get("now_mcap") or 0
        if rest.get("value") is None:  # first price since it started resting: that is its starting value
            rest["value"] = m or None
            continue
        start = rest["value"]
        g = db["times"].get(a, {}).get("graduated")
        why = None
        if g and datetime.datetime.fromtimestamp(g, datetime.timezone.utc).isoformat() >= rest["since"]:
            why = "graduated from the Pons curve"
        elif m >= WAKE_VALUE > start:  # crossed $25k from below (6 Nov test: tokens already above it woke at once)
            why = f"crossed $25k (${start/1e3:.1f}k → ${m/1e3:.0f}k)"
        elif m >= WAKE_X * start:
            why = f"doubled (${start/1e3:.1f}k → ${m/1e3:.1f}k)"
        if why:
            wake(db, a, why, m, now, symbols)
            woke.append(a)
    return woke


def log_run(row):
    new = not os.path.exists(RUNS)
    with open(RUNS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RUN_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def read_runs(n=60):
    if not os.path.exists(RUNS):
        return []
    return list(csv.DictReader(open(RUNS, encoding="utf-8")))[-n:]


BUCKETS = [("Within 6 hours", 0, 0.25), ("6–24 hours", 0.25, 1), ("1–2 days", 1, 2), ("2–7 days", 2, 7), ("7+ days", 7, 1e9)]


def graduation_study(db, rows, pdb, now):
    """Our listed Pons tokens launched 2+ days ago: when did they graduate, and what are the late ones worth now?"""
    seen, out = set(), {"buckets": {b[0]: 0 for b in BUCKETS}, "never": 0, "late": [], "total": 0}
    for r in rows:
        a = r["address"].lower()
        t = db["times"].get(a)
        if a in seen or not t or not t.get("created"):
            continue
        seen.add(a)
        created = datetime.datetime.fromtimestamp(t["created"], datetime.timezone.utc)
        if _days(now, created) < ACTIVE_DAYS:
            continue
        out["total"] += 1
        if not t.get("graduated"):
            out["never"] += 1
            continue
        d = (t["graduated"] - t["created"]) / 86400
        for name, lo, hi in BUCKETS:
            if lo <= d < hi:
                out["buckets"][name] += 1
        if d >= ACTIVE_DAYS:
            out["late"].append({"symbol": r.get("symbol") or "?", "days": round(d, 1), "score": r["scoring"]["score"],
                                "now": (pdb.get(a) or {}).get("now_mcap")})
    out["late"].sort(key=lambda x: -(x["now"] or 0))
    return out


def save_study(study):
    """One file per day (the last run of the day wins), so the evidence can be compared over time."""
    os.makedirs(STUDIES, exist_ok=True)
    day = study["time"][:10]
    json.dump(study, open(os.path.join(STUDIES, f"{day}.json"), "w", encoding="utf-8"), indent=1)


# ---------- the "Scanner health" tab ----------

def _bars_svg(vals, labels, tips, e, target=None, unit=""):
    """Vertical bars, one series, newest on the right. Thin marks, rounded tops, recessive axis, hover tooltips."""
    if not vals:
        return "<p class='muted'>No runs logged yet.</p>"
    W, H, P, B = 720, 160, 34, 22
    top = max(max(vals), target or 0) * 1.15 or 1
    n = len(vals)
    step = (W - P - 8) / n
    bw = max(3, min(18, step - 2))
    y = lambda v: H - B - (H - B - 8) * v / top
    out = [f"<svg viewBox='0 0 {W} {H}' role='img' class='chart' aria-label='{e(labels[0] if labels else '')}'>"]
    for g in (0, top / 2):
        out.append(f"<line x1='{P}' x2='{W}' y1='{y(g):.1f}' y2='{y(g):.1f}' class='grid'/>"
                   f"<text x='{P - 6}' y='{y(g) + 4:.1f}' class='ax' text-anchor='end'>{g:.0f}{unit}</text>")
    if target:
        out.append(f"<line x1='{P}' x2='{W}' y1='{y(target):.1f}' y2='{y(target):.1f}' class='target'/>"
                   f"<text x='{W - 2}' y='{y(target) - 5:.1f}' class='ax' text-anchor='end'>target {target:.0f}{unit}</text>")
    for i, v in enumerate(vals):
        x = P + 4 + i * step
        h = max(1.5, (H - B) - y(v))
        out.append(f"<g class='bar'><rect x='{x:.1f}' y='{y(v):.1f}' width='{bw:.1f}' height='{h:.1f}' rx='2'/>"
                   f"<rect x='{x - 1:.1f}' y='8' width='{step:.1f}' height='{H - B - 8}' class='hit'><title>{e(tips[i])}</title></rect></g>")
    for i in (0, n - 1):
        out.append(f"<text x='{P + 4 + i * step + bw / 2:.1f}' y='{H - 6}' class='ax' text-anchor='middle'>{e(labels[i])}</text>")
    return "".join(out) + "</svg>"


def _hbars(items, e):
    """Horizontal bars for a small set of categories, value labelled at the end of each bar."""
    top = max([v for _, v, _ in items] + [1])
    return "<div class='hbars'>" + "".join(
        f"<div class='hrow' title='{e(tip)}'><span class='hl'>{e(name)}</span>"
        f"<span class='ht'><span class='hb' style='width:{100 * v / top:.1f}%'></span></span><span class='hv'>{v}</span></div>"
        for name, v, tip in items) + "</div>"


def html(db, study, runs, e, money):
    tiles = [("Active", study["active"], "checked every scan"), ("Resting", study["resting"], "checked once a day"),
             ("Woken (7 days)", study["woken_7d"], "came back to active"),
             ("Last scan", f"{float(runs[-1]['minutes']):.0f} min" if runs else "–", "target under 15")]
    out = ["<h2 style='margin:22px 0 6px'>Scanner health</h2>",
           "<p class='top'>How the scanner spends its time, and the data behind which tokens get checked how often. "
           "Rules: tiers.py and SCORING.md.</p>",
           "<div class='tiles'>" + "".join(f"<div class='tile'><b>{e(str(v))}</b><span>{e(k)}</span><small>{e(s)}</small></div>"
                                          for k, v, s in tiles) + "</div>"]
    # scan time
    mins = [float(r["minutes"]) for r in runs]
    tips = [f"{r['time'][5:16].replace('T', ' ')} UTC · {float(r['minutes']):.1f} min · {r['active']} active · "
            f"{r['resting_checked']} resting checked · {r['rescored']} re-scored" for r in runs]
    labels = [r["time"][5:16].replace("T", " ") for r in runs]
    out.append("<h3>Scan time per run (minutes)</h3>" + _bars_svg(mins, labels, tips, e, target=15)
               + "<details class='tv'><summary>Table</summary><table class='sum'><tr><th>Run (UTC)</th><th>Minutes</th><th>Active</th>"
               "<th>Resting checked</th><th>Re-scored</th><th>Woken</th></tr>"
               + "".join(f"<tr><td>{e(r['time'][5:16].replace('T', ' '))}</td><td>{float(r['minutes']):.1f}</td><td>{e(r['active'])}</td>"
                         f"<td>{e(r['resting_checked'])}</td><td>{e(r['rescored'])}</td><td>{e(r['woken'])}</td></tr>" for r in reversed(runs))
               + "</table></details>")
    # graduation timing
    g = study["graduation"]
    grads = sum(g["buckets"].values())
    items = [(k, v, f"{v} of {grads} graduates") for k, v in g["buckets"].items()] + [
        ("Never graduated", g["never"], f"{g['never']} still on the Pons curve after {ACTIVE_DAYS}+ days")]
    out.append(f"<h3>When our listed Pons tokens graduated</h3><p class='muted'>{g['total']} listed Pons tokens launched "
               f"{ACTIVE_DAYS}+ days ago (launch and graduation times from Pons). This is the evidence for the {ACTIVE_DAYS}-day "
               f"active window: if many graduate late and climb fast, resting tokens need checking more often.</p>" + _hbars(items, e))
    if g["late"]:
        out.append("<p class='muted'>Graduated after day " + str(ACTIVE_DAYS) + " (would have been resting first): "
                   + " · ".join(f"<b>{e(x['symbol'])}</b> {x['days']}d, now {e(money(x['now']))}" for x in g["late"][:12]) + "</p>")
    # woken
    wk = sorted(db["woken"].items(), key=lambda kv: kv[1]["at"], reverse=True)[:20]
    out.append("<h3>Woken tokens</h3>" + ("<table class='sum'><tr><th>Token</th><th>Woken (UTC)</th><th>Why</th><th>Resting at</th><th>Woken at</th></tr>"
               + "".join(f"<tr><td><b>{e(w.get('symbol') or '?')}</b></td><td>{e(w['at'][5:16].replace('T', ' '))}</td><td>{e(w['why'])}</td>"
                         f"<td>{e(money(w.get('value_rest')))}</td><td>{e(money(w.get('value_woken')))}</td></tr>" for a, w in wk)
               + "</table>" if wk else "<p class='muted'>None yet. A resting token wakes if it graduates, reaches $25k or doubles.</p>"))
    out.append(f"<p class='muted'>A copy of these numbers is saved once a day in data/studies/ so they can be compared over time.</p>")
    return "".join(out)
