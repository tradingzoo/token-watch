"""Price log for every token the GitHub watch scores, high or low.

Why: so we can see later where the score was wrong (a low score that went up, a high
score that fell). It never changes a score.

Saved:
- data/price_track.json : per token: price (market cap) and score when first tracked,
  highest seen and when, latest, and every score change.
- data/price_log.csv     : one row per token at most every 30 minutes (the full record).
"""
import csv, datetime, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "data", "price_track.json")
LOGCSV = os.path.join(HERE, "data", "price_log.csv")
LOG_EVERY_MIN = 30


def _dex_batch(addrs, fetch_json):
    """Market cap for up to 30 tokens per DexScreener call. Returns {addr_lower: (mcap, where)}."""
    out = {}
    for i in range(0, len(addrs), 30):
        part = addrs[i:i + 30]
        pairs = fetch_json("https://api.dexscreener.com/tokens/v1/robinhood/" + ",".join(part)) or []
        best = {}
        for p in pairs:
            a = ((p.get("baseToken") or {}).get("address") or "").lower()
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if a and (a not in best or liq > best[a][0]):
                best[a] = (liq, p.get("marketCap") or p.get("fdv"), p)
        for a, (liq, m, p) in best.items():
            if m:
                tx = (p.get("txns") or {}).get("h24") or {}
                out[a] = (float(m), "exchange", {"vol24": (p.get("volume") or {}).get("h24") or 0, "liq": liq,
                                                 "trades24": (tx.get("buys") or 0) + (tx.get("sells") or 0)})
    return out


def update(state, fetch_json, market, now, log=print):
    rows = {**state.get("github", {}), **state.get("sites", {})}  # GitHub tokens and site-check tokens
    db = json.load(open(FILE, encoding="utf-8")) if os.path.exists(FILE) else {}
    stamp = now.isoformat(timespec="seconds")
    got = _dex_batch(list(rows), fetch_json)
    for key, r in rows.items():
        if key not in got:  # still on the Pons launchpad: one page per token
            try:
                mk = market(r["address"])
            except Exception:
                mk = {}
            if mk.get("mcap"):
                got[key] = (float(mk["mcap"]), mk.get("where") or "Pons launchpad", {})
    new_rows = []
    for key, r in rows.items():
        score = r["scoring"]["score"]
        t = db.setdefault(key, {"address": r["address"], "symbol": r.get("symbol"),
                                "first_seen": r.get("first_seen"), "start_at": stamp,
                                "start_mcap": None, "start_score": score,
                                "high_mcap": None, "high_at": None, "scores": [[stamp, score]]})
        t["symbol"] = r.get("symbol") or t.get("symbol")
        if t["scores"][-1][1] != score:
            t["scores"].append([stamp, score])
        t["score"] = score
        if key not in got:
            continue
        m, where, mkt = got[key]
        t["market"] = mkt  # 24h volume, liquidity, trades: for the ghost-market warning
        if t["start_mcap"] is None:
            t["start_mcap"], t["start_at"] = m, stamp
        if t["high_mcap"] is None or m > t["high_mcap"]:
            t["high_mcap"], t["high_at"] = m, stamp
        if t.get("low_mcap") is None or m < t["low_mcap"]:
            t["low_mcap"] = m
        last = t.get("logged_at")
        if not last or (now - datetime.datetime.fromisoformat(last)).total_seconds() >= LOG_EVERY_MIN * 60:
            new_rows.append([stamp, r["address"], t["symbol"], score, round(m, 2), where])
            t["logged_at"] = stamp
        t["now_mcap"], t["now_at"], t["where"] = m, stamp, where
    tmp = FILE + ".tmp"
    json.dump(db, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, FILE)
    if new_rows:
        first = not os.path.exists(LOGCSV)
        with open(LOGCSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if first:
                w.writerow(["time_utc", "address", "symbol", "score", "market_cap_usd", "where"])
            w.writerows(new_rows)
    log(f"Prices: {len(got)} of {len(rows)} tokens priced, {len(new_rows)} rows logged")
    return db


def _money(x):
    if x is None:
        return "?"
    return f"${x/1e6:.2f}M" if x >= 1e6 else (f"${x/1e3:.1f}k" if x >= 1e3 else f"${x:.0f}")


def _pct(a, b):
    if not a or b is None:
        return None
    return (b / a - 1) * 100


GHOST_MCAP = 250_000  # ghost market: worth this much...
GHOST_TRADES = 25     # ...but fewer trades than this in 24h (5 Nov test: winners trade 100-3,000 times a day;
                      # TRENCHERS 13, WIN 4, AGE 7). Warning only, never changes the score (user, 5 Nov).


def ghost(t):
    """Warning text if the token is worth a lot but hardly trades, else ''."""
    mk, m = (t or {}).get("market") or {}, (t or {}).get("now_mcap") or 0
    if m < GHOST_MCAP or "trades24" not in mk or mk["trades24"] >= GHOST_TRADES:
        return ""
    return (f"👻 Ghost market: worth {_money(m)} but only {mk['trades24']} trades ({_money(mk.get('vol24') or 0)}) "
            f"in 24h. The price may be propped up or stale; liquidity is {_money(mk.get('liq'))}, "
            f"so selling near this price may not be possible.")


def card_line(key, db):
    """One line for a token's card."""
    t = db.get(key)
    if not t or t.get("start_mcap") is None:
        return "<p class='xline'>📈 Price: not priced yet</p>"
    g = ghost(t)
    if g:
        return f"<p class='xline' style='color:var(--warn,#b45309)'><b>{g}</b></p>" + card_line_plain(t)
    return card_line_plain(t)


def card_line_plain(t):
    if t.get("start_mcap") is None:
        return ""
    ch, hi = _pct(t["start_mcap"], t.get("now_mcap")), _pct(t["start_mcap"], t.get("high_mcap"))
    sign = lambda p: "?" if p is None else f"{p:+.0f}%"
    return (f"<p class='xline'>📈 Price since tracked ({t['start_at'][:16].replace('T',' ')} UTC, score then {t['start_score']}): "
            f"{_money(t['start_mcap'])} → now {_money(t.get('now_mcap'))} ({sign(ch)}) · highest {_money(t.get('high_mcap'))} ({sign(hi)})</p>")


def section(db, esc):
    """Table: every scored token, its score and what the price did. Biggest moves first."""
    rows = [t for t in db.values() if t.get("start_mcap")]
    if not rows:
        return ""
    rows.sort(key=lambda t: _pct(t["start_mcap"], t.get("high_mcap")) or 0, reverse=True)
    trs = []
    for t in rows:
        ch, hi = _pct(t["start_mcap"], t.get("now_mcap")), _pct(t["start_mcap"], t.get("high_mcap"))
        verdict = ""
        if t["start_score"] < 40 and (hi or 0) >= 100:
            verdict = "⚠️ Low score but doubled: look at what we missed"
        elif t["start_score"] >= 60 and (ch or 0) <= -50:
            verdict = "⚠️ High score but halved"
        elif t["start_score"] >= 60 and (hi or 0) >= 100:
            verdict = "✅ High score and doubled"
        elif t["start_score"] < 40 and (ch or 0) <= -50:
            verdict = "✅ Low score and halved"
        sc = f"{t['start_score']}" + (f" → {t['score']}" if t.get("score") != t["start_score"] else "")
        trs.append(f"<tr><td><b>{esc(t.get('symbol') or '?')}</b></td><td>{esc(sc)}</td><td>{_money(t['start_mcap'])}</td>"
                   f"<td>{_money(t.get('now_mcap'))}</td><td>{'?' if ch is None else f'{ch:+.0f}%'}</td>"
                   f"<td>{_money(t.get('high_mcap'))} ({'?' if hi is None else f'{hi:+.0f}%'})</td><td>{verdict}</td></tr>")
    return ("<details class='card' open><summary><b>Was the score right? Price since each token was first tracked</b></summary>"
            "<p class='sub'>Every scored token, high or low, is priced each run. Score = the score when first tracked (→ now, if it changed). "
            "Biggest rise first. Full record: data/price_log.csv. Scores marked against prices from 4 Nov 2026.</p>"
            "<table class='sum'><tr><th>Token</th><th>Score</th><th>Start</th><th>Now</th><th>Change</th><th>Highest</th><th></th></tr>"
            + "".join(trs) + "</table></details>")
