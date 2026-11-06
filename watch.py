"""GitHub watch for new Robinhood Chain tokens.

Runs every 7 minutes (Windows Task Scheduler: "robinhood-scan github watch").
Each run:
  1. lists new tokens on Pons (newest) and DexScreener (Robinhood Chain profiles and boosts)
  2. looks for a public GitHub link: in the token's description and links, then on its website
  3. scores every token that has one (rules: SCORING.md) and writes the reasons
  4. rebuilds site/index.html (open it in a browser)

Hand-checked findings go in reviews.json and replace the script's guesses.
"""
import csv, json, os, re, subprocess, shutil, sys, time, datetime, html, urllib.request, urllib.parse
from collections import Counter
import statistics
import x_info, deployers, test_tokens, prices, shipping, sitecheck, dexpools, notify, test61, tiers

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "data", "watch_state.json")
SITE = os.path.join(HERE, "site", "index.html")
SITE_URL = "https://tradingzoo.github.io/token-watch/"
REVIEWS = os.path.join(HERE, "reviews.json")
LOG = os.path.join(HERE, "last_watch.txt")
UA = "Mozilla/5.0 (robinhood-scan research script)"
NOW = datetime.datetime.now(datetime.timezone.utc)
RESCORE_HOURS = 6       # projects shown on the page (61+)
RESCORE_HIDDEN_HOURS = 24  # hidden (1-60) but still active (young): user, 6 Nov, to cut scan time
RESCORE_RESTING_HOURS = 72  # resting tokens (tiers.py): hidden and older
RESCORE_ZERO_HOURS = 168    # score 0 (copies, not their own code)
MAX_RESCORES = 20          # per list per run, most overdue first, so a batch due at once can't pile up
BUDGET_MIN = 12            # after this many minutes a scan skips optional work (re-scores, resting slice); next scan does it
START = time.time()
RESTING = set()            # addresses resting this run (tiers.py), filled in main()


def over_budget():
    return (time.time() - START) / 60 > BUDGET_MIN


def rescore_hours(g):
    score = g["scoring"]["score"]
    if score >= SHOW_AT:
        return RESCORE_HOURS
    if score == 0:
        return RESCORE_ZERO_HOURS
    return RESCORE_RESTING_HOURS if (g.get("address") or "").lower() in RESTING else RESCORE_HIDDEN_HOURS


def rescore_due(g):
    return days_between(NOW, iso(g["scored_at"])) * 24 >= rescore_hours(g)
COPY_CACHE = {}  # repo@last-push -> (flags, notes); saved in the state file
GH = shutil.which("gh") or r"C:\Users\zacha\AppData\Local\Programs\GitHub CLI\gh.exe"
CURL = shutil.which("curl") or r"C:\Windows\System32\curl.exe"
NOWIN = 0x08000000 if os.name == "nt" else 0  # no console window pop-ups

log_lines = []
def log(*a):
    s = " ".join(str(x) for x in a)
    log_lines.append(s)
    try:
        print(s, flush=True)
    except Exception:
        pass


# ---------- fetching ----------
def fetch(url, timeout=20, limit=3_000_000):
    """Text of a URL, or None. Uses urllib, falls back to curl (some sites fail Python's certificate check)."""
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout)
        return r.read(limit).decode("utf-8", "replace")
    except Exception:
        pass
    try:
        p = subprocess.run([CURL, "-sL", "-m", str(timeout), "-A", UA, url], capture_output=True, timeout=timeout + 5,
                           creationflags=NOWIN)
        return p.stdout[:limit].decode("utf-8", "replace") if p.returncode == 0 and p.stdout else None
    except Exception:
        return None


def fetch_json(url):
    t = fetch(url)
    try:
        return json.loads(t) if t else None
    except Exception:
        return None


def gh(path, include_headers=False):
    args = [GH, "api", path] + (["-i"] if include_headers else [])
    try:
        p = subprocess.run(args, capture_output=True, timeout=40, creationflags=NOWIN)
    except Exception:
        return None
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode != 0:
        return None
    if include_headers:
        head, _, body = out.replace("\r\n", "\n").partition("\n\n")
        try:
            return head, json.loads(body)
        except Exception:
            return head, None
    try:
        return json.loads(out)
    except Exception:
        return None


# ---------- discovery ----------
def pons_tokens(saved_file=None):
    s = open(saved_file, encoding="utf-8").read() if saved_file else fetch("https://ponsfamily.com/launchpad?sort=newest")
    if not s:
        log("Pons: could not load")
        return []
    found = _pons_parse(s)
    log(f"Pons: {len(found)} tokens on the newest page")
    return list(found.values())


def pons_busy():
    """Pons's top-by-market-cap and top-by-volume pages: catches tokens that take off after leaving the newest page."""
    found = {}
    for sort in ("marketcap", "volume"):
        s = fetch(f"https://ponsfamily.com/launchpad?sort={sort}")
        found.update(_pons_parse(s) if s else {})
    log(f"Pons: {len(found)} tokens on the market-cap and volume pages")
    return list(found.values())


CATCHUP = os.path.join(HERE, "data", "catchup.json")  # older launches still to check (one-time sweep, 5 Nov)
CATCHUP_PER_RUN = 20
CATCHUP_SITE_SLOTS = 15  # of the site check's new slots per run, reserved for catch-up tokens


def catchup(state):
    """Up to CATCHUP_PER_RUN older Pons tokens from data/catchup.json that the scanner hasn't fully checked yet.
    A token leaves the list once both the GitHub check and the site check have looked at it."""
    if not os.path.exists(CATCHUP):
        return []
    todo = json.load(open(CATCHUP, encoding="utf-8"))
    plain = set(state.get("catchup_plain", []))  # no website and no X: only the GitHub check applies
    done = lambda a: a in state["github"] or a in state.get("sites", {}) or (
        a in state["seen"] and (a in state.get("site_checked", {}) or a in plain))
    todo = [a for a in todo if not done(a)]
    json.dump(todo, open(CATCHUP, "w", encoding="utf-8"))
    got = {a: pons_one(a) for a in todo[:CATCHUP_PER_RUN]}
    not_pons = [a for a, t in got.items() if not t]  # launched elsewhere (FOBO-style): build it from DexScreener
    if not_pons:
        got.update(dexpools.lookup(not_pons, fetch_json))
    out = [t for t in got.values() if t]
    for t in out:
        t["catchup"] = True  # gets reserved site-check slots (site_pass)
    plain |= {a for a, t in got.items() if t and not (t.get("website") or x_info.parse(t.get("twitter"))[0])}
    state["catchup_plain"] = sorted(plain & set(todo))
    gone = {a for a, t in got.items() if not t}  # not on Pons or DexScreener: nothing to check
    if gone:
        todo = [a for a in todo if a not in gone]
        json.dump(todo, open(CATCHUP, "w", encoding="utf-8"))
    if todo:
        log(f"Catch-up: {len(out)} older tokens added this run, {len(todo)} left")
    return out


PONS_ONE = {}  # address -> token facts from its own Pons page, this run only


def pons_one(addr):
    """One token's facts from its own Pons page (for tokens that are no longer on the newest page)."""
    a = addr.lower()
    if a not in PONS_ONE:
        s = fetch(f"https://ponsfamily.com/launchpad/{a}")
        PONS_ONE[a] = _pons_parse(s).get(a) if s else None
    return PONS_ONE[a]


def _pons_parse(s):
    s = s.replace('\\"', '"')
    dec = json.JSONDecoder()
    found = {}
    for m in re.finditer(r'\{"address":"0x[0-9a-f]{40}","name"', s):
        try:
            o, _ = dec.raw_decode(s, m.start())
        except Exception:
            continue
        if "createdAt" not in o:
            continue
        soc = {k: v for k, v in (o.get("socials") or {}).items() if v}
        found[o["address"]] = {
            "address": o["address"], "symbol": o.get("symbol"), "name": o.get("name"), "source": "pons",
            "launched": datetime.datetime.fromtimestamp(o["createdAt"], datetime.timezone.utc).isoformat(timespec="seconds"),
            "description": o.get("description") or "", "links": list(soc.values()), "website": soc.get("website"),
            "twitter": soc.get("twitter"), "mcap": o.get("marketCapUsd"), "stage": o.get("stage"),
            "deployer": o.get("deployer"),
        }
    return found


def dex_tokens():
    out = {}
    for ep in ["token-profiles/latest/v1", "token-boosts/latest/v1", "token-boosts/top/v1", "community-takeovers/latest/v1"]:
        for x in fetch_json(f"https://api.dexscreener.com/{ep}") or []:
            if x.get("chainId") != "robinhood":
                continue
            a = x["tokenAddress"]
            links = [l.get("url") for l in x.get("links") or [] if l.get("url")]
            web = next((l.get("url") for l in x.get("links") or [] if (l.get("type") or l.get("label") or "").lower() in ("website", "")
                        and l.get("url") and "x.com" not in l["url"] and "t.me" not in l["url"] and "github" not in l["url"]), None)
            prev = out.get(a, {})
            out[a] = {"address": a, "symbol": prev.get("symbol"), "name": None, "source": "dexscreener",
                      "launched": None, "description": x.get("description") or "", "links": links,
                      "website": web, "twitter": next((u for u in links if "x.com" in u or "twitter.com" in u), None)}
    log(f"DexScreener: {len(out)} Robinhood Chain tokens in profiles/boosts")
    return list(out.values())


PONS_TIMES = {}  # address -> createdAt / graduatedAt / stage seen on its Pons page this run (saved by tiers.py)
RUN_STATS = {}   # counts for data/runs.csv


def pons_times(addr):
    """Launch and graduation time from a token's own Pons page (for tokens priced on an exchange, whose page
    the price check doesn't open)."""
    s = fetch(f"https://ponsfamily.com/launchpad/{addr}")
    if not s:
        return
    s = s.replace('\\"', '"')
    i = s.find('{"address":"%s"' % addr)
    if i < 0:
        return
    try:
        o, _ = json.JSONDecoder().raw_decode(s, i)
        o = o.get("launch") or o
        PONS_TIMES[addr] = {k: o.get(k) for k in ("createdAt", "graduatedAt", "stage")}
    except Exception:
        pass


def test_keep():
    """Addresses (lower case) of both 30-day tests' tokens: always fully checked."""
    keep = set()
    try:
        keep |= {t["address"].lower() for t in csv.DictReader(open(os.path.join(HERE, "tokens.csv"), encoding="utf-8"))}
    except Exception:
        pass
    try:
        keep |= set(json.load(open(test61.FILE, encoding="utf-8")).get("tokens", {}))
    except Exception:
        pass
    return keep


def market(addr):
    """Symbol, market cap and where it trades now."""
    pairs = [p for p in fetch_json(f"https://api.dexscreener.com/tokens/v1/robinhood/{addr}") or []
             if ((p.get("liquidity") or {}).get("usd") or 0) >= prices.JUNK_LIQ]  # trap pools give fake prices
    if pairs:
        best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
        return {"symbol": best["baseToken"]["symbol"], "name": best["baseToken"]["name"],
                "mcap": best.get("marketCap") or best.get("fdv"), "where": "exchange",
                "quote": (best.get("quoteToken") or {}).get("symbol"),
                "launched": datetime.datetime.fromtimestamp(min(p.get("pairCreatedAt") or 9e12 for p in pairs) / 1000,
                                                            datetime.timezone.utc).isoformat(timespec="seconds")}
    s = fetch(f"https://ponsfamily.com/launchpad/{addr.lower()}")
    if s:
        s = s.replace('\\"', '"')
        i = s.find('{"address":"%s"' % addr.lower())
        if i >= 0:
            try:
                o, _ = json.JSONDecoder().raw_decode(s, i)
                o = o.get("launch") or o
                PONS_TIMES[addr.lower()] = {k: o.get(k) for k in ("createdAt", "graduatedAt", "stage")}  # tiers.py
                return {"symbol": o.get("symbol"), "name": o.get("name"), "mcap": o.get("marketCapUsd"),
                        "where": f"Pons launchpad ({o.get('stage')})"}
            except Exception:
                pass
    return {}


# ---------- finding the GitHub ----------
GH_RE = re.compile(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))(?:/([A-Za-z0-9_.-]+))?", re.I)
GH_SKIP = {"features", "sponsors", "orgs", "about", "pricing", "login", "join", "topics", "marketplace", "settings",
           "site", "security", "enterprise", "collections", "apps", "readme", "trending", "explore", "contact"}


def github_links(text):
    res = []
    for m in GH_RE.finditer(text or ""):
        owner, repo = m.group(1), m.group(2)
        if owner.lower() in GH_SKIP:
            continue
        if repo:
            repo = re.sub(r"\.git$", "", repo)
            if repo.lower() in ("issues", "pulls", "releases"):
                repo = None
        res.append((owner, repo))
    return list(dict.fromkeys(res))


def website_text(url):
    """(page html, text of up to 4 of its own script files). Many sites only build their links in JavaScript."""
    if not url or not url.startswith("http"):
        return "", ""
    page = fetch(url) or ""
    parts = []
    host = urllib.parse.urlparse(url).netloc
    for src in re.findall(r'<script[^>]+src="([^"]+)"', page)[:12]:
        full = urllib.parse.urljoin(url, src)
        if urllib.parse.urlparse(full).netloc != host:
            continue
        parts.append(fetch(full, limit=2_500_000) or "")
        if len(parts) >= 4:
            break
    # follow the files those scripts load (settings files like config.js often hold the GitHub link and token address)
    extra = []
    for js in parts[:4]:
        for imp in re.findall(r"""(?:from\s*|import\s*\(\s*|import\s+)["'](\.{0,2}/[^"']+\.m?js)["']""", js)[:6]:
            full = urllib.parse.urljoin(url if url.endswith("/") else url + "/", imp)
            if urllib.parse.urlparse(full).netloc == host:
                extra.append(fetch(full, limit=1_000_000) or "")
    return page, "\n".join(parts + extra)


LIB_OWNERS = {"vercel", "supabase", "ethers-io", "uuidjs", "krakenfx", "facebook", "reactjs", "vuejs", "sveltejs",
              "microsoft", "google", "googlechrome", "mozilla", "nodejs", "npm", "tailwindlabs", "twbs", "jquery",
              "wevm", "wagmi-dev", "rainbow-me", "walletconnect", "reown-com", "uniswap", "openzeppelin", "foundry-rs",
              "ethereum", "web3", "chainsafe", "solana-labs", "metamask", "coinbase", "privy-io", "dynamic-labs",
              "lodash", "axios", "mrdoob", "pmndrs", "framer", "motiondivision", "radix-ui", "shadcn", "lucide-icons",
              "feross", "paulmillr", "indutny", "browserify", "webpack", "babel", "zloirock", "remix-run", "vitejs",
              "nextjs", "tanstack", "apollographql", "graphql", "sentry", "getsentry", "posthog", "stripe", "anthropics",
              "openai", "huggingface", "d3", "chartjs", "tradingview", "ipfs", "protocol", "highlightjs", "prismjs",
              "markedjs", "cure53", "mathjax", "katex", "fortawesome", "github"}


NOT_A_SITE = {"github.com", "x.com", "twitter.com", "t.me", "discord.gg", "discord.com", "linktr.ee", "medium.com",
              "youtube.com", "reddit.com", "gitbook.io", "ponsfamily.com", "dexscreener.com"}


def name_bits(tok):
    """Words that should appear in the project's own repo: symbol, name, website name, X handle."""
    bits = set()
    handle = re.search(r"(?:x|twitter)\.com/([^/?#]+)", tok.get("twitter") or "")
    site = domain(tok.get("website") or "")
    for v in (tok.get("symbol"), tok.get("name"), "" if site in NOT_A_SITE else site.split(".")[0],
              handle.group(1) if handle else ""):
        for w in re.split(r"[^a-z0-9]+", (v or "").lower()):
            if len(w) >= 4 and w not in ("token", "coin", "finance", "labs", "agent", "agents", "status", "https"):
                bits.add(w)
    return bits


def related(tok, owner, repo):
    hay = (owner + " " + (repo or "")).lower().replace("-", "").replace("_", "")
    return any(b in hay for b in name_bits(tok))


def choose_link(tok, links_by_origin):
    """Pick the project's own repo. Links shown on the token page or as a link on the website are taken as
    'what they point people to'; links found only inside script files must look related to the token
    (otherwise they are code libraries the site happens to use)."""
    # 1. a repo whose name matches the project wins, wherever it was found (token page, visible link, or settings file)
    for origin in ("token page", "website", "website code"):
        cands = [l for l in links_by_origin.get(origin, []) if l[0].lower() not in LIB_OWNERS and related(tok, *l)]
        if cands:
            cands.sort(key=lambda l: l[1] is None)
            return cands[0], ("website" if origin == "website code" else origin)
    # 2. otherwise what they visibly point people to
    for origin in ("token page", "website"):
        cands = [l for l in links_by_origin.get(origin, []) if l[0].lower() not in LIB_OWNERS]
        if cands:
            cands.sort(key=lambda l: l[1] is None)
            return cands[0], origin
    cands = [l for l in links_by_origin.get("website code", []) if l[0].lower() not in LIB_OWNERS and related(tok, *l)]
    if cands:
        cands.sort(key=lambda l: l[1] is None)
        return cands[0], "website"
    return None, None


INFO_GROUPS = {"Team", "Live product"}  # parts shown as information only, no points (5 Nov)
PRIVATE_CAP = 40  # public code is weighed more: a private GitHub can't score above this
PRIVATE_CLAIMED_CAP = 60  # ...unless their own website posts the token's address (DARK, 5 Nov)


def score_private(tok, full, owner, user, found_on, symbol_counts, review, reasons, flags, add, total):
    """GitHub account is real but shows no code (private repos, or the linked repo is private/deleted).
    Score only what can be checked without the code; Real code = 0; capped at PRIVATE_CAP."""
    rname = full.split("/")[1]
    if not user.get("login"):
        flags.append(f"GitHub link is dead: github.com/{owner} doesn't exist")
        return {"repo": full, "score": 0, "capped": True, "flags": flags, "private": True,
                "reasons": {"Really theirs": [f"❌ github.com/{owner} doesn't exist"]}, "roadmap": [], "facts": {}}
    what = (f"the linked repo {full} is private or deleted" if rname else f"github.com/{owner} has no public repos")
    srcs = project_sources(tok)
    claimed = any(tok["address"].lower() in t.lower() for w, u, t in srcs)
    cap = PRIVATE_CLAIMED_CAP if claimed else PRIVATE_CAP
    reasons["Really theirs"].append(f"🔒 Private GitHub: {what}. Code can't be checked, so the score is capped at {cap}"
                                    + (" (not 40: their own website posts the token's address)" if claimed else ""))
    text = " ".join([tok.get("description") or ""] + [t for w, u, t in srcs if w == "docs"]).lower()
    rv = review.get("checks", {})
    # Platform (40): same guesses as a public repo, from the token page and their docs
    if "earns" in rv:
        add("Platform", rv["earns"][0], rv["earns"][1] + " — checked by hand", "✅" if rv["earns"][0] >= 20 else "🟡")
    else:
        hits = sorted({w.strip() for w in EARN_WORDS if w in text})
        if len(hits) >= 2:
            add("Platform", 20, f"Looks like it earns fees from users ({', '.join(hits[:4])}) — guess from their text, needs a look", "🟡")
        elif hits:
            add("Platform", 10, f"Maybe earns fees ({hits[0]}) — guess from their text, needs a look", "🟡")
        else:
            add("Platform", 0, "No sign it earns fees from other people using it")
    if "fees_back" in rv:
        add("Platform", rv["fees_back"][0], rv["fees_back"][1] + " — checked by hand",
            "✅" if rv["fees_back"][0] >= 20 else ("🟡" if rv["fees_back"][0] else "❌"))
    else:
        hits = back_hits(text)
        add("Platform", 10 if hits else 0, (f"Says fees go back to the token ({', '.join(hits[:3])}) — claimed, not checked on chain"
                                            if hits else "No sign fees go back to the token"), "🟡" if hits else None)
    # Really theirs (20): website links the GitHub; GitHub account named after the project
    add("Really theirs", 10 if found_on == "website" else 0,
        "Their website links this GitHub" if found_on == "website" else "Only the token page links this GitHub (anyone can add that)")
    named = related(tok, owner, None)
    add("Really theirs", 10 if named else 0,
        f"GitHub account {owner} is named after the project" if named else f"GitHub account {owner} isn't named after the project")
    if found_on != "website" and not named:
        flags.append(f"Nothing ties the private GitHub {owner} to this token — may be someone else's account")
    ment = token_mentions(tok, srcs)
    for m in ment[:3]:
        reasons["Really theirs"].append(f"✅ Their {m['where']} mentions the token: {m['what']} ({m['url']})")
    # Real code (20): can't see it
    add("Real code", 0, "Code is private: changes, contracts and tests can't be checked")
    # Team (10): account age or followers
    age = days_between(NOW, iso(user["created_at"])) if user.get("created_at") else 0
    ok = age >= 90 or (user.get("followers") or 0) >= 10
    add("Team", 10 if ok else 0, f"GitHub account {age:.0f} days old, {user.get('followers', 0)} followers")
    # Safety (10): only what their own pages say
    sec = [x for x in ("audit", "timelock") if x in text]
    add("Safety", 5 if sec else 0, ("Their docs mention: " + ", ".join(sec)) if sec else "No audit or timelock info on their pages")
    if symbol_counts.get(tok.get("symbol"), 0) >= 3:
        flags.append(f"{tok.get('symbol')} was launched {symbol_counts[tok.get('symbol')]} times on Pons")
    for f in review.get("flags", []):
        flags.append(f + " (checked by hand)")
    not_theirs = [f for f in flags if " times on Pons" not in f and not f.startswith(X_MISMATCH) and not f.startswith(UNCLAIMED)]
    t = total()
    final = 0 if not_theirs else min(t, 25 if flags else cap)
    if t > cap and not flags:
        reasons["Really theirs"].append(f"ℹ️ Points add up to {t}, capped at {cap} because the code is private")
    return {"repo": full, "score": final, "capped": final < t, "flags": flags, "private": True,
            "reasons": reasons, "notes": review.get("notes", []), "roadmap": [],
            "facts": {"created": (user.get("created_at") or "?")[:10], "pushed": "private", "commits": "private"}}


def pick_repos(owner, repo):
    if repo:
        return [f"{owner}/{repo}"]
    repos = gh(f"users/{owner}/repos?sort=pushed&per_page=20") or []
    keep = [r["full_name"] for r in repos if not r.get("fork") and r.get("size", 0) > 0][:2]
    return keep or [f"{owner}/"]  # empty account -> red flag later



# ---------- does the project itself mention the token? ----------
def project_sources(tok):
    """[(where, url, text)] from the website, its code files, and its docs."""
    out = []
    site = tok.get("website") or ""
    if not site.startswith("http") or any(x in site for x in ("x.com/", "twitter.com/", "t.me/")):
        return out
    if sitecheck.listing_page(site):  # its own page on Pons/pump.fun/etc. lists its address but isn't their site
        return out
    page, code = website_text(site)
    out.append(("website", site, page))
    out.append(("website code", site, code))  # its script files: links and addresses often live here
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(site))
    host = domain(site)
    tries = [base + "/llms-full.txt", base + "/llms.txt", f"https://docs.{host}/llms-full.txt",
             f"https://docs.{host}/llms.txt", base + "/docs"]
    hrefs = re.findall(r'href="([^"]+)"', page)
    tries += [urllib.parse.urljoin(site, h) for h in hrefs
              if re.search(r"docs?|whitepaper|litepaper|gitbook|tokenomics|token", h, re.I)
              and not re.search(r"github\.com|x\.com|twitter|t\.me|discord", h, re.I)][:4]
    seen = set()
    for u in tries:
        if u in seen:
            continue
        seen.add(u)
        t = fetch(u, timeout=15, limit=1_500_000)
        if t and len(t) > 300 and "<title>404" not in t[:3000] and "Not Found" not in t[:200]:
            out.append(("docs", u, t))
    return out


# A page saying there is no token yet, or that other tokens are fake (BLACKPOOL, 6 Nov: its FAQ said
# "Token details are TBA ... treat anything else as unofficial" while a $BLACKPOOL token traded on Pons).
DISCLAIM = re.compile(r"(?:\bare|\bis|:)\s*\**\s*TBA\b|to be announced|there is no (?:official )?token|(?:we )?(?:do not|don't) have (?:a|an official) token|no official token|not (?:yet )?launched (?:a|any|our) token"
                      r"|haven'?t launched|has not launched|anything else as unofficial|any token will be announced"
                      r"|(?:fake|unofficial|unaffiliated) tokens?|not affiliated with any token|beware of (?:fake|scam)", re.I)


def token_disclaimer(tok, sources):
    """The project's own page saying there's no official token yet, as a short quote, or None."""
    for where, url, text in sources:
        for m in re.finditer(r"\btoken\b", text, re.I):
            off = max(0, m.start() - 200)
            d = DISCLAIM.search(text[off:m.end() + 250])
            if d:
                q = text[max(0, off + d.start() - 90):off + d.end() + 110]
                q = html.unescape(re.sub(r"<[^>]+>", " ", q))
                q = re.sub(r'"?(?:@type|acceptedAnswer|name|text)"?\s*:|"?(?:Question|Answer)"?\s*,|[{}"\[\]]', " ", q)
                q = re.sub(r"\s+", " ", q).strip(" ,:")
                q = re.sub(r"^[^A-Z]{0,20}(?=[A-Z])", "", q)  # start at a sentence, not mid-word
                return where, url, q[:200]
    return None


def token_mentions(tok, sources):
    """Evidence that the project's own pages mention this token."""
    addr = tok["address"].lower()
    sym = re.escape((tok.get("symbol") or "").strip())
    pats = [("its contract address", re.compile(re.escape(addr), re.I))]
    if len(sym) >= 2:
        pats.append((f"${tok['symbol']}", re.compile(r"\$" + sym + r"\b", re.I)))
        pats.append((f"'{tok['symbol']} token'", re.compile(r"\b" + sym + r"\s+token\b", re.I)))
    pats.append(("a link to its Pons page", re.compile(r"ponsfamily\.com/launchpad/" + re.escape(addr), re.I)))
    pats.append(("a link to its DexScreener page", re.compile(r"dexscreener\.com/robinhood/" + re.escape(addr), re.I)))
    found = []
    for where, url, text in sources:
        for label, rx in pats:
            m = rx.search(text)
            if m and label != "its contract address" and DISCLAIM.search(text[max(0, m.start() - 300):m.end() + 300]):
                continue  # "Is there a BLACKPOOL token? Token details are TBA": not a claim (6 Nov)
            if m:
                a, b = max(0, m.start() - 70), m.end() + 70
                snip = re.sub(r"<[^>]+>", " ", text[a:b])
                snip = re.sub(r"\s+", " ", html.unescape(snip)).strip()
                found.append({"where": where, "url": url, "what": label, "snippet": snip[:180]})
    # one line per page+kind
    uniq = {}
    for f in found:
        uniq.setdefault((f["url"], f["what"]), f)
    return list(uniq.values())

X_MISMATCH = "X account doesn't match the website"
X_CACHE = {}  # handle (lower) -> fxtwitter facts, this run only


def x_account(handle):
    """Facts for one X account (bio + recent posts, incl. token addresses it posted). Reuses x_info.json if fresh."""
    k = handle.lower()
    if k not in X_CACHE:
        rec = None
        try:
            db = json.load(open(x_info.FILE, encoding="utf-8")) if os.path.exists(x_info.FILE) else {}
            rec = (db.get("accounts") or {}).get(k)
            X_CACHE[k] = rec if x_info._fresh(rec, NOW) else x_info._lookup(handle, fetch_json, NOW)
        except Exception:
            X_CACHE[k] = rec  # couldn't check now: use the last result (older than 12h) rather than nothing
    return X_CACHE[k]


def official_x(tok, srcs):
    """The project's official X = the one their WEBSITE links (a token page can list anyone's X for free).
    Returns site handles, token's handle, official handle, whether it posted this token's address, and mismatch."""
    site_text = " ".join(t for w, u, t in srcs if w in ("website", "website code"))
    site = []
    for m in re.finditer(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_/]*/status)", site_text):
        h = m.group(1)
        if h.lower() not in x_info.NOT_HANDLES and h.lower() not in [s.lower() for s in site]:
            site.append(h)
    site = site[:5]
    token_h, is_post = x_info.parse(tok.get("twitter"))
    token_h = None if is_post else token_h
    official = next((h for h in site if token_h and h.lower() == token_h.lower()), site[0] if site else None)
    acct = x_account(official) if official else None
    posted = bool(acct and acct.get("found") and tok["address"].lower() in (acct.get("cas") or []))
    # A freed-up handle can be grabbed by anyone (CUBE, 4 Nov). A brand-new account posting the address doesn't count.
    joined = iso(acct.get("joined")) if posted and acct.get("joined") else None
    young = bool(posted and (not joined or days_between(NOW, joined) < 30))
    mismatch = bool(token_h and site and token_h.lower() not in [h.lower() for h in site])
    return {"site": site, "token": token_h, "official": official, "posted": posted and not young,
            "young": young, "joined": joined, "mismatch": mismatch}


def x_mismatch_note(ox, where):
    acct = x_account(ox["token"]) if ox.get("token") else None
    gone = not acct or not acct.get("found")
    return (f"X differs: the token links @{ox['token']}" + (" (that account no longer exists)" if gone else "")
            + ", but the project now uses " + ", ".join("@" + h for h in ox["site"])
            + f". The token's address is on their own {where}, so it is theirs: warning only, no cap")


COPYCAT = "Copycat token"
UNCLAIMED = "Dev never mentions this token"
UNOFFICIAL = "Probably not the team's token (checked by hand)"


def copycat(tok, ox):
    """Same-name copy check (bytejury, 5 Nov): someone relaunches a token under the same name and links the
    real project's website and X. If the project's X posts a DIFFERENT address for a token with the same
    name or symbol, and doesn't post this one, this token is very likely the copy. Returns the real one or None."""
    addr = tok["address"].lower()
    handles = [h for h in (ox.get("official"), x_info.parse(tok.get("twitter"))[0]) if h]
    for h in dict.fromkeys(x.lower() for x in handles):
        acct = x_account(h)
        cas = (acct or {}).get("cas") or []
        if not acct or not acct.get("found") or addr in cas:
            continue
        warned = " ".join(acct.get("fake_posts") or []).lower()
        for ca in [c for c in cas if c != addr and c not in warned][:4]:  # never call an address they warned about "real"
            other = pons_one(ca)
            if not other:
                continue
            same = [w for w, a, b in (("symbol", other.get("symbol"), tok.get("symbol")), ("name", other.get("name"), tok.get("name")))
                    if a and b and a.strip().lower() == b.strip().lower()]
            if same:
                return {"real": ca, "handle": acct.get("handle") or h, "same": same, "launched": other.get("launched"),
                        "mcap": other.get("mcap")}
    return None


# ---------- scoring (rules in SCORING.md) ----------
EARN_WORDS = ["protocol fee", "swap fee", "trading fee", "fees", "launchpad", "lending", "borrow", "exchange", " dex",
              "perps", "perpetual", "options", "liquidity", "vault", "marketplace", "hook", "pay per", "payments"]
BACK_WORDS = ["buyback", "buy back", "buy-back", "burn", "staking", "stake ", "stakers", "revenue share", "fee share",
              "holders earn", "to holders", "paid to holders", "distributed to holders", "real yield"]
# A "no / not / never / without" up to 2 words before the word, in the same sentence, means they say they DON'T do it
# (6 Nov, MERY: "there is no buyback, no burn tax and no revenue share" had earned +10 for a buyback).
NEG_BEFORE = re.compile(r"\b(?:no|not|never|without|zero|nor|don'?t|doesn'?t|won'?t|isn'?t|aren'?t)\b"
                        r"(?:[^\w.!?;:\n]+\w+){0,2}[^\w.!?;:\n]*$", re.I)


def said_not(text, start):
    """True if the words just before position `start` deny it ("there is no buyback")."""
    return bool(NEG_BEFORE.search(text[max(0, start - 60):start]))


def back_hits(text):
    """BACK_WORDS found in text, leaving out the ones they say they don't do."""
    return sorted({w.strip() for w in BACK_WORDS
                   if any(not said_not(text, m.start()) for m in re.finditer(re.escape(w), text))})


def domain(u):
    try:
        d = urllib.parse.urlparse(u if "//" in u else "https://" + u).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def days_between(a, b):
    return abs((a - b).total_seconds()) / 86400


def iso(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def readme_of(full):
    r = gh(f"repos/{full}/readme")
    if not r or not r.get("content"):
        return ""
    import base64
    try:
        return base64.b64decode(r["content"]).decode("utf-8", "replace")
    except Exception:
        return ""


def commit_stats(full):
    """(number of commits, first commit date, last commit date, first commit id)"""
    r = gh(f"repos/{full}/commits?per_page=1", include_headers=True)
    if not r or not r[1]:
        return 0, None, None, None
    head, body = r
    last = iso(body[0]["commit"]["author"]["date"])
    m = re.search(r'page=(\d+)>; rel="last"', head)
    n = int(m.group(1)) if m else 1
    first, first_sha = last, body[0]["sha"]
    if n > 1:
        r2 = gh(f"repos/{full}/commits?per_page=1&page={n}")
        if r2:
            first, first_sha = iso(r2[0]["commit"]["author"]["date"]), r2[0]["sha"]
    return n, first, last, first_sha


# ---------- copy check ----------
CODE_EXT = (".sol", ".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go", ".move", ".vy")
SKIP_PATH = re.compile(r"(^|/)(lib|libs|node_modules|vendor|vendored|dist|build|out|public|static|assets|third_party|"
                       r"deps|external|submodules|test|tests|__tests__|mocks?|examples?|scripts?|abis?|generated|gen|types|typechain|artifacts|locales?|i18n)(/|$)|\.min\.|\.d\.ts$|\.(test|spec|config)\.|"
                       r"(^|/)(package-lock|pnpm-lock|yarn\.lock)", re.I)
BORING = re.compile(r"^\s*(import|from|export \*|#|//|/\*|\*|pragma|using|require|use |package |module\.exports|"
                    r"\}|\{|return;|else|try|catch|console\.)", re.I)


def distinctive_lines(full, tree_items, want=3):
    files = [t for t in tree_items if t.get("type") == "blob" and t["path"].endswith(CODE_EXT) and not SKIP_PATH.search(t["path"])]
    files.sort(key=lambda t: t.get("size", 0), reverse=True)
    picked = []
    for f in files[:8]:
        raw = fetch(f"https://raw.githubusercontent.com/{full}/HEAD/{urllib.parse.quote(f['path'])}", limit=400_000) or ""
        lines = raw.splitlines()
        cands = []
        for i, ln in enumerate(lines[len(lines) // 5:]):  # skip the header part of the file
            s = ln.strip()
            if not (35 <= len(s) <= 110) or BORING.match(s) or s.count('"') + s.count("'") > 4 or re.match(r"""^["'][^"']+["']\s*:""", s):
                continue
            idents = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", s)
            if len(set(idents)) >= 3:
                cands.append((len(set(idents)), s))
        if cands:
            cands.sort(reverse=True)
            picked.append((f["path"], cands[0][1]))
        if len(picked) >= want:
            break
    return picked


def copy_check(full, tree_items, repo_created, first_sha, n_commits):
    """Returns (red_flags, notes). Looks for this repo's code in older repos by other people,
    and for code that all arrived in the very first change."""
    flags, notes = [], []
    owner = full.split("/")[0].lower()
    hits = Counter()
    self_found = 0
    lines = distinctive_lines(full, tree_items)
    for path, line in lines:
        q = re.sub(r'["\\]', " ", line)
        r = gh("search/code?q=" + urllib.parse.quote(f'"{q}"') + "&per_page=30")
        time.sleep(7)  # GitHub allows ~10 code searches a minute
        items = (r or {}).get("items", [])
        self_found += any(it["repository"]["full_name"].lower() == full.lower() for it in items)
        others = {it["repository"]["full_name"] for it in items if it["repository"]["owner"]["login"].lower() != owner}
        for o in others:
            hits[o] += 1
    older = []
    for other, n in hits.most_common(10):
        info = gh(f"repos/{other}") or {}
        c = iso(info.get("created_at"))
        if c and repo_created and c < repo_created:
            older.append((other, n, info.get("stargazers_count", 0)))
    strong = sorted([o for o in older if o[1] >= 2], key=lambda o: (o[1], o[2]), reverse=True)
    if strong:
        o = strong[0]
        more = f", plus {len(strong) - 1} other older repos" if len(strong) > 1 else ""
        flags.append(f"Code matches older repo {o[0]} ({o[2]} stars){more}: {o[1]} of {len(lines)} sample lines — may be copied")
    elif older:
        o = older[0]
        notes.append(f"ℹ️ 1 of {len(lines)} sample lines also appears in older repo {o[0]} — could be shared library code")
    elif lines and self_found:
        notes.append(f"✅ Copy check: {len(lines)} sample lines from their main code not found in anyone else's older repo")
    elif lines:
        notes.append("ℹ️ Copy check couldn't run yet: GitHub's search hasn't indexed this repo (common for new repos), will retry")
        flags.append("__retry__")
    else:
        notes.append("ℹ️ Copy check: not enough of their own code to sample")

    blobs = sum(1 for t in tree_items if t.get("type") == "blob")
    if first_sha and blobs >= 30:
        fc = gh(f"repos/{full}/commits/{first_sha}") or {}
        n_first = len(fc.get("files") or [])
        share = n_first / blobs
        if share >= 0.6:
            notes.append(f"ℹ️ {'300+' if n_first >= 300 else n_first} of {blobs} files arrived in the very first change"
                         " — could be copied, or moved over from a private repo")
    return flags, notes


def roadmap_of(full, tree, website):
    pts = []
    files = [p for p in tree if "roadmap" in p.lower() and not p.lower().endswith((".css", ".js", ".mjs", ".test.mjs"))]
    for p in files[:3]:
        if p.lower().endswith((".md", ".json")):
            raw = fetch(f"https://raw.githubusercontent.com/{full}/HEAD/{urllib.parse.quote(p)}") or ""
            if p.lower().endswith(".md"):
                done = len(re.findall(r"- \[x\]", raw, re.I))
                todo = len(re.findall(r"- \[ \]", raw))
                items = len(re.findall(r"^\s*[-*] ", raw, re.M))
                pts.append(f"`{p}`: {items} items" + (f", {done} ticked done, {todo} not done" if done + todo else ""))
            else:
                try:
                    j = json.loads(raw)
                    lists = [v for v in (j.values() if isinstance(j, dict) else [j]) if isinstance(v, list)]
                    n = max((len(v) for v in lists), default=0)
                    pts.append(f"`{p}`: {n} planned items")
                except Exception:
                    pts.append(f"`{p}` found")
    ch = next((p for p in tree if p.lower() == "changelog.md"), None)
    if ch:
        raw = fetch(f"https://raw.githubusercontent.com/{full}/HEAD/{ch}") or ""
        pts.append(f"CHANGELOG.md: {len(re.findall(r'^## ', raw, re.M))} updates shipped so far")
    if website:
        r = fetch(urllib.parse.urljoin(website, "/roadmap"))
        if r and "roadmap" in r.lower() and len(r) > 2000:
            pts.append(f"Website has a roadmap page: {urllib.parse.urljoin(website, '/roadmap')}")
    return pts or ["No roadmap found in the repo or on the website"]


def score(tok, full, found_on, symbol_counts, review):
    reasons = {"Platform": [], "Really theirs": [], "Real code": [], "Team": [], "Safety": []}
    flags, total = [], 0

    def add(group, pts, text, mark=None):
        nonlocal total
        if group in INFO_GROUPS:  # shown, not scored (5 Nov test: Team didn't separate winners from dead tokens)
            reasons[group].append(f"ℹ️ {text}")
            return
        total += pts
        mark = mark or ("✅" if pts > 0 else "❌")
        reasons[group].append(f"{mark} {text} (+{pts})")

    owner = full.split("/")[0]
    repo = gh(f"repos/{full}") if full.split("/")[1] else None
    user = gh(f"users/{owner}") or {}
    if not repo:
        return score_private(tok, full, owner, user, found_on, symbol_counts, review, reasons, flags, add, lambda: total)

    readme = readme_of(full)
    tree_r = gh(f"repos/{full}/git/trees/HEAD?recursive=1") or {}
    tree = [t["path"] for t in tree_r.get("tree", [])]
    n_commits, first_c, last_c, first_sha = commit_stats(full)
    contribs = [c["login"] for c in (gh(f"repos/{full}/contributors?per_page=20") or []) if "[bot]" not in c.get("login", "")]
    repo_text = " ".join([repo.get("description") or "", readme]).lower()
    text = " ".join([tok.get("description") or "", repo_text]).lower()
    created = iso(repo["created_at"])
    launched = iso(tok.get("launched"))
    acct_age = days_between(NOW, iso(user["created_at"])) if user.get("created_at") else 0
    tok_site = domain(tok.get("website") or "")
    if tok_site in NOT_A_SITE:  # "website" is just a GitHub/X/Telegram page, not their own site
        tok_site = ""
    home = domain(repo.get("homepage") or "")
    rv = review.get("checks", {})

    srcs = project_sources(tok)
    docs_text = " ".join(t for w, u, t in srcs if w == "docs").lower()
    text = text + " " + docs_text  # their own docs count for the platform guesses

    # --- Platform (40) ---
    if "earns" in rv:
        add("Platform", rv["earns"][0], rv["earns"][1] + " — checked by hand", "✅" if rv["earns"][0] >= 20 else "🟡")
    else:
        hits = sorted({w.strip() for w in EARN_WORDS if w in text})
        if len(hits) >= 2:
            add("Platform", 20, f"Looks like it earns fees from users ({', '.join(hits[:4])}) — guess from their text, needs a look", "🟡")
        elif hits:
            add("Platform", 10, f"Maybe earns fees ({hits[0]}) — guess from their text, needs a look", "🟡")
        else:
            add("Platform", 0, "No sign it earns fees from other people using it")
    if "fees_back" in rv:
        add("Platform", rv["fees_back"][0], rv["fees_back"][1] + " — checked by hand",
            "✅" if rv["fees_back"][0] >= 20 else ("🟡" if rv["fees_back"][0] else "❌"))
    else:
        hits = back_hits(text)
        if hits:
            add("Platform", 10, f"Says fees go back to the token ({', '.join(hits[:3])}) — claimed, not checked on chain", "🟡")
        else:
            add("Platform", 0, "No sign fees go back to the token")

    # --- Really theirs (20) ---
    addr = tok["address"].lower()
    # 6 Nov (LETRO): say exactly where on GitHub the address is: the About line, the README, the owner's
    # profile bio or the code. Any of them shows the repo's owner claims the token.
    gh_where = [w for w, ok in (("repo's About line", addr in (repo.get("description") or "").lower()),
                                ("README", addr in readme.lower()),
                                ("GitHub profile bio", addr in (user.get("bio") or "").lower())) if ok]
    if not gh_where and n_commits:
        sc = gh(f"search/code?q={addr}+repo:{full}")
        if sc and sc.get("total_count"):
            gh_where = ["repo's files"]
    in_repo = bool(gh_where)
    ox = official_x(tok, srcs)
    in_site = any(addr in t.lower() for w, u, t in srcs)
    where = [w for w, ok in ((" and ".join(gh_where), in_repo), ("website", in_site),
                             (f"official X @{ox['official']}", ox["posted"])) if ok]
    add("Really theirs", 10 if where else 0,
        ("Token's address is posted by their " + ", ".join(where)) if where
        else "Token's address isn't posted by their repo, website or official X"
             + ("" if ox["official"] else " (website links no X account to check)"))
    if ox["young"]:
        reasons["Really theirs"].append(
            f"🟡 Their X @{ox['official']} posts the address, but the account is brand new"
            + (f" (made {ox['joined']:%d %b %Y})" if ox["joined"] else "")
            + " — names can change hands, so it doesn't count (+0)")
    cc = copycat(tok, ox)
    if cc:
        when = f", launched {iso(cc['launched']):%d %b %H:%M} UTC" if cc.get("launched") else ""
        flags.append(f"{COPYCAT}: the project's X @{cc['handle']} posts a different address with the same "
                     f"{' and '.join(cc['same'])}: {cc['real']}{when}. It never posts this one, so this is very likely "
                     f"someone copying the name and links")
    if ox["mismatch"]:
        if in_repo or in_site:  # a copy can't post its address on the real site or repo (TRENCHERS, 5 Nov)
            reasons["Really theirs"].append("ℹ️ " + x_mismatch_note(ox, "repo" if in_repo else "website"))
        else:
            flags.append(f"{X_MISMATCH}: the token links @{ox['token']}, but its website links "
                         + ", ".join("@" + h for h in ox["site"]) + " — may be someone copying the project's links")
    linked = []
    if found_on == "website":
        linked.append("website links the repo")
    if tok_site and (home == tok_site or tok_site in readme.lower()):
        linked.append("repo links the website")
    pts = 10 if len(linked) == 2 else (5 if linked else 0)
    add("Really theirs", pts, ("Repo and website: " + ", ".join(linked)) if linked else "Repo and website don't link to each other",
        "✅" if pts == 10 else ("🟡" if pts else "❌"))
    mentions_token = any(b in repo_text for b in name_bits(tok)) or related(tok, owner, full.split("/")[1])
    if not in_repo and not mentions_token and not (tok_site and (home == tok_site or tok_site in readme.lower())):
        flags.append(f"Repo never mentions this token, its name or its website" + (f" (repo's own site is {home})" if home else "")
                     + " — may be someone else's project")
    else:
        # A matching repo NAME is not proof (anyone can name a token after a famous repo). Real evidence:
        # token address in repo, repo links their website, or the GitHub ACCOUNT is named after the project.
        # ...but an account name is no proof for a big, older account either: anyone can name a token
        # "Parity Technologies" and link github.com/paritytech (PARITY, 5 Nov).
        acct_made = iso(user["created_at"]) if user.get("created_at") else None
        famous_acct = bool((user.get("followers", 0) >= 500 or user.get("public_repos", 0) >= 100) and launched and acct_made
                           and acct_made < launched - datetime.timedelta(days=60))
        evidence = (in_repo or (tok_site and (home == tok_site or tok_site in readme.lower()))
                    or (related(tok, owner, None) and not famous_acct))
        famous_older = (repo.get("stargazers_count", 0) >= 500 and launched and created
                        and created < launched - datetime.timedelta(days=60))
        if not evidence and (found_on != "website" or famous_older or famous_acct):
            if famous_acct:
                flags.append(f"Nothing ties this big, older GitHub account ({owner}: {user.get('public_repos', 0):,} repos, "
                             f"{user.get('followers', 0):,} followers, made {acct_made:%b %Y}) to this token: it never mentions the "
                             f"token's address and doesn't link its website. A matching name isn't proof — likely someone using a famous name")
            else:
                why = (f"a popular older repo ({repo.get('stargazers_count', 0):,} stars, made {created:%b %Y})" if famous_older
                       else "the repo")
                flags.append(f"Nothing ties {why} to this token: it never mentions the token's address or website, and the "
                             f"GitHub account ({owner}) isn't named after the project — likely someone else's project")
    if launched and created and created > launched + datetime.timedelta(days=1):
        reasons["Really theirs"].append(f"ℹ️ Repo was created {days_between(created, launched):.0f} days after the token launched")
    ck = f"{full}@{repo.get('pushed_at','')[:10]}"
    if ck not in COPY_CACHE:
        COPY_CACHE[ck] = copy_check(full, tree_r.get("tree", []), created, first_sha, n_commits)
    cflags, cnotes = COPY_CACHE[ck]
    if "__retry__" in cflags:  # search had not indexed the repo: try again next time
        COPY_CACHE.pop(ck)
        cflags = [f for f in cflags if f != "__retry__"]
    flags += cflags
    reasons["Really theirs"] += cnotes

    # --- does the project itself mention the token? (information only for now) ---
    ment = token_mentions(tok, srcs) + ([{"where": "GitHub", "url": f"https://github.com/{full}", "what": "its contract address",
                                          "snippet": ""}] if in_repo else [])
    read = ", ".join(sorted({f"{w} ({urllib.parse.urlparse(u).netloc}{urllib.parse.urlparse(u).path})" for w, u, _ in srcs})) or "no website"
    if ment:
        for m in ment[:4]:
            reasons["Really theirs"].append(f"✅ Their {m['where']} mentions the token: {m['what']}" +
                                            (f" — “{m['snippet']}”" if m["snippet"] else "") + f" ({m['url']})")
    else:
        reasons["Really theirs"].append(f"❌ Their website, docs and GitHub never mention the token (read: {read})")
    disc = None if (in_repo or in_site) else token_disclaimer(tok, srcs)
    if disc:  # their own page says no token yet, and doesn't post this one's address: note it (6 Nov, BLACKPOOL)
        reasons["Really theirs"].append(f"⚠️ Their {disc[0]} says there's no official token yet: “{disc[2]}” ({disc[1]}) "
                                        "— and it doesn't post this token's address")
    token_mentioned = bool(ment)
    # A big, older project whose dev never posts or mentions the token: anyone can launch a token on
    # Pons named after a popular repo and point it at the real links (SEO, OMHER, 5 Nov). Cap at 25
    # until the dev claims it; lifts by itself at the next rescore once they do.
    made = iso(user["created_at"]) if user.get("created_at") else None
    old_enough = lambda d: bool(launched and d and d < launched - datetime.timedelta(days=60))
    big = ((user.get("followers", 0) >= 500 or user.get("public_repos", 0) >= 100) and old_enough(made)) or           (repo.get("stargazers_count", 0) >= 500 and old_enough(created))
    if big and not where and not token_mentioned:
        flags.append(f"{UNCLAIMED}: {owner}'s GitHub is big and older than the token ({repo.get('stargazers_count', 0):,} stars, "
                     f"{user.get('followers', 0):,} followers), but its repo, website and X never post or mention the token. "
                     f"Likely launched by someone else using their project — capped at 25 until the dev claims it")

    # --- works with past winners (+5, 5 Nov after OSTRA's Raeto vaults): their site, repo or own X ---
    xh = ox.get("official") or ox.get("token")
    wins, on_x = sitecheck.past_winners(tok, repo_text + " " + " ".join(t for w, u, t in srcs), x_account(xh) if xh else None)
    if wins:  # a bonus only: not working with a past winner is never listed as a miss (user, 5 Nov)
        add("Platform", 5, "Works with past winners: " + ", ".join(wins) + (" (from their X posts)" if on_x else ""))

    # --- Real code (20) ---
    span = days_between(last_c, first_c) if first_c and last_c else 0
    ok_n, ok_span = n_commits >= 20, span >= 7
    pts = 10 if ok_n and ok_span else (5 if ok_n or ok_span else 0)
    add("Real code", pts, f"{n_commits} changes over {span:.0f} days", "✅" if pts == 10 else ("🟡" if pts else "❌"))
    sol = any(p.endswith(".sol") for p in tree)
    tests = any(re.search(r"(^|/)(test|tests|__tests__|spec)(/|$)|\.test\.|_test\.", p) for p in tree)
    pts = 10 if sol and tests else (5 if sol or tests else 0)
    what = [x for x, ok in (("smart contracts", sol), ("tests", tests)) if ok]
    add("Real code", pts, ("Has " + " and ".join(what)) if what else "No smart contracts or tests",
        "✅" if pts == 10 else ("🟡" if pts else "❌"))

    # --- Team (10) ---
    stars = repo.get("stargazers_count", 0) + repo.get("forks_count", 0)
    facts = f"account {acct_age:.0f} days old, {len(contribs)} people, {repo.get('stargazers_count',0)} stars, {repo.get('forks_count',0)} forks"
    ok = acct_age >= 90 or len(contribs) >= 2 or stars >= 10
    add("Team", 10 if ok else 0, ("Not a brand-new one-person repo: " if ok else "One person, new account, no outside interest: ") + facts)

    # --- Safety (10) ---
    has_addr = bool(re.search(r"0x[0-9a-fA-F]{40}", readme))
    add("Safety", 5 if has_addr else 0, "Contract addresses listed in the README" if has_addr else "No contract addresses in the README")
    if not has_addr and gh_where and gh_where != ["README"]:  # note only, no points (user, 6 Nov)
        reasons["Safety"].append(f"ℹ️ The token's address is in the {' and '.join(gh_where)}, just not in the README")
    sec = [x for x, ok in (("SECURITY file", any(p.lower().endswith("security.md") for p in tree)),
                           ("audit", "audit" in text or any("audit" in p.lower() for p in tree)),
                           ("timelock", "timelock" in text)) if ok]
    add("Safety", 5 if sec else 0, ("Safety info: " + ", ".join(sec)) if sec else "No security, audit or timelock info")
    if any("audit" in p.lower() for p in tree) and "ai" in " ".join(p.lower() for p in tree if "audit" in p.lower()):
        reasons["Safety"].append("ℹ️ Audit looks self-done or AI-done, not an outside firm")

    # --- red flags ---
    if repo.get("fork"):
        flags.append(f"Repo is a copy (fork) of {repo.get('parent', {}).get('full_name', 'another repo')}")
    if repo.get("size", 0) == 0:
        flags.append("Repo is empty")
    if symbol_counts.get(tok.get("symbol"), 0) >= 3:
        flags.append(f"{tok.get('symbol')} was launched {symbol_counts[tok.get('symbol')]} times on Pons")
    for f in review.get("flags", []):
        flags.append(f + " (checked by hand)")

    # Not their GitHub (someone else's project, copied code, fork, empty) -> 0. Other red flags -> capped at 25.
    not_theirs = [f for f in flags if " times on Pons" not in f and not f.startswith(X_MISMATCH) and not f.startswith(UNCLAIMED)]
    capped = bool(flags)
    final = 0 if not_theirs else (min(total, 25) if capped else min(total, 100))  # parts add up to 105
    if cc:
        reasons.setdefault("Really theirs", []).insert(0, "⛔ Score set to 0: this token is a copy, the project's X posts a different address (see the warning above)")
    elif not_theirs:
        reasons.setdefault("Really theirs", []).insert(0, "⛔ Score set to 0: this GitHub is not their own work (see the warning above)")
    return {"repo": full, "score": final, "raw_score": total, "capped": capped, "not_theirs": bool(not_theirs), "flags": flags,
            "reasons": reasons, "roadmap": roadmap_of(full, tree, tok.get("website")) + review.get("roadmap", []),
            "notes": review.get("notes", []), "token_mentioned": token_mentioned, "copy_of": cc["real"] if cc else None,
            "sources_read": [u for w, u, _ in srcs],
            "facts": {"commits": n_commits, "stars": repo.get("stargazers_count", 0), "created": repo["created_at"][:10],
                      "pushed": repo["pushed_at"][:10], "people": len(contribs)}}


# ---------- page ----------
def money(x):
    if not x:
        return "-"
    return f"${x/1e6:.2f}M" if x >= 1e6 else f"${x/1e3:.0f}k"


def skipped_html(state):
    e = html.escape
    week = (NOW - datetime.timedelta(days=7)).isoformat()
    rows = [x for x in state.get("skipped", []) if x["when"] >= week]
    if not rows:
        return "<details class='card'><summary>Skipped GitHub links, last 7 days (0)</summary><p>None.</p></details>"
    seen, out = set(), []
    for x in sorted(rows, key=lambda x: x["when"], reverse=True):
        k = (x["address"], tuple(x["ignored"]))
        if k in seen:
            continue
        seen.add(k)
        ign = ", ".join(f'<a href="https://github.com/{e(i)}" target="_blank" rel="noopener">{e(i)}</a>' for i in x["ignored"])
        used = f'used <a href="https://github.com/{e(x["used"])}" target="_blank" rel="noopener">{e(x["used"])}</a>' if x.get("used") else "no repo used"
        out.append(f"<li><b>{e(x.get('symbol') or '?')}</b> ({e(x['when'][:10])}, {e(domain(x.get('website') or '') or 'no website')}): {used}; ignored {ign}</li>")
    return (f"<details class='card'><summary>Skipped GitHub links, last 7 days ({len(out)} tokens)</summary>"
            "<p class='sub'>Links the scanner found but did not use, mostly code libraries inside websites. "
            "If a real project is here, tell Claude and it goes in reviews.json.</p><ul>" + "".join(out) + "</ul></details>")


# Shows every "2026-11-05 02:47 UTC" or "4 Nov 13:35 UTC" on the page in the visitor's own time zone.
# The original UTC time stays as a tooltip. If the browser can't run it, the UTC times simply stay.
LOCAL_TIME_JS = r"""(()=>{try{
const M={Jan:0,Feb:1,Mar:2,Apr:3,May:4,Jun:5,Jul:6,Aug:7,Sep:8,Oct:9,Nov:10,Dec:11};
const full=new Intl.DateTimeFormat(undefined,{day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
const short=new Intl.DateTimeFormat(undefined,{day:'numeric',month:'short',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
const re=/([0-9]{4})-([0-9]{2})-([0-9]{2})[ T]([0-9]{2}):([0-9]{2})(?::[0-9]{2})? ?UTC|\b([0-9]{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) ([0-9]{2}):([0-9]{2}) UTC/g;
const yr=new Date().getUTCFullYear();
const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,{acceptNode:n=>/SCRIPT|STYLE/.test(n.parentNode.nodeName)?2:1});
const nodes=[];while(w.nextNode())nodes.push(w.currentNode);
for(const n of nodes){const s=n.nodeValue;re.lastIndex=0;if(!re.test(s))continue;re.lastIndex=0;
 const f=document.createDocumentFragment();let last=0,m;
 while((m=re.exec(s))){f.append(s.slice(last,m.index));
  const t=m[1]?Date.UTC(+m[1],m[2]-1,+m[3],+m[4],+m[5]):Date.UTC(yr,M[m[7]],+m[6],+m[8],+m[9]);
  const sp=document.createElement('span');sp.title=m[0];sp.textContent=(m[1]?full:short).format(t);f.append(sp);last=re.lastIndex;}
 f.append(s.slice(last));n.replaceWith(f);}
const top=document.querySelector('p.top');
if(top)top.append(' Times are in your time zone ('+Intl.DateTimeFormat().resolvedOptions().timeZone+'); hover a time to see it in UTC.');
}catch(e){}})();"""

PAGE_JS = r"""
// Everything that has to run again after the page refreshes itself in the background.
window.TW_SHOW=()=>{const tabs=[...document.querySelectorAll('section.tab')],links=[...document.querySelectorAll('#tabs a')];
let id=(location.hash||'#github').slice(1);if(!tabs.some(t=>t.id===id))id='github';
tabs.forEach(t=>t.hidden=t.id!==id);links.forEach(a=>a.classList.toggle('on',a.dataset.tab===id));};
window.TW_INIT=()=>{TW_SHOW();
document.querySelectorAll('button.wrong').forEach(b=>b.onclick=()=>{const m=b.dataset.msg;
const done=()=>{b.textContent='Copied: paste it to Claude and add the right repo';};
if(navigator.clipboard)navigator.clipboard.writeText(m).then(done,()=>prompt('Copy this and paste it to Claude:',m));else prompt('Copy this and paste it to Claude:',m);});
document.querySelectorAll('button.ca').forEach(b=>b.onclick=()=>{const t=b.textContent,c=b.dataset.ca;
const ok=()=>{b.textContent='Copied ✓';setTimeout(()=>b.textContent=t,1500);};
if(navigator.clipboard)navigator.clipboard.writeText(c).then(ok,()=>prompt('Copy:',c));else prompt('Copy:',c);});
document.querySelectorAll('.bar button').forEach(b=>b.onclick=()=>{b.closest('.bar').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
const f=b.dataset.f;b.closest('section').querySelectorAll('article.card').forEach(c=>{const s=+c.dataset.score,n=c.dataset.new==='1',fl=!!c.querySelector('.flag');
c.style.display=(f==='all'||(f==='new'&&n)||(f==='60'&&s>=60)||(f==='flag'&&fl))?'':'none'})});
TW_TIME();};
window.addEventListener('hashchange',()=>{TW_SHOW();window.scrollTo(0,0);});

// Sound when a token newly reaches 60+ on the GitHub or Site check list (5 Nov).
// Browsers only allow sound after a click on the page, so the page no longer reloads itself:
// it fetches the new version every 5 minutes and swaps it in, which keeps the sound switched on.
(()=>{
const KEY='tw-seen60',SKEY='tw-sound',EVERY=5*60*1000;
const get=k=>{try{return localStorage.getItem(k)}catch(e){return null}},put=(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}};
const high=doc=>[...doc.querySelectorAll('#github article.card,#sites article.card')].filter(c=>+c.dataset.score>=60&&c.dataset.addr)
  .map(c=>({a:c.dataset.addr,s:(c.querySelector('h2')||{}).firstChild?.textContent.trim()||'?',sc:+c.dataset.score,tab:c.closest('section.tab')?.id||'github'}));
let ctx=null,on=get(SKEY)==='1',fresh=[];
const btn=document.getElementById('sound'),toast=document.getElementById('toast');
const live=()=>ctx&&ctx.state==='running';
const paint=()=>{btn.textContent=on?(live()?'🔔 Sound on':'🔔 Tap the page to arm sound'):'🔕 Sound off';btn.classList.toggle('on',on&&live());};
const arm=()=>{if(!on)return;try{ctx=ctx||new(window.AudioContext||window.webkitAudioContext)();ctx.resume().then(paint);}catch(e){}};
document.addEventListener('pointerdown',arm);document.addEventListener('keydown',arm);
const chime=()=>{if(!live())return;const t=ctx.currentTime;[[659.25,0],[880,.16],[1318.5,.32]].forEach(([f,d])=>{
  const o=ctx.createOscillator(),g=ctx.createGain();o.type='sine';o.frequency.value=f;
  g.gain.setValueAtTime(.0001,t+d);g.gain.exponentialRampToValueAtTime(.22,t+d+.02);g.gain.exponentialRampToValueAtTime(.0001,t+d+.7);
  o.connect(g).connect(ctx.destination);o.start(t+d);o.stop(t+d+.75);});};
btn.onclick=e=>{e.stopPropagation();on=!on;put(SKEY,on?'1':'0');if(on){arm();setTimeout(chime,150);}paint();};
const check=list=>{const prev=get(KEY),seen=new Set(prev?JSON.parse(prev):[]);
  const out=prev?list.filter(x=>!seen.has(x.a)):[];  // first visit: just remember, no alert
  put(KEY,JSON.stringify([...new Set([...seen,...list.map(x=>x.a)])].slice(-4000)));return out;};
const mark=()=>fresh.forEach(x=>document.querySelectorAll(`article.card[data-addr="${x.a}"]`).forEach(c=>c.classList.add('fresh')));
const show=(add,sound)=>{if(!add.length)return;fresh=[...add,...fresh.filter(f=>!add.some(x=>x.a===f.a))];mark();
  toast.innerHTML='<b>🔔 New 60+</b> '+fresh.map(x=>`<a href="#${x.tab}">${x.s} <span>${x.sc}</span></a>`).join(' ')+'<button aria-label="Close">×</button>';
  toast.hidden=false;document.title=`(${fresh.length}) Token Watch`;
  toast.querySelector('button').onclick=()=>{toast.hidden=true;fresh=[];document.title='Token Watch';
    document.querySelectorAll('article.fresh').forEach(c=>c.classList.remove('fresh'));};
  if(sound)chime();};
TW_INIT();paint();show(check(high(document)),false);  // new since your last visit: shown, no sound (not armed yet)
setInterval(async()=>{try{
  const r=await fetch(location.pathname+'?t='+Date.now(),{cache:'no-store'});if(!r.ok)return;
  const doc=new DOMParser().parseFromString(await r.text(),'text/html'),nm=doc.querySelector('main');if(!nm)return;
  const add=check(high(doc));
  // don't pull the page out from under someone reading an open card; the toast still tells them
  if(!document.querySelector('main section.tab:not([hidden]) article.card details[open]')){const y=scrollY;document.querySelector('main').replaceWith(nm);TW_INIT();mark();scrollTo(0,y);}
  show(add,true);
}catch(e){}},EVERY);
})();
"""



def score_bits(sc):
    """(parts, pluses, misses, cap) for a card: points per part, the main pluses and misses, any cap."""
    parts, plus, minus = [], [], []
    clean = lambda x: re.sub(r"\s+—.*$", "", re.sub(r"\s*\(\+\d+\)$", "", x)).lstrip("✅🟡❌ℹ️ ").strip()[:95]
    for g, items in sc.get("reasons", {}).items():
        pts = sum(int(m.group(1)) for x in items if (m := re.search(r"\(\+(\d+)\)$", x)))
        if re.sub(r"\s*\(.*\)$", "", g) not in INFO_GROUPS:  # information-only parts get no chip
            parts.append((re.sub(r"\s*\(.*\)$", "", g), pts))
        for x in items:
            m = re.search(r"\(\+(\d+)\)$", x)
            if m and int(m.group(1)) >= 10 and x.startswith(("✅", "🟡")):
                plus.append((int(m.group(1)), clean(x)))
            elif m and int(m.group(1)) == 0 and x.startswith("❌") and "past winners" not in x:
                minus.append(clean(x))
    cap = next((x for x in sum(sc.get("reasons", {}).values(), [])
                if re.match(r"(?:⛔|🟡 Capped|ℹ️ Points add up|ℹ️ The GitHub code is private)", x)), "")
    if not cap and sc.get("flags") and sc["score"] <= 25:
        cap = "Capped at 25 by the warning above"
    return parts, [p for _, p in sorted(plus, key=lambda p: -p[0])[:3]], minus[:2], clean(cap) if cap else ""


# Narrative tags (5 Nov): display only, never scored. First matches win, at most 3.
NARRATIVES = [
    ("AI agents", r"\bagents?\b|\bagentic\b|\bMCP\b|\bautonomous\b|ERC-?8004"),
    ("AI", r"\bAI\b|\bLLMs?\b|\binference\b|\bmodels?\b|\bGPT\b|machine learning|\bneural\b"),
    ("Privacy", r"\bprivacy\b|\bprivate\b|\bzk\b|zero[- ]knowledge|\bshielded\b|\bstealth\b|\bconfidential\b"),
    ("Stocks / RWA", r"\bstocks?\b|stock tokens?|tokeni[sz]ed (?:stocks?|equit)|\bequit(?:y|ies)\b|\bRWA\b|\$?\b(?:NVDA|TSLA|AAPL|MSFT)\b"),
    ("DeFi", r"\blend(?:ing)?\b|\bborrow|\byield\b|\bvaults?\b|\bperps?\b|\bdex\b|\bliquidity\b|\boptions\b|\bcredit\b|\bstak(?:e|ing)\b|\bswap\b"),
    ("Launchpad", r"\blaunchpad\b|\blaunch(?:es)? (?:tokens|coins)\b|\bcoin launcher\b|\bbonding curve\b"),
    ("Payments", r"\bpayments?\b|\bx402\b|\bpay (?:per|with|by)\b|\bcheckout\b"),
    ("Prediction", r"\bpredictions?\b|\bforecasts?\b|\bbetting\b|\bodds\b"),
    ("Gaming / NFT", r"\bgames?\b|\bgaming\b|\bNFTs?\b|\barena\b"),
    ("Dev tools", r"\bSDK\b|\bAPI\b|\bdevelopers?\b|\binfrastructure\b|\bRPC\b|\bCLI\b|\bopen[- ]source\b"),
]
MEME = (r"\bmeme\b|\bdog\b|\bdoge\b|\bcat\b|\bpepe\b|\bfrog\b|\binu\b|\bwojak\b|\bmoon\b|\bape\b|\bcommunity token\b"
        r"|\bmascot\b|\bparody\b")  # mascot, doge, parody added 6 Nov (FLORA, COGE)


def narratives(r, sc, xdb):
    """Up to 3 narrative tags, plus 'Public dev' when a 6-month+ GitHub account names the project's X."""
    h0, _ = x_info.parse(r.get("twitter"))
    bio = ((((xdb or {}).get("accounts") or {}).get((h0 or "").lower()) or {}).get("bio") or "")
    text = " ".join([r.get("name") or "", r.get("description") or "", bio])  # the project's own words only
    tags = [n for n, rx in NARRATIVES if re.search(rx, text, re.I)]
    if "AI agents" in tags and "AI" in tags:
        tags.remove("AI")
    tags = tags[:3]
    if not tags and re.search(MEME, " ".join([r.get("name") or "", r.get("description") or ""]), re.I):
        tags = ["Meme"]
    owner = (sc.get("repo") or "").split("/")[0].lower()
    h, _ = x_info.parse(r.get("twitter"))
    gh_x = (((xdb or {}).get("gh") or {}).get(owner) or {}).get("twitter") or ""
    m = re.search(r"account (\d+) days old", " ".join(sum(sc.get("reasons", {}).values(), [])))
    if owner and h and gh_x.lower() == h.lower() and m and int(m.group(1)) >= 180:
        tags.append("Public dev")
    return tags


def is_meme(r, tags):
    """Meme coin, for leaving it out of Possible misses (user, 6 Nov: ignore memes for now). Meme words in the name,
    description or website address (flora.meme), and no AI tag: an AI project is never called a meme."""
    if any("AI" in t for t in tags):
        return False
    return "Meme" in tags or bool(re.search(MEME, " ".join([r.get("name") or "", r.get("description") or "",
                                                              domain(r.get("website") or "")]), re.I))


CHECK_AGE_DAYS = 3        # score check: tokens at least this old...
TOOK_OFF = 500_000        # ...now worth this much "took off"
DIED = 20_000             # ...now worth less than this "died"


def score_check_html(state, pdb, e, sec):
    """One list (sec = 'github' or 'sites'): a headline answer, then 'Is the score working?' for tokens 3+ days old
    that took off vs died: median score, share at the page cut-off, points per part. Updates every run; the cut-off and
    weights get set from this once the groups are big enough (5 Nov). Split per list on 6 Nov (user)."""
    def parts(sc):
        out = {}
        for g, items in sc.get("reasons", {}).items():
            name = re.sub(r"\s*\(.*\)$", "", g)
            if name not in INFO_GROUPS:
                out[name] = sum(int(m.group(1)) for x in items if (m := re.search(r"\(\+(\d+)\)$", x)))
        return out
    took, died, mid = [], [], []
    for a, r in state.get(sec, {}).items():
        if not r.get("launched") or days_between(NOW, iso(r["launched"])) < CHECK_AGE_DAYS:
            continue
        m = (pdb.get(a.lower()) or {}).get("now_mcap") or r.get("mcap") or 0
        (took if m >= TOOK_OFF else died if m < DIED else mid).append(r["scoring"])
    if not took and not died:
        return f"<p class='muted'>No {CHECK_AGE_DAYS}+ day old tokens on this list yet.</p>"
    hi = lambda g: sum(s["score"] >= SHOW_AT for s in g)
    shown = hi(took) + hi(died) + hi(mid)
    head = (f"<p class='answer'>Of the <b>{shown}</b> tokens here that scored {SHOW_AT}+ and launched {CHECK_AGE_DAYS}+ days ago: "
            f"<b>{hi(took)} took off</b> (now {money(TOOK_OFF)}+), <b>{hi(died)} died</b> (under {money(DIED)}), {hi(mid)} in between.</p>")
    med = lambda g: f"{statistics.median(s['score'] for s in g):.0f}" if g else "–"
    pct = lambda g: f"{hi(g)} of {len(g)}" if g else "–"
    keys = list(dict.fromkeys(k for s in took + died for k in parts(s)))
    avg = lambda g, k: f"{statistics.mean(parts(s).get(k, 0) for s in g):.0f}" if g else "–"
    rows = [("Median score", med(took), med(died)), (f"Scored {SHOW_AT}+", pct(took), pct(died))]
    rows += [(f"{k} (avg points)", avg(took, k), avg(died, k)) for k in keys]
    small = len(took) < 15 or len(died) < 15
    return (head + f"<h3>Is the score working?</h3><p class='muted'>All tokens on this list launched {CHECK_AGE_DAYS}+ days ago, shown or hidden. "
            f"A part that helps gives the took-off group clearly more points.</p>"
            f"<table class='sc'><tr><th></th><th>Took off ({len(took)})</th><th>Died ({len(died)})</th></tr>"
            + "".join(f"<tr><td>{e(a_)}</td><td>{e(b)}</td><td>{e(c)}</td></tr>" for a_, b, c in rows) + "</table>"
            + ("<p class='muted'>Too few tokens yet to set the cut-off from this: wait for 15+ in each group.</p>" if small else ""))


# --- Shortlist (5 Nov): strict gates + 2 or more signs that winners shared. A place to look first, not advice. ---
SHORT_TRADES = 50          # trades in the last 24h
SHORT_LIQ = 20_000         # dollars of liquidity
SHORT_SIGNS = 2            # winner signs needed
RH_QUOTES = re.compile(r"^(?:USDG|[A-Z]{1,5}x?)$")


def winner_signs(r, sc):
    """Signs that separated winners from losers in our tests (all from data the scanner already has)."""
    txt = " ".join(sum(sc.get("reasons", {}).values(), []))
    q = (r.get("quote") or "").upper()
    return [n for n, ok in (
        ("2+ plug-in tools", sc.get("tools", 0) >= 2),
        ("takes payments", "Takes real payments" in txt),
        ("works with a past winner", "Works with past winners" in txt),
        ("Robinhood Chain assets", bool(re.search(r"✅ (?:Built on Robinhood Chain|Trades against)", txt))
         or (q and q not in ("ETH", "WETH", "USDC", "USDT", "WBTC") and bool(RH_QUOTES.match(q)))),
        ("real code", bool(re.search(r"✅ \d+ changes over", txt))),
        # GitHub route: a GitHub score of 60+ split winners 5 of 6 vs dead 0 of 9 (5 Nov test)
        ("strong GitHub score", sc.get("kind") != "site" and sc["score"] >= 60),
    ) if ok]


REVIEW_FROM = "2026-11-06T03:15"  # only projects launched from here on (user, 6 Nov: no going back over older ones)
REVIEW_QUEUE = os.path.join(HERE, "data", "review_queue.json")
# Page cut-off (user, 6 Nov): 60 and below are not shown anywhere on the page. They are still scored and priced every run,
# and the 'Was the score right?' tab lists hidden tokens whose price doubled, in case the score missed something.
SHOW_AT = 61
REVIEW_AT = SHOW_AT
NOT_PROJECT_SITES = NOT_A_SITE | {"ponsfamily.com", "dexscreener.com", "vercel.app", "netlify.app", "github.io", "gitbook.io"}


def copy_addresses(state, reviews):
    """Addresses known to be copies or not the team's token: copycat flag, or a hand check saying so."""
    out = set()
    for sec in ("github", "sites"):
        for a, r in state.get(sec, {}).items():
            if any(f.startswith(COPYCAT) for f in r.get("scoring", {}).get("flags", [])):
                out.add(a.lower())
    for a, v in reviews.items():
        if isinstance(v, dict) and (v.get("unofficial") or any("not the team's token" in f for f in v.get("flags", []))):
            out.add(a.lower())
    return out


def wallet_note(addr, wallets, copies):
    """(serial?, short text) about the wallet that launched this token."""
    w = (wallets or {}).get(addr.lower())
    if not w:
        return False, "launch wallet not checked yet"
    if not w.get("pons"):
        return False, "not launched on Pons"
    if w["launches"] > deployers.BOT_WALLET:
        return False, f"shared launch wallet ({w['launches']:,} tokens)"
    bad = [o.get("symbol") or "?" for o in w.get("others", []) if (o.get("address") or "").lower() in copies]
    if bad:
        return True, f"serial launcher: this wallet made {w['launches']} tokens, including copies ({', '.join(bad[:4])})"
    if w["launches"] == 1:
        return False, "only token from its wallet"
    return False, f"its wallet made {w['launches']} tokens"


def group_projects(ents, wallets, copies, e):
    """One card per project (user, 6 Nov: 'just show me the legit project').
    Same project = same GitHub repo, same website, or same symbol + name. Proof, not size: if the team posted one token's
    address (or a hand check confirms it), only that one shows. If none is confirmed, one card shows with a 'Not confirmed'
    box listing every address, because the biggest or first token can just as easily be the fake.
    Returns (html cards in page order, entries shown, entries in unconfirmed groups)."""
    parent = list(range(len(ents)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    first = {}
    for i, x in enumerate(ents):
        r, sc = x["r"], x["sc"]
        keys = [("n", (r.get("symbol") or "?").strip().lower(), (r.get("name") or "").strip().lower())]
        repo = (sc.get("repo") or "").lower().strip("/")
        if sc.get("kind") != "site" and "/" in repo and not repo.startswith("pons-labs/"):  # launchpad's own account isn't a project
            keys.append(("repo", repo))
        d = domain(r.get("website") or "")
        if d and d not in NOT_PROJECT_SITES:  # foo.vercel.app is a project's own address; vercel.app alone is not
            keys.append(("site", d))
        for k in keys:
            if k in first:
                parent[find(i)] = find(first[k])
            else:
                first[k] = i
    groups = {}
    for i in range(len(ents)):
        groups.setdefault(find(i), []).append(i)
    out, shown, unconfirmed = [], [], []
    for root in sorted(groups, key=lambda g: min(groups[g])):  # page order = first member's place
        g = [ents[i] for i in groups[root]]
        if len(g) == 1:
            out.append(g[0]["html"]); shown.append(g[0])
            continue
        real = [x for x in g if x["proof"] and x["r"]["address"].lower() not in copies]
        if real:
            for x in real:
                out.append(x["html"]); shown.append(x)
            continue
        pick = next((x for x in g if not wallet_note(x["r"]["address"], wallets, copies)[0]), g[0])
        lines = []
        for x in g:
            serial, note = wallet_note(x["r"]["address"], wallets, copies)
            a = x["r"]["address"]
            lines.append(f"<li{' class=bad' if serial else ''}><code>{e(a[:6] + '…' + a[-4:])}</code> {e(x['r'].get('symbol') or '?')}"
                         f" · score {x['sc']['score']} · {e(money(x['r'].get('mcap')))} · launched {e(ago(x['r'].get('launched')) or '?')}"
                         f" · {'⚠️ ' if serial else ''}{e(note)}</li>")
        box = (f"<div class='unconf'><b>⚠️ Not confirmed:</b> {len(g)} tokens claim this project and the team hasn't posted any of "
               f"their addresses. Any of them could be fake. Below is one of them; when the team posts an address the page "
               f"switches to it by itself.<ul>{''.join(lines)}</ul></div>")
        out.append(pick["html"].replace("<header>", box + "<header>", 1))
        shown.append(pick)
        unconfirmed.extend(g)
    return out, shown, unconfirmed


def review_queue_html(q, e):
    """Tokens at 60+ still waiting for a hand review (written by Claude when asked; see SCORING.md)."""
    if not q:
        return ""
    rows = "".join(f"<li><b>{e(x['symbol'])}</b> {x['score']} · {e(money(x['mcap']))}"
                   + (f" · {e(', '.join(x['tags']))}" if x["tags"] else "") + f" <span class='muted'>({e(x['why'])})</span></li>"
                   for x in q[:60])
    return (f"<details class='dups' style='margin-top:24px'><summary>📝 Hand review queue ({len(q)}): tokens at {REVIEW_AT}+ "
            f"launched since 6 Nov without a review, AI projects first</summary><ul style='margin:8px 0 0'>{rows}</ul></details>")


def shortlist_live(picks):
    """(live, early): the Shortlist proper and the riskier 'passes everything but trading' list."""
    good = [p for p in picks if len(p[4]) >= SHORT_SIGNS]
    live = [p for p in good if (p[3].get("trades24") or 0) >= SHORT_TRADES and (p[3].get("liq") or 0) >= SHORT_LIQ]
    return live, [p for p in good if p not in live]


def shortlist_html(picks, e, joined=None):
    """picks: (row, sc, warnings, market, signs, card_html). Gates: real and theirs, no warnings, trading for real.
    joined: {address: when it joined}, for the 'joined the list' tag (first 24h)."""
    live, early = shortlist_live(picks)
    joined = joined or {}
    order = lambda ps: sorted(ps, key=lambda p: (-len(p[4]), -p[1]["score"]))
    def tag(p):
        j = joined.get(p[0]["address"].lower())
        return f"<span class='joined'>🆕 joined the list {e(ago(j))}</span> " if j and days_between(NOW, iso(j)) < 1 else ""
    def block(ps):
        return "".join(p[5].replace('<p class="verdict">', '<p class="signs">' + tag(p) + '✅ ' + e(" · ".join(p[4])) + '</p><p class="verdict">', 1)
                       for p in order(ps))
    return (f"<h2 style='margin:22px 0 6px'>Shortlist: where to look first</h2>"
            f"<p class='top'>Every token here passes all of these: it's the team's own token (they post its address or mention it), "
            f"no warnings of any kind, at least {SHORT_TRADES} trades in the last day and {money(SHORT_LIQ)}+ liquidity, and "
            f"at least {SHORT_SIGNS} of the signs winners shared: 2+ plug-in tools, takes payments, works with a past winner, "
            f"uses Robinhood Chain assets, real code, strong GitHub score. Most signs first. "
            f"<b>Not proven to predict price yet, and not advice</b>: the price tracking will show if this list beats the rest.</p>"
            + (block(live) or "<p class='muted'>Nothing passes every gate right now.</p>")
            + (f"<details class='dups'><summary>Early: passes everything except trading ({len(early)}), riskier</summary>{block(early)}</details>"
               if early else ""))


# --- Still building (5 Nov): the team's own token + real GitHub changes on several different days lately ---
BUILD_DAYS = 3             # different days with real (non-bot) changes in the last 8 days
BUILD_RECENT = 3           # and a change in the last this-many days
BUILD_AGE = 3              # token at least this many days old, so the work is after launch, not just before it


def build_activity(a, ship):
    """(days active in the last 8, changes, days since last change) from the still-shipping data, or None."""
    s = ((ship or {}).get("tokens") or {}).get(a.lower()) or {}
    runs = [x for x in s.get("runs", []) if "per_day" in x]
    if not runs:
        return None
    first = (NOW - datetime.timedelta(days=7)).strftime("%Y-%m-%d")  # 8 calendar days, today included
    pd = {d: n for d, n in (runs[-1]["per_day"] or {}).items() if d >= first}
    last = runs[-1].get("last_commit")
    since = days_between(NOW, iso(last)) if last else 99
    return len(pd), sum(pd.values()), since


def building_html(picks, e):
    """picks: (row, sc, warnings, activity, card_html)."""
    ok = [p for p in picks if p[3] and p[3][0] >= BUILD_DAYS and p[3][2] <= BUILD_RECENT
          and days_between(NOW, iso(p[0].get("launched") or p[0]["first_seen"])) >= BUILD_AGE]
    ok.sort(key=lambda p: (-p[3][0], -p[3][1]))
    def one(p):
        d, n, since = p[3]
        line = f"🛠️ Real changes on {d} of the last 8 days ({n} changes), last one {('today' if since < 1 else f'{since:.0f} days ago')}"
        return p[4].replace('<p class="verdict">', f'<p class="signs">{e(line)}</p><p class="verdict">', 1)
    return (f"<h2 style='margin:22px 0 6px'>Still building: teams that keep working</h2>"
            f"<p class='top'>The team's own token (they post its address or mention it), no score warnings, launched {BUILD_AGE}+ days ago, "
            f"and real GitHub changes on at least {BUILD_DAYS} different days in the last 8, the latest in the last {BUILD_RECENT} days. "
            f"Bots don't count. Price doesn't matter here. Teams with no public code can't show up yet. Most active first.</p>"
            + ("".join(one(p) for p in ok) or "<p class='muted'>No token passes right now.</p>"))


QUICK_AT = 60  # cards at this score or more get a Quick read (user, 6 Nov: key words to decide fast, deep dive later)


# Words that show a description says what the product is or does. A blurb with none of them is a slogan.
PRODUCT_WORDS = (r"\b(apps?|platform|protocol|agents?|agentic|api|sdk|mcp|tools?|toolkit|builds?|building|trad(e|es|ing)|swaps?|"
                 r"exchange|pay|payments?|launch(es|pad)?|markets?|marketplace|wallets?|data|index|vaults?|lend(ing)?|borrow(ing)?|"
                 r"stak(e|ing)|bridge|games?|gaming|infra(structure)?|network|engine|terminal|bots?|assistant|models?|compute|"
                 r"router|routing|oracle|dex|perps?|yield|liquidity|pools?|hooks?|analytics|search|browser|cloud|storage|layer|"
                 r"framework|library|plugin|extension|automat\w*|inference|llm|gpu|code|coding|developers?|devs?|"
                 r"predictions?|options|machines?|nfts?|dao|security|audits?|memory|commerce|workflows?|defi|assets|"
                 r"investors?|tokeni[sz]\w*|rwa|lets you|helps you|allows)\b")


def what_it_does(r, xdb):
    """One line on what the product is: the token's own description, else their X bio, else 'Not explained' (user, 6 Nov)."""
    cut = lambda s: s if len(s) <= 200 else s[:197].rsplit(" ", 1)[0] + "…"
    own = re.sub(r"\s+", " ", (r.get("description") or "")).strip()
    if own and re.search(PRODUCT_WORDS, own, re.I):
        return cut(own)
    h, _ = x_info.parse(r.get("twitter"))
    bio = re.sub(r"\s+", " ", ((((xdb or {}).get("accounts") or {}).get((h or "").lower()) or {}).get("bio") or "")).strip()
    bio = re.sub(r"\s*(?:https?://\S+|(?:Token )?CA:?\s*0x[0-9a-fA-F]{40})", "", bio).strip()
    if bio and re.search(PRODUCT_WORDS, bio, re.I):
        return cut(bio) + " (from their X)"
    return "Not explained on their page" + (" (their words are under About)" if own else "")


def quick_read(r, sc, tags, warn_items, act, xdb=None):
    """(chips, rows) built only from facts the scanner already has. chips: [(kind, text)] with kind g/a/r
    (good / claimed-or-unknown / risk). rows: [(label, text)] for the Details block. No judgement, just key words."""
    said = " ".join(sum(sc.get("reasons", {}).values(), []))
    has = lambda pat: re.search(pat, said)
    good, amber, risk = [], [], []
    # proof it's theirs
    m = has(r"✅ Token's address is posted by their ([^(]+?) \(")
    if m:
        w = m.group(1).lower()
        where = [n for n, k in (("site", r"website|docs"), ("GitHub", r"repo|readme|about|bio|files"), ("X", r"official x")) if re.search(k, w)]
        good.append("CA on " + "+".join(where or ["their pages"]))
    elif has(r"Token's address isn't"):
        risk.append("CA not posted by team")
    if has(r"never mention the token"):
        risk.append("team never mentions token")
    # what's built
    m = has(r"✅ (\d+) changes over (\d+) days")
    if m:
        good.append(f"open code · {m.group(1)} commits")
    if has(r"Code is private"):
        amber.append("private code")
    if has(r"✅ Has smart contracts and tests"):
        good.append("contracts + tests")
    for pat, label in ((r"✅ Site offers an MCP", "MCP"), (r"✅ Site offers an SDK", "SDK"), (r"✅ Site offers API keys", "API keys"),
                       (r"✅ Has docs written for AI", "AI-readable docs")):
        if has(pat):
            good.append(label)
    if has(r"Has a working app"):
        good.append("live app")
    if has(r"Made for AI agents"):
        good.append("built for AI agents")
    if act and act[0] >= 3:
        good.append(f"building: {act[0]} of last 8 days")
    # money
    if has(r"✅ Takes real payments"):
        good.append("takes payments")
    if has(r"Built on Robinhood Chain's own assets|Trades against"):
        good.append("uses USDG / stock tokens")
    m = has(r"Works with past winners: ([^(]+)")
    if m:
        good.append("works with " + m.group(1).strip().rstrip(","))
    if has(r"Looks like it earns fees|Maybe earns fees"):
        amber.append("earns fees? (guess)")
    if has(r"Says (?:fees|money) go(?:es)? back to the token"):
        amber.append("buyback/burn claimed")
    if has(r"Holding the token unlocks"):
        amber.append("holding unlocks product")
    if has(r"Mentions an audit|Audit looks self-done"):
        amber.append("audit unchecked")
    if has(r"One person, new account"):
        risk.append("1 dev, new account")
    for f, _n in warn_items[:3]:
        risk.append(re.split(r"[:(—]", f)[0].strip()[:42])
    chips = [("g", x) for x in good] + [("a", x) for x in amber] + [("r", x) for x in risk]
    rows = [("What it does", what_it_does(r, xdb)),
            ("Narrative", ", ".join(tags) or "No clear tag"),
            ("Money", ", ".join([x for x in good if x in ("takes payments", "uses USDG / stock tokens")] + amber[:3]) or "No money signs found"),
            ("Theirs?", next((x for x in good if x.startswith("CA on")), None) or ", ".join(x for x in risk if "CA" in x or "mentions" in x) or "Not shown"),
            ("Built", ", ".join(x for x in good if not x.startswith("CA on") and x not in ("takes payments", "uses USDG / stock tokens")) or "Nothing checked"),
            ("Watch for", ", ".join(risk + [x for x in amber if x in ("private code", "audit unchecked")]) or "Nothing flagged")]
    return chips, rows


def key_points(sc, act):
    """Up to 3 written-out key points for the closed card (user, 6 Nov): is it theirs, the money claim, the
    GitHub/product activity. Each is (icon, text) taken from the score's own lines, shortened."""
    lines = sum(sc.get("reasons", {}).values(), [])
    def pick(pat):
        return next((x for x in lines if re.search(pat, x)), None)
    def tidy(x):
        x = re.sub(r"\s*\(\+\d+\)$", "", x)
        x = x.replace(" — claimed, not checked on chain", " — claimed").replace(" — guess from their text, needs a look", " — a guess")
        x = re.sub(r"\b1 days\b", "1 day", x)
        x = re.sub(r" \(website links no X account to check\)", "", x)
        return x[2:].strip() if x[:1] in "✅❌🟡" else x
    out = []
    t = pick(r"Token's address is posted by") or pick(r"Token's address isn't")
    if t:
        out.append(("✅" if t.startswith("✅") else "❌", tidy(t)))
    m = pick(r"✅ Takes real payments") or pick(r"Says (?:fees|money) go(?:es)? back to the token") or pick(r"Looks like it earns fees|Maybe earns fees")
    if m:
        out.append(("✅" if m.startswith("✅") else "🟡", tidy(re.sub(r" \(“[^”]*”\)", "", m))))
    c = pick(r"\d+ changes over \d+ days")
    if c and not c.startswith("❌"):
        txt = tidy(c) + (f" · building {act[0]} of last 8 days" if act and act[0] >= 3 else "")
        out.append(("✅" if c.startswith("✅") else "🟡", txt))
    elif pick(r"Code is private"):
        out.append(("🔒", "Code is private"))
    else:
        tools = [n for p, n in ((r"✅ Site offers an MCP", "MCP"), (r"✅ Site offers an SDK", "SDK"), (r"✅ Site offers API keys", "API keys"),
                                (r"✅ Has docs written for AI", "AI docs")) if pick(p)]
        if tools:
            out.append(("✅", "Plug-in tools: " + ", ".join(tools)))
        elif pick(r"Has a working app"):
            out.append(("✅", "Has a working app"))
    return out[:3]


def ago(ts):
    """'40 min ago', '5 h ago', '3 days ago'."""
    if not ts:
        return ""
    m = days_between(NOW, iso(ts)) * 24 * 60
    return f"{m:.0f} min ago" if m < 90 else (f"{m / 60:.0f} h ago" if m < 48 * 60 else f"{m / 1440:.0f} days ago")


def short_n(n):
    n = n or 0
    return f"{n / 1e6:.1f}M" if n >= 1e6 else (f"{n / 1e3:.1f}k" if n >= 1e3 else f"{n:.0f}")


def quick_facts(r, sc, xdb, wallets, pdb, ship, e):
    """The Quick facts rows for a card (5 Nov layout): one short line each."""
    a = r["address"].lower()
    rows = []
    pt = pdb.get(a) or {}
    mk = pt.get("market") or {}
    val = [f"Value {money(pt.get('now_mcap') or r.get('mcap'))}"]
    if mk.get("liq"):
        val.append(f"Liquidity {money(mk['liq'])}")
    if "trades24" in mk:
        val.append(f"Trades 24h {mk['trades24']}")
    if pt.get("start_mcap") and pt.get("now_mcap"):
        val.append(f"Since found {(pt['now_mcap'] / pt['start_mcap'] - 1) * 100:+.0f}%")
    rows.append(("Market", " · ".join(val)))
    h, is_post = x_info.parse(r.get("twitter"))
    if h:
        acct = (xdb.get("accounts") or {}).get(h.lower()) or {}
        if acct.get("found") is False:
            rows.append(("X", f"@{h} · not found now"))
        elif acct:
            j = acct.get("joined")
            rows.append(("X", f"@{acct.get('handle') or h} · {short_n(acct.get('followers'))} followers"
                         + (f" · made {iso(j):%b %Y}" if j else "")))
        else:
            rows.append(("X", f"@{h}"))
    else:
        rows.append(("X", "none listed"))
    f = sc.get("facts") or {}
    if sc.get("kind") == "site":
        rows.append(("Website", f"{sc.get('tools', 0)} of 4 plug-in tools · {f.get('contract_addresses', 0)} contract addresses"))
    elif sc.get("private"):
        rows.append(("GitHub", f"{sc.get('repo')} · private code"))
    else:
        rows.append(("GitHub", f"{f.get('stars', 0)} stars · {f.get('commits', '?')} commits · {f.get('people', '?')} {'person' if f.get('people') == 1 else 'people'}"
                     + f" · since {f.get('created', '?')} · last change {f.get('pushed', '?')}"))
    w = (wallets or {}).get(a)
    if w:
        others = w.get("others") or []
        if w.get("launches", 1) <= 1:
            txt = "first launch"
        else:
            txt = f"{w['launches'] - 1} other launches" + (": " + ", ".join(o.get("symbol") or "?" for o in others[:3]) if others else "")
        rows.append(("Launch wallet", f"{txt} · {w.get('wallet_txs', '?')} transactions"))
    rec = ((ship or {}).get("tokens") or {}).get(a)
    if rec:
        rows.append(("Status", f"{shipping.DOT[rec['status']]} {rec['status']} · " + " · ".join(rec.get("reasons") or [])[:90]))
    return "<dl class='facts'>" + "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in rows) + "</dl>"


def build_site(state, xdb=None, wallets=None, test_html="", all_rows=None, pdb=None, ship=None, health=""):
    pdb = pdb or {}
    rows = sorted(state["github"].values(), key=lambda r: r.get("launched") or r["first_seen"], reverse=True)  # newest launch first
    # newest project first: by launch time (when found, if the launch time isn't known)
    site_rows = sorted(state.get("sites", {}).values(), key=lambda r: r.get("launched") or r["first_seen"], reverse=True)
    xdb, wallets = xdb or {}, wallets or {}
    all_rows = all_rows or rows  # every token on the page, for the same-X checks
    e = html.escape
    def md(s):  # `code` only
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", e(s))
    cards, site_cards, picks, builders, review_q = [], [], [], [], []
    reviews = json.load(open(REVIEWS, encoding="utf-8")) if os.path.exists(REVIEWS) else {}
    copies = copy_addresses(state, reviews)
    memes = {r["address"].lower() for r in rows + site_rows if is_meme(r, narratives(r, r["scoring"], xdb))}
    for r in rows + site_rows:
        sc = r["scoring"]
        if sc["score"] < SHOW_AT:  # hidden from the page (user, 6 Nov); still scored and priced
            continue
        is_site = sc.get("kind") == "site"
        new = days_between(NOW, iso(r.get("launched") or r["first_seen"])) < 1  # launched in the last day
        links = [(f"https://ponsfamily.com/launchpad/{r['address'].lower()}", "Pons"),
                 (f"https://dexscreener.com/robinhood/{r['address']}", "DexScreener")]
        if not is_site:
            links.append((f"https://github.com/{sc['repo']}", "GitHub"))
        if r.get("website"):
            links.append((r["website"], "Website"))
        if r.get("twitter"):
            links.append((r["twitter"], "X"))
        groups = []
        for g, items in sc.get("reasons", {}).items():
            if items:
                items = [i for i in items if "past winners we know of" not in i and "Doesn't link any past winners" not in i]
                groups.append(f"<h4>{e(g)}</h4><ul>" + "".join(f"<li>{md(i)}</li>" for i in items) + "</ul>")
        xline, xwarn = x_info.facts(r, all_rows, xdb, NOW)
        wline, wwarn = deployers.facts(r, wallets)
        serial, snote = wallet_note(r["address"], wallets, copies)
        if serial:  # its launcher also made known copies (user, 6 Nov)
            wwarn = wwarn + [snote[0].upper() + snote[1:]]
        xline = xline + wline  # status and price are in Quick facts
        allw = sc.get("flags", []) + xwarn + wwarn
        seen_w = Counter(allw)  # the same warning twice is shown once with ×2 (user, 5 Nov)
        ghost_w = prices.ghost(pdb.get(r["address"].lower()))
        notes = ("<h4>Checked by hand</h4><ul>" + "".join(f"<li>{md(n)}</li>" for n in sc.get("notes", [])) + "</ul>") if sc.get("notes") else ""
        road = "<h4>Roadmap</h4><ul>" + "".join(f"<li>{md(x)}</li>" for x in sc.get("roadmap", [])) + "</ul>"
        band = "hi" if sc["score"] >= 60 else ("mid" if sc["score"] >= 40 else "lo")
        # badge only, no score change (user, 5 Nov): the team has never posted or mentioned this token anywhere
        said = " ".join(sum(sc.get("reasons", {}).values(), []))
        unclaimed = sc["score"] > 0 and not re.search(r"✅ (?:Token's address is posted|Their [\w ]+ mentions the token)", said)
        if is_site:
            f = sc.get("facts", {})
            meta = (f"Site check · {sc.get('tools', 0)} of 4 plug-in tools · {f.get('contract_addresses', 0)} contract addresses"
                    f" · scored {r['scored_at'][:16].replace('T', ' ')} UTC")
            meta_html = f"<p class=\"meta\">{e(meta)}</p>"
        else:
            meta_html = (f"""<p class="meta"><button class="wrong" data-msg="{e('Wrong repo? ' + (r.get('symbol') or '') + ' ' + r['address'] + ' was matched to github.com/' + sc['repo'] + '. The right one is: ')}">Wrong repo?</button> Repo {e(sc['repo'])} · {sc['facts'].get('commits','?')} changes · created {e(sc['facts'].get('created','?'))} · last update {e(sc['facts'].get('pushed','?'))} · scored {e(r['scored_at'][:16].replace('T',' '))} UTC</p>""")
        # --- 5 Nov layout: closed card = 4 lines; Details = Quick facts, Warnings, Score, About, Full evidence ---
        a_ = r["address"]
        unoff = reviews.get(a_.lower(), {}).get("unofficial")  # hand note: probably not the team's token (no score change)
        hand = reviews.get(a_.lower(), {}).get("review") or {}  # hand review (6 Nov): what it does, unique, scalable, money...
        hand_html = ("<h4>Hand review" + (f" · {e(reviews[a_.lower()].get('checked', ''))}" if reviews[a_.lower()].get("checked") else "")
                     + "</h4><dl class='facts hand'>" + "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in hand.items()) + "</dl>") if hand else ""
        warn_items = ([(UNOFFICIAL + ": " + unoff, 1)] if unoff else []) + list(seen_w.items()) + ([(ghost_w, 1)] if ghost_w else [])
        has_unclaimed_flag = any(f.startswith(UNCLAIMED) for f in allw)
        badges = (("<span class='new'>NEW</span>" if new else "")
                  + (" <span class='grp'>🔒 private code</span>" if sc.get("private") else "")
                  + (" <span class='grp' title='Their repo, website and X never post the token address or mention the token.'>🤐 unclaimed</span>"
                     if unclaimed and not has_unclaimed_flag else "")
                  + (f" <span class='grp' title='{e(unoff)}'>❓ maybe not official</span>" if unoff else "")
                  + (" <span class='grp watch' title='Reviewed by hand: open Details'>📝 hand review</span>" if hand else ""))
        parts, plus, minus, cap = score_bits(sc)
        tags = narratives(r, sc, xdb)
        act = build_activity(a_, ship)
        kps = key_points(sc, act)
        qr_chips, qr_rows = quick_read(r, sc, tags, warn_items, act, xdb) if sc["score"] >= QUICK_AT else ([], [])
        said_kp = " ".join(t for _, t in kps).lower()
        def _shown(t):  # a chip the key points already say (user, 6 Nov: key points first, chips for the rest)
            return ((t.startswith(("CA on", "CA not posted")) and ("address" in said_kp))
                    or (t.startswith(("open code", "building:")) and "changes over" in said_kp)
                    or (t == "private code" and "private" in said_kp)
                    or (t == "buyback/burn claimed" and "go back" in said_kp)
                    or (t == "takes payments" and "payments" in said_kp)
                    or (t.startswith("earns fees?") and "earns fees" in said_kp)
                    or (t in ("MCP", "SDK", "API keys", "AI-readable docs") and "plug-in tools" in said_kp)
                    or (t == "live app" and "working app" in said_kp)
                    or (bool(warn_items) and t == re.split(r"[:(—]", warn_items[0][0])[0].strip()[:42]))  # top warning has its own line
        qr_chips = [(k, t) for k, t in qr_chips if not _shown(t)]
        qr_line = ("<p class='qr'>" + "".join(f"<span class='q{dict(g='g', a='a', r='x')[k]}'>{e(t)}</span>" for k, t in qr_chips) + "</p>") if qr_chips else ""
        qr_html = ("<h4>Quick read</h4><dl class='facts hand'>" + "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in qr_rows)
                   + "</dl>") if qr_rows else ""
        top_plus = re.sub(r"\s*\(.*$", "", plus[0]) if plus else ""
        top_warn = re.split(r"[:(—]", warn_items[0][0])[0].strip()[:60] if warn_items else ""
        verdict = "".join(f"<span class='kp {'good' if i == '✅' else ('bad' if i == '❌' else 'mid')}'>{i} {e(t)}</span>" for i, t in kps) + (
            (f"<span class='kp bad'>⚠️ {e(top_warn)}" + (f" (+{len(warn_items) - 1} more)" if len(warn_items) > 1 else "") + "</span>")
            if top_warn else "<span class='kp muted'>No warnings</span>")
        warn_html = ("<h4>Warnings</h4>" + "".join(
            f"<div class='flag'>⚠️ {e(f if len(f) <= 170 else f[:167] + '…')}{f' <b>×{n}</b>' if n > 1 else ''}</div>" for f, n in warn_items)
                     ) if warn_items else ""
        score_html = (f"<h4>Score {sc['score']}</h4><div class='chips'>"
                      + " ".join(f"<span class='chip{' zero' if not pts else ''}'>{e(n)} +{pts}</span>" for n, pts in parts) + "</div>"
                      + (f"<p class='cap'>{e(cap)}</p>" if cap else "")
                      + "<ul class='pm'>" + "".join(f"<li class='p'>{e(x)}</li>" for x in plus)
                      + "".join(f"<li class='m'>{e(x)}</li>" for x in minus) + "</ul>")
        about = (r.get("description") or "").strip()
        about = about if len(about) <= 220 else about[:217].rsplit(" ", 1)[0] + "…"
        proof = (bool(re.search(r"✅ Token's address is posted", said))
                 or (not unoff and (bool(hand) or reviews.get(a_.lower(), {}).get("official") is True)))
        (site_cards if is_site else cards).append(dict(r=r, sc=sc, proof=proof, unclaimed=unclaimed, unoff=unoff, hand=hand,
                                                       warn_items=warn_items, act=act, tags=tags, is_site=is_site, html=f"""
<article class="card" data-score="{sc['score']}" data-new="{int(new)}" data-addr="{e(a_.lower())}">
  <header>
    <div class="score {band}" style="--p:{sc['score']}">{sc['score']}<small>/ 100</small></div>
    <div class="title">
      <h2>{e(r.get('symbol') or '?')} <span class="nm">· {e(r.get('name') or '')}</span>
        <button class="ca" data-ca="{e(a_)}" title="Copy the contract address">{e(a_[:6] + '…' + a_[-4:])} ⧉</button> {badges}</h2>
      <p class="sub">{e(money(r.get('mcap')))} · launched {e(ago(r.get('launched')) or '?')} · {e(r.get('where') or '')}</p>
      <p class="verdict">{verdict}</p>
      {('<p class="tags">' + ''.join(f'<span class="tag">{e(t)}</span>' for t in tags) + '</p>') if tags else ''}
      {qr_line}
      <p class="links">{" · ".join(f'<a href="{e(u)}" target="_blank" rel="noopener">{e(t)}</a>' for u, t in links)}</p>
    </div>
  </header>
  <details class="more"><summary>Details</summary>
  {hand_html}{qr_html}
  <h4>Quick facts</h4>{quick_facts(r, sc, xdb, wallets, pdb, ship, e)}
  {warn_html}
  {score_html}
  {f"<h4>About</h4><p class='desc'>{e(about)}</p>" if about else ""}
  <details><summary>Full evidence</summary>{xline}{''.join(groups)}{notes}{road}
  {meta_html}</details>
  </details>
</article>"""))
    cards, gh_shown, gh_unconf = group_projects(cards, wallets, copies, e)
    site_cards, site_shown, site_unconf = group_projects(site_cards, wallets, copies, e)
    not_sure = {x["r"]["address"].lower() for x in gh_unconf + site_unconf}  # never on the Shortlist or Still building
    try:  # second 30-day test: every project shown at 61+, GitHub and Site check apart (user, 6 Nov)
        t61 = test61.update([("sites" if x["is_site"] else "github", x["r"], x["sc"]) for x in gh_shown + site_shown], pdb, NOW)
    except Exception as ex:
        print(f"Test 61: skipped ({ex})")
        t61 = {}
    try:
        old_test = [t["address"].lower() for t in csv.DictReader(open(os.path.join(HERE, "tokens.csv"), encoding="utf-8"))]
    except Exception:
        old_test = []
    keep = ({x["r"]["address"].lower() for x in gh_shown + site_shown} | set(old_test)
            | set((t61 or {}).get("tokens", {})))  # Status changes: page + test tokens only
    by_list = {sec: {a.lower() for a in state.get(sec, {})} for sec in ("github", "sites")}
    scores_html = "".join(
        f"<h2 style='margin:28px 0 6px'>{label}</h2>" + score_check_html(state, pdb, e, sec)
        + prices.section(pdb, e, SHOW_AT, memes, by_list[sec])
        for sec, label in (("github", "GitHub"), ("sites", "Site check")))
    for x in gh_shown + site_shown:
        r, sc, unclaimed, unoff, hand, warn_items, card_html = (x["r"], x["sc"], x["unclaimed"], x["unoff"], x["hand"],
                                                                x["warn_items"], x["html"])
        a_, tags, is_site = r["address"], x["tags"], x["is_site"]
        sure = a_.lower() not in not_sure
        if (sure and sc["score"] > 0 and not unclaimed and not unoff and not sc.get("flags")
                and r["address"].lower() not in {p[0]["address"].lower() for p in builders}):
            builders.append((r, sc, warn_items, x["act"], card_html))
        launched_at = r.get("launched") or r["first_seen"]
        if (sc["score"] >= REVIEW_AT and not unoff and not hand and launched_at >= REVIEW_FROM
                and a_.lower() not in {q["address"] for q in review_q}):
            review_q.append({"address": a_.lower(), "symbol": r.get("symbol") or "?", "name": r.get("name") or "",
                             "score": sc["score"], "mcap": (pdb.get(a_.lower()) or {}).get("now_mcap") or r.get("mcap") or 0,
                             "tags": tags, "website": r.get("website"), "twitter": r.get("twitter"),
                             "github": None if is_site else sc.get("repo"), "why": "not reviewed yet"})
        if (sure and sc["score"] > 0 and not unclaimed and not warn_items
                and r["address"].lower() not in {p[0]["address"].lower() for p in picks}):
            picks.append((r, sc, warn_items, (pdb.get(a_.lower()) or {}).get("market") or {}, winner_signs(r, sc), card_html))
    try:  # phone alert for tokens joining the Shortlist (notify.py); never stops the page
        joined = notify.update([{"address": p[0]["address"], "symbol": p[0].get("symbol") or "?", "name": p[0].get("name") or "",
                                 "score": p[1]["score"], "mcap": (pdb.get(p[0]["address"].lower()) or {}).get("now_mcap") or p[0].get("mcap"),
                                 "signs": p[4]} for p in shortlist_live(picks)[0]], NOW, money, SITE_URL, print)
    except Exception as ex:
        print(f"Alert: skipped ({ex})")
        joined = {}
    review_q.sort(key=lambda q: (not any("AI" in t for t in q["tags"]), -q["score"], -(q["mcap"] or 0)))  # AI first (user, 6 Nov)
    try:
        json.dump({"updated": NOW.isoformat(timespec="seconds"), "tokens": review_q}, open(REVIEW_QUEUE, "w", encoding="utf-8"), indent=1)
    except Exception as ex:
        print(f"Review queue: not saved ({ex})")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Token Watch</title>
<style>
/* Design system, 5 Nov 2026. Built on:
   - Type: modular scale, ratio 1.25 (major third) from 15px: 12 / 15 / 18.75 / 23.4 / 29.3 (Bringhurst, Elements of Typographic Style)
   - Space: 4px base grid, steps 4 / 8 / 12 / 16 / 24 / 32 / 48 (8-point grid; Mueller-Brockmann, Grid Systems)
   - Measure: body text capped at about 68 characters (Bringhurst: 45-75)
   - Colour: OKLCH, so equal lightness looks equal; one cool neutral hue for greys; every text colour passes WCAG AA 4.5:1
   - Hierarchy by weight and colour before size; fewer borders, more space (Refactoring UI)
   - Numbers in tabular figures so columns line up; ink only where it carries data (Tufte)
   - Score ring: the arc is the score, so the shape carries the number
   - Nested corners: inner radius = outer radius minus padding */
:root{{--chart:#3263c3;--bg:#f5f7f9;--card:#fff;--ink:#171b20;--mute:#5f646a;--line:#dfe1e5;--soft:#edf0f4;--accent:#3263c3;--hi:#007e46;--mid:#9a6100;--lo:#ba3630;--flag:#ffece9;--goodbg:#e3f8e9;
--t-1:12px;--t0:15px;--t1:18.75px;--t2:23.4px;--t3:29.3px;
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;--r:12px;
--shadow:0 1px 2px rgb(16 24 40/.05),0 1px 3px rgb(16 24 40/.06)}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--chart:#5f8ff0;--bg:#0d1013;--card:#15191d;--ink:#e8ebef;--mute:#a0a5ac;--line:#2a2e34;--soft:#1e2226;--accent:#7daafd;--hi:#5ccb89;--mid:#eeb154;--lo:#f47c70;--flag:#381f1c;--goodbg:#132a1b;--shadow:none}}}}
:root[data-theme="dark"]{{--chart:#5f8ff0;--bg:#0d1013;--card:#15191d;--ink:#e8ebef;--mute:#a0a5ac;--line:#2a2e34;--soft:#1e2226;--accent:#7daafd;--hi:#5ccb89;--mid:#eeb154;--lo:#f47c70;--flag:#381f1c;--goodbg:#132a1b;--shadow:none}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:var(--t0)/1.6 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}}
main{{max-width:880px;margin:0 auto;padding:var(--s6) var(--s4) var(--s7)}}
h1{{font-size:var(--t3);line-height:1.2;letter-spacing:-.02em;margin:0 0 var(--s2);font-weight:750}}
h2{{font-size:var(--t1);line-height:1.3;letter-spacing:-.01em;margin:0;font-weight:650}}
h3{{font-size:var(--t0);margin:var(--s5) 0 var(--s2);font-weight:650}}
h4{{margin:var(--s4) 0 var(--s1);font-size:var(--t0)}}
section.tab>h2{{font-size:var(--t2);letter-spacing:-.015em;margin:var(--s5) 0 var(--s2)!important}}
.top{{color:var(--mute);margin:0 0 var(--s5);max-width:68ch;font-size:14px}}
a{{color:var(--accent);text-decoration:none}} a:hover{{text-decoration:underline;text-underline-offset:2px}}
code{{font:13px ui-monospace,"SF Mono",Consolas,monospace;background:var(--soft);border-radius:4px;padding:0 4px}}
ul{{margin:0;padding-left:20px}} li{{margin:2px 0}}
.tabs{{position:sticky;top:0;z-index:5;display:flex;gap:var(--s1);overflow-x:auto;scrollbar-width:none;background:color-mix(in oklab,var(--bg) 88%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);padding:var(--s3) 0;margin:var(--s3) 0 var(--s2);border-bottom:1px solid var(--line)}}
.tabs a{{flex:none;color:var(--mute);border-radius:999px;padding:6px 14px;font-size:14px;font-weight:550;white-space:nowrap}}
.tabs a:hover{{background:var(--soft);color:var(--ink);text-decoration:none}}
.tabs a.on{{background:var(--ink);color:var(--card)}} .tabs a.on .cnt{{color:inherit;opacity:.7}}
.cnt{{font-size:var(--t-1);color:var(--mute);font-variant-numeric:tabular-nums;margin-left:2px}}
.bar{{display:flex;gap:var(--s1);flex-wrap:wrap;margin:0 0 var(--s4);padding:var(--s1);background:var(--soft);border-radius:10px;width:fit-content}}
.bar button{{border:0;background:none;color:var(--mute);border-radius:6px;padding:6px 12px;cursor:pointer;font:inherit;font-size:14px;font-weight:550}}
.bar button.on{{background:var(--card);color:var(--ink);box-shadow:var(--shadow)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:var(--s4) var(--s5);margin-bottom:var(--s3);box-shadow:var(--shadow);transition:border-color .15s}}
.card:hover{{border-color:color-mix(in oklab,var(--line) 50%,var(--mute))}}
.card header{{display:flex;gap:var(--s4);align-items:flex-start}}
.title{{min-width:0;flex:1}}
.score{{--p:0;flex:none;width:64px;height:64px;border-radius:50%;display:grid;place-content:center;text-align:center;font-size:var(--t1);font-weight:750;line-height:1;font-variant-numeric:tabular-nums;
 background:radial-gradient(closest-side,var(--card) 84%,transparent 85%),conic-gradient(currentColor calc(var(--p)*1%),var(--soft) 0)}}
.score small{{display:block;font-size:10px;font-weight:500;color:var(--mute);margin-top:3px;letter-spacing:.02em}}
.hi{{color:var(--hi)}} .mid{{color:var(--mid)}} .lo{{color:var(--lo)}}
.card h2{{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s1) var(--s2)}}
.nm{{font-weight:450;font-size:var(--t0);color:var(--mute)}}
.sub,.meta{{color:var(--mute);margin:2px 0;font-size:13px;font-variant-numeric:tabular-nums}}
.links{{margin:var(--s2) 0 0;font-size:13px;font-weight:550}}
.verdict{{margin:var(--s2) 0 0;font-size:14px;display:flex;flex-wrap:wrap;gap:var(--s1) var(--s3)}}
.verdict:empty{{display:none}} .verdict .kp{{display:block;width:100%}} .verdict .mid{{color:var(--mid)}} .verdict .good{{color:var(--hi)}} .verdict .bad{{color:var(--lo)}} .verdict .muted{{color:var(--mute)}}
.signs{{margin:var(--s2) 0 0;font-size:13px;color:var(--hi);font-weight:600;background:var(--goodbg);border-radius:6px;padding:2px var(--s2);width:fit-content;max-width:100%}}
.joined{{background:var(--accent);color:var(--card);border-radius:4px;padding:0 6px;margin-right:6px;font-weight:700}}
.qr{{margin:var(--s2) 0 0;display:flex;gap:4px;flex-wrap:wrap;font-size:12px;font-weight:550}} .qr span{{border-radius:5px;padding:1px 7px}} .qg{{background:var(--goodbg);color:var(--hi)}} .qa{{background:color-mix(in oklab,var(--mid) 14%,transparent);color:var(--mid)}} .qx{{background:var(--flag);color:var(--lo)}}
.key{{display:flex;flex-wrap:wrap;gap:4px 14px;margin:0 0 var(--s1);font-size:13px;color:var(--mute)}} .key .qg,.key .qa,.key .qx{{border-radius:5px;padding:0 7px;font-size:12px;font-weight:550}}
.tags{{margin:var(--s2) 0 0;display:flex;gap:var(--s1);flex-wrap:wrap}}
.tag{{font-size:var(--t-1);font-weight:550;border-radius:999px;padding:1px 10px;background:var(--soft);color:var(--mute)}}
.new{{font-size:11px;font-weight:700;letter-spacing:.04em;background:var(--accent);color:var(--card);border-radius:999px;padding:1px 8px}}
.grp{{font-size:var(--t-1);font-weight:550;border:1px solid var(--line);border-radius:999px;padding:0 8px;color:var(--mute)}}
.grp.watch{{color:var(--accent);border-color:var(--accent)}} .grp.benchmark{{color:var(--hi);border-color:var(--hi)}}
button.ca{{font:12px ui-monospace,"SF Mono",Consolas,monospace;border:1px solid var(--line);background:var(--soft);color:var(--mute);border-radius:6px;padding:1px 8px;cursor:pointer}}
button.ca:hover{{color:var(--ink);border-color:var(--mute)}}
summary{{cursor:pointer;color:var(--accent);font-weight:550;font-size:14px;list-style:none}} summary::-webkit-details-marker{{display:none}}
summary::before{{content:"\\203A";display:inline-block;width:1em;transition:transform .15s}} details[open]>summary::before{{transform:rotate(90deg)}}
.more{{margin-top:var(--s3);border-top:1px solid var(--line);padding-top:var(--s2)}}
.more h4{{margin:var(--s5) 0 var(--s2);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--mute)}}
.facts{{display:grid;grid-template-columns:max-content 1fr;gap:var(--s1) var(--s4);margin:0;font-size:14px;font-variant-numeric:tabular-nums}} .facts dt{{color:var(--mute)}} .facts.hand{{grid-template-columns:minmax(110px,max-content) 1fr;gap:var(--s2) var(--s4)}} .facts.hand dt{{font-weight:600}} .facts dd{{margin:0}}
.flag{{background:var(--flag);border-radius:8px;padding:var(--s2) var(--s3);margin:var(--s2) 0 0;font-size:14px}}
.chips{{display:flex;flex-wrap:wrap;gap:var(--s1);font-size:13px;font-variant-numeric:tabular-nums}}
.chip{{background:var(--soft);border-radius:6px;padding:1px 8px;font-weight:550}} .chip.zero{{color:var(--mute);font-weight:450}}
.cap,.why .cap{{margin:var(--s2) 0 0;font-size:13px;color:var(--mid)}}
ul.pm{{list-style:none;padding-left:0;margin:var(--s2) 0;font-size:14px}} ul.pm li{{padding-left:18px;text-indent:-18px}}
ul.pm li.p::before{{content:"+";display:inline-block;width:18px;text-indent:0;color:var(--hi);font-weight:700}} ul.pm li.m::before{{content:"\\2013";display:inline-block;width:18px;text-indent:0;color:var(--lo);font-weight:700}}
.desc{{margin:0;max-width:68ch}}
.why{{border-left:2px solid var(--line);padding:var(--s1) 0 var(--s1) var(--s3);margin:var(--s2) 0}} .why ul{{margin:var(--s1) 0 0;font-size:14px}}
.unconf{{background:var(--flag);border-radius:8px;padding:var(--s2) var(--s3);margin:0 0 var(--s3);font-size:14px}} .unconf ul{{margin:var(--s1) 0 0;font-size:13px}} .unconf li.bad{{color:var(--lo);font-weight:600}}
.dups{{margin:calc(-1*var(--s1)) 0 var(--s4) var(--s4)}} .dups>summary{{margin-bottom:var(--s2)}} .dups .card{{opacity:.88}}
.xline{{margin:var(--s2) 0 0;font-size:13px;color:var(--mute)}} .ship{{color:var(--ink)}}
.muted{{color:var(--mute);font-size:13px}}
.answer{{background:var(--soft);border-radius:8px;padding:var(--s2) var(--s3);margin:var(--s2) 0;font-size:15px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--s3);margin:var(--s3) 0 var(--s4)}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:var(--s3) var(--s4);display:flex;flex-direction:column;gap:2px}}
.tile b{{font-size:var(--t2);font-variant-numeric:tabular-nums;line-height:1.1}} .tile span{{font-size:13px;font-weight:600}} .tile small{{font-size:12px;color:var(--mute)}}
svg.chart{{width:100%;height:auto;display:block;margin:var(--s2) 0}} svg.chart .grid{{stroke:var(--line);stroke-width:1}}
svg.chart .target{{stroke:var(--mute);stroke-width:1.5;stroke-dasharray:4 4}} svg.chart .ax{{fill:var(--mute);font-size:11px;font-variant-numeric:tabular-nums}}
svg.chart .bar rect:first-child{{fill:var(--chart)}} svg.chart .hit{{fill:transparent}} svg.chart .bar:hover rect:first-child{{opacity:.75}}
.hbars{{display:grid;gap:6px;margin:var(--s3) 0;max-width:620px}} .hrow{{display:grid;grid-template-columns:140px 1fr 40px;align-items:center;gap:var(--s2);font-size:14px}}
.hl{{color:var(--mute)}} .ht{{background:var(--soft);border-radius:4px;height:14px;overflow:hidden}} .hb{{display:block;height:100%;background:var(--chart);border-radius:4px;min-width:2px}}
.hv{{font-variant-numeric:tabular-nums;font-weight:600}} details.tv>summary{{font-size:13px}}
table.sc{{border-collapse:collapse;margin:var(--s2) 0 var(--s3);font-size:14px;font-variant-numeric:tabular-nums}}
table.sc td,table.sc th{{border-bottom:1px solid var(--line);padding:6px var(--s4) 6px 0;text-align:left}} table.sc th{{color:var(--mute);font-weight:550;font-size:13px}}
.test h2{{margin:0 0 var(--s1)}}
table.sum{{border-collapse:collapse;width:100%;font-size:13px;margin:var(--s3) 0;display:block;overflow-x:auto;font-variant-numeric:tabular-nums}}
.sum th,.sum td{{border-bottom:1px solid var(--line);padding:6px var(--s2);text-align:left;vertical-align:top}} .sum th{{color:var(--mute);font-weight:550}}
.trow{{border-top:1px solid var(--line);padding:var(--s2) 0}} .trow summary{{color:var(--ink);font-size:14px;font-weight:450}} .trow summary b{{margin-right:var(--s1)}}
.kv{{color:var(--mute);font-size:13px;margin-left:var(--s2);white-space:nowrap;font-variant-numeric:tabular-nums}} .kv.warn{{color:var(--lo)}}
button.wrong{{font:inherit;font-size:12px;border:1px solid var(--line);background:none;color:var(--mute);border-radius:6px;padding:1px 8px;cursor:pointer;margin-right:6px}}
.sound{{position:fixed;left:16px;bottom:16px;z-index:9;font:inherit;font-size:13px;font-weight:600;border:1px solid var(--line);background:var(--card);color:var(--mute);border-radius:999px;padding:6px 14px;cursor:pointer;box-shadow:var(--shadow)}}
.sound.on{{color:var(--hi);border-color:var(--hi)}}
.toast{{position:fixed;right:16px;bottom:16px;z-index:9;max-width:min(420px,calc(100vw - 32px));background:var(--ink);color:var(--card);border-radius:12px;padding:12px 40px 12px 16px;font-size:14px;box-shadow:0 8px 24px rgb(0 0 0/.25)}}
.toast a{{color:var(--card);font-weight:650;margin-right:10px;white-space:nowrap}} .toast a span{{opacity:.7;font-weight:500}}
.toast button{{position:absolute;top:6px;right:8px;border:0;background:none;color:inherit;font-size:18px;cursor:pointer;opacity:.7}}
.card.fresh{{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in oklab,var(--accent) 25%,transparent)}}
@media (max-width:600px){{.toast{{bottom:64px}}}}
@media (max-width:600px){{main{{padding:var(--s5) var(--s4) var(--s7)}} h1{{font-size:var(--t2)}} .card{{padding:var(--s4)}} .card header{{gap:var(--s3)}} .score{{width:52px;height:52px;font-size:var(--t0)}} .score small{{display:none}} .dups{{margin-left:0}}}}
</style></head><body>
<button id="sound" class="sound" title="Play a sound when a token newly scores {SHOW_AT}+ on the GitHub or Site check list">🔕 Sound off</button>
<div id="toast" class="toast" role="status" hidden></div>
<main>
<h1>Token Watch</h1>
<p class="key"><span>✅ checked</span><span>🟡 claimed or guessed, not checked</span><span>❌ missing</span><span>⚠️ warning</span><span>🔒 private code</span>
<span class="qg">green chip = good</span><span class="qa">amber = claimed / unchecked</span><span class="qx">red = risk</span></p>
<nav class="tabs" id="tabs">
<a href="#short" data-tab="short">Shortlist <span class="cnt">{sum(1 for p in picks if len(p[4]) >= SHORT_SIGNS and (p[3].get('trades24') or 0) >= SHORT_TRADES and (p[3].get('liq') or 0) >= SHORT_LIQ)}</span></a>
<a href="#building" data-tab="building">Still building</a>
<a href="#github" data-tab="github">GitHub <span class="cnt">{len(cards)}</span></a>
<a href="#sites" data-tab="sites">Site check <span class="cnt">{len(site_cards)}</span></a>
<a href="#test" data-tab="test">30-day test</a>
<a href="#status" data-tab="status">Status changes</a>
<a href="#scores" data-tab="scores">Was the score right?</a>
<a href="#health" data-tab="health">Scanner health</a>
</nav>
<p class="top">New Robinhood Chain tokens (Pons + DexScreener). Checked about every 15 minutes. Last run {NOW:%Y-%m-%d %H:%M} UTC · showing only projects scoring {SHOW_AT}+, one card per project ({len(cards)} GitHub, {len(site_cards)} site check, of {len(rows) + len(site_rows)} scored) · {state.get('checked_total',0)} tokens checked in all. Lower scores are still tracked: see <a href="#scores">Was the score right?</a> for any that took off. Scoring rules: SCORING.md.</p>
<section class="tab" id="short">{shortlist_html(picks, e, joined)}{review_queue_html(review_q, e)}</section>
<section class="tab" id="building">{building_html(builders, e)}</section>
<section class="tab" id="sites">
<h2 style="margin:22px 0 6px">Site check: websites developers and AI agents can plug into</h2>
<p class="top">No GitHub needed: their own site has {sitecheck.LIST_AT}+ of API keys, SDK, MCP, llms.txt. Rules: SCORING.md.</p>
<div class="bar"><button class="on" data-f="all">All</button><button data-f="new">New (24h)</button><button data-f="flag">Red flags</button></div>
{''.join(site_cards) if site_cards else f'<p>No site-check projects score {SHOW_AT}+ right now.</p>'}
</section>
<section class="tab" id="status">{shipping.alerts_html(ship, NOW, keep) if ship else '<p>No status data yet.</p>'}</section>
<section class="tab" id="test">{test61.html(t61, NOW, e, money)}{test_html or '<p>The first test section is refreshed about twice a day.</p>'}</section>
<section class="tab" id="scores">{scores_html}</section>
<section class="tab" id="health">{health or '<p>Scanner health appears after the next scan.</p>'}</section>
<section class="tab" id="github">
<h2 style="margin:22px 0 10px">New tokens with a public GitHub</h2>
<div class="bar"><button class="on" data-f="all">All</button><button data-f="new">New (24h)</button><button data-f="flag">Red flags</button></div>
{''.join(cards) if cards else f'<p>No GitHub projects score {SHOW_AT}+ right now.</p>'}
{skipped_html(state)}
</section>
</main><script>
window.TW_TIME=()=>{{{LOCAL_TIME_JS}}};
{PAGE_JS}
</script></body></html>"""
    os.makedirs(os.path.dirname(SITE), exist_ok=True)
    open(SITE, "w", encoding="utf-8").write(page)


def with_site_check(sc, tok, review):
    """Private GitHub (code can't be checked): also score their website with the site check and keep the
    higher score, so a private repo can't hide a strong product (DARK, 5 Nov: 40 on GitHub, 80 on its site)."""
    if not sc.get("private") or sc["score"] == 0 or not sitecheck.has_site(tok):
        return sc
    ss = sitecheck.score(tok, review, sys.modules[__name__])
    if not ss or ss["score"] <= sc["score"] or ss.get("copy_of"):
        return sc
    out = dict(sc)
    out["reasons"] = {f"Website (site check: {ss['score']})": [ln for g in ss["reasons"].values() for ln in g],
                      **{f"{g} (GitHub check: {sc['score']})" if i == 0 else g: v for i, (g, v) in enumerate(sc["reasons"].items())}}
    out["reasons"][next(iter(out["reasons"]))].insert(
        0, f"ℹ️ The GitHub code is private, so the score uses their website instead: {ss['score']} (the GitHub check gave {sc['score']})")
    out.update(score=ss["score"], raw_score=ss.get("raw_score"), site_score=ss["score"], github_score=sc["score"],
               flags=sc["flags"] + [f for f in ss["flags"] if f not in sc["flags"]])
    return out


def launch_date(addr):
    """(launched, source): the Pons launch time for Pons tokens, else the token's first trade on DexScreener."""
    p = pons_one(addr)
    if p and p.get("launched"):
        return p["launched"], "pons"
    m = market(addr) or {}
    return (m.get("launched"), "first trade") if m.get("launched") else (None, None)


def keep_launch(r, g):
    """A rescore keeps the checked launch date from the earlier record."""
    if g and g.get("launched_src"):
        r["launched"], r["launched_src"] = g["launched"], g["launched_src"]


def fix_launch_dates(state):
    """Once per listed token: store its true launch date (5 Nov: some had none, Pons ones had the pool date)."""
    n = 0
    for sec in ("github", "sites"):
        for a, r in state.get(sec, {}).items():
            if r.get("launched_src"):
                continue
            when, src = launch_date(r["address"])
            if when:
                r["launched"], r["launched_src"] = when, src
                n += 1
    if n:
        log(f"Launch dates: set for {n} listed tokens")


def site_from_x(tok):
    """Pons lists no website (UBIK, 5 Nov): use the website on the token's own X profile, but only if that X
    posts this token's address. A copy, or a token linking someone else's famous X, never passes."""
    h, is_post = x_info.parse(tok.get("twitter"))
    acct = x_account(h) if h and not is_post else None
    if not acct or not acct.get("found") or tok["address"].lower() not in (acct.get("cas") or []):
        return None
    t2 = {**tok, "website": acct.get("bio_site"), "site_via_x": acct.get("handle") or h}
    return t2 if sitecheck.has_site(t2) else None


def site_pass(toks, state, reviews):
    """Site check for tokens with no public GitHub (rules in SCORING.md, code in sitecheck.py)."""
    sites = state.setdefault("sites", {})
    looked = state.setdefault("site_checked", {})
    for key, g in sites.items():  # keep re-scoring listed ones that have left the newest lists
        if key not in toks:
            toks[key] = {k: g.get(k) for k in ("address", "symbol", "name", "description", "website", "twitter", "launched", "site_via_x")}
            toks[key].update({"links": [], "source": "earlier"})
    todo = []
    for key, t in toks.items():
        if key in state["github"] or reviews.get(key, {}).get("skip"):
            continue
        if not sitecheck.has_site(t) and not (key in sites or x_info.parse(t.get("twitter"))[0]):
            continue
        g = sites.get(key)
        if g:
            if rescore_due(g):
                todo.append((key, t))
            continue
        last = looked.get(key)
        if last:
            launched = iso(t.get("launched"))
            if days_between(NOW, iso(last)) * 24 < sitecheck.RECHECK_HOURS:
                continue
            if launched and days_between(NOW, launched) > sitecheck.NEW_DAYS:
                continue
        todo.append((key, t))
    new = [x for x in todo if x[0] not in sites]
    # 6 Nov: catch-up tokens kept losing their place to new launches (SEER, HMM never got checked),
    # so up to CATCHUP_SITE_SLOTS of the slots go to them first; new launches get the rest
    cu = [x for x in new if x[1].get("catchup")][:CATCHUP_SITE_SLOTS]
    new = cu + [x for x in new if x not in cu]
    over = [k for k, _ in new[sitecheck.MAX_NEW_PER_RUN:] if k not in looked]
    if over:  # didn't fit this run: queue them for catch-up so a token seen only once isn't lost (5 Nov: HMM)
        q = json.load(open(CATCHUP, encoding="utf-8")) if os.path.exists(CATCHUP) else []
        q += [k for k in over if k not in set(q)]
        json.dump(q, open(CATCHUP, "w", encoding="utf-8"))
        log(f"Site check: {len(over)} tokens didn't fit this run, queued for catch-up")
    new = new[:sitecheck.MAX_NEW_PER_RUN]
    again = sorted([x for x in todo if x[0] in sites], key=lambda x: sites[x[0]]["scored_at"])[:0 if over_budget() else MAX_RESCORES]  # most overdue first; none if over the time budget
    todo = again + new
    RUN_STATS["rescored"] = RUN_STATS.get("rescored", 0) + len(again)
    n_listed = 0
    for key, t in todo:
        looked[key] = NOW.isoformat(timespec="seconds")
        mk = market(t["address"])
        t2 = {**t, **{k: v for k, v in mk.items() if v and (k not in ("symbol", "launched") or not t.get(k))}}
        if not sitecheck.has_site(t2):
            t2x = site_from_x(t2)
            if not t2x:
                if key in sites:  # listed before, but its "website" turned out not to be theirs (5 Nov rule)
                    log(f"  SITE REMOVED: {sites[key].get('symbol')} {sites[key].get('website')} is not the project's own website")
                    del sites[key]
                continue
            t2 = t2x
        try:
            sc = sitecheck.score(t2, reviews.get(key, {}), sys.modules[__name__])
        except Exception as ex:
            log(f"  {t2.get('symbol')}: site check failed ({ex})")
            continue
        g = sites.get(key)
        if not sc or (not sc["listed"] and not g):
            continue
        sites[key] = {"address": t["address"], "symbol": t2.get("symbol"), "name": t2.get("name"),
                      "description": t2.get("description"), "website": t2.get("website"), "twitter": t2.get("twitter"),
                      "site_via_x": t2.get("site_via_x"),
                      "launched": t2.get("launched"), "mcap": mk.get("mcap") or t.get("mcap"), "where": mk.get("where") or t.get("stage"),
                      "first_seen": (g or {}).get("first_seen", NOW.isoformat(timespec="seconds")),
                      "scored_at": NOW.isoformat(timespec="seconds"), "found_on": "website", "scoring": sc}
        keep_launch(sites[key], g)
        n_listed += not g
        log(f"  {'SITE RESCORED' if g else 'NEW SITE'}: {t2.get('symbol')} {t2.get('website')} score {sc['score']} ({sc['tools']} plug-in tools)")
    cutoff = (NOW - datetime.timedelta(days=sitecheck.NEW_DAYS + 2)).isoformat()
    state["site_checked"] = {k: v for k, v in looked.items() if v >= cutoff or k in sites}
    log(f"Site check: {len(todo)} sites checked, {n_listed} newly listed, {len(sites)} listed in all")


# ---------- main ----------
def main():
    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {"seen": {}, "github": {}, "checked_total": 0}
    reviews = json.load(open(REVIEWS, encoding="utf-8")) if os.path.exists(REVIEWS) else {}
    COPY_CACHE.update({k: tuple(v) for k, v in state.get("copy_cache", {}).items()})
    state.setdefault("skipped", [])
    # active vs resting (tiers.py, 6 Nov): resting = hidden and older; checked once a day, woken when they move
    global RESTING
    tdb = tiers.load()
    pdb0 = {k.lower(): v for k, v in (json.load(open(prices.FILE, encoding="utf-8")) if os.path.exists(prices.FILE) else {}).items()}
    keep = test_keep()
    scored = list(state["github"].values()) + list(state.get("sites", {}).values())
    symbols = {r["address"].lower(): r.get("symbol") or "?" for r in scored}
    active, RESTING = tiers.split(tdb, scored, NOW, keep, SHOW_AT, pdb0)
    ptoks = pons_tokens()
    seed = os.path.join(HERE, "data", "raw_2026-11-04", "pons.html")
    if not state["seen"] and os.path.exists(seed):  # first run: also check the 4 Nov list
        have = {t["address"] for t in ptoks}
        ptoks += [t for t in pons_tokens(seed) if t["address"] not in have]
    symbol_counts = Counter(t["symbol"] for t in ptoks)
    for s, c in state.get("symbol_counts", {}).items():
        symbol_counts[s] = max(symbol_counts[s], c)
    state["symbol_counts"] = dict(symbol_counts)
    toks = {t["address"].lower(): t for t in dex_tokens()}
    toks.update({t["address"].lower(): t for t in ptoks})
    for key, g in state["github"].items():  # keep re-scoring tokens that have left the newest lists
        if key not in toks:
            toks[key] = {k: g.get(k) for k in ("address", "symbol", "name", "description", "website", "twitter", "launched", "site_via_x")}
            toks[key].update({"links": [], "source": "earlier"})
    for t in pons_busy():  # tokens taking off after they left the newest page (MERY, UPOCH, 5 Nov)
        a = t["address"].lower()
        if a in RESTING:  # a resting token on Pons's top market-cap / volume list wakes now, not at its daily check
            tiers.wake(tdb, a, "on Pons's top market-cap / volume list", t.get("mcap"), NOW, symbols)
            RESTING.discard(a)
        toks.setdefault(a, t)
    for t in catchup(state):  # older launches from the one-time sweep, a few a run
        toks.setdefault(t["address"].lower(), t)["catchup"] = True
    try:  # every new token trading on Robinhood Chain, not only Pons ones (FOBO, 5 Nov)
        deployers.refresh_index(log)
        for t in dexpools.run(deployers.rpc, fetch_json, deployers.KNOWN, lambda a: a in state["seen"], NOW, log):
            toks.setdefault(t["address"].lower(), t)
    except Exception as ex:
        log(f"Pool feed: failed ({ex})")
    fix_launch_dates(state)

    # new tokens first, then re-scores, most overdue first; at most MAX_RESCORES re-scores a run
    queue = sorted(toks.items(), key=lambda kv: (kv[0] in state["github"], (state["github"].get(kv[0]) or {}).get("scored_at", "")))
    rescored = 0
    while queue:
        key, t = queue.pop(0)
        g = state["github"].get(key)
        if key in state["seen"] and not g:
            continue  # already checked, no GitHub
        if g and (not rescore_due(g) or rescored >= MAX_RESCORES or over_budget()):
            continue
        rescored += bool(g)
        RUN_STATS["rescored"] = RUN_STATS.get("rescored", 0) + bool(g)
        if key not in state["seen"]:
            state["checked_total"] = state.get("checked_total", 0) + 1
        state["seen"][key] = NOW.isoformat(timespec="seconds")
        if g:
            owner, repo = ((reviews.get(key, {}).get("repo") or g["scoring"]["repo"]) + "/").split("/")[:2]
            found_on = g.get("found_on", "token page")
        else:
            text = " ".join([t.get("description") or ""] + (t.get("links") or []))
            by = {"token page": github_links(text)}
            if not by["token page"] and t.get("website"):
                page, code = website_text(t["website"])
                by["website"] = github_links(" ".join(re.findall(r'href="([^"]+)"', page)))
                by["website code"] = github_links(page + code)
            pick, found_on = choose_link(t, by)
            rv0 = reviews.get(key, {})
            if rv0.get("repo"):  # hand fix: the right repo
                pick, found_on = tuple((rv0["repo"] + "/").split("/")[:2]), found_on or "checked by hand"
            ignored = [f"{o}/{r}" if r else o for lst in by.values() for (o, r) in lst
                       if not pick or (o, r) != tuple(pick)]
            if ignored:
                state["skipped"].append({"when": NOW.isoformat(timespec="seconds"), "address": t["address"],
                                         "symbol": t.get("symbol"), "website": t.get("website"),
                                         "used": f"{pick[0]}/{pick[1]}" if pick and pick[1] else (pick[0] if pick else None),
                                         "ignored": sorted(set(ignored))[:12]})
            if not pick or rv0.get("skip"):
                continue
            owner, repo = pick
        full = pick_repos(owner, repo or None)[0]
        mk = market(t["address"])
        t2 = {**t, **{k: v for k, v in mk.items() if v and (k not in ("symbol", "launched") or not t.get(k))}}
        rv = reviews.get(key, {})
        try:
            sc = score(t2, full, found_on, symbol_counts, rv)
            sc = with_site_check(sc, t2, rv)
        except Exception as ex:
            log(f"  {t2.get('symbol')}: scoring failed ({ex})")
            continue
        state["github"][key] = {"address": t["address"], "symbol": t2.get("symbol"), "name": t2.get("name"),
                                "description": t2.get("description"), "website": t2.get("website"), "twitter": t2.get("twitter"),
                                "launched": t2.get("launched"), "mcap": mk.get("mcap") or t.get("mcap"), "where": mk.get("where") or t.get("stage"),
                                "first_seen": (g or {}).get("first_seen", NOW.isoformat(timespec="seconds")),
                                "scored_at": NOW.isoformat(timespec="seconds"), "found_on": found_on, "scoring": sc}
        keep_launch(state["github"][key], g)
        log(f"  {'RESCORED' if g else 'NEW GITHUB'}: {t2.get('symbol')} -> {full} score {sc['score']}" + (" RED FLAG" if sc["flags"] else ""))
        real = sc.get("copy_of")
        if real and real not in toks:  # the project's real token: check it too
            rt = pons_one(real)
            if rt:
                toks[real] = rt
                queue.append((real, rt))
                log(f"  COPYCAT: {t2.get('symbol')} {key} copies {real}, checking the real one too")

    site_pass(toks, state, reviews)

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    cutoff = (NOW - datetime.timedelta(days=30)).isoformat()
    state["skipped"] = [x for x in state["skipped"] if x["when"] >= cutoff]
    for key in [k for k, v in reviews.items() if v.get("skip")]:
        state["github"].pop(key, None)
        state.get("sites", {}).pop(key, None)
    state["copy_cache"] = {k: list(v) for k, v in COPY_CACHE.items()}
    json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)
    # extras: X, Telegram, launch wallet, 30-day test section. Never stop the watch over these.
    try:
        trows = test_tokens.load(fetch, fetch_json, NOW)
    except Exception as ex:
        log(f"Test tokens: skipped ({ex})")
        trows = []
    allrows = list(state["github"].values()) + list(state.get("sites", {}).values()) + trows
    # active tokens (incl. ones added this run) get every check; resting ones only in today's slice (tiers.py)
    scored = list(state["github"].values()) + list(state.get("sites", {}).values())
    symbols.update({r["address"].lower(): r.get("symbol") or "?" for r in scored})
    active, RESTING = tiers.split(tdb, scored, NOW, keep, SHOW_AT, pdb0)
    slice_ = [] if over_budget() else tiers.due_resting(tdb, RESTING, NOW)
    look = active | set(slice_)
    checkrows = [r for r in allrows if "scoring" not in r or r["address"].lower() in look]
    log(f"Tiers: {len(active)} active, {len(RESTING)} resting, {len(slice_)} resting checked this run")
    try:
        xdb = x_info.update(checkrows, fetch_json, NOW, log, fetch=fetch, gh_user=lambda o: gh(f"users/{o}"))
    except Exception as ex:
        log(f"X: skipped ({ex})")
        xdb = json.load(open(x_info.FILE, encoding="utf-8")) if os.path.exists(x_info.FILE) else {}
    try:
        wallets = deployers.update(allrows, market, log)
    except Exception as ex:
        log(f"Wallets: skipped ({ex})")
        wallets = json.load(open(deployers.FILE, encoding="utf-8")) if os.path.exists(deployers.FILE) else {}
    try:
        ship = shipping.update(checkrows, fetch, fetch_json, xdb, GH, NOW, log)
    except Exception as ex:
        log(f"Shipping: skipped ({ex})")
        ship = json.load(open(shipping.FILE, encoding="utf-8")) if os.path.exists(shipping.FILE) else None
    try:
        test_html = test_tokens.section(trows, xdb, wallets, NOW, allrows, ship=ship) if trows else ""
    except Exception as ex:
        log(f"Test section: skipped ({ex})")
        test_html = ""
    try:
        pdb = prices.update(state, fetch_json, market, NOW, log, pons_for=look)
    except Exception as ex:
        log(f"Prices: skipped ({ex})")
        pdb = json.load(open(prices.FILE, encoding="utf-8")) if os.path.exists(prices.FILE) else {}
    health = ""
    try:  # launch/graduation times, wake-ups, run log, daily study (tiers.py). Never stops the page.
        pdb_l = {k.lower(): v for k, v in pdb.items()}
        # first: tokens we saw on the curve that now trade on an exchange = they graduated; get the exact time
        grad = [a for a, t in tdb["times"].items() if t.get("stage") == "curve" and a not in PONS_TIMES
                and "exchange" in ((pdb_l.get(a) or {}).get("where") or "")]
        missing = grad + [r["address"].lower() for r in scored if r["address"].lower() in deployers.KNOWN
                          and r["address"].lower() not in tdb["times"] and r["address"].lower() not in PONS_TIMES]
        for a in missing[:tiers.TIMES_PER_RUN]:  # small and capped, so it runs even over the time budget
            pons_times(a)
        for a, o in PONS_TIMES.items():
            tiers.record_times(tdb, a, o, NOW)
        pdb_l = {k.lower(): v for k, v in pdb.items()}
        woke = tiers.wake_check(tdb, RESTING, slice_, pdb_l, NOW, symbols)
        for a in woke:
            log(f"  WOKE: {symbols.get(a)} ({tdb['woken'][a]['why']})")
        week = (NOW - datetime.timedelta(days=7)).isoformat()
        study = {"time": NOW.isoformat(timespec="seconds"), "active": len(active), "resting": len(tdb["resting"]),
                 "woken_7d": sum(1 for w in tdb["woken"].values() if w["at"] >= week),
                 "graduation": tiers.graduation_study(tdb, scored, pdb_l, NOW)}
        tiers.save(tdb)
        tiers.save_study(study)
        tiers.log_run({"time": NOW.isoformat(timespec="seconds"), "minutes": round((time.time() - START) / 60, 1),
                       "active": len(active), "resting": len(tdb["resting"]), "resting_checked": len(slice_),
                       "rescored": RUN_STATS.get("rescored", 0), "woken": len(woke), "listed": len(scored)})
        health = tiers.html(tdb, study, tiers.read_runs(60), html.escape, money)
    except Exception as ex:
        log(f"Tiers: skipped ({ex})")
    build_site(state, xdb, wallets, test_html, allrows, pdb, ship, health=health)
    log(f"Done {NOW:%Y-%m-%d %H:%M} UTC: {len(state['github'])} tokens with GitHub on the page")
    try:
        import publish_site
        publish_site.publish(log)
    except Exception as ex:
        log(f"Live site: skipped ({ex})")


def pid_running(pid):
    """True if a process with this id is still alive (a killed scan leaves its lock behind)."""
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    # Only one copy at a time: copies running together overwrite each other's results.
    # The lock holds the scan's process id; if that process is gone (e.g. killed by the
    # Task Scheduler time limit) the lock is stale and is ignored.
    LOCK = os.path.join(HERE, "data", "watch.lock")
    try:
        if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 60 * 60:
            try:
                other = int(open(LOCK).read().strip())
            except ValueError:
                other = 0
            if other and other != os.getpid() and pid_running(other):
                print("Another scan is still running; skipping this one.")
                sys.exit(0)
        open(LOCK, "w").write(str(os.getpid()))
    except OSError:
        pass
    try:
        main()
    finally:
        open(LOG, "w", encoding="utf-8").write("\n".join(log_lines) + "\n")
        try:
            os.remove(LOCK)
        except OSError:
            pass
