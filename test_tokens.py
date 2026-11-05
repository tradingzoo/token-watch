"""The 16 tokens in the 30-day test (tokens.csv): their X, website, Telegram and launch wallet,
shown as a section of site/index.html so watch tokens can be compared with the winners (benchmarks)
and the faded tokens.

Links come from DexScreener (token info) and the Pons token page, saved in data/test_links.json
and refreshed once a day. Nothing here touches the day-30 rule, baseline or snapshots.
"""
import csv, json, os, re, datetime, html, statistics
import x_info, deployers

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "data", "test_links.json")
GROUPS = [("watch", "Watch (new)"), ("benchmark", "Benchmark (winners)"), ("faded", "Faded (ran up, then fell)")]


def load(fetch, fetch_json, now):
    cache = json.load(open(FILE, encoding="utf-8")) if os.path.exists(FILE) else {}
    rows = []
    for t in csv.DictReader(open(os.path.join(HERE, "tokens.csv"), encoding="utf-8")):
        a = t["address"]
        c = cache.get(a.lower())
        if not c or (now - datetime.datetime.fromisoformat(c["checked"])).total_seconds() > 24 * 3600:
            c = {"checked": now.isoformat(timespec="seconds"), "links": []}
            pairs = fetch_json(f"https://api.dexscreener.com/tokens/v1/robinhood/{a}") or []
            info = next((p["info"] for p in pairs if p.get("info")), {})
            for s in info.get("socials") or []:
                if s.get("url"):
                    c["links"].append(s["url"])
                    c.setdefault(s.get("type"), s["url"])
            webs = [w.get("url") for w in info.get("websites") or [] if w.get("url")]
            c["links"] += webs
            site = next((w for w in webs if "github.com" not in w and "npmjs" not in w), None)
            if pairs:
                c["launched"] = datetime.datetime.fromtimestamp(min(p.get("pairCreatedAt") or 9e12 for p in pairs) / 1000,
                                                                datetime.timezone.utc).isoformat(timespec="seconds")
            s = (fetch(f"https://ponsfamily.com/launchpad/{a.lower()}") or "").replace('\\"', '"')
            i = s.find('{"address":"%s"' % a.lower())
            if i >= 0:
                try:
                    o, _ = json.JSONDecoder().raw_decode(s, i)
                    o = o.get("launch") or o
                    soc = {k: v for k, v in (o.get("socials") or {}).items() if v}
                    for k in ("twitter", "telegram"):  # DexScreener first (the team keeps it updated); Pons fills gaps
                        if soc.get(k) and not c.get(k) and re.search(r"\.(com|me)/[A-Za-z0-9_]{3,}", soc[k]):
                            c[k] = soc[k]
                    site = site or soc.get("website")
                    if o.get("createdAt"):
                        c["launched"] = datetime.datetime.fromtimestamp(o["createdAt"], datetime.timezone.utc).isoformat(timespec="seconds")
                    c["links"] += list(soc.values())
                except Exception:
                    pass
            c["website"] = site
            cache[a.lower()] = c
        rows.append({"address": a, "symbol": t["symbol"], "group": t["group"], "why": t.get("why", ""),
                     "twitter": c.get("twitter"), "telegram": c.get("telegram"), "website": c.get("website"),
                     "links": c.get("links", []), "launched": c.get("launched")})
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    json.dump(cache, open(FILE, "w", encoding="utf-8"), indent=1)
    return rows


def _num(x, fmt="{:,}"):
    return "–" if x is None else fmt.format(x)


def _med(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def section(rows, xdb, wallets, now, compare_rows=None, ship=None):
    import shipping
    """compare_rows: every token on the site, for the same/near-identical X checks."""
    e = html.escape
    compare_rows = compare_rows or rows
    acct = lambda r: xdb.get("accounts", {}).get((x_info.parse(r.get("twitter"))[0] or "").lower())
    def made_before(r):
        a = acct(r)
        if not a or not a.get("joined") or not r.get("launched"):
            return None
        return (datetime.datetime.fromisoformat(r["launched"]) - datetime.datetime.fromisoformat(a["joined"])).days
    def tg_members(r):
        t = xdb.get("telegram", {}).get((x_info.telegram_name(r, acct(r)) or "").lower())
        return t.get("members") if t and t.get("found") else None
    def other_launches(r):
        w = wallets.get(r["address"].lower()) or {}
        if not w.get("pons"):
            return None
        return "bot" if w["launches"] > deployers.BOT_WALLET else w["launches"] - 1

    # group summary: the one fair comparison is "how old was the X account when the token launched"
    summ = []
    for g, label in GROUPS:
        gr = [r for r in rows if r["group"] == g]
        mb = [made_before(r) for r in gr]
        has_x = sum(1 for r in gr if acct(r) and acct(r).get("found"))
        has_tg = sum(1 for r in gr if tg_members(r) is not None)
        ol = [other_launches(r) for r in gr]
        multi = sum(1 for x in ol if isinstance(x, int) and x > 0)
        m = _med(mb)
        age = "–" if m is None else f"{m:.0f} day{'' if round(m) == 1 else 's'}"
        summ.append(f"<tr><td>{e(label)}</td><td>{has_x}/{len(gr)}</td><td>{age}</td>"
                    f"<td>{_num(_med([acct(r).get('followers') if acct(r) else None for r in gr]), '{:,.0f}')}</td>"
                    f"<td>{has_tg}/{len(gr)}</td><td>{multi}/{sum(1 for x in ol if x is not None)}</td></tr>")

    body = []
    for g, label in GROUPS:
        for r in [r for r in rows if r["group"] == g]:
            a = acct(r)
            mb = made_before(r)
            xl, xw = x_info.facts(r, compare_rows, xdb, now)
            wl, ww = deployers.facts(r, wallets)
            flags = "".join(f"<div class='flag'>⚠️ {e(f)}</div>" for f in xw + ww)
            h = x_info.parse(r.get("twitter"))[0]
            ol = other_launches(r)
            body.append(f"""<details class="trow"><summary><b>{e(r['symbol'])}</b> <span class="grp {g}">{e(g)}</span>
 {shipping.kv(r, ship)}
 <span class="kv">X: {('@' + e(h)) if h else 'none'}</span>
 <span class="kv">account {('made ' + str(mb) + 'd before token') if mb is not None and mb >= 0 else (('made ' + str(-mb) + 'd after token') if mb is not None else '–')}</span>
 <span class="kv">{_num(a.get('followers') if a else None)} followers</span>
 <span class="kv">TG {_num(tg_members(r))}</span>
 <span class="kv">wallet: {'–' if ol is None else ('shared bot' if ol == 'bot' else (str(ol) + ' other launches'))}</span>
 {'<span class="kv warn">⚠️ ' + str(len(xw + ww)) + '</span>' if xw + ww else ''}</summary>
 <p class="sub">{e(r['why'])}</p>{shipping.line(r, ship)}{xl}{wl}{flags}</details>""")
    return f"""
<section class="card test">
<h2>30-day test tokens: X, Telegram and launch wallet</h2>
<p class="sub">The 16 tokens in the day-30 test (tokens.csv). Facts only: none of this changes the test's rule or result.
Refreshed about twice a day. Click a row for details.</p>
<table class="sum"><thead><tr><th>Group</th><th>Has X</th><th>X account age at launch (median)</th><th>Followers now (median)</th><th>Has Telegram</th><th>Wallet launched others</th></tr></thead>
<tbody>{''.join(summ)}</tbody></table>
<p class="sub">Fair to compare: <b>account age at launch</b> and <b>wallet history</b> (both fixed on launch day).
Not fair: <b>followers now</b>, because the winners have had weeks to grow. Follower growth for the watch tokens is saved daily from 4 Nov, so by day 30 we can compare growth instead.</p>
{''.join(body)}
</section>"""
