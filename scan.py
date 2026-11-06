"""Robinhood Chain token watch.

Run:  python scan.py
Each run:
  1. reads tokens.csv
  2. gets each token's market cap now (DexScreener; Pons launchpad page if not trading yet)
  3. saves it to data/snapshots/<time>.json
  4. on the very first run, saves data/baseline.json (day 0) - never overwritten after that
  5. writes checks/<date>.md comparing now with day 0, and the result of the rule in README.md
"""
import csv, json, os, re, sys, time, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (robinhood-scan research script)", "Accept": "application/json,text/html"}
RULE_MAX_DROP = 0.45   # see README: worst benchmark was 43% off its peak


def get(url, as_json=True, tries=4):
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25)
            body = r.read().decode("utf-8", "replace")
            return json.loads(body) if as_json else body
        except Exception:
            time.sleep(6 * (i + 1))
    return None


def from_dex(addr):
    pairs = get(f"https://api.dexscreener.com/tokens/v1/robinhood/{addr}")
    if not pairs:
        return None
    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    mc = best.get("marketCap") or best.get("fdv")
    if not mc:
        return None
    return {"source": "dexscreener", "mcap": mc, "price": float(best["priceUsd"]),
            "liquidity": sum((p.get("liquidity") or {}).get("usd") or 0 for p in pairs),
            "vol24": sum((p.get("volume") or {}).get("h24") or 0 for p in pairs)}


def from_pons(addr):
    html = get(f"https://ponsfamily.com/launchpad/{addr.lower()}", as_json=False)
    if not html:
        return None
    s = html.replace('\\"', '"')
    i = s.find('{"address":"%s"' % addr.lower())
    if i < 0:
        return None
    try:
        o, _ = json.JSONDecoder().raw_decode(s, i)
    except Exception:
        return None
    o = o.get("launch") or o   # the token page wraps the token's data in "launch"
    if o.get("marketCapUsd") is None:
        return None
    return {"source": "pons", "mcap": o.get("marketCapUsd"), "price": o.get("priceUsd"),
            "stage": o.get("stage"), "trades_total": o.get("tradeCount"), "vol_total": o.get("volumeUsd")}


def peak_since(addr, since_ts, now_price, now_mcap):
    """Highest market cap since day 0, from GeckoTerminal hourly prices (traded tokens only)."""
    pools = get(f"https://api.geckoterminal.com/api/v2/networks/robinhood/tokens/{addr}/pools?page=1")
    time.sleep(3)
    if not pools or not pools.get("data") or not now_price:
        return None
    # Use the pool with the most money in it. Popular tokens get "trap pools" (35-89% fees, ~$0 in them)
    # whose prices can spike wildly; the first pool listed is not always the real one.
    best = max(pools["data"], key=lambda p: float(p["attributes"].get("reserve_in_usd") or 0))
    pool = best["attributes"]["address"]
    o = get(f"https://api.geckoterminal.com/api/v2/networks/robinhood/pools/{pool}/ohlcv/hour?limit=1000&currency=usd&token=base")
    time.sleep(3)
    rows = [r for r in ((o or {}).get("data", {}).get("attributes", {}).get("ohlcv_list") or []) if r[0] >= since_ts]
    if not rows:
        return None
    return max(r[2] for r in rows) * (now_mcap / now_price)


def money(x):
    if x is None:
        return "-"
    return f"${x/1e6:.2f}M" if x >= 1e6 else f"${x/1e3:.0f}k"


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    # once an hour: skip if the last snapshot is under 50 minutes old (6 Nov: it ran every scan, 5 min each,
    # because the outside trigger counts as a manual start). "--force" runs it anyway.
    snap_dir = os.path.join(HERE, "data", "snapshots")
    last = sorted(os.listdir(snap_dir))[-1] if os.path.isdir(snap_dir) and os.listdir(snap_dir) else None
    if last and "--force" not in sys.argv:
        t_last = datetime.datetime.strptime(last[:15], "%Y-%m-%dT%H%M").replace(tzinfo=datetime.timezone.utc)
        if (now - t_last).total_seconds() < 50 * 60:
            print(f"Not due: last check {last[:15]} UTC (runs once an hour)")
            return
    tokens = list(csv.DictReader(open(os.path.join(HERE, "tokens.csv"), encoding="utf-8")))
    snap = {"taken_utc": now.isoformat(timespec="seconds"), "tokens": {}}
    for t in tokens:
        d = from_dex(t["address"]) or from_pons(t["address"])
        snap["tokens"][t["symbol"]] = d or {"source": "none"}
        print(f"  {t['symbol']:10} {money((d or {}).get('mcap')):>10}  ({(d or {}).get('source','not found')})", flush=True)
        time.sleep(0.5)

    os.makedirs(os.path.join(HERE, "data", "snapshots"), exist_ok=True)
    json.dump(snap, open(os.path.join(HERE, "data", "snapshots", now.strftime("%Y-%m-%dT%H%M") + ".json"), "w"), indent=1)

    base_path = os.path.join(HERE, "data", "baseline.json")
    if not os.path.exists(base_path):
        json.dump(snap, open(base_path, "w"), indent=1)
        print("\nDay 0 saved to data/baseline.json (this file is never changed again).")
    base = json.load(open(base_path))
    t0 = datetime.datetime.fromisoformat(base["taken_utc"])
    days = (now - t0).total_seconds() / 86400

    # highest market cap seen: GeckoTerminal hourly for traded tokens, plus every saved snapshot
    snaps = [json.load(open(os.path.join(HERE, "data", "snapshots", f)))
             for f in sorted(os.listdir(os.path.join(HERE, "data", "snapshots")))]
    lines = [f"# Check {now:%Y-%m-%d} (day {days:.1f} since {t0:%Y-%m-%d %H:%M} UTC)", "",
             "| Token | Group | Day 0 | Now | Change | Highest seen | Down from highest | Where it trades |",
             "|---|---|---|---|---|---|---|---|"]
    verdicts, progress = [], []
    for t in tokens:
        sym = t["symbol"]
        b = base["tokens"].get(sym, {}).get("mcap")
        n = snap["tokens"][sym].get("mcap")
        seen = [s["tokens"].get(sym, {}).get("mcap") for s in snaps]
        hi = max([x for x in seen if x] or [0]) or None
        if days >= 1 and snap["tokens"][sym].get("source") == "dexscreener":
            p = peak_since(t["address"], t0.timestamp(), snap["tokens"][sym]["price"], n)
            if p and (hi is None or p > hi):
                hi = p
        ch = f"{n/b:.2f}x" if (b and n) else "-"
        dd = f"{(1-n/hi)*100:.0f}%" if (hi and n) else "-"
        where = snap["tokens"][sym].get("source")
        if where == "pons":
            where = f"Pons launchpad ({snap['tokens'][sym].get('stage')})"
        lines.append(f"| {sym} | {t['group']} | {money(b)} | {money(n)} | {ch} | {money(hi)} | {dd} | {where} |")
        progress.append({"symbol": sym, "group": t["group"], "address": t["address"], "day0": b, "now": n, "high": hi,
                         "passing": bool(b and n and hi and n > b and (1 - n / hi) <= RULE_MAX_DROP)})
        if t["group"] == "watch" and b and n and hi:
            ok = n > b and (1 - n / hi) <= RULE_MAX_DROP
            verdicts.append(f"- **{sym}**: {'acts like the winners' if ok else 'does not'} "
                            f"(now {n/b:.2f}x day 0, {(1-n/hi)*100:.0f}% below its highest)")
        elif t["group"] == "watch":
            verdicts.append(f"- **{sym}**: no data")

    lines += ["", "## Rule (written on day 0, see README.md)", "",
              "A watch token acts like the winners if it is above its day-0 market cap AND no more than 45% below the highest market cap seen since day 0.",
              "Only the day-30 result counts; earlier checks are progress reports.", ""] + verdicts
    os.makedirs(os.path.join(HERE, "checks"), exist_ok=True)
    out = os.path.join(HERE, "checks", f"{now:%Y-%m-%d}.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"\nWrote {out}")
    # same numbers for the site's 30-day test tab (test_tokens.py); progress only, the day-30 result is the rule in README
    json.dump({"checked": now.isoformat(timespec="seconds"), "day": round(days, 1), "tokens": progress},
              open(os.path.join(HERE, "data", "test_progress.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
