"""Still shipping? GREEN / AMBER / RED for every watched token. Free, no key.

Idea from Aaron's Pons scanner notes (4 Nov 2026): the point is to catch a project being
abandoned early, not to call the price. Each run compares with earlier runs and only
writes an alert when a token's status changes.

What each run reads, per token:
  code    - the last real change across the project's public GitHub (bots don't count).
            Uses the time the change landed on GitHub (committer time), not the time it was
            written (author time), which can be a day off when people are in other time zones.
  website - does it load
  X       - does the account still exist, and is the token's address still in its bio
  market  - market cap and money in the main pool (DexScreener; the pool with the most money,
            so fake "trap pools" are ignored), compared with about 24 hours ago

Rules (shown on the site):
  RED    no real GitHub change for 7+ days · repo deleted or made private · every repo archived ·
         website down on every check for 6+ hours · X account gone · address removed from X bio
  AMBER  no real GitHub change for 3-6 days · website failed on the latest check ·
         market cap down 50%+ or pool money down 40%+ in 24h while most tokens did not fall
  GREEN  a real GitHub change in the last 3 days and nothing above
  GREY   no public code of their own to watch (still goes AMBER/RED on website, X and market)

Never changes a score or the 30-day test. Saved in data/shipping.json.
"""
import json, os, re, subprocess, datetime, html, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "data", "shipping.json")
NOWIN = 0x08000000 if os.name == "nt" else 0
KEEP_HOURS = 72          # how much run history to keep per token
BOT = re.compile(r"\[bot\]|github-actions|dependabot|renovate|semantic-release|^bot$", re.I)
GH_LINK = re.compile(r"github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})(?:/([A-Za-z0-9_.-]+))?", re.I)
GH_SKIP = {"features", "sponsors", "orgs", "about", "pricing", "login", "topics", "marketplace", "settings", "site"}
ORDER = {"GREEN": 0, "GREY": 1, "AMBER": 2, "RED": 3}
DOT = {"GREEN": "🟢", "AMBER": "🟠", "RED": "🔴", "GREY": "⚪"}


# ---------- GitHub ----------
def _gh(gh_path, path):
    """(status, data): status 'ok', 'gone' (404) or 'error'."""
    try:
        p = subprocess.run([gh_path, "api", path], capture_output=True, timeout=40, creationflags=NOWIN)
    except Exception:
        return "error", None
    if p.returncode != 0:
        err = (p.stderr + p.stdout).decode("utf-8", "replace")
        return ("gone", None) if ("404" in err or "Not Found" in err) else ("error", None)
    try:
        return "ok", json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception:
        return "error", None


def code_target(r):
    """(owner, repo or None) of the project's own GitHub, or (None, None)."""
    sc = r.get("scoring")
    if sc:
        if sc.get("not_theirs") or sc.get("private"):  # private repo: nothing public to watch
            return None, None
        owner, _, repo = (sc.get("repo") or "").partition("/")
        return (owner or None), (repo or None)
    for u in r.get("links") or []:
        m = GH_LINK.search(u or "")
        if m and m.group(1).lower() not in GH_SKIP:
            return m.group(1), (re.sub(r"\.git$", "", m.group(2)) if m.group(2) else None)
    m = re.search(r"\(([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]+)\)", r.get("why") or "")  # tokens.csv note, e.g. "(priors-agents/priors)"
    if m:
        return m.group(1), m.group(2)
    return None, None


def iso(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def code_facts(owner, repo, gh_path, cache, now, run_cache):
    """Last real change across the owner's recently pushed repos (plus the named repo)."""
    key = f"{owner}/{repo or ''}".lower()
    if key in run_cache:
        return run_cache[key]
    out = {"repos": [], "gone": [], "archived": [], "last": None, "bot_only_7d": False, "per_day": {},
           "releases": [], "full_page": False}
    st, lst = _gh(gh_path, f"users/{owner}/repos?sort=pushed&per_page=10")
    if st == "gone":
        out["gone"].append(owner)
        run_cache[key] = out
        return out
    if st == "error":
        out["error"] = True
        run_cache[key] = out
        return out
    names = [x["full_name"] for x in lst or [] if not x.get("fork") and x.get("size", 0) > 0][:3]
    info = {x["full_name"].lower(): x for x in lst or []}
    if repo and f"{owner}/{repo}".lower() not in info:
        st2, one = _gh(gh_path, f"repos/{owner}/{repo}")
        if st2 == "gone":
            out["gone"].append(f"{owner}/{repo}")
        elif one:
            info[one["full_name"].lower()] = one
            names = [one["full_name"]] + names
    elif repo:
        names = [info[f"{owner}/{repo}".lower()]["full_name"]] + [n for n in names if n.lower() != f"{owner}/{repo}".lower()]
    names = list(dict.fromkeys(names))[:4]
    since = (now - datetime.timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    human, bots = [], 0
    for full in names:
        meta = info.get(full.lower()) or {}
        if meta.get("archived"):
            out["archived"].append(full)
        out["repos"].append(full)
        c = cache.get(full.lower())
        pushed = meta.get("pushed_at")
        if not c or c.get("pushed_at") != pushed or not pushed:  # only re-read commits when the repo changed
            st3, commits = _gh(gh_path, f"repos/{full}/commits?since={since}&per_page=100")
            if st3 != "ok":
                continue
            c = {"pushed_at": pushed, "commits": []}
            for x in commits or []:
                cm = x.get("commit") or {}
                who = ((x.get("author") or {}).get("login") or "") + " " + ((cm.get("author") or {}).get("name") or "")
                when = (cm.get("committer") or {}).get("date") or (cm.get("author") or {}).get("date")
                c["commits"].append([when, bool(BOT.search(who.strip()))])
            c["full_page"] = len(commits or []) >= 100
            # a published release counts as shipping too (closed-source teams often only publish app downloads)
            st5, rel = _gh(gh_path, f"repos/{full}/releases?per_page=1")
            if st5 == "ok" and rel:
                c["last_release"] = rel[0].get("published_at")
            # last real change ever, for repos quiet for more than 8 days
            if not any(not b for _, b in c["commits"]):
                st4, last = _gh(gh_path, f"repos/{full}/commits?per_page=10")
                for x in last or []:
                    cm = x.get("commit") or {}
                    who = ((x.get("author") or {}).get("login") or "") + " " + ((cm.get("author") or {}).get("name") or "")
                    if not BOT.search(who.strip()):
                        c["last_human"] = (cm.get("committer") or {}).get("date")
                        break
            cache[full.lower()] = c
        for when, is_bot in c["commits"]:
            if is_bot:
                bots += 1
            else:
                human.append(when)
                d = when[:10]
                out["per_day"][d] = out["per_day"].get(d, 0) + 1
        if c.get("last_human"):
            human.append(c["last_human"])
        if c.get("last_release"):
            out["releases"].append(c["last_release"])
        out["full_page"] = out["full_page"] or c.get("full_page", False)
    out["last"] = max(human) if human else None
    out["last_release"] = max(out["releases"]) if out["releases"] else None
    week = (now - datetime.timedelta(days=7)).isoformat()
    out["bot_only_7d"] = bots > 0 and not any(h >= week[:19] for h in human)
    run_cache[key] = out
    return out


# ---------- market ----------
def market_facts(addr, fetch_json):
    pairs = fetch_json(f"https://api.dexscreener.com/tokens/v1/robinhood/{addr}") or []
    if not pairs:
        return None
    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    return {"mcap": best.get("marketCap") or best.get("fdv"), "liq": (best.get("liquidity") or {}).get("usd")}


def _day_ago(runs, now):
    """The saved run closest to 24h ago (20-28h window), or None."""
    best = None
    for x in runs:
        h = (now - iso(x["t"])).total_seconds() / 3600
        if 20 <= h <= 28 and (best is None or abs(h - 24) < abs((now - iso(best["t"])).total_seconds() / 3600 - 24)):
            best = x
    return best


# ---------- main ----------
def update(rows, fetch, fetch_json, xdb, gh_path, now, log=print):
    db = json.load(open(FILE, encoding="utf-8")) if os.path.exists(FILE) else {}
    db.setdefault("tokens", {})
    db.setdefault("repo_cache", {})
    db.setdefault("alerts", [])
    first_ever = not db["tokens"]
    run_cache, site_cache, seen = {}, {}, set()
    accts = (xdb or {}).get("accounts", {})
    import x_info

    # pass 1: facts
    facts = {}
    for r in rows:
        a = r["address"].lower()
        if a in seen:
            continue
        seen.add(a)
        f = {"t": now.isoformat(timespec="seconds")}
        owner, repo = code_target(r)
        f["own_code"] = bool(owner)
        if owner:
            c = code_facts(owner, repo, gh_path, db["repo_cache"], now, run_cache)
            f.update({"last_commit": c["last"], "repos": c["repos"], "gone": c["gone"], "archived": c["archived"],
                      "bot_only_7d": c["bot_only_7d"], "per_day": c["per_day"], "code_error": c.get("error", False),
                      "last_release": c.get("last_release"), "full_page": c.get("full_page", False)})
            if not c["repos"] and not c["gone"] and not c.get("error"):
                f["own_code"] = False  # account with no public code
        site = r.get("website") or ""
        if site.startswith("http") and not re.search(r"(x|twitter)\.com/|t\.me/|github\.com/", site):
            if site not in site_cache:
                t = fetch(site) or ""
                site_cache[site] = len(t) > 200
            f["site_up"] = site_cache[site]
        h, _ = x_info.parse(r.get("twitter"))
        acc = accts.get((h or "").lower()) if h else None
        if acc and acc.get("checked"):
            f["x_found"] = bool(acc.get("found"))
            f["bio_ca"] = a in (acc.get("bio") or "").lower()
        m = market_facts(r["address"], fetch_json)
        if m:
            f.update(m)
        facts[a] = (r, f)

    # chain-wide move: median 24h change across every token with market data
    ch_m, ch_l = {}, {}
    for a, (r, f) in facts.items():
        old = _day_ago(db["tokens"].get(a, {}).get("runs", []), now)
        if old and old.get("mcap") and f.get("mcap"):
            ch_m[a] = f["mcap"] / old["mcap"] - 1
        if old and old.get("liq") and f.get("liq"):
            ch_l[a] = f["liq"] / old["liq"] - 1
    med_m = statistics.median(ch_m.values()) if len(ch_m) >= 5 else None
    med_l = statistics.median(ch_l.values()) if len(ch_l) >= 5 else None

    # pass 2: status
    changed = 0
    for a, (r, f) in facts.items():
        rec = db["tokens"].setdefault(a, {"runs": []})
        runs = [x for x in rec["runs"] if (now - iso(x["t"])).total_seconds() < KEEP_HOURS * 3600]
        red, amber, green = [], [], []
        if f.get("own_code") and not f.get("code_error"):
            if f.get("gone"):
                red.append(f"GitHub repo deleted or made private ({', '.join(f['gone'])})")
            if f.get("repos") and len(f["archived"]) == len(f["repos"]):
                red.append("Every GitHub repo is archived (frozen)")
            lc = iso(f.get("last_commit"))
            lr = iso(f.get("last_release"))
            if lr and (not lc or lr > lc):  # newest ship was a release
                lc, kind = lr, "release"
            else:
                kind = "change"
            if lc:
                days = (now - lc).total_seconds() / 86400
                ago = f"{days:.0f} days" if days >= 1.5 else f"{days * 24:.0f} hours"
                if days >= 7:
                    red.append(f"No real GitHub change or release for {ago}")
                elif days >= 3:
                    amber.append(f"No real GitHub change or release for {ago}")
                else:
                    wk = sum(f["per_day"].values())
                    green.append(f"Last real GitHub {kind} {ago} ago ({wk}{'+' if f.get('full_page') else ''} change{'' if wk == 1 else 's'} in the last 7 days)")
            elif f.get("repos"):
                red.append("No real GitHub change found at all (only bot changes)" if f.get("bot_only_7d")
                           else "No real GitHub change in the last 8 days")
            if f.get("bot_only_7d") and lc and (now - lc).days >= 3 and kind != "release":
                amber.append("Only bot changes on GitHub this week")
            # a past day's count went up since the last run = changes pushed late (normal, noted only)
            prev = next((x for x in reversed(runs) if x.get("per_day")), None)
            if prev:
                late = [d for d, n in f["per_day"].items() if d < now.strftime("%Y-%m-%d") and n > prev["per_day"].get(d, 0)]
                if late:
                    f["late_days"] = late
        if "site_up" in f:
            recent = [x for x in runs if "site_up" in x and (now - iso(x["t"])).total_seconds() <= 6 * 3600] + [f]
            span = (now - iso(recent[0]["t"])).total_seconds() / 3600
            if not f["site_up"] and len(recent) >= 3 and span >= 5.5 and not any(x["site_up"] for x in recent):
                red.append(f"Website down on every check for {span:.0f} hours ({r.get('website')})")
            elif not f["site_up"]:
                amber.append(f"Website didn't load on the latest check ({r.get('website')})")
        if f.get("x_found") is False and any(x.get("x_found") for x in runs):
            red.append("X account gone (deleted, suspended or renamed)")
        if f.get("bio_ca") is False and f.get("x_found") and any(x.get("bio_ca") for x in runs):
            red.append("Token's address was removed from the X bio")
        if a in ch_m and ch_m[a] <= -0.5 and (med_m is None or med_m > -0.25):
            amber.append(f"Market cap down {-ch_m[a] * 100:.0f}% in 24h while most tokens did not fall")
        if a in ch_l and ch_l[a] <= -0.4 and (med_l is None or med_l > -0.2):
            amber.append(f"Money in the main pool down {-ch_l[a] * 100:.0f}% in 24h while most tokens did not fall")

        status = "RED" if red else ("AMBER" if amber else ("GREEN" if green else "GREY"))
        reasons = red + amber + green
        if status == "GREY":
            reasons = ["No public code of their own to watch"] + reasons
        if f.get("code_error") and f.get("own_code"):
            reasons.append("GitHub didn't answer this run; code status kept from last time")
            if rec.get("status") in ("GREEN", "AMBER", "RED") and not red and not amber:
                status = rec["status"]
        old = rec.get("status")
        new_red = [x for x in red if x not in (rec.get("reasons") or [])]
        if old and (old != status or new_red):
            better = ORDER.get(status, 0) < ORDER.get(old, 0)
            db["alerts"].append({"t": f["t"], "address": r["address"], "symbol": r.get("symbol"), "from": old,
                                 "to": status, "why": (new_red or reasons)[0], "better": better})
            changed += 1
        if old != status:
            rec["since"] = f["t"]
        rec.update({"symbol": r.get("symbol"), "status": status, "reasons": reasons, "checked": f["t"]})
        rec.setdefault("since", f["t"])
        keep = {k: f[k] for k in ("t", "last_commit", "site_up", "x_found", "bio_ca", "mcap", "liq", "per_day") if k in f}
        rec["runs"] = runs + [keep]

    cutoff = (now - datetime.timedelta(days=30)).isoformat()
    db["alerts"] = [x for x in db["alerts"] if x["t"] >= cutoff]
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    with open(FILE + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(db, fh, indent=1)
    os.replace(FILE + ".tmp", FILE)
    counts = {s: sum(1 for a in facts if db["tokens"][a]["status"] == s) for s in ORDER}
    log(f"Shipping: {counts['GREEN']} green, {counts['AMBER']} amber, {counts['RED']} red, {counts['GREY']} grey"
        + (" (first run: starting points saved, no alerts)" if first_ever else f", {changed} changes"))
    return db


# ---------- page ----------
def line(r, db):
    """One line for a token card."""
    rec = (db or {}).get("tokens", {}).get(r["address"].lower())
    if not rec:
        return ""
    e = html.escape
    since = rec.get("since", "")[:16].replace("T", " ")
    return (f"<p class='xline ship'>{DOT[rec['status']]} <b>{rec['status']}</b> since {e(since)} UTC: "
            + e(" · ".join(rec.get("reasons") or [])) + "</p>")


def kv(r, db):
    """Short badge for the test-token rows."""
    rec = (db or {}).get("tokens", {}).get(r["address"].lower())
    return f"<span class='kv'>{DOT[rec['status']]} {rec['status']}</span>" if rec else ""


def alerts_html(db, now):
    e = html.escape
    week = (now - datetime.timedelta(days=7)).isoformat()
    rows = sorted([x for x in (db or {}).get("alerts", []) if x["t"] >= week], key=lambda x: x["t"], reverse=True)
    toks = (db or {}).get("tokens", {})
    counts = " · ".join(f"{DOT[s]} {sum(1 for t in toks.values() if t.get('status') == s)} {s.lower()}"
                        for s in ("GREEN", "AMBER", "RED", "GREY"))
    items = "".join(
        f"<li>{e(x['t'][:16].replace('T', ' '))} UTC · <b>{e(x.get('symbol') or '?')}</b> "
        f"{DOT.get(x['from'], '')}→{DOT.get(x['to'], '')} {e(x['to'])}: {e(x['why'])}</li>" for x in rows[:40])
    return f"""
<section class="card">
<h2>Still shipping? Changes in the last 7 days</h2>
<p class="sub">Now: {counts}. Checks each project's GitHub, website, X and market every run and lists a token here only when its status changes.
🟢 real GitHub change or release in the last 3 days (bots don't count) · 🟠 3–6 days quiet, website failed once, or a sharp drop the rest of the chain didn't have ·
🔴 7+ days quiet, repo gone, website down 6+ hours, X account gone or address removed from its bio · ⚪ no public code of their own to watch.
Catches projects going quiet; it doesn't predict price.</p>
{('<ul>' + items + '</ul>') if items else '<p>No changes yet.</p>'}
</section>"""
