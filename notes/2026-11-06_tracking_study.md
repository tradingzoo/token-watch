# How often to check which tokens (6 Nov 2026)

Question: the scanner checked every listed token fully every scan, so scans grew with the list (39 min for a
15-minute schedule). Which tokens can be checked less often without missing winners?
Data from three checks run on 6 Nov. Result: `tiers.py` (active vs resting), rules in SCORING.md.

## 1. Random Pons launches (base rate)
- Method: 600 random launches from 10-40 days ago (out of 89,575 in that window, ~3,000 a day), each token's own
  Pons page read on 6 Nov (stage, createdAt, graduatedAt, value now, trades). 596 read.
- Graduated (left the Pons curve for an exchange): **3 of 596 (0.5%)**, all **within their first day**.
- None graduated later; none is worth $25k+ now. Median value now $3,651 (about the start value); median 7 trades ever.
- Limit: these are ordinary launches. Our listed tokens are a picked group (GitHub or developer tools) - see 2.

## 2. Our listed Pons tokens (the picked group)
- Method: every token on the GitHub or Site check list that launched on Pons 2+ days ago (136), Pons page read 6 Nov.
- Graduated: **86 of 136 (63%)**.
  - within 6 hours: 66 (77% of graduates) · 6-24 hours: 7 · 1-2 days: 7 · **after 2 days: 6**
- Late graduates (after day 2): MORROW 14.7 days (now $112k), ZOKI 7.9 days (now $577k), ZHOOK 9.1 days, TIDE 5.8,
  BULLY 5.3, OSTRA 2.8 (now $311k, score 85).
- So our group differs from random launches: late graduation is rare but real, and some late ones became winners.
- Still on the curve after 2+ days: 50. Two showed a high of $25k+ in our price record, but both are copies whose
  record briefly picked up the real token's price (a data quirk), not real value.

## 3. Winners (tokens that peaked at $500k+)
- Method: Robinhood Chain pools from GeckoTerminal (top 200 by volume and by trades), tokens 10+ days old, daily
  price candles from launch. 52 peaked at $500k+.
- Limit: most of the 52 are tokenized stocks and older exchange tokens (QQQ, GOOGL, USDG...), not launches; only 5
  are Pons launches. Daily candles are too coarse to time a climb within a day. Treat as weak evidence.
- The 5 Pons winners: 3 graduated within hours; **PRIORS after 5.4 days and ORBIO after 6.1 days**, and both passed
  **$500k within a day of graduating** (ORBIO went on to a $117M peak).

## What this means for the rule
1. Keep every token fully checked for its first **2 days** (77% of our graduates go within 6 hours; margin added).
2. After that, hidden tokens can **rest**: their slow checks (Pons page, X) once a day, nothing deleted.
3. Resting tokens must **wake within a scan**, not a day: winners can graduate late and climb to $500k in under a
   day (PRIORS, ORBIO). So every resting token that trades on an exchange is still priced every scan (one cheap batch
   request per 30 tokens), and any resting token on Pons's top market-cap / volume list wakes at once. It wakes if it
   graduates, reaches $25k, or doubles.
4. Keep measuring: the "Scanner health" tab shows graduation timing for our tokens (updated every scan) and which
   tokens woke; a copy is saved daily in data/studies/. If late risers turn out to be common, check resting tokens
   more often.
