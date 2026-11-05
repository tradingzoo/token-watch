# Robinhood Chain token watch

Live page: https://tradingzoo.github.io/token-watch/ · Not financial advice.

Two things live here:

1. **GitHub watch** (every 15 minutes, on GitHub's servers, no PC needed): new tokens on Pons and DexScreener that link a public GitHub, each scored out of 100 with the reasons as dot points. Rules: [SCORING.md](SCORING.md). Hand-checked results: `reviews.json`. Script: `watch.py`, run by `.github/workflows/scan.yml`. Last run's log: `last_watch.txt`.
2. **30-day test** (below). `scan.py` also runs there once an hour.

**Running it on GitHub (since 5 Nov 2026):** each run checks out this repo, runs the scan, and commits the results and the page (`index.html`). The full list of Pons launches (`data/pons_launches.csv`, 67MB+) is kept in GitHub's run cache, not the repo; if the cache is lost it is rebuilt from the chain. To change the code on the PC: `git pull` first, edit, then `git push`.

**What starts each scan:** GitHub's own timer didn't fire reliably, so a free cron-job.org job (set up 5 Nov 2026) calls GitHub's "run workflow" address every 15 minutes, using a key limited to running scans on this repo (fine-grained token "cron-job scan trigger", expires **4 Nov 2027**: make a new one before then and paste it into the job's Authorization header). GitHub's timer is left on as a backup.

**Extra facts on the site** (free, no login or key, never change a score or the test):
- `x_info.py`: each token's X account via fxtwitter (joined date, followers, posts, likes per post, follower growth saved daily), past names via memory.lol (patchy), whether the X posted this token's address (official) or warned about fakes, whether X bio / GitHub profile / website point at each other, and Telegram group size from the public t.me page. Saved in `data/x_info.json`.
- `deployers.py`: the wallet that launched each Pons token, read from Robinhood Chain's public RPC; how many other tokens that wallet launched and where they are now. All Pons launches are kept in `data/pons_launches.json` (only new blocks fetched each run).
- `prices.py`: prices every scored token each run, including those scored 0, so we can see where the score was wrong. It saves each token's starting market cap with its score at that time, the highest market cap and when, the current market cap, and every score change in `data/price_track.json`. It adds one row per token every 30 minutes to `data/price_log.csv`. The site shows a line on each card and a "Was the score right?" table that marks low scores that doubled and high scores that halved. Tracking started 4 Nov 15:11 UTC; tokens found earlier that day start from that time, not from when they were found.
- `test_tokens.py`: the 30-day test section at the top of the site (the 16 tokens in `tokens.csv`, grouped watch / benchmark / faded). Links saved in `data/test_links.json`.

---

## 30-day test

Started 4 Nov 2026. A test of one idea: **do new tokens that look like past winners go on to act like them?**

## What's in here

| Where | What |
|---|---|
| `tokens.csv` | The 16 tokens: 5 **watch** (new), 5 **benchmark** (winners), 6 **faded** (ran up then fell). Addresses and why each is here. |
| `notes/2026-11-04_scan.md` | What I found on 4 Nov: the projects, their GitHubs, and how the winners grew. |
| `data/baseline.json` | Day 0: every token's market cap at 4 Nov 2026 11:46 UTC. **Never changed after that.** |
| `data/snapshots/` | One file per run, so we can see the highest point each token hit. |
| `data/prices/hourly_2026-11-04.json` | Hourly price history back to launch for the benchmarks and faded tokens. |
| `data/raw_2026-11-04/` | The raw pages and API replies the scan was based on. |
| `checks/` | One report per day: day 0 vs now, for every token. |
| `CHECK.bat` | Double-click to run a check. Run it daily if you can (more runs = better record of each token's highest point); at minimum on 11 Nov and 4 Dec. |

## The rule (written on day 0, before seeing any results)

A watch token **acts like the winners** if, at **day 30 (4 Dec 2026)**:

1. its market cap is above day 0, **and**
2. it is no more than **45%** below the highest market cap seen since day 0.

Why 45%: the worst of the five winners (HOOKR) sits 43% below its peak. The faded tokens are all 66% or more below.

Day 7 (11 Nov) is a progress check only. Only day 30 counts.

Benchmarks and faded tokens are tracked over the same 30 days. That shows whether the whole chain went up or down, so a watch token isn't judged in a vacuum.

## Limits

- 5 winners is a small sample. This is a pattern to test, not a rule that's been proven.
- BARRAGE, FLOEM and RULERS are still on the Pons launchpad at about $4–5k. Their highest point comes from the daily snapshots only (no hourly history until they trade on an exchange), so a spike between checks can be missed.
- Data comes from DexScreener, GeckoTerminal and Pons. If one of them changes its site, the check will say "no data" and need a fix.
