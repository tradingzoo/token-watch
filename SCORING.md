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

Both scores give **+5** when the project works with a token that already did well (Hookr, Orbio, Raeto, Priors, Harmonic, WTH, Fobo, Delta, UBIK; never itself). It now counts links on their site or repo **and** the names in their own recent X posts (OSTRA: "idle earnings go to work in … Raeto vaults"). On X, everyday words (Harmonic, Delta, Priors, WTH) only count as a $TICKER or their web address. GitHub score parts now add up to 105, shown capped at 100.

## Card layout (5 Nov)

Each card shows a short **Why {score}** block (points per part, the main pluses and misses, and any cap) above the folded **All reasons**. Tokens with the same name (copies, relaunches) are folded under the best-scoring one: "+15 more tokens named NYMRA (copies)". Nothing is hidden for good, and no score changes.

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

