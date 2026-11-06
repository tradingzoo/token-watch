# How the GitHub score works

Agreed 4 Nov 2026. Out of 100. Every point shows on the page as a dot point with ✅ (yes), 🟡 (partial / guessed / not switched on) or ❌ (no).

The score answers **"is the code real, is it theirs, and does the token get anything from it?"** It does not say the token will go up. In our benchmarks a GitHub did not predict winners. Earning fees from others did, so that part counts most.

| Part | Check | Points |
|---|---|---|
| **Platform (40)** | Earns fees from other people using it | 20 |
| | Fees go back to the token (buyback, burn, staking, holders paid). Live and checked = 20; built but off, or only claimed = 10 | 20 |
| **Really theirs (20)** | Token's address is posted by their repo, website or official X (changed 5 Nov) | 10 |
| | Repo and website link to each other (both ways = 10, one way = 5) | 10 |
| **Real code (20)** | 20+ changes, worked on over 7+ days (one of the two = 5) | 10 |
| | Has smart contracts and tests (one of the two = 5) | 10 |
| **Team (10)** | Not a brand-new one-person repo: account 3+ months old, or 2+ people, or 10+ stars/forks | 10 |
| **Safety (10)** | Contract addresses in the README | 5 |
| | Security file, audit or timelock mentioned | 5 |

**Not their GitHub = score 0** (decided 4 Nov). A repo only counts as theirs with real evidence: it mentions the token's address, or it links the token's website, or the GitHub *account* is named after the project. A matching *repo* name alone is not enough, since anyone can name a token after a famous repo. Score 0 when:
- the repo never mentions the token, its name or its website, or nothing ties it to the token and it's a popular older repo (500+ stars, made 60+ days before the token)
- the code is copied from someone else's repo (copy check, or checked by hand)
- the GitHub *account* is big and older (500+ followers or 100+ repos, made 60+ days before the token) and the only tie is its name (added 5 Nov: PARITY linked github.com/paritytech, Parity Technologies' account from 2015). A matching account name only counts for smaller or newer accounts
- the repo is a fork or is empty (a GitHub account that shows no code is a *private GitHub*, scored below)

**Private GitHub** (decided 4 Nov). Some projects link a real GitHub account or repo, but the code is private (no public repos, or the linked repo is private or deleted). These are scored too, but public code counts for more:
- Platform (40): the same guesses, from the token page and their docs
- Really theirs (20): their website links the GitHub (10); the GitHub account is named after the project (10)
- Real code: 0, since the code can't be seen
- Team (10): account 3+ months old or 10+ followers
- Safety (5): their docs mention an audit or timelock
- **Capped at 40.** A card with a private GitHub shows 🔒.
- If nothing ties the account to the token, the score is 0. If the GitHub account doesn't exist, the score is 0 (dead link).

**Other red flags** cap the score at 25 and show a warning:
- the repo never mentions the token, its name or its website (may be someone else's project)
- the GitHub account has no public code, or the repo is empty
- the repo is a copy (fork) of another repo
- the same symbol was launched 3+ times on Pons
- **copy check:** 2 or more of 3 sample lines from their main code also appear in an older repo by someone else
- **X doesn't match the website** (added 5 Nov): the token links a different X account from any its website links. Capped at 25, not 0, because a real team can link an old or second account by mistake

**Official X** (added 5 Nov): the official X is the one the project's **website** links, never just the one the token page lists (anyone can list a real project's X on a token, see FLOEM). It counts for the address check only if it posts this token's address in its bio or recent posts **and** the account is 30+ days old. A brand-new account posting it shows 🟡 and gets no points: when a company renames its X, anyone can take the old name (CUBE, 4 Nov: the dev then said the token was a scam).

**Dev never mentions this token = capped at 25** (added 5 Nov, after SEO and OMHER). Anyone can launch a token on Pons named after a popular project and point it at the real website, GitHub and X. The project's own quality (code, stars, team) then scores high even though the dev has nothing to do with the token. The check: if the GitHub is big and older than the token (500+ followers or 100+ repos on the account, or 500+ stars on the repo, made 60+ days before launch) and its repo, website and X never post the token's address or mention the token, the card gets the warning "Dev never mentions this token" and the score is capped at 25. It lifts by itself at the next rescore once the dev posts the address.

**Copycat token = score 0** (added 5 Nov, after $BYTE). Scammers relaunch a token under the same name and paste in the real project's website, GitHub and X, so everything looks right. The check: if the project's X (the one its website links, or the one the token links) posts a **different** address for a token with the same name or symbol on Pons, and never posts this one, the token is flagged "Copycat token" and scored 0. The scanner then checks the real one too, even if it has already left Pons's newest list. An address the X account itself calls fake is never treated as the real one. Tested 5 Nov on the 60 listed tokens: 13 copies found (8 NYMRA, plus KROMT, DARE, EXPO, SAIBOT92, BYTE), all checked against launch times and the X accounts.

**Copy check, how it works:** it takes 3 distinctive lines from their biggest code files (skipping libraries, tests and auto-generated files) and searches all of GitHub for them.
- ✅ = it found the repo itself and nobody else's older copy
- ℹ️ "couldn't run yet" = GitHub's search hasn't indexed the repo (normal for repos under about a week old). It retries every 6 hours. This is **not** a pass.
- ℹ️ "1 of 3 lines" in an older repo = probably shared library code, not a flag
- ℹ️ "most files arrived in the very first change" = could be copied, or moved over from a private repo. A note, not a flag.
- It can name a big repo that also contains the original rather than the original itself (GitHub only returns the top matches). Tested 4 Nov on PancakeSwap (a known Uniswap copy): flagged.

**Fixing a wrong match:** each card has a "Wrong repo?" button that copies a message to paste to Claude. Claude puts the fix in `reviews.json`: `"repo": "owner/name"` uses the right repo, and `"skip": true` drops the token.

**Skipped links:** the bottom of the page lists, for the last 7 days, every GitHub link the scanner found but didn't use (mostly code libraries inside websites). It's there so you can check real projects aren't being missed.

**Roadmap** has no points. The page lists any roadmap file, roadmap page or changelog it finds, and how much has shipped.

**Guesses vs checked:** the script can only guess the Platform part from the project's own words (marked "guess, needs a look"). When Claude checks a token by hand (code and live contract), the result goes in `reviews.json`, replaces the guess, and shows under "Checked by hand".

**Which tokens appear:** every new token on Pons (newest page) or DexScreener (Robinhood Chain profiles and boosts) that links a public GitHub, either on its token page or on its website. GitHub links that only appear inside a website's code files are kept only if they look related to the token (most are code libraries).

# Still shipping? (GREEN / AMBER / RED)

Added 5 Nov 2026, from Aaron's Pons scanner notes. Script: `shipping.py`, saved in `data/shipping.json`. It never changes a score or the 30-day test. It catches projects going quiet; it doesn't predict price.

Each run checks every token on the site plus the 16 test tokens: the project's own GitHub (last real change or release, bots don't count, using the time it landed on GitHub), whether the website loads, whether the X account still exists and still shows the address in its bio, and market cap / money in the main pool against about 24 hours ago.

| Status | When |
|---|---|
| 🟢 GREEN | A real GitHub change or release in the last 3 days, and nothing below |
| 🟠 AMBER | 3–6 days with no real change or release · website didn't load on the latest check · market cap down 50%+ or pool money down 40%+ in 24h while most tokens did not fall |
| 🔴 RED | 7+ days with no real change or release · repo deleted or made private · every repo archived · website down on every check for 6+ hours · X account gone · address removed from the X bio |
| ⚪ GREY | No public code of their own to watch (no GitHub, a private one, or someone else's). Can still go AMBER/RED on website, X and market |

The page's "Still shipping?" box lists a token only when its status changes. The first run (5 Nov) only saved starting points.

## Badges and private code (5 Nov)

- **🤐 dev hasn't mentioned this token** (badge only, no score change): the project's repo, website and X never post the token's address or mention it. The big-older-GitHub cap of 25 above still applies; for everyone else it's just the badge. On 5 Nov, 60 of about 130 cards got it, including ORBIO (a real winner that never posts its address), so it means 'unconfirmed', not 'fake'.
- **Private GitHub cap** is 40, or **60** when the token's own website posts its address (DARK, 5 Nov: $3.9M, address and Pons link on darkwoods.ai, code private).
- **Private GitHub + a real website:** the site check also scores the website and the card keeps the **higher** score, with both shown (DARK: GitHub check 55, site check 80 → 80). A private repo shouldn't hide a strong product.

## Works with past winners (5 Nov)

Both scores give a **+5 bonus** when the project works with a token that already did well (not doing so is never listed as a miss) (Hookr, Orbio, Raeto, Priors, Harmonic, WTH, Fobo, Delta, UBIK; never itself). It now counts links on their site or repo **and** the names in their own recent X posts (OSTRA: "idle earnings go to work in … Raeto vaults"). On X, everyday words (Harmonic, Delta, Priors, WTH) only count as a $TICKER or their web address. GitHub score parts now add up to 105, shown capped at 100.

## Card layout (5 Nov)

Closed, each card is four lines: score, name, a **click-to-copy contract address**, badges; value · launched how long ago · where it trades; one ✅ main plus and one ⚠️ main warning (+N more); links. **Details** opens, always in this order: Quick facts (market, X, GitHub or website, launch wallet, status), Warnings (each once, ×N for repeats), Score (points per part, cap, top pluses and misses), About, and Full evidence (every reason line). NEW means launched in the last 24 hours. **Narrative tags** under the warnings line (display only, never scored): up to 3 of AI agents, AI, Privacy, Stocks / RWA, DeFi, Launchpad, Payments, Prediction, Gaming / NFT, Dev tools, Meme — from the project's own words (name, description, X bio) — plus **Public dev** when a GitHub account at least 6 months old names the project's X. One card per project (see "What the page shows" below).

## Score refinement (5 Nov): two parts shown, not scored

Tested on our own tokens launched before 2 Nov (took off = now $500k+, died = now under $20k): **Team** (GitHub score) and **Live product** (site check: app, agents, audit) gave the dead tokens as many points as the winners, so they're now information lines (ℹ️) with no points. *Takes real payments* keeps its 5 points and moved to Money and Robinhood Chain. Effect on the same tokens: site check, dead tokens scoring 60+ went from 3 of 8 to 1 of 8 (winners unchanged, 8 of 13); GitHub, winners 60+ 5 of 6, dead 0 of 9.

The **Is the score working?** table on the *Was the score right?* tab redoes this comparison every run (tokens 3+ days old, median score, share 60+, points per part). Once each group has 15+ tokens, the 60 cut-off and the weights get set from it.

## Ghost market warning (added 5 Nov, warning only)

A token worth **$250k+** with **fewer than 25 trades in 24 hours** gets a 👻 warning on its card: the price may be propped up or stale, and selling near it may not be possible. It never changes the score (user's choice). Why trades and not volume: on 5 Nov, 'under 1% of value traded a day' would have flagged half the real winners (UBIK, GF, HMM, PONS); real winners trade 100–3,000 times a day, while TRENCHERS traded 13 times, WIN 4, AGE 7.

## Site check: tokens with no GitHub (added 5 Nov)

**Why.** The GitHub score skips every token without a public GitHub, so it missed winners like HOOKR and HARMONIC. On 5 Nov we compared 19 tokens worth $2M+ (with a website) against 65 random Pons tokens that went nowhere (under $20k, a week or more old). Winners' websites let developers and AI agents plug in directly:

| On the site | Winners | Losers |
|---|---|---|
| 3+ of API key, SDK, MCP, llms.txt | 32% | 2% |
| MCP for AI agents | 37% | 3% |
| llms.txt | 37% | 5% |
| Links other winners | 42% | 5% |
| Says money goes back to the token | 79% | 28% |

Caveat: these are today's websites, so a winner may have built its developer page after it ran. The price tracking on each card is there to test whether these signs show up early.

**Who is listed.** A token with no GitHub whose own website (not an X, Telegram or news page) has **2 or more** of: API keys, an SDK or install line, MCP, llms.txt, **or** a site score of **40+** (added 5 Nov after UPOCH and SIC: strong finished products with fewer developer tools; test: 10 of 17 winners listed instead of 8, 11 of 64 losers instead of 9 — a wide net on purpose). New tokens are looked at when found and again once a day for 14 days; up to 40 new sites a run. Only what a visitor or agent can read counts (pages and docs, not script code: news sites' ad scripts mention "SDK" too).

**Older tokens** (added 5 Nov, after MERY and UPOCH). The scanner started on 4 Nov and only read Pons's newest page, so tokens launched earlier, or that took off after leaving that page, were never checked. Each run now also reads Pons's top-by-market-cap and top-by-volume pages. A one-time sweep of older Pons tokens with a trading pool (data/catchup.json) is checked 20 a run until done.

**Tokens not launched on Pons** (added 5 Nov, after FOBO: its own launchpad, $60k to $3.9M, never seen). Each run reads every new Uniswap pool on Robinhood Chain (dexpools.py) and follows the non-Pons tokens, checking their value on DexScreener about 1 hour, 1 day, 3 days and 7 days in. Any worth $25k+ with $5k+ liquidity get the GitHub check and the site check like a Pons token.

**No website on Pons** (added 5 Nov, after UBIK). Some projects list only an X account on Pons. The site check then uses the website on that X profile, but only if the X account itself posts this token's address, so a copy or a token linking someone else's X never gets in. The card says where the site came from.

**Score /100.**

| Part | What counts | Points |
|---|---|---|
| **Plug-in tools (45)** | API keys (incl. a holder's key or `Authorization: Bearer`) 10 · SDK or install line (incl. terminal installs: brew, curl | sh, winget) 10 · MCP 10 · llms.txt 10 · developer page (/developers, /docs, /build) or docs link 5 | 45 |
| **Really theirs (25)** | Token's address on their website/docs, or posted by their official X (30+ days old) 15 · 2+ contract addresses listed 5 · works with past winners (Hookr, Orbio, Raeto, Priors, Harmonic, WTH, Fobo, Delta, UBIK; not itself) 5 | 25 |
| **Money and Robinhood Chain (20)** | Says money goes back to the token (buyback, burn, staking, revenue share) **or** holding the token unlocks the product (e.g. "a wallet holding 200,000 UBIK", token-gated), 🟡 claimed, not checked 10 · uses stock tokens or USDG, on the site or as its trading pair (paired with USDG, TSLA, NVDA…) 10 | 20 |
| **Live product (15)** | App, dashboard, console or wallet connect 5, or an app with 3+ sections (like SIC) 10 · made for AI agents (on the site, or in their official X's recent posts) 5 · mentions an audit, 🟡 not checked 5 · **takes real payments** (pay by card, Stripe, Apple Pay, top-ups, buy credits; 5 Nov test: winners 41%, losers 5%) 5 | 20 |

Adds up to 110, so a few points can be missed and still score 100 (shown capped at 100).

- **Copycat token = 0** (same rule as above).
- **Other red flags** (X doesn't match the website, hand-check flags) cap at 25. **Except** (5 Nov, after TRENCHERS): if the token's address is on the project's own website or repo, an X mismatch is a warning only, no cap — a copy can't post its address on the real site. Usually it's an old or renamed X account.
- **Not their website** (5 Nov): a link to the token's page on another platform (Pons, pump.fun, otcdesks, an audit site; the link holds a token address or a /coin/ /token/ path) or a news/reference page (Wikipedia, BBC, SEC…) doesn't count as the project's website. Tested on 921 links: 86 flagged, no winner.
- **Address not shown anywhere** (site, docs, recent X posts) caps at 60. Copies paste a real site's links, so an unclaimed token can't score top marks; not lower than 60 because real winners like ORBIO and HARMONIC don't post their address either.


## Shortlist tab (5 Nov)
A place to look first, not advice and not proven yet. A token is on it only if **all** of these hold:
- It's the team's own token: score above 0, and their site, repo or X posts its address or mentions it.
- No warnings of any kind (including 👻 ghost market and ❓ maybe not official).
- At least 50 trades in the last 24h and $20k+ liquidity.
- At least 2 of the signs winners shared: 2+ plug-in tools, takes payments, works with a past winner, uses Robinhood Chain assets (stock tokens / USDG), real code, a GitHub score of 60+ (that split winners 5 of 6 vs dead 0 of 9).

Most signs first, then score. Tokens that pass everything except trading go under "Early" (riskier).

## Maybe not official (hand note)
`"unofficial": "why"` in reviews.json puts a ❓ badge and a warning on the card. The score doesn't change, but it keeps the token off the Shortlist. First used on CAPAFY (5 Nov): Capafy never mentions a token and a brand-new wallet made it.

## Still building tab (5 Nov)
Teams that keep working, whatever the price does. A token is listed when all of these hold:
- It's the team's own token (they post its address or mention it), with no score warnings and no ❓ maybe-not-official note.
- It launched 3+ days ago, so the work counts after launch and not just in the run-up to it.
- Its GitHub has real changes (bots don't count) on at least 3 different days out of the last 8, the latest within 3 days.

Data comes from the still-shipping check (shipping.py). Teams with no public code can't show up yet.

## Shortlist alerts (5 Nov)
notify.py sends a phone alert (Telegram and/or ntfy, set as GitHub secrets) when a token joins the Shortlist, with its score, value, signs, contract address and DexScreener link. A token that drops off and returns after 24h+ away is announced again as "back"; shorter dips stay quiet. Tokens already on the list when alerts started don't alert. On the page, a token that joined in the last 24h shows "🆕 joined the list".

## Sound when a token reaches 60+ (5 Nov)
The page plays a short chime when a token newly scores 60+ on the GitHub or Site check list. Click "🔕 Sound off" (bottom left) to switch it on; browsers only allow sound after a click on the page, so after opening the page, tap anywhere once. The page no longer reloads itself: it fetches the new version every 5 minutes and swaps it in (not while you have a card's details open), which keeps the sound switched on. New 60+ tokens get a popup (bottom right), a blue outline and a count in the tab title. Tokens that reached 60+ since your last visit show in the popup when you open the page. Remembered per browser.

## Every exchange DexScreener shows (6 Nov)
DexScreener's Robinhood page can't be read by a script (it has a bot check), so the pool feed reads the same thing from the chain: every new pool on Uniswap v4, v2-style exchanges (this includes the flap.sh launchpad, ~580 launches a day), v3-style and Aerodrome-style exchanges. Tokens worth $25k+ with $5k+ liquidity (checked about 1h, 1 day, 3 days and 7 days after their first pool) go to the GitHub and site checks. On 6 Nov the last 24h held ~1,100 tokens outside Uniswap v4, of which 1 had a website: so this is a safety net, not a big source.

## Junk pools ignored for prices (6 Nov)
A DexScreener pool with under $500 of liquidity is ignored when reading a token's value: tiny "trap" pools give fake prices (LETRO showed $13.7k from a $0.34 pool while it really traded at ~$40k; EXPO showed $26k from a $1 pool while worth $3.7k on Pons). The Pons page is used instead. Highs already recorded from such pools before 6 Nov may be too high.

## Where on GitHub the address is (6 Nov)
"Token's address is posted by their ..." now names the exact place on GitHub: the repo's About line, the README, the owner's profile bio, or the repo's files. The profile bio counts too (it's the repo owner's own account). If the address is in the About line or bio but not the README, Safety adds an ℹ️ note saying so (no points change: the +5 is for listing contract addresses in the README).

## "No token yet" pages (6 Nov)
A line like "Is there a BLACKPOOL token? Token details are TBA" no longer counts as the project mentioning the token. If the project's own pages say there's no official token yet (TBA, "treat anything else as unofficial", "there is no official token", "beware of fake tokens"...) and they don't post this token's address, the card shows a ⚠️ line quoting it. No points change.

## Hand reviews (6 Nov)
`"review": {"What it does": ..., "Unique?": ..., "Scalable?": ..., "Narrative fit": ..., "How it makes money": ..., "Token today": ..., "Watch for": ...}` in reviews.json shows as a "Hand review" block at the top of the card's Details, with a 📝 hand review badge on the closed card. Information only, no score change. First one: LETRO. **Keep each line short** (one sentence, about 20 words or less; Watch for = short items split by ·) so it can be taken in at a glance; longer evidence goes in `notes` (shown under Full evidence). User, 6 Nov.

## Hand review queue (6 Nov)
Tokens launched from 6 Nov 03:15 UTC on that score 60+ (and aren't marked maybe-not-official) without a hand review go in data/review_queue.json and a collapsed "📝 Hand review queue" list at the bottom of the Shortlist tab, AI projects first, then by score and value. Reviews are written by Claude when asked ("do the reviews"); the scanner itself doesn't write them.

Older tokens are not queued and reviews are not redone (user, 6 Nov).

## Quick read (6 Nov)
Every card scoring 60+ gets a row of key-word chips on the closed card and a "Quick read" block in Details (what it does, narrative, money, theirs?, built, watch for). Built only from facts the scanner already has: green = good, amber = claimed/guessed/unchecked, red = risk. No judgement: it's for deciding fast; ask Claude for a deep dive. On these cards the old one-line verdict is hidden (the chips cover it).

## Key points on every card (6 Nov)
The closed card shows up to 3 written-out key points taken from the score's own lines, then the top warning: 1) is it theirs (where the address is posted, or that it isn't), 2) the money signal (takes payments, or fees go back to the token, or earns fees), 3) activity (commits over days and recent building days; or private code; or plug-in tools; or a working app). On 60+ cards the Quick read chips follow, without anything the key points already say. Full scoring stays in Details.

## What the page shows (6 Nov)
**Cut-off: only projects scoring 61+ are shown**, on every tab (GitHub, Site check, Shortlist, Still building, review queue). Tokens at 60 and below are still scored and priced every run (data/price_track.json, data/price_log.csv). The *Was the score right?* tab opens with **Possible misses**: hidden tokens whose value at least doubled to $25k+, so anything the score missed still shows up. Meme coins are left out of this list for now (only counted): meme words in the name, description or website address (meme, doge, cat, inu, mascot, parody…), never when the project has an AI tag. The full price record sits below it, closed.

**One card per project; proof, not size.** Tokens are the same project when they share a GitHub repo, a website, or the same symbol and name. Size and launch order don't decide which is real, because a copy can be bigger or first. If the team posted one token's address on their X, website or GitHub, or a hand check confirms it (`reviews.json`: a hand `review`, or `"official": true`), only that token shows; the copies are not shown. If none is confirmed, one card shows with a **Not confirmed** box listing every address, its score, value, age and launch wallet, and none of them can reach the Shortlist or Still building. When the team posts an address, the page switches to it by itself, and the copycat check flags the rest.

**Serial launcher** (red): the token's launch wallet also launched known copies (copycat flag, or marked not official by hand). Shown in the Not confirmed box and as a warning on the card.


**Second 30-day test (started 6 Nov, `test61.py`, `data/test61.json`).** Every project the page shows (61+) enters at its value the first time it is shown, in two sections: GitHub and Site check. After 30 days it passes if it is above its entry value and no more than 45% below its highest since entry (the same rule as the 4 Nov test). Entries are never changed or removed. The 4 Nov test (README) is unchanged and shown below it, with each token's scanner list as a label only.

**Status changes** list only the projects on the page and the 30-day test tokens: real colour changes only, the latest per token, split into good news and warnings. An X account counts as gone only when X says it doesn't exist; a lookup that gets no answer keeps the last result (6 Nov: failed lookups had marked live accounts like OAK and ORBIO as gone).

**What it does** (Quick read) uses the token's own description when it says what the product is, else their X bio (marked "from their X"), else "Not explained on their page".

**"No buyback" is not a buyback (6 Nov).** The money-back check (buyback, burn, staking, revenue share…) ignores a word when "no / not / never / without" comes up to 2 words before it in the same sentence. MERY's site says "there is no buyback, no burn tax and no revenue share" and had been given +10 for a buyback; OFFROUTER says "No staking".

**Active vs resting tokens (6 Nov, `tiers.py`; evidence in notes/2026-11-06_tracking_study.md).** *Active* = shown (61+), a 30-day test token, or launched / graduated / woken in the last 2 days: price, status and X checked every scan. *Resting* = every other (hidden, older) token: nothing is deleted; its Pons page and X are checked once a day, spread across scans (a small slice each run). Every resting token that trades on an exchange is still priced every scan (cheap batch), and a resting token **wakes** at once if it graduates, reaches $25k, doubles from its resting value, or appears on Pons's top market-cap / volume list. Each scan has a 12-minute budget: after that, optional work (re-scores, the resting slice) waits for the next scan. Every scan is logged in data/runs.csv; the "Scanner health" tab shows scan time, active / resting counts, graduation timing and woken tokens; a daily copy goes in data/studies/.

**How often scores are redone (6 Nov).** Shown projects (61+) every 6 hours; hidden but active (young) every 24 hours; resting every 72 hours; score 0 every 7 days; at most 20 re-scores per list per run, most overdue first. Prices and status are still checked every run for every listed token. Tokens with no GitHub when first seen are not checked for a GitHub again (user's call: a project without one at launch rarely adds one; the site check covers no-GitHub projects).

**Audit claims (6 Nov).** "Not audited", "unaudited" and "no audit" no longer count as mentioning an audit (EXPO and OFFROUTER only said they were not audited; 44 of 55 shown tokens "mentioned an audit"). A roadmap line like "Audit (next)" still counts: telling planned from done needs a hand check.

**Token line on every card (6 Nov, after MERY).** Each card says what the token itself does for holders, apart from what the product earns: 🟡 "fees go back to holders, claimed" or "holding it unlocks the product, claimed", else ❌ "Token has no use for holders". A hand check can set it in reviews.json (`"token_use": {"none": true, "text": ..., "source": ...}`). On 6 Nov: 54 of 58 shown projects claim fees go back (the words are common, so it stays "claimed"), 3 show no use (MERY, Nautilo, RAIL).

**Plug-in tools must not be denied (6 Nov).** API keys, SDK and MCP count only if the site doesn't deny them ("MCP... no API key" had scored API keys for MERY; AUTONOMO and WAFERMAP also say "no API key", as pay-per-call x402 services do).

**Hand reviews follow the deep-dive checklist in CLAUDE.md (6 Nov).** Fields: What it does, Unique?, In use? (on-chain activity by outside wallets, not the team), How it makes money, Token today, Team, Watch for. One short sentence each; evidence and sources go in `notes`.

