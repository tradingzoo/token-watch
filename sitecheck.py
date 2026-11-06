"""Site check: scores Robinhood Chain tokens that have NO public GitHub, from their website alone.

Why (5 Nov 2026 study, rules in SCORING.md): winners like HOOKR and HARMONIC have no GitHub, but their
websites let developers and AI agents plug in directly (API keys, SDK, MCP, llms.txt). Of 19 tokens worth
$2M+, 32% had 3+ of those four; of 65 random losers with a website, 2% did.

A token is listed only if its site has 2+ of the four plug-in tools. Score /100, reasons as dot points.
Facts only for the 30-day test: never changes the test or its rule.
"""
import re
import html
import urllib.parse

LIST_AT = 2  # plug-in tools needed to be listed (study: 37% of winners, 9% of losers)
LIST_SCORE = 40  # ...or a site score this high: a strong finished product with fewer tools (UPOCH, SIC, 5 Nov).
                 # Test 5 Nov: listed 10 of 17 winners (was 8) and 11 of 64 losers (was 9). Wide net on purpose.
RECHECK_HOURS = 24  # tokens not listed yet: look again once a day while they are new
NEW_DAYS = 14  # ...for this many days after launch
MAX_NEW_PER_RUN = 40  # keep each run short

TOOLS = [
    ("API key", r"\bapi[ _-]?keys?\b|Authorization:\s*`?Bearer\b|\bholder'?s? (?:api )?keys?\b", "API keys for developers"),
    ("SDK", r"npm (?:i|install) [@\w]|pip install \w|\bSDK\b|npx [@\w]"
            r"|brew install \w|curl -[a-z]*s[a-z]* [^\n]*\|\s*(?:ba)?sh|winget install|irm [^\n]*\|\s*iex|cargo install \w|go install \w",
     "an SDK or install line"),  # terminal installs added 5 Nov (DARK, HARMONIC)
    ("MCP", r"\bMCP\b|mcp\.json", "an MCP connection for AI agents"),
]
# Points per tool (6 Nov, from the "Is the score working?" data, 3+ day old tokens, took off 41 vs died 15):
# API keys were MORE common among dead tokens (22% vs 47%) and MCP showed no difference (29% vs 33%), so they
# score 0 and 5; both still count toward the 2-tool listing rule. Listing contract addresses was the strongest sign
# (88% vs 47%): 5 -> 15 points. Address on site AND official X (32% vs 7%): +5. Tested: tokens at 61+ that took off
# 10 -> 18 of 41, that died 1 -> 1 of 15. Notes in SCORING.md.
TOOL_POINTS = {"API key": 0, "SDK": 10, "MCP": 5}
SITE_VERSION = 2  # scores made before this version are re-done first (at most 20 a run), so the change reaches every token in hours
OTHER = {
    "money": r"buy ?backs?|buy-backs?|\bburn(?:ed|s)?\b|\bstak(?:e|ing|ers)\b|revenue share|holders.{0,25}(?:share|earn|receive)",
    # takes real payments (5 Nov test: winners 41%, losers 5%; pricing pages alone didn't separate them)
    "pay": r"\b(?:pay|paid|pays) (?:by|with) (?:card|credit card)|\bcredit card\b|\bdebit card\b|\bstripe\b|apple pay"
           r"|\btop[- ]?ups?\b|\bbuy credits\b",
    # holding the token unlocks the product (UBIK, 5 Nov: "a wallet holding 200,000 UBIK" gets a key)
    "access": r"\b(?:holders? of|holding|hold) (?:at least |over )?\d[\d,.]*\s*(?:k|m|thousand|million)?\s*\$?[A-Za-z]{2,}"
              r"|\btoken[- ]gated\b|\bholder'?s? (?:api )?keys?\b|\bavailable (?:only )?to holders\b",
    "rh": r"stock tokens?|tokeni[sz]ed (?:stock|equit)|\bUSDG\b",
    "app": r"launch (?:the )?(?:app|console)|open (?:the )?app|connect wallet|\bdashboard\b",
    "audit": r"\baudit(?:ed)?\b",
    "agents": r"\bAI agents?\b|\bagents? (?:can|pay|that)\b|\byour agents?\b|\bfor agents\b|\bagent[- ]native\b",
    "winners": r"hookr\.fun|orbio\.so|raeto\.cc|priors\.trade|harmonicagent|whatthehook|fobo\.fun|deltaliquidity|ubik\.gold",
}
WINNER_NAMES = {"hookr.fun": "Hookr", "orbio.so": "Orbio", "raeto.cc": "Raeto", "priors.trade": "Priors",
                "harmonicagent": "Harmonic", "whatthehook": "WTH", "fobo.fun": "Fobo", "deltaliquidity": "Delta",
                "ubik.gold": "UBIK"}  # UBIK added 5 Nov ($23M peak, $6M now)
SOCIAL = re.compile(r"(?:^|\.)(?:x\.com|twitter\.com|t\.me|t\.co|github\.com|ponsfamily\.com|pons\.family|reddit\.com|youtube\.com|youtu\.be|"
                    r"instagram\.com|tiktok\.com|dexscreener\.com|gmgn\.ai|linktr\.ee|discord\.gg|discord\.com|medium\.com|"
                    # news, reference and big-company pages that memes use as their "website" (5 Nov test)
                    r"wikipedia\.org|bbc\.com|bbc\.co\.uk|sec\.gov|truthsocial\.com|linkedin\.com|facebook\.com|"
                    r"web\.archive\.org|urbandictionary\.com|globenewswire\.com|gofundme\.com|robinhood\.com|"
                    r"nvidia\.com|apple\.com|huggingface\.co)$")
# a token's own page on someone else's platform (Pons, pump.fun, otcdesks, an audit site...): not their website
_EVM = re.compile(r"0x[0-9a-fA-F]{40}")
_SOL = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{32,44}(?![A-Za-z0-9])")
_TOKEN_PATH = re.compile(r"/(?:coins?|tokens?|address|launchpad|pairs?|swap|trade)/", re.I)


def listing_page(url):
    """True if the link is a token page on another platform (5 Nov test: 86 of 921 links, no winner)."""
    path = urllib.parse.urlparse(url or "").path or ""
    return bool(_EVM.search(path) or _SOL.search(path)
                or (_TOKEN_PATH.search(path + "/") and len(path.strip("/").split("/")) >= 2))


# Past winners named in a project's own X posts (OSTRA, 5 Nov: "idle earnings go to work in ... Raeto vaults").
# Plain names only where the word isn't an everyday word; $TICKERs for all.
WINNER_WORDS = {"Raeto": r"\bRaeto\b", "Hookr": r"\bHookr\b", "Orbio": r"\bOrbio\b", "Fobo": r"\bFOBO\b|\bfobo\.fun",
                "UBIK": r"\bUBIK\b", "Priors": r"\$PRIORS\b|priors\.trade", "Harmonic": r"\$HARMONIC\b|harmonicagent",
                "WTH": r"\$WTH\b|whatthehook", "Delta": r"\$DELTA\b|deltaliquidity"}


def past_winners(tok, site_text, x_acct):
    """(names, found_on_x): past winners the project's site links, or its own recent X posts name. Never itself."""
    own = urllib.parse.urlparse(tok.get("website") or "").netloc.lower()
    me = {(tok.get("symbol") or "").upper(), (tok.get("name") or "").upper()}
    wins = {WINNER_NAMES[k] for k in WINNER_NAMES if k not in own and re.search(re.escape(k), site_text or "", re.I)}
    wins -= {n for n in wins if n.upper() in me}
    xt = " ".join((x_acct or {}).get("texts") or [])
    on_x = {n for n, rx in WINNER_WORDS.items() if n not in wins and n.upper() not in me and re.search(rx, xt, re.I)}
    return sorted(wins | on_x), bool(on_x)


def has_site(tok):
    u = tok.get("website") or ""
    if not u.startswith("http") or listing_page(u):
        return False
    host = urllib.parse.urlparse(u).netloc.lower().removeprefix("www.")
    return bool(host) and not SOCIAL.search(host)


def _real(w, url, probe):
    """Text of a page, or '' if it's missing or the site answers every address with the same page."""
    t = w.fetch(url, timeout=15, limit=1_500_000) or ""
    if len(t) < 300 or "<title>404" in t[:3000] or "Not Found" in t[:200]:
        return ""
    if probe and abs(len(t) - len(probe)) < 200:
        return ""
    return t


def score(tok, review, w):
    """w = the watch module (fetch, project_sources, official_x, copycat, token_mentions). Returns a scoring dict
    shaped like watch.score's, with kind='site' and repo=None, or None if the website doesn't load."""
    site = tok["website"]
    srcs = w.project_sources(tok)
    if not srcs or len(srcs[0][2]) < 500:
        return None
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(site))
    probe = w.fetch(base + "/zz-no-such-page-81", timeout=15, limit=1_500_000) or ""
    dev_pages = []
    t = _real(w, base + "/pricing", probe)  # read for payment signs only, not a developer page
    if t:
        srcs.append(("docs", base + "/pricing", t))
    for p in ("/developers", "/docs", "/build"):
        t = _real(w, base + p, probe)
        if t:
            dev_pages.append(base + p)
            srcs.append(("docs", base + p, t))
    # what a visitor or agent reads: the pages and docs, without script code (library code and news sites'
    # ad scripts mention "SDK" and "API key" too; tested 5 Nov: every winner keeps its tools without them)
    text = html.unescape(" ".join(re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", t)
                                  for where, u, t in srcs if where != "website code"))
    llms = [u for where, u, t in srcs if u.endswith((".txt",)) and "<html" not in t[:500].lower()]

    reasons = {"Plug-in tools": [], "Really theirs": [], "Money and Robinhood Chain": [], "Live product": []}
    flags, total = [], 0
    if tok.get("site_via_x"):
        reasons["Really theirs"].append(f"ℹ️ Pons lists no website: found {site} on their X @{tok['site_via_x']}, which posts the token's address")

    def add(group, pts, txt, mark=None):
        nonlocal total
        if group in w.INFO_GROUPS:  # shown, not scored (5 Nov test: Live product didn't separate winners from dead tokens)
            reasons[group].append(f"ℹ️ {txt}")
            return
        total += pts
        mark = mark or ("✅" if pts > 0 else "❌")
        reasons[group].append(f"{mark} {txt} (+{pts})")

    # --- Plug-in tools (40): the four the study found ---
    n_tools = 0
    for name, rx, words in TOOLS:
        # a tool counts only if not denied: "MCP... no API key" had scored API keys (MERY, 6 Nov)
        ok = any(not w.said_not(text, m.start()) for m in re.finditer(rx, text, re.I))
        n_tools += ok
        add("Plug-in tools", TOOL_POINTS[name] if ok else 0, ("Site offers " if ok else "No sign of ") + words)
    n_tools += bool(llms)
    add("Plug-in tools", 10 if llms else 0,
        f"Has docs written for AI to read ({urllib.parse.urlparse(llms[0]).path})" if llms else "No llms.txt (docs for AI to read)")
    doc_link = bool(re.search(r'href="[^"]*(?:/developers?\b|/docs\b|docs\.|gitbook)', text, re.I))
    add("Plug-in tools", 5 if (dev_pages or doc_link) else 0,
        ("Developer page: " + ", ".join(urllib.parse.urlparse(u).path for u in dev_pages)) if dev_pages
        else ("Links to developer docs" if doc_link else "No developer page or docs link"))

    # --- Really theirs (25) ---
    addr = tok["address"].lower()
    on_site = any(addr in t.lower() for where, u, t in srcs)
    ox = w.official_x(tok, srcs)
    where = [x for x, ok in (("website or docs", on_site), (f"official X @{ox['official']}", ox["posted"])) if ok]
    add("Really theirs", (20 if len(where) == 2 else 15) if where else 0,  # site AND official X: +5 (6 Nov study)
        ("Token's address is posted by their " + " and ".join(where)) if where
        else "Token's address isn't on their website, docs or official X")
    n_addr = len({a.lower() for a in re.findall(r"0x[0-9a-fA-F]{40}", text)})
    add("Really theirs", 15 if n_addr >= 2 else 0, f"Lists {n_addr} contract addresses" if n_addr >= 2 else "Lists fewer than 2 contract addresses",
        "✅" if n_addr >= 2 else "❌")
    wins, on_x = past_winners(tok, text, w.x_account(ox["official"]) if ox["official"] else None)
    if wins:  # a bonus only: not working with a past winner is never listed as a miss (user, 5 Nov)
        add("Really theirs", 5, "Works with past winners: " + ", ".join(wins) + (" (from their X posts)" if on_x else ""))
    cc = w.copycat(tok, ox)
    if cc:
        flags.append(f"{w.COPYCAT}: the project's X @{cc['handle']} posts a different address with the same "
                     f"{' and '.join(cc['same'])}: {cc['real']}. It never posts this one, so this is very likely someone copying the name and links")
    if ox["mismatch"]:
        if on_site:  # address on their own site: a copy can't do that (TRENCHERS, 5 Nov)
            reasons["Really theirs"].append("ℹ️ " + w.x_mismatch_note(ox, "website"))
        else:
            flags.append(f"{w.X_MISMATCH}: the token links @{ox['token']}, but its website links "
                         + ", ".join("@" + h for h in ox["site"]) + " — may be someone copying the project's links")

    # --- Money and Robinhood Chain (20) ---
    m = next((x for x in re.finditer(OTHER["money"], text, re.I) if not w.said_not(text, x.start())), None)  # not "no buyback"
    a = None if m else re.search(OTHER["access"], text, re.I)
    add("Money and Robinhood Chain", 10 if (m or a) else 0,
        f"Says money goes back to the token ({m.group(0).lower()}) — claimed, not checked on chain" if m
        else (f"Holding the token unlocks the product (“{a.group(0)}”) — claimed, not checked" if a
              else "No sign money goes back to the token, or that holding it unlocks anything"),
        "🟡" if (m or a) else "❌")
    m = re.search(OTHER["rh"], text, re.I)
    q = (tok.get("quote") or "").upper()
    rh_pair = bool(q) and q not in ("ETH", "WETH", "USDC", "USDT", "WBTC")  # USDG or a stock token (TSLA, NVDA, SPY...)
    add("Money and Robinhood Chain", 10 if (m or rh_pair) else 0,
        f"Built on Robinhood Chain's own assets ({m.group(0)})" if m
        else ((f"Trades against {q}, " + ("Robinhood Chain's own dollar" if q == "USDG" else "a Robinhood Chain stock token"))
              if rh_pair else "No use of stock tokens or USDG"))

    # --- Live product (15): a deep app (3+ sections, like SIC) counts double ---
    own_host = urllib.parse.urlparse(site).netloc.lower().removeprefix("www.")
    app_links = {h.split("?")[0].rstrip("/") for h in re.findall(r'href="([^"#]+)"', text)
                 if re.match(r"(?:https?://(?:app|console|dashboard)\.[^/]*)|/(?:app|dashboard|console)(?:/|$|\?)", h, re.I)
                 or re.match(r"https?://(?:www\.)?" + re.escape(own_host) + r"/(?:app|dashboard|console)(?:/|$|\?)", h, re.I)}
    app_word = re.search(OTHER["app"], text, re.I)
    if len(app_links) >= 3:
        add("Live product", 10, f"Has a working app with {len(app_links)} sections (" +
            ", ".join(sorted(urllib.parse.urlparse(u).path or u for u in app_links)[:5]) + ")")
    else:
        ok = bool(app_links or app_word)
        add("Live product", 5 if ok else 0,
            "Has a working app (app, dashboard, console or wallet connect)" if ok else "No app or wallet connect found")
    ag = bool(re.search(OTHER["agents"], text, re.I))
    xa = w.x_account(ox["official"]) if (not ag and ox["official"]) else None
    ag_x = bool(xa and re.search(OTHER["agents"], " ".join(xa.get("texts") or []), re.I))
    add("Live product", 5 if (ag or ag_x) else 0,
        "Made for AI agents to use" if ag else (f"Made for AI agents to use (says so on their X @{ox['official']})" if ag_x
                                                 else "Not aimed at AI agents"))
    au = w.says_audited(text)  # "not audited" / "unaudited" do not count (6 Nov)
    add("Live product", 5 if au else 0, "Mentions an audit — not checked" if au else "No audit mentioned", "🟡" if au else "❌")
    pay = re.search(OTHER["pay"], text, re.I)
    add("Money and Robinhood Chain", 5 if pay else 0, f"Takes real payments (“{pay.group(0)}”): a service with paying customers" if pay
        else "No sign it takes payments (card or credits)")

    for f in review.get("flags", []):
        flags.append(f + " (checked by hand)")
    # copycat -> 0. Address nowhere on their own pages -> capped at 60 (copies paste the real site's links;
    # 60 not lower because real winners like ORBIO and HARMONIC don't post their address either).
    final = min(total, 100)  # parts add up to 110, so a few points can be missed
    if cc:
        final = 0
        reasons["Really theirs"].insert(0, "⛔ Score set to 0: this token is a copy, the project's X posts a different address (see the warning above)")
    elif flags:
        final = min(total, 25)
    elif not where:
        final = min(total, 60)
        reasons["Really theirs"].insert(0, "🟡 Capped at 60: nothing on their own pages or recent X posts shows this token is theirs")
    return {"kind": "site", "v": SITE_VERSION, "repo": None, "score": final, "raw_score": total, "capped": final < total, "flags": flags,
            "reasons": reasons, "roadmap": review.get("roadmap", []), "notes": review.get("notes", []),
            "tools": n_tools, "listed": not cc and (n_tools >= LIST_AT or final >= LIST_SCORE), "copy_of": cc["real"] if cc else None,
            "token_mentioned": on_site, "sources_read": [u for where, u, t in srcs],
            "facts": {"tools": n_tools, "dev_pages": dev_pages, "contract_addresses": n_addr, "winners_linked": wins}}
