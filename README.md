# GTA VI launch-day Twitch forecast

Entry for [make.fun bounty `gta6-twitch-ccu-forecast-01`](https://make.fun/bounty/gta6-twitch-ccu-forecast-01):
forecast Grand Theft Auto VI's Twitch concurrent viewers for each hour of its
release day, 2026-11-19 (UTC), hours 2–24, as five quantiles per hour.

> **Placeholders — fill in when the repository is created:**
> GitHub owner: `Vrayroom` · Repository: `gta6-twitch-ccu-forecast` · Entry repo URL:
> `https://github.com/Vrayroom/gta6-twitch-ccu-forecast`

## Method

A launch day's Twitch curve is anchored on its hour-1 print `p1` and shaped
by past big launches (donors). For each donor we precomputed the release-day
hourly ratios `r_h = viewers(h) / viewers(1)`, `h = 2..24`, from SullyGnome's
hourly Twitch category averages — the same source the competition kit's
comparables use — plus the four practice launches' own release-day curves
from that source. The donor table is embedded in `main.py` (no network at
run time).

For a case with hour-1 print `p1`:

- each donor is weighted by **size match**,
  `w = exp(-|ln(h1) - ln(p1)| / 0.3)`, so donors whose first hour was about
  as big as this case's count most;
- donors whose unlock was a **rolling midnight local** (the class GTA VI
  belongs to) keep full weight; all others are downweighted to 0.25;
- **live-service / free-to-play** launches are excluded outright (different
  shape: slow burn, not a midnight-unlock spike);
- donors with hour-1 under 5,000 are excluded: their ratios explode (their
  category was nearly empty at midnight UTC) and carry no signal about a
  big launch;
- for each hour `h`, the five quantiles are the **weighted quantiles** of the
  donors' log-ratios at that hour: `q_tau(h) = p1 * exp(Q_tau(ln r_h))`.

Guards: quantiles are non-decreasing, q05 is at least 20% of `p1`, q95 is
capped at 20× `p1` (a far sanity bound that never binds on the donors,
whose largest ratio is ~12×). No network, no model call, deterministic:
the same input bytes always produce the same output bytes. Runtime is
~0.1 s per case (cap is 8 s).

## Validation

Practice cases p00–p03, exact pinball loss on the log scale, answers from
the same SullyGnome source (hour-1 prints match the cases' `known` rows
exactly):

| case | game | loss | house baseline |
|------|------|------|----------------|
| p00 | Marvel's Wolverine | 0.160 | 0.744 |
| p01 | Red Dead Redemption 2 | 0.118 | 0.287 |
| p02 | God of War Ragnarök | 0.057 | 0.215 |
| p03 | Marvel's Spider-Man 2 | 0.144 | 0.303 |
| **mean** | | **0.120** | **0.387** |

The practice leaderboard's best entry was ≈ 0.169. The hyperparameters
(size scale 0.3, non-midnight weight 0.25) were chosen on the practice mean
**and** on a leave-one-donor-out check over the midnight-local donors
(mean 0.240, median 0.145) — not on any single case. Adding extra spread
or a 2.5× q95 cap made both worse, so neither is used.

Typical forecast shape for a large hour-1 print (e.g. 600k–1M): a dip to
~0.5–0.7× in hours 3–12, rising to a peak of ~0.9–1.3× in hours 19–22
(US prime time), then easing off — the shape every midnight-local AAA
launch in the donor pool shows.

## Run

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` in the input dir (schema `makefun/twitch-ccu-case/v1`)
and writes `<id>.out` per case:
`{"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, …]}`.
If the donor model ever fails on a case, it falls back to the house
persistence forecast so the output is always a valid file.

## Files

- `main.py` — the whole entry (model + embedded donor table), Python 3.13
  standard library only.
- `LICENSE` — MIT.
- `.makefun/owner.json` — payout wallet for the prize claim.
