"""Second 30-day test (started 6 Nov 2026, user): do the projects the page shows (score 61+) act like winners?
Split in two, GitHub and Site check, because they are scored differently.

Who enters: every project shown on the page (one card per project, score 61+), at its market cap the first time
it is seen there. Projects already shown when the test started enter at that first run's value.
Rule (same as the 4 Nov test, README): 30 days after entering, a token passes if its market cap is
above its entry value AND no more than 45% below the highest value seen since it entered.
Entries are never changed or removed (a later score drop or warning doesn't take a token out), so the result
can't be tidied up afterwards. Highest = from each run's price (about every 15-30 minutes), so a short spike
between runs can be missed.
"""
import json, os, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "data", "test61.json")
DAYS = 30
MAX_DROP = 0.45
ROUTES = (("github", "GitHub"), ("sites", "Site check"))


def _passing(t):
    return t["now"] > t["entry_mcap"] and t["now"] >= (1 - MAX_DROP) * t["high"]


def update(shown, pdb, now):
    """shown: [(route, row, scoring)] for the cards on the page. pdb: prices.update() result. Returns the test data."""
    db = json.load(open(FILE, encoding="utf-8")) if os.path.exists(FILE) else {
        "started": now.isoformat(timespec="seconds"), "days": DAYS, "max_drop": MAX_DROP, "tokens": {}}
    stamp = now.isoformat(timespec="seconds")
    for route, r, sc in shown:
        a = r["address"].lower()
        m = (pdb.get(a) or {}).get("now_mcap")
        if a in db["tokens"] or not m:
            continue
        db["tokens"][a] = {"symbol": r.get("symbol") or "?", "route": route, "entered": stamp, "entry_score": sc["score"],
                           "entry_mcap": m, "now": m, "now_at": stamp, "high": m, "high_at": stamp}
    for a, t in db["tokens"].items():
        if "final" in t:
            continue
        m = (pdb.get(a) or {}).get("now_mcap")
        due = datetime.datetime.fromisoformat(t["entered"]) + datetime.timedelta(days=DAYS)
        if m:
            t["now"], t["now_at"] = m, stamp
            if m > t["high"]:
                t["high"], t["high_at"] = m, stamp
        if now >= due:  # day 30 reached: the result is fixed from here on
            t["final"] = "pass" if _passing(t) else "fail"
            t["final_at"] = stamp
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    tmp = FILE + ".tmp"
    json.dump(db, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, FILE)
    return db


def html(db, now, e, money):
    if not db or not db.get("tokens"):
        return ""
    start = db["started"][:16].replace("T", " ")
    out = [f"<h2 style='margin:22px 0 6px'>30-day test: do 61+ projects act like winners?</h2>"
           f"<p class='top'>Started {e(start)} UTC. Every project the page shows enters at its value when first shown. "
           f"After {DAYS} days it <b>passes</b> if it is above that value and no more than {MAX_DROP:.0%} below its highest since. "
           f"Until then ✅/❌ is <b>passing so far</b>. Entries are never removed.</p>"]
    for route, label in ROUTES:
        toks = sorted([t for t in db["tokens"].values() if t["route"] == route], key=lambda t: t["entered"], reverse=True)
        if not toks:
            out.append(f"<h3>{e(label)}</h3><p class='muted'>No tokens yet.</p>")
            continue
        done = [t for t in toks if "final" in t]
        live = [t for t in toks if "final" not in t]
        so_far = sum(_passing(t) for t in live)
        moved = [t for t in live if t["now"] != t["entry_mcap"]]
        head = ((f"<b>{so_far} of {len(moved)}</b> passing so far" + (f" ({len(live) - len(moved)} not moved yet)" if len(moved) < len(live) else ""))
                if moved else "Just started: no price moves yet." if live else "")
        if done:
            head += (" · " if head else "") + f"<b>final: {sum(t['final'] == 'pass' for t in done)} of {len(done)} passed</b>"
        rows = []
        for t in toks:
            due = datetime.datetime.fromisoformat(t["entered"]) + datetime.timedelta(days=DAYS)
            left = max(0, (due - now).days)
            ok = (t["final"] == "pass") if "final" in t else _passing(t)
            ch = t["now"] / t["entry_mcap"]
            off = 1 - t["now"] / t["high"] if t["high"] else 0
            if "final" in t:
                state = "✅ passed" if ok else "❌ failed"
            elif t["now"] == t["entry_mcap"]:
                state = "· no change yet"
            else:
                state = "✅" if ok else "❌"
            rows.append(f"<tr><td><b>{e(t['symbol'])}</b></td><td>{t['entry_score']}</td><td>{money(t['entry_mcap'])}</td>"
                        f"<td>{money(t['now'])} ({ch:.2f}x)</td><td>{money(t['high'])} (now {off:.0%} below)</td>"
                        f"<td>{'done' if 'final' in t else f'{left}d'}</td><td>{state}</td></tr>")
        out.append(f"<h3>{e(label)} ({len(toks)})</h3><p class='muted'>{head}</p>"
                   "<table class='sum'><tr><th>Token</th><th>Score in</th><th>Entered at</th><th>Now</th><th>Highest</th>"
                   "<th>Days left</th><th>Passing?</th></tr>" + "".join(rows) + "</table>")
    return "".join(out)
