"""Every token trading on Robinhood Chain, not just Pons launches (5 Nov, after FOBO: launched on its own
launchpad, went from $60k to $3.9M, and the scanner never saw it).

Source: new-pool events on Robinhood Chain: Uniswap v4 "Initialize", plus (6 Nov) v2/v3/Aerodrome-style pool
creation, which covers flap.sh launches too. Each names the pool's two tokens. Each run reads the new pools since the last run (one RPC call), keeps the non-Pons tokens, and
checks their value on DexScreener (30 tokens a call) about 1 hour, 1 day, 3 days and 7 days after we first
see them. A token worth MIN_MCAP+ with MIN_LIQ+ liquidity is handed to the GitHub check and the site check.

Saved in data/pool_feed.json (one token per line so git diffs stay small).
"""
import json, os, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "data", "pool_feed.json")
POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"  # Uniswap v4 on Robinhood Chain (found via MERY's pool, 5 Nov)
INITIALIZE = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
# 6 Nov: DexScreener's Robinhood page also lists pools on other exchanges (Uniswap v2/v3, Aerodrome-style,
# and the flap.sh launchpad: ~580 launches a day). Every new pool of any of these kinds is read too;
# only tokens that reach MIN_MCAP with MIN_LIQ liquidity get passed on, so the extra cost is ~2 calls a run.
PAIR_CREATED = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"   # Uniswap v2 style (flap.sh too)
POOL_CREATED = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"   # Uniswap v3 style
SOLIDLY_CREATED = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"  # Aerodrome/Velodrome style
TOKEN_TOPICS = {INITIALIZE: (2, 4), PAIR_CREATED: (1, 3), POOL_CREATED: (1, 3), SOLIDLY_CREATED: (1, 3)}
CHECK_AT = [1, 24, 72, 168]  # hours after we first see the token
MIN_MCAP = 25_000
MIN_LIQ = 5_000
MAX_CALLS = 15  # DexScreener calls per run (450 tokens); the rest wait for the next run
ZERO = "0x" + "0" * 40


def _logs(rpc, a, b):
    try:
        return rpc("eth_getLogs", [{"fromBlock": hex(a), "toBlock": hex(b), "topics": [list(TOKEN_TOPICS)]}])
    except ValueError:
        if b <= a:
            raise
        m = (a + b) // 2
        return _logs(rpc, a, m) + _logs(rpc, m + 1, b)


def dex_tok(pairs):
    """A token record (same shape as Pons/DexScreener ones) from its DexScreener pairs."""
    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    info = next((p["info"] for p in pairs if p.get("info")), {}) or {}
    socials = [s.get("url") for s in info.get("socials") or [] if s.get("url")]
    webs = [w.get("url") for w in info.get("websites") or [] if w.get("url")]
    return {"address": best["baseToken"]["address"], "symbol": best["baseToken"]["symbol"], "name": best["baseToken"]["name"],
            "source": "dex pool", "description": "", "links": webs + socials,
            "website": webs[0] if webs else None,
            "twitter": next((u for u in socials if "x.com" in u.lower() or "twitter.com" in u.lower()), None),
            "launched": datetime.datetime.fromtimestamp(min(p.get("pairCreatedAt") or 9e12 for p in pairs) / 1000,
                                                        datetime.timezone.utc).isoformat(timespec="seconds"),
            "mcap": best.get("marketCap") or best.get("fdv"), "liq": (best.get("liquidity") or {}).get("usd") or 0,
            "quote": (best.get("quoteToken") or {}).get("symbol")}


def lookup(addrs, fetch_json, max_calls=None):
    """{addr: token record} for those DexScreener knows, 30 per call."""
    out = {}
    for n, i in enumerate(range(0, len(addrs), 30)):
        if max_calls is not None and n >= max_calls:
            break
        by = {}
        for p in fetch_json("https://api.dexscreener.com/tokens/v1/robinhood/" + ",".join(addrs[i:i + 30])) or []:
            a = ((p.get("baseToken") or {}).get("address") or "").lower()
            if a:
                by.setdefault(a, []).append(p)
        out.update({a: dex_tok(ps) for a, ps in by.items()})
    return out


def run(rpc, fetch_json, pons_known, skip, now, log=print):
    """New pools since last run, then value checks for tokens that are due. Returns token records worth a look.
    pons_known: every Pons token (handled by the Pons route). skip(addr): True if the scanner already has it."""
    db = json.load(open(FILE, encoding="utf-8")) if os.path.exists(FILE) else {}
    toks = db.setdefault("tokens", {})
    latest = int(rpc("eth_blockNumber", []), 16)
    start = db.get("to_block") or latest - 9_000  # first run: the last ~15 minutes (older ones: one-time catch-up)
    stamp = now.isoformat(timespec="seconds")
    new = 0
    for l in _logs(rpc, start + 1, latest) if latest > start else []:
        i, j = TOKEN_TOPICS.get(l["topics"][0], (2, 4))
        for t in l["topics"][i:j]:
            a = "0x" + t[-40:]
            if a != ZERO and a not in pons_known and a not in toks:
                toks[a] = [stamp, 0]  # [first seen, checks done]
                new += 1
    db["to_block"] = latest
    age = lambda a: (now - datetime.datetime.fromisoformat(toks[a][0])).total_seconds() / 3600
    due = sorted((a for a, (seen, k) in toks.items() if k < len(CHECK_AT) and age(a) >= CHECK_AT[k]), key=age)
    got = lookup(due, fetch_json, MAX_CALLS)
    asked = due[:MAX_CALLS * 30]
    for a in asked:
        toks[a][1] += 1
    keep = [t for a, t in got.items() if (t["mcap"] or 0) >= MIN_MCAP and t["liq"] >= MIN_LIQ and not skip(a)]
    for a in list(toks):  # done, or a week past the last check
        if toks[a][1] >= len(CHECK_AT) or age(a) > CHECK_AT[-1] + 24:
            del toks[a]
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write('{"to_block": %d, "tokens": {\n' % db["to_block"])
        f.write(",\n".join(f"{json.dumps(a)}: {json.dumps(v)}" for a, v in sorted(toks.items())))
        f.write("\n}}\n")
    os.replace(tmp, FILE)
    log(f"Pool feed: {new} new non-Pons tokens, {len(asked)} value checks ({len(due) - len(asked)} wait), "
        f"{len(keep)} worth a look, {len(toks)} being followed")
    return keep
