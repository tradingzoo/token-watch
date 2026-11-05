"""GitHub watch for new Robinhood Chain tokens.

Runs every 7 minutes (Windows Task Scheduler: "robinhood-scan github watch").
Each run:
  1. lists new tokens on Pons (newest) and DexScreener (Robinhood Chain profiles and boosts)
  2. looks for a public GitHub link: in the token's description and links, then on its website
  3. scores every token that has one (rules: SCORING.md) and writes the reasons
  4. rebuilds site/index.html (open it in a browser)

Hand-checked findings go in reviews.json and replace the script's guesses.
"""
import json, os, re, subprocess, shutil, sys, time, datetime, html, urllib.request, urllib.parse
from collections import Counter
import x_info, deployers, test_tokens, prices, shipping, sitecheck

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "data", "watch_state.json")
SITE = os.path.join(HERE, "site", "index.html")
REVIEWS = os.path.join(HERE, "reviews.json")
LOG = os.path.join(HERE, "last_watch.txt")
UA = "Mozilla/5.0 (robinhood-scan research script)"
NOW = datetime.datetime.now(datetime.timezone.utc)
RESCORE_HOURS = 6
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
    out = [t for t in got.values() if t]
    plain |= {a for a, t in got.items() if t and not (t.get("website") or x_info.parse(t.get("twitter"))[0])}
    state["catchup_plain"] = sorted(plain & set(todo))
    gone = {a for a, t in got.items() if not t}  # no Pons page: nothing to check
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


def market(addr):
    """Symbol, market cap and where it trades now."""
    pairs = fetch_json(f"https://api.dexscreener.com/tokens/v1/robinhood/{addr}")
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


PRIVATE_CAP = 40  # public code is weighed more: a private GitHub can't score above this


def score_private(tok, full, owner, user, found_on, symbol_counts, review, reasons, flags, add, total):
    """GitHub account is real but shows no code (private repos, or the linked repo is private/deleted).
    Score only what can be checked without the code; Real code = 0; capped at PRIVATE_CAP."""
    rname = full.split("/")[1]
    if not user.get("login"):
        flags.append(f"GitHub link is dead: github.com/{owner} doesn't exist")
        return {"repo": full, "score": 0, "capped": True, "flags": flags, "private": True,
                "reasons": {"Really theirs": [f"❌ github.com/{owner} doesn't exist"]}, "roadmap": [], "facts": {}}
    what = (f"the linked repo {full} is private or deleted" if rname else f"github.com/{owner} has no public repos")
    reasons["Really theirs"].append(f"🔒 Private GitHub: {what}. Code can't be checked, so the score is capped at {PRIVATE_CAP}")
    srcs = project_sources(tok)
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
        hits = sorted({w.strip() for w in BACK_WORDS if w in text})
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
    final = 0 if not_theirs else min(t, 25 if flags else PRIVATE_CAP)
    if t > PRIVATE_CAP and not flags:
        reasons["Really theirs"].append(f"ℹ️ Points add up to {t}, capped at {PRIVATE_CAP} because the code is private")
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
        try:
            db = json.load(open(x_info.FILE, encoding="utf-8")) if os.path.exists(x_info.FILE) else {}
            rec = (db.get("accounts") or {}).get(k)
            X_CACHE[k] = rec if x_info._fresh(rec, NOW) else x_info._lookup(handle, fetch_json, NOW)
        except Exception:
            X_CACHE[k] = None
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


COPYCAT = "Copycat token"
UNCLAIMED = "Dev never mentions this token"


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
        hits = sorted({w.strip() for w in BACK_WORDS if w in text})
        if hits:
            add("Platform", 10, f"Says fees go back to the token ({', '.join(hits[:3])}) — claimed, not checked on chain", "🟡")
        else:
            add("Platform", 0, "No sign fees go back to the token")

    # --- Really theirs (20) ---
    addr = tok["address"].lower()
    in_repo = addr in repo_text
    if not in_repo and n_commits:
        sc = gh(f"search/code?q={addr}+repo:{full}")
        in_repo = bool(sc and sc.get("total_count"))
    ox = official_x(tok, srcs)
    in_site = any(addr in t.lower() for w, u, t in srcs)
    where = [w for w, ok in (("repo", in_repo), ("website", in_site),
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
    final = 0 if not_theirs else (min(total, 25) if capped else total)
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


def build_site(state, xdb=None, wallets=None, test_html="", all_rows=None, pdb=None, ship=None):
    pdb = pdb or {}
    rows = sorted(state["github"].values(), key=lambda r: r.get("launched") or r["first_seen"], reverse=True)  # newest launch first
    # newest project first: by launch time (when found, if the launch time isn't known)
    site_rows = sorted(state.get("sites", {}).values(), key=lambda r: r.get("launched") or r["first_seen"], reverse=True)
    xdb, wallets = xdb or {}, wallets or {}
    all_rows = all_rows or rows  # every token on the page, for the same-X checks
    e = html.escape
    def md(s):  # `code` only
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", e(s))
    cards, site_cards = [], []
    for r in rows + site_rows:
        sc = r["scoring"]
        is_site = sc.get("kind") == "site"
        new = days_between(NOW, iso(r["first_seen"])) < 1
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
                groups.append(f"<h4>{e(g)}</h4><ul>" + "".join(f"<li>{md(i)}</li>" for i in items) + "</ul>")
        xline, xwarn = x_info.facts(r, all_rows, xdb, NOW)
        wline, wwarn = deployers.facts(r, wallets)
        xline = shipping.line(r, ship) + xline + wline + prices.card_line(r["address"].lower(), pdb)
        flags = "".join(f"<div class='flag'>⚠️ {e(f)}</div>" for f in sc.get("flags", []) + xwarn + wwarn)
        notes = ("<h4>Checked by hand</h4><ul>" + "".join(f"<li>{md(n)}</li>" for n in sc.get("notes", [])) + "</ul>") if sc.get("notes") else ""
        road = "<h4>Roadmap</h4><ul>" + "".join(f"<li>{md(x)}</li>" for x in sc.get("roadmap", [])) + "</ul>"
        band = "hi" if sc["score"] >= 60 else ("mid" if sc["score"] >= 40 else "lo")
        if is_site:
            f = sc.get("facts", {})
            meta = (f"Site check · {sc.get('tools', 0)} of 4 plug-in tools · {f.get('contract_addresses', 0)} contract addresses"
                    f" · scored {r['scored_at'][:16].replace('T', ' ')} UTC")
            meta_html = f"<p class=\"meta\">{e(meta)}</p>"
        else:
            meta_html = (f"""<p class="meta"><button class="wrong" data-msg="{e('Wrong repo? ' + (r.get('symbol') or '') + ' ' + r['address'] + ' was matched to github.com/' + sc['repo'] + '. The right one is: ')}">Wrong repo?</button> Repo {e(sc['repo'])} · {sc['facts'].get('commits','?')} changes · created {e(sc['facts'].get('created','?'))} · last update {e(sc['facts'].get('pushed','?'))} · scored {e(r['scored_at'][:16].replace('T',' '))} UTC</p>""")
        (site_cards if is_site else cards).append(f"""
<article class="card" data-score="{sc['score']}" data-new="{int(new)}">
  <header>
    <div class="score {band}">{sc['score']}<small>/100</small></div>
    <div class="title">
      <h2>{e(r.get('symbol') or '?')} {"<span class='new'>NEW</span>" if new else ""}{" <span class='grp'>🔒 private GitHub</span>" if sc.get('private') else ""}</h2>
      <p class="sub">{e(r.get('name') or '')} · {('launched ' + e(r['launched'][:16].replace('T',' ')) + ' UTC · ') if r.get('launched') else ''}found {e(r['first_seen'][:16].replace('T',' '))} UTC · {e(money(r.get('mcap')))} · {e(r.get('where') or '')}</p>
      <p class="links">{" · ".join(f'<a href="{e(u)}" target="_blank" rel="noopener">{e(t)}</a>' for u, t in links)}</p>
    </div>
  </header>
  {xline}
  {flags}
  <p class="desc">{e((r.get('description') or '')[:260])}</p>
  <details{" open" if new else ""}><summary>Why this score</summary>{''.join(groups)}{notes}{road}
  {meta_html}</details>
</article>""")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="420"><title>Token Watch</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e4e4df;--hi:#1f7a4d;--mid:#a86b00;--lo:#b3372f;--flag:#fdecea;--accent:#2f5bd3}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#151614;--card:#1e1f1c;--ink:#ecebe6;--mute:#9c9b94;--line:#33342f;--hi:#4cc38a;--mid:#e0a63a;--lo:#ef7a6f;--flag:#3a2220;--accent:#8aa8ff}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:860px;margin:0 auto;padding:20px 16px 60px}}
h1{{font-size:22px;margin:0 0 4px}} .top{{color:var(--mute);margin:0 0 16px}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}} .bar button{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:6px 12px;cursor:pointer}}
.bar button.on{{border-color:var(--accent);color:var(--accent)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}}
.card header{{display:flex;gap:14px;align-items:flex-start}}
.score{{font-size:30px;font-weight:700;min-width:78px;text-align:center;border-radius:10px;padding:6px 4px;border:2px solid}}
.score small{{font-size:13px;font-weight:400;color:var(--mute)}} .hi{{color:var(--hi)}} .mid{{color:var(--mid)}} .lo{{color:var(--lo)}}
h2{{margin:0;font-size:19px}} .sub,.meta{{color:var(--mute);margin:2px 0;font-size:13px}} .links{{margin:4px 0 0;font-size:13px}}
a{{color:var(--accent)}} .new{{font-size:11px;background:var(--accent);color:var(--card);border-radius:5px;padding:1px 6px;vertical-align:middle}}
.flag{{background:var(--flag);border-radius:8px;padding:6px 10px;margin:10px 0 0;font-size:14px}}
.desc{{margin:10px 0 6px}} summary{{cursor:pointer;color:var(--accent)}} h4{{margin:12px 0 2px;font-size:14px}}
.xline{{margin:8px 0 0;font-size:13px;color:var(--mute)}} .ship{{color:var(--ink)}}
.test h2{{margin:0 0 4px}} table.sum{{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0;display:block;overflow-x:auto}}
.sum th,.sum td{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}} .sum th{{color:var(--mute);font-weight:500}}
.trow{{border-top:1px solid var(--line);padding:8px 0}} .trow summary{{color:var(--ink);font-size:14px}} .trow summary b{{margin-right:4px}}
.kv{{color:var(--mute);font-size:13px;margin-left:8px;white-space:nowrap}} .kv.warn{{color:var(--lo)}}
.grp{{font-size:11px;border:1px solid var(--line);border-radius:5px;padding:0 5px;color:var(--mute)}} .grp.watch{{color:var(--accent);border-color:var(--accent)}} .grp.benchmark{{color:var(--hi);border-color:var(--hi)}}
.tabs{{position:sticky;top:0;z-index:5;display:flex;gap:6px;overflow-x:auto;background:var(--bg);padding:8px 0;margin:6px 0 4px;border-bottom:1px solid var(--line)}}
.tabs a{{flex:none;text-decoration:none;color:var(--ink);border:1px solid var(--line);background:var(--card);border-radius:8px;padding:6px 12px;font-size:14px;white-space:nowrap}}
.tabs a.on{{border-color:var(--accent);color:var(--accent);font-weight:600}} .cnt{{font-size:12px;color:var(--mute)}}
ul{{margin:0;padding-left:20px}} button.wrong{{font-size:12px;border:1px solid var(--line);background:none;color:var(--mute);border-radius:6px;padding:1px 8px;cursor:pointer;margin-right:6px}} li{{margin:2px 0}} code{{font-size:13px}}
</style></head><body><main>
<h1>Token Watch</h1>
<nav class="tabs" id="tabs">
<a href="#github" data-tab="github">GitHub <span class="cnt">{len(rows)}</span></a>
<a href="#sites" data-tab="sites">Site check <span class="cnt">{len(site_rows)}</span></a>
<a href="#test" data-tab="test">30-day test</a>
<a href="#status" data-tab="status">Status changes</a>
<a href="#scores" data-tab="scores">Was the score right?</a>
</nav>
<p class="top">New Robinhood Chain tokens (Pons + DexScreener). Checked about every 15 minutes. Last run {NOW:%Y-%m-%d %H:%M} UTC · {len(rows)} GitHub tokens · {len(site_rows)} site-check tokens · {state.get('checked_total',0)} tokens checked in all. Scoring rules: SCORING.md. 🟡 = partial, guessed or not switched on yet.</p>
<section class="tab" id="sites">
<h2 style="margin:22px 0 6px">Site check: tokens whose website lets developers and AI agents plug in</h2>
<p class="top">No GitHub needed. Listed when their own website has at least {sitecheck.LIST_AT} of API key, SDK, MCP and llms.txt.
Why: on 5 Nov, 32% of tokens worth $2M+ had 3 or more of these, against 2% of random tokens that went nowhere. Rules: SCORING.md.
Prices are tracked so we can see whether this works.</p>
{''.join(site_cards) if site_cards else '<p>No tokens have passed the site check yet.</p>'}
</section>
<section class="tab" id="status">{shipping.alerts_html(ship, NOW) if ship else '<p>No status data yet.</p>'}</section>
<section class="tab" id="test">{test_html or '<p>The 30-day test section is refreshed about twice a day.</p>'}</section>
<section class="tab" id="scores">{prices.section(pdb, e)}</section>
<section class="tab" id="github">
<h2 style="margin:22px 0 10px">New tokens with a public GitHub</h2>
<div class="bar"><button class="on" data-f="all">All</button><button data-f="new">New (24h)</button><button data-f="60">60+</button><button data-f="flag">Red flags</button></div>
{''.join(cards) if cards else '<p>No tokens with a public GitHub yet.</p>'}
{skipped_html(state)}
</section>
</main><script>
(()=>{{const tabs=[...document.querySelectorAll('section.tab')],links=[...document.querySelectorAll('#tabs a')];
const show=()=>{{let id=(location.hash||'#github').slice(1);if(!tabs.some(t=>t.id===id))id='github';
tabs.forEach(t=>t.hidden=t.id!==id);links.forEach(a=>a.classList.toggle('on',a.dataset.tab===id));}};
window.addEventListener('hashchange',()=>{{show();window.scrollTo(0,0);}});show();}})();
document.querySelectorAll('button.wrong').forEach(b=>b.onclick=()=>{{const m=b.dataset.msg;
const done=()=>{{b.textContent='Copied: paste it to Claude and add the right repo';}};
if(navigator.clipboard)navigator.clipboard.writeText(m).then(done,()=>prompt('Copy this and paste it to Claude:',m));else prompt('Copy this and paste it to Claude:',m);}});
document.querySelectorAll('.bar button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.bar button').forEach(x=>x.classList.toggle('on',x===b));
const f=b.dataset.f;document.querySelectorAll('#github article.card').forEach(c=>{{const s=+c.dataset.score,n=c.dataset.new==='1',fl=!!c.querySelector('.flag');
c.style.display=(f==='all'||(f==='new'&&n)||(f==='60'&&s>=60)||(f==='flag'&&fl))?'':'none'}})}});
{LOCAL_TIME_JS}
</script></body></html>"""
    os.makedirs(os.path.dirname(SITE), exist_ok=True)
    open(SITE, "w", encoding="utf-8").write(page)


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
            if days_between(NOW, iso(g["scored_at"])) * 24 >= RESCORE_HOURS:
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
    new = [x for x in todo if x[0] not in sites][:sitecheck.MAX_NEW_PER_RUN]
    todo = [x for x in todo if x[0] in sites] + new
    n_listed = 0
    for key, t in todo:
        looked[key] = NOW.isoformat(timespec="seconds")
        mk = market(t["address"])
        t2 = {**t, **{k: v for k, v in mk.items() if v and (k not in ("symbol", "launched") or not t.get(k))}}
        if not sitecheck.has_site(t2):
            t2 = site_from_x(t2)
            if not t2:
                continue
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
        toks.setdefault(t["address"].lower(), t)
    for t in catchup(state):  # older launches from the one-time sweep, a few a run
        toks.setdefault(t["address"].lower(), t)
    fix_launch_dates(state)

    queue = list(toks.items())
    while queue:
        key, t = queue.pop(0)
        g = state["github"].get(key)
        if key in state["seen"] and not g:
            continue  # already checked, no GitHub
        if g and days_between(NOW, iso(g["scored_at"])) * 24 < RESCORE_HOURS:
            continue
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
    try:
        xdb = x_info.update(allrows, fetch_json, NOW, log, fetch=fetch, gh_user=lambda o: gh(f"users/{o}"))
    except Exception as ex:
        log(f"X: skipped ({ex})")
        xdb = json.load(open(x_info.FILE, encoding="utf-8")) if os.path.exists(x_info.FILE) else {}
    try:
        wallets = deployers.update(allrows, market, log)
    except Exception as ex:
        log(f"Wallets: skipped ({ex})")
        wallets = json.load(open(deployers.FILE, encoding="utf-8")) if os.path.exists(deployers.FILE) else {}
    try:
        ship = shipping.update(allrows, fetch, fetch_json, xdb, GH, NOW, log)
    except Exception as ex:
        log(f"Shipping: skipped ({ex})")
        ship = json.load(open(shipping.FILE, encoding="utf-8")) if os.path.exists(shipping.FILE) else None
    try:
        test_html = test_tokens.section(trows, xdb, wallets, NOW, allrows, ship=ship) if trows else ""
    except Exception as ex:
        log(f"Test section: skipped ({ex})")
        test_html = ""
    try:
        pdb = prices.update(state, fetch_json, market, NOW, log)
    except Exception as ex:
        log(f"Prices: skipped ({ex})")
        pdb = json.load(open(prices.FILE, encoding="utf-8")) if os.path.exists(prices.FILE) else {}
    build_site(state, xdb, wallets, test_html, allrows, pdb, ship)
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
