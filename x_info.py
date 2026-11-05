"""Free X (Twitter) facts for each token on the site. No login, no key.

Sources:
  fxtwitter (api.fxtwitter.com): joined date, fixed account ID, followers, posts, last ~20 posts
  memory.lol: past usernames, where it has a record (patchy, mostly older accounts)

Called by watch.py. Each account is refreshed at most every REFRESH_HOURS.
Saved in data/x_info.json. Never changes a score: it adds facts and warning flags only.
"""
import json, os, re, time, datetime, html

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "data", "x_info.json")
REFRESH_HOURS = 12
NOT_HANDLES = {"i", "intent", "home", "search", "hashtag", "share", "explore"}


def parse(url):
    """(handle, is_post_link) from an x.com / twitter.com link, or (None, False)."""
    m = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(/status/\d+)?", url or "")
    if not m or m.group(1).lower() in NOT_HANDLES:
        return None, False
    return m.group(1), bool(m.group(2))


def _dt(s):
    try:
        return datetime.datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
    except Exception:
        return None


def _lookup(handle, fetch_json, now):
    u = fetch_json(f"https://api.fxtwitter.com/{handle}")
    if not u or u.get("code") != 200 or not u.get("user"):
        return {"handle": handle, "found": False, "checked": now.isoformat(timespec="seconds")}
    u = u["user"]
    joined = _dt(u.get("joined") or "")
    st = fetch_json(f"https://api.fxtwitter.com/2/profile/{handle}/statuses") or {}
    own = [t for t in st.get("results") or [] if (t.get("author") or {}).get("id") == u.get("id")]
    times = sorted((d for d in (_dt(t.get("created_at") or "") for t in own) if d), reverse=True)
    week = now - datetime.timedelta(days=7)
    n = len(own)
    return {
        "handle": u.get("screen_name") or handle, "found": True, "id": u.get("id"), "name": u.get("name"),
        "joined": joined.isoformat() if joined else None, "followers": u.get("followers"),
        "following": u.get("following"), "posts": u.get("tweets"),
        "verified": (u.get("verification") or {}).get("type") if (u.get("verification") or {}).get("verified") else None,
        "last_post": times[0].isoformat() if times else None,
        "sample": n, "sample_full_week": bool(times) and times[-1] >= week and n >= 15,
        "posts_7d": sum(1 for d in times if d >= week),
        "avg_likes": round(sum(t.get("likes") or 0 for t in own) / n, 1) if n else None,
        "avg_views": round(sum(t.get("views") or 0 for t in own) / n) if n else None,
        "bio_site": (u.get("website") or {}).get("url"), "bio": u.get("description") or "",
        # token addresses the account itself posted (bio + recent posts), and any "fake contract" warning
        "cas": sorted({m.lower() for s in [u.get("description") or ""] + [t.get("text") or "" for t in own]
                       for m in re.findall(r"(?<![0-9a-fA-F])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])", s)}),  # not tx hashes
        "fake_posts": [re.sub(r"\s+", " ", t.get("text") or "")[:200] + " (" + (t.get("created_at") or "")[4:16] + " UTC)"
                       for t in own if re.search(r"\b(fake|scam|impersonat\w*)\b", t.get("text") or "", re.I)
                       and re.search(r"\b(CA|contract|token|address|launched)\b", t.get("text") or "", re.I)][:3],
        "checked": now.isoformat(timespec="seconds"),
    }


def telegram_name(r, a):
    """Telegram group name from the token's links or the X bio."""
    for s in [r.get("telegram") or ""] + list(r.get("links") or []) + [(a or {}).get("bio") or ""]:
        m = re.search(r"t\.me/([A-Za-z0-9_]{4,32})\b", s)
        if m and m.group(1).lower() not in ("joinchat", "share", "addlist", "s"):
            return m.group(1)
    return None


def _telegram(name, fetch):
    """Member count from the public t.me page, or None."""
    s = fetch(f"https://t.me/{name}") or ""
    m = re.search(r'tgme_page_extra">([^<]+)<', s)
    if not m:
        return {"found": False}
    txt = m.group(1).replace("\xa0", " ")
    n = re.search(r"([\d ,]+)\s+(members|subscribers)", txt)
    on = re.search(r"([\d ,]+)\s+online", txt)
    num = lambda g: int(re.sub(r"\D", "", g)) if g else None
    return {"found": True, "members": num(n.group(1)) if n else None, "kind": n.group(2) if n else None,
            "online": num(on.group(1)) if on else None}


def domain(u):
    m = re.search(r"https?://(?:www\.)?([^/?#]+)", (u or "").strip(), re.I)
    return m.group(1).lower() if m else ""


def _past_names(handle, fetch_json):
    d = fetch_json(f"https://api.memory.lol/v1/tw/{handle}")
    if d is None:
        return None  # service did not answer: try again next time
    names = set()
    for a in d.get("accounts") or []:
        names.update((a.get("screen-names") or a.get("screen_names") or {}).keys())
    return sorted(n for n in names if n.lower() != handle.lower())


def _fresh(rec, now):
    return rec and (now - datetime.datetime.fromisoformat(rec["checked"])).total_seconds() < REFRESH_HOURS * 3600


def update(rows, fetch_json, now, log=print, fetch=None, gh_user=None):
    """rows: token records (need 'address', 'twitter'; optional 'telegram', 'links', 'scoring.repo').
    fetch(url) -> text, for Telegram pages. gh_user(owner) -> GitHub profile dict, for link-back.
    Returns the saved x_info dict."""
    db = json.load(open(FILE, encoding="utf-8")) if os.path.exists(FILE) else {}
    db.setdefault("accounts", {})   # handle (lower) -> latest facts
    db.setdefault("ids", {})        # fixed account ID -> [handles seen, oldest first]
    db.setdefault("past", {})       # handle (lower) -> past names from memory.lol
    db.setdefault("history", {})    # handle (lower) -> {date: [followers, posts]}
    db.setdefault("telegram", {})   # group name (lower) -> latest facts
    db.setdefault("tg_history", {}) # group name (lower) -> {date: members}
    db.setdefault("gh", {})         # GitHub owner (lower) -> {'twitter', 'blog', 'checked'}
    today = now.strftime("%Y-%m-%d")
    for r in rows:
        if fetch:
            h0, _ = parse(r.get("twitter"))
            tg = telegram_name(r, db["accounts"].get((h0 or "").lower()))
            if tg and not _fresh(db["telegram"].get(tg.lower()), now):
                try:
                    t = _telegram(tg, fetch)
                    db["telegram"][tg.lower()] = {**t, "name": tg, "checked": now.isoformat(timespec="seconds")}
                    if t.get("members") is not None:
                        db["tg_history"].setdefault(tg.lower(), {})[today] = t["members"]
                except Exception as ex:
                    log(f"  Telegram {tg}: failed ({ex})")
        owner = ((r.get("scoring") or {}).get("repo") or "").split("/")[0]
        if gh_user and owner and not _fresh(db["gh"].get(owner.lower()), now):
            try:
                u = gh_user(owner) or {}
                db["gh"][owner.lower()] = {"twitter": u.get("twitter_username"), "blog": u.get("blog"),
                                           "checked": now.isoformat(timespec="seconds")}
            except Exception:
                pass
    done = 0
    for r in rows:
        h, _ = parse(r.get("twitter"))
        if not h:
            continue
        key = h.lower()
        old = db["accounts"].get(key)
        if _fresh(old, now) and "cas" in old:
            continue
        try:
            info = _lookup(h, fetch_json, now)
        except Exception as ex:
            log(f"  X {h}: lookup failed ({ex})")
            continue
        if not info["found"] and old and old.get("found"):
            info = {**old, "found": False, "checked": info["checked"], "gone_since": old.get("gone_since") or info["checked"]}
        if old:  # keep every address and warning ever seen: posts scroll out of the last-20 window
            info["cas"] = sorted(set(info.get("cas") or []) | set(old.get("cas") or []))
            info["fake_posts"] = list(dict.fromkeys((info.get("fake_posts") or []) + (old.get("fake_posts") or [])))[:5]
        db["accounts"][key] = info
        if info["found"] and info.get("followers") is not None:
            db["history"].setdefault(key, {})[today] = [info["followers"], info.get("posts")]
        if info.get("id") and info["found"]:
            seen = db["ids"].setdefault(info["id"], [])
            if info["handle"] not in seen:
                seen.append(info["handle"])
        if key not in db["past"]:
            p = _past_names(h, fetch_json)
            if p is not None:
                db["past"][key] = p
        done += 1
        time.sleep(1)  # be polite to the free service
    if done:
        log(f"X: refreshed {done} accounts")
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    with open(FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(db, f, indent=1)
    os.replace(FILE + ".tmp", FILE)
    return db


def _ago(iso_s, now):
    d = datetime.datetime.fromisoformat(iso_s)
    days = (now - d).days
    return d.strftime("%d %b %Y").lstrip("0"), days


def facts(r, rows, db, now):
    """(fact_line_html, [warning texts]) for one token's card."""
    e = html.escape
    h, is_post = parse(r.get("twitter"))
    if not r.get("twitter"):
        return "<p class='xline'>𝕏 No X account listed.</p>", []
    if not h:
        return "", []
    warn = []
    if is_post:
        warn.append(f"X link goes to a single post by @{h}, not a project account")
    # another token on the list uses the same or a near-identical X account
    norm = lambda s: re.sub(r"[_\d]+$", "", s.lower()).replace("_", "")
    likely_copy = False
    accts = db.get("accounts", {})
    a = accts.get(h.lower())
    done = set()
    for o in rows:
        oh, _ = parse(o.get("twitter"))
        if not oh or o["address"].lower() == r["address"].lower() or not o.get("symbol") or (oh.lower(), o["address"]) in done:
            continue
        done.add((oh.lower(), o["address"]))
        if oh.lower() == h.lower():
            warn.append(f"Same X account as another token on this list ({o['symbol']})")
        elif norm(oh) == norm(h):
            oa = accts.get(oh.lower()) or {}
            older = a and oa.get("joined") and a.get("joined") and oa["joined"] < a["joined"]
            bigger = a and (oa.get("followers") or 0) > 10 * max(a.get("followers") or 0, 1)
            if older or bigger:
                likely_copy = True
                warn.append(f"Likely a copycat: @{oh} has a near-identical name and is "
                            + " and ".join(x for x, y in (("older", older), (f"much bigger ({oa.get('followers', 0):,} followers)", bigger)) if y))
                for p in oa.get("fake_posts") or []:
                    warn.append(f"@{oh} warns about fakes: “{p}”")
            else:
                warn.append(f"Near-identical X name to another token ({o['symbol']}: @{oh}), possible copycat")
    if not a:
        return "<p class='xline'>𝕏 Not checked yet.</p>", warn
    if not a["found"]:
        warn.append("X account not found now (deleted, suspended or renamed)")
        if not a.get("id"):
            return "", warn
    # is this the project's official token? only an address the account posted itself counts
    cas = a.get("cas") or []
    official = r["address"].lower() in cas
    import deployers  # only flag other addresses that are known Pons tokens (not app contracts)
    others = [c for c in cas if c != r["address"].lower() and c in deployers.KNOWN]
    other_ca = (not official and others and not is_post)
    if not official:
        for p in a.get("fake_posts") or []:
            warn.append("Its X account warns about fakes: “" + p + "”")
    names = db.get("ids", {}).get(a.get("id") or "", [])
    if len(names) > 1:
        warn.append("X account changed its name while we watched: " + " → ".join("@" + n for n in names))
    past = db.get("past", {}).get(h.lower()) or []
    if past:
        warn.append("X account used other names before: " + ", ".join("@" + p for p in past))
    bits = []
    if official:
        bits.append("🟡 this X posted the token's address, but the X itself looks like a copy" if likely_copy
                    else "✓ this X posted the token's address")
    if other_ca:
        bits.append(f"🟡 this X posted a different Pons token's address ({others[0][:8]}…{others[0][-4:]}), not this one: check which is theirs")
    if a.get("joined"):
        d, days = _ago(a["joined"], now)
        age = f"joined {d} ({days} days ago)"
        if r.get("launched"):
            gap = (datetime.datetime.fromisoformat(r["launched"]) - datetime.datetime.fromisoformat(a["joined"])).days
            age += f", {gap} days before the token" if gap >= 0 else f", {-gap} days after the token"
        bits.append(age)
    if a.get("followers") is not None:
        bits.append(f"{a['followers']:,} followers")
    if a.get("posts") is not None:
        bits.append(f"{a['posts']:,} posts")
    if a.get("last_post"):
        d, days = _ago(a["last_post"], now)
        bits.append("last post today" if days == 0 else f"last post {d}")
        if days >= 14:
            warn.append(f"No X posts in {days} days")
        wk = a.get("posts_7d") or 0
        bits.append(f"{wk}{'+' if a.get('sample_full_week') else ''} posts in last 7 days")
    elif a.get("found"):
        bits.append("no recent posts")
    if a.get("avg_likes") is not None:
        bits.append(f"about {a['avg_likes']:g} likes and {a['avg_views']:,} views per post")
        f = a.get("followers") or 0
        if f >= 2000 and a["avg_likes"] < f * 0.002:
            bits.append("🟡 few likes for its follower count (could be bought followers)")
    if a.get("verified"):
        bits.append(f"verified ({a['verified']})")
    if past == [] and h.lower() in db.get("past", {}):
        bits.append("no past names on record (memory.lol, patchy)")
    g = growth(db.get("history", {}).get(h.lower()), now)
    if g:
        bits.append(g)
    link = f'<a href="https://x.com/{e(a.get("handle") or h)}" target="_blank" rel="noopener">@{e(a.get("handle") or h)}</a>'
    lines = [f"<p class='xline'>𝕏 {link}: " + e(" · ".join(bits)) + "</p>"]
    # do the links point at each other?
    match = []
    tsite, bsite = domain(r.get("website")), domain(a.get("bio_site"))
    if tsite and bsite:
        if tsite == bsite or tsite.endswith("." + bsite) or bsite.endswith("." + tsite):
            match.append("X bio links to the token's website ✓")
        else:
            match.append(f"🟡 X bio links to {bsite}, token lists {tsite}")
    owner = ((r.get("scoring") or {}).get("repo") or "").split("/")[0]
    gh = db.get("gh", {}).get(owner.lower()) if owner else None
    if gh:
        if gh.get("twitter"):
            if gh["twitter"].lower() == (a.get("handle") or h).lower():
                match.append("GitHub profile links back to this X ✓")
            else:
                match.append(f"🟡 GitHub profile names a different X (@{gh['twitter']})")
        elif domain(gh.get("blog")) and tsite and domain(gh.get("blog")) == tsite:
            match.append("GitHub profile links to the token's website ✓")
    tg = telegram_name(r, a)
    t = db.get("telegram", {}).get((tg or "").lower())
    if t and t.get("found") and t.get("members") is not None:
        s = f"Telegram {t['members']:,} {t.get('kind') or 'members'}" + (f", {t['online']:,} online" if t.get("online") is not None else "")
        tgr = growth({d: [v, None] for d, v in db.get("tg_history", {}).get(tg.lower(), {}).items()}, now, "members")
        match.append(s + (f" ({tgr})" if tgr else ""))
    elif t and not t.get("found"):
        match.append(f"🟡 Telegram link t.me/{tg} shows no group")
    if match:
        lines.append("<p class='xline'>🔗 " + e(" · ".join(match)) + "</p>")
    return "".join(lines), warn


def growth(hist, now, what="followers"):
    """'+N followers in D days' from a {date: [count, ...]} history, using the oldest day within 7 days."""
    if not hist or len(hist) < 2:
        return ""
    days = sorted(hist)
    last = days[-1]
    week = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    base = next((d for d in days if d >= week), days[0])
    if base == last:
        base = days[-2]
    a, b = hist[base][0], hist[last][0]
    if a is None or b is None:
        return ""
    n = (datetime.date.fromisoformat(last) - datetime.date.fromisoformat(base)).days
    return f"{b - a:+,} {what} in {n} day{'s' if n != 1 else ''}"
