# Token Watch: notes for Claude

Read this first in every session. It carries the working rules agreed with the owner (moved here from another folder's notes on 6 Nov 2026).

## How to work with the owner
- **Be direct.** One clear step at a time, in plain words. No jargon, or explain it in a few words. Ask one question at a time.
- The owner **uses** the project rather than codes it. Claude picks the approach and explains it simply. Decide foundations together; don't assume.
- **Data first:** facts, past cases with dates, then what they suggest.

## What this project is
- Scans new Robinhood Chain tokens (Pons launchpad + DexScreener) and publishes https://tradingzoo.github.io/token-watch/.
- Runs on GitHub Actions (`.github/workflows/scan.yml`): `watch.py` every 15 min, `scan.py` hourly. An outside cron service triggers the runs because GitHub's own cron didn't fire. No PC needed; the old Windows task is disabled.
- `watch.py` builds the page (`site/index.html`). **Never edit `site/index.html` by hand**: every scan rebuilds it.
- Scoring rules: `SCORING.md`. Hand checks: `reviews.json`. Open ideas: `notes/TODO.md`.

## Before and after editing
- `git pull` first; `git push` when done. The bot commits data every ~15 min.
- On a clash the bot's data wins. Data JSON files are merged whole, never line by line (`.gitattributes`), after a line merge put one token's price inside another's record (EGO/FRONG, 5 Nov).
- Code changes take effect at the next scan.
- Test page changes by building from saved data with phone alerts stubbed out (`notify.update`) and output sent to a temp folder, not `site/`.

## Token deep dive (when the owner asks to review / deep-dive / research a token)
Run every step, then report in one page. Tested on MERY 6 Nov: it found what a quick review missed (no outside users,
SDK not published, paid API only a demo, token's one use unused, two scanner misreads).
1. **Theirs?** Where the team posts this exact address (site, X, GitHub): quote + link. If nowhere: "not confirmed" at the top.
2. **Copies / launcher:** same name, site or repo on our lists; launch wallet history (data/wallets.json).
3. **Read everything:** every page of the site (home, docs, token, developers, app pages, roadmap, risks), X bio and recent posts. Also their API's own status or config page (try `/health`, `/status`, `/api/config` on the API host): on RAETO (6 Nov) it was the best source, naming the token address, the staking switch (built, off) and live usage counts; MERY's `/api/live?what=config` listed its contracts.
4. **Product:** one plain sentence; live (app link) / beta / idea; who can't use it.
5. **Token's job for holders:** quote the sentence. Fees back / holding unlocks / bond or deposit / **no use**.
6. **Money:** pricing or fees; check any paid API is real (call its public endpoints). "Not stated" if none.
7. **Is anyone using it?** Count on-chain activity on the contracts they list (Robinhood Chain RPC eth_getLogs) and who sent it (team/operator vs outside wallets). Check claimed SDKs exist (npm/PyPI), code is public (GitHub), audit done / planned / none (quote).
8. **Team:** named people? account and domain ages; earlier projects or tokens and how they went.
9. **Check the scanner:** every claim on the card against the source; list corrections (then fix the scanner if it's a pattern).
10. **Compare:** 2-3 closest projects on our lists plus the closest winner, one table (live product, payments, token use, users, code, audit, followers).
11. **Risks:** each with its source.
12. **Verdict (3 lines):** what's strong, what's missing, what would change the view (specific things to watch).
Rules: every fact gets a source and check time; "not checked" is never "no"; no price/volume analysis unless asked (trading can be faked; the project builds conviction); AI projects first. Afterwards save the result in reviews.json: `review` (What it does, Unique?, In use?, How it makes money, Token today, Team, Watch for: one short sentence each), `notes` (evidence with sources), `token_use`.

## Agreed rules (don't change without asking)
- **Page cut-off: only 61+ shows** (`SHOW_AT`), on every tab. Lower scores are still scored and priced. The "Was the score right?" tab lists **Possible misses** (hidden tokens that doubled to $25k+), with meme coins left out (counted only).
- **One card per project, proof not size.** Same project = same repo, website, or symbol + name. The real token is the one whose address the team posted (X, site, GitHub) or a hand check confirmed. Never pick by market cap or launch time: the fake can be bigger or first. Unconfirmed groups get a "Not confirmed" box listing every address and launch wallet.
- **Focus on AI projects.** Ignore DeFi and memes for now: don't propose scoring fixes for them; in miss checks only flag AI projects the scanner under-rated.
- **Wide net:** if a rule would hide a real project, prefer listing it with honest warnings over skipping it. Test changes against winners vs losers.
- **Few checks early:** don't propose a new check after every deep dive. Do deep dives as reports. Suggest a check only for a clear, tested gap, or when asked.
- **Looks unofficial?** Add `"unofficial": "why"` to `reviews.json` without asking. It shows a ❓ badge and keeps the token off the Shortlist; the score doesn't change.
- **A pullback is still a winner.** In "what winners share" studies, group by how far a token ran (e.g. ORBIO, HARMONIC are winners).
- **Active vs resting (tiers.py):** tokens are fully checked for 2 days, then hidden ones rest (daily slow checks, priced every scan, woken when they move). Change the windows only with data (notes/2026-11-06_tracking_study.md, the Scanner health tab).
- **Show changes and wait for the owner's OK before pushing.**
- **30-day test:** day 0 = `data/baseline.json` (4 Nov 2026). Never overwrite it or change the rule in README after the fact. Day-30 check: 4 Dec 2026.
