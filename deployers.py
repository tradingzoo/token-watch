"""Who launched each token, and what else that wallet launched. Free, no key.

Source: Robinhood Chain's public RPC (rpc.mainnet.chain.robinhood.com). Every Pons launch
writes a "launch" event that names the token and the wallet that launched it. We keep a local
list of all of them (data/pons_launches.json) and add only new blocks each run.

For each token on the site: how many other tokens its wallet launched, what happened to them
(market cap now), and how many transactions the wallet has ever sent.
Never changes a score: facts and warning flags only.
"""
import json, os, time, datetime, urllib.request, urllib.error, html

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, "data", "pons_launches.csv")        # token,wallet,block  (append only)
META = os.path.join(HERE, "data", "pons_launches_meta.json")  # {"to_block": n}
FILE = os.path.join(HERE, "data", "wallets.json")             # per-token results shown on the site
RPC = "https://rpc.mainnet.chain.robinhood.com"
FACTORY = "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e"  # Pons launchpad (all launches so far)
LAUNCH = "0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607"  # its launch event
START = 27_000_000      # first Pons launch is at block 27,027,321
BOT_WALLET = 50         # a wallet with more launches than this is a launch bot or service
DEAD_MCAP = 10_000      # under $10k now = went nowhere
REFRESH_HOURS = 12
KNOWN = set()           # every Pons token address (lower case), filled by refresh_index


def rpc(method, params):
    for i in range(6):
        try:
            req = urllib.request.Request(RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                         {"content-type": "application/json", "User-Agent": "Mozilla/5.0 (robinhood-scan)"})
            r = json.loads(urllib.request.urlopen(req, timeout=90).read())
            if "error" in r:
                raise ValueError(r["error"].get("message", "rpc error"))
            return r["result"]
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(10 * (i + 1))
    raise RuntimeError("RPC rate limit")


def _logs(a, b):
    """Launch events between blocks a and b, splitting the range when the RPC says too many."""
    try:
        return rpc("eth_getLogs", [{"address": FACTORY, "fromBlock": hex(a), "toBlock": hex(b), "topics": [LAUNCH]}])
    except ValueError as ex:
        if "exceeds" in str(ex) or "spans" in str(ex):
            mid = (a + b) // 2
            time.sleep(1)
            return _logs(a, mid) + _logs(mid + 1, b)
        raise


def save_json(path, obj):
    """Write to a temp file then swap it in, so a half-written file is never left behind."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def refresh_index(log=print):
    """Adds new launches to the list (only blocks after the last run). Returns all launches."""
    meta = json.load(open(META, encoding="utf-8")) if os.path.exists(META) else {"to_block": START - 1}
    latest = int(rpc("eth_blockNumber", []), 16)
    b, added = meta["to_block"] + 1, 0
    os.makedirs(os.path.dirname(LIST), exist_ok=True)
    while b <= latest:
        e = min(b + 9_999_999, latest)
        rows = [f"0x{x['topics'][1][26:]},0x{x['topics'][3][26:]},{int(x['blockNumber'], 16)}\n" for x in _logs(b, e)]
        with open(LIST, "a", encoding="utf-8") as f:  # list first, then the marker: a crash can only repeat, never skip
            f.writelines(rows)
        meta["to_block"] = e
        save_json(META, meta)
        added += len(rows)
        b = e + 1
        time.sleep(1)
    launches, seen = [], set()
    for line in open(LIST, encoding="utf-8") if os.path.exists(LIST) else []:
        p = line.strip().split(",")
        if len(p) == 3 and p[0] not in seen:
            seen.add(p[0])
            launches.append((p[0], p[1], int(p[2])))
    KNOWN.update(seen)
    if added:
        log(f"Wallets: {added} new Pons launches (total {len(launches):,})")
    return launches


def _block_time(n, cache):
    if n not in cache:
        cache[n] = int(rpc("eth_getBlockByNumber", [hex(n), False])["timestamp"], 16)
    return cache[n]


def update(rows, market, log=print):
    """rows: the site's token records. market(addr) -> {'symbol','mcap',...} (watch.market).
    Saves per-token results in data/wallets.json and returns them."""
    launches = refresh_index(log)
    by_token, by_wallet = {}, {}
    for tok, w, blk in launches:
        by_token[tok] = (w, blk)
        by_wallet.setdefault(w, []).append((blk, tok))
    cache = json.load(open(FILE, encoding="utf-8")) if os.path.exists(FILE) else {}
    times = {}
    now = datetime.datetime.now(datetime.timezone.utc)
    for r in rows:
        key = r["address"].lower()
        old = cache.get(key)
        if old and (now - datetime.datetime.fromisoformat(old["checked"])).total_seconds() < REFRESH_HOURS * 3600:
            continue
        if key not in by_token:
            cache[key] = {"checked": now.isoformat(timespec="seconds"), "pons": False}
            continue
        w, blk = by_token[key]
        others = sorted((b, t) for b, t in by_wallet[w] if t != key)
        res = {"checked": now.isoformat(timespec="seconds"), "pons": True, "wallet": w,
               "launches": len(by_wallet[w]), "before": sum(1 for b, _ in others if b < blk),
               "after": sum(1 for b, _ in others if b > blk), "others": []}
        try:
            res["wallet_txs"] = int(rpc("eth_getTransactionCount", ["0x" + w[2:], "latest"]), 16)
        except Exception:
            pass
        if len(by_wallet[w]) <= BOT_WALLET:
            for b, t in others[-8:][::-1]:  # the 8 most recent other launches
                try:
                    m = market(t) or {}
                    when = datetime.datetime.fromtimestamp(_block_time(b, times), datetime.timezone.utc)
                except Exception:
                    continue
                res["others"].append({"address": t, "symbol": m.get("symbol"), "mcap": m.get("mcap"),
                                      "launched": when.isoformat(timespec="seconds")})
                time.sleep(0.5)
        cache[key] = res
    save_json(FILE, cache)
    return cache


def _money(x):
    if not x:
        return "?"
    return f"${x/1e6:.1f}M" if x >= 1e6 else (f"${x/1e3:.0f}k" if x >= 1e3 else f"${x:.0f}")


def facts(r, cache):
    """(fact_line_html, [warning texts]) for one token's card."""
    e = html.escape
    w = (cache or {}).get(r["address"].lower())
    if not w:
        return "", []
    if not w.get("pons"):
        return "<p class='xline'>👛 Not launched on Pons, so its launch wallet isn't checked.</p>", []
    warn, bits = [], []
    link = f'<a href="https://robinhoodchain.blockscout.com/address/{e(w["wallet"])}" target="_blank" rel="noopener">{e(w["wallet"][:8])}…</a>'
    n_other = w["launches"] - 1
    if w["launches"] > BOT_WALLET:
        bits.append(f"shared launch wallet ({w['launches']:,} tokens), likely a bot or launch service, so it tells us little")
    elif n_other == 0:
        bits.append("first and only token from this wallet")
    else:
        bits.append(f"this wallet launched {n_other} other token{'s' if n_other != 1 else ''} ({w['before']} before, {w['after']} after this one)")
        dead = [o for o in w["others"] if (o.get("mcap") or 0) < DEAD_MCAP]
        if w["others"]:
            bits.append("recent: " + ", ".join(f"{o.get('symbol') or '?'} {_money(o.get('mcap'))}" for o in w["others"][:5]))
        if len(w["others"]) >= 2 and len(dead) >= max(2, int(0.75 * len(w["others"]))):
            warn.append(f"Launch wallet's other tokens mostly went nowhere ({len(dead)} of {len(w['others'])} checked are under {_money(DEAD_MCAP)})")
        elif w["after"] >= 2:
            warn.append(f"Launch wallet kept launching new tokens after this one ({w['after']} more)")
    if w.get("wallet_txs") is not None:
        n = w["wallet_txs"]
        bits.append(f"wallet has sent {n:,} transaction{'' if n == 1 else 's'} in total")
    return f"<p class='xline'>👛 {link}: " + e(" · ".join(bits)) + "</p>", warn
