"""Phone alert when a token joins the Shortlist (5 Nov 2026).

Sends to Telegram, ntfy, or both, whichever is set up as a GitHub secret (the repo is public,
so the keys never go in the code):
  Telegram: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
  ntfy:     NTFY_TOPIC  (a long random topic name; install the ntfy app and subscribe to it)

Rules:
  - A token is announced the first time it joins the Shortlist.
  - If it drops off and comes back after 24h+ away, it's announced again as "back". Shorter dips
    (trades going just under 50 for a few hours) stay quiet, so the phone isn't spammed.
  - The very first run sends one summary of what's already on the list instead of one alert each.
  - Only runs on GitHub (the scan); a test run on the PC never sends or changes the record.
Record: data/shortlist_seen.json.
"""
import json, os, datetime, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "data", "shortlist_seen.json")
BACK_AFTER_H = 24
MAX_SINGLE = 5          # more newcomers than this in one run go in one combined message


def load():
    try:
        return json.load(open(FILE, encoding="utf-8"))
    except Exception:
        return {"seeded": False, "tokens": {}}


def _post(url, data, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def send(title, text, link=None, log=print):
    """Returns True if at least one channel took it."""
    ok = False
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            body = urllib.parse.urlencode({"chat_id": chat, "text": f"{title}\n\n{text}" + (f"\n\n{link}" if link else ""),
                                           "disable_web_page_preview": "true"}).encode()
            _post(f"https://api.telegram.org/bot{tok}/sendMessage", body)
            ok = True
        except Exception as ex:
            log(f"Alert: Telegram failed ({ex})")
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            h = {"Title": title.encode("ascii", "ignore").decode() or "Token Watch", "Tags": "green_circle"}
            if link:
                h["Click"] = link
            _post(f"https://ntfy.sh/{urllib.parse.quote(topic)}", text.encode("utf-8"), h)
            ok = True
        except Exception as ex:
            log(f"Alert: ntfy failed ({ex})")
    return ok


def _line(t, money):
    return (f"{t['symbol']} ({t['name']}) · score {t['score']} · {money(t['mcap'])}\n"
            f"Signs: {', '.join(t['signs'])}\n"
            f"CA: {t['address']}\n"
            f"https://dexscreener.com/robinhood/{t['address']}")


def update(live, now, money, site_url, log=print):
    """live: list of dicts (address, symbol, name, score, mcap, signs). Returns {address: joined_iso} for the badge."""
    db = load()
    toks = db.setdefault("tokens", {})
    on_gh = bool(os.environ.get("GITHUB_ACTIONS"))
    stamp = now.isoformat(timespec="seconds")
    new, back = [], []
    seeding = not db.get("seeded")  # already on the list when alerts started: no "joined" tag, no alert
    live_set = {t["address"].lower() for t in live}
    for t in live:
        a = t["address"].lower()
        rec = toks.get(a)
        if not rec:
            new.append(t)
            toks[a] = {"symbol": t["symbol"], "in": True, "joined": None if seeding else stamp, "first": stamp, "left": None}
        elif not rec.get("in"):
            away_h = (now - datetime.datetime.fromisoformat(rec["left"])).total_seconds() / 3600 if rec.get("left") else 999
            if away_h >= BACK_AFTER_H:
                back.append(t)
            rec.update({"in": True, "joined": stamp if away_h >= BACK_AFTER_H else rec.get("joined", stamp), "left": None})
    for a, rec in toks.items():
        if rec.get("in") and a not in live_set:
            rec.update({"in": False, "left": stamp})
    joined = {a: r.get("joined") for a, r in toks.items() if r.get("in")}
    if not on_gh:
        return joined  # PC test run: show only, never send or save
    if not db.get("seeded"):
        db["seeded"] = True
        if live:
            send(f"Token Watch: Shortlist is on ({len(live)} tokens)",
                 "Alerts are switched on. You'll get a message when a new token joins.\n\nOn the list now:\n"
                 + "\n".join(f"- {t['symbol']} · score {t['score']} · {money(t['mcap'])}" for t in live),
                 site_url + "#short", log)
    else:
        fresh = [("New on the Shortlist", t) for t in new] + [("Back on the Shortlist", t) for t in back]
        if len(fresh) > MAX_SINGLE:
            send(f"Token Watch: {len(fresh)} tokens joined the Shortlist",
                 "\n\n".join(f"{k}: " + _line(t, money) for k, t in fresh), site_url + "#short", log)
        else:
            for k, t in fresh:
                send(f"{k}: {t['symbol']}", _line(t, money), site_url + "#short", log)
        if fresh:
            log(f"Alert: {len(fresh)} Shortlist alert(s): " + ", ".join(t["symbol"] for _, t in fresh))
    json.dump(db, open(FILE, "w", encoding="utf-8"), indent=1)
    return joined
