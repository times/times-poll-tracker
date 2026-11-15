# Poll average and momentum check: method v0.3 (14 Nov 2026)

## Code and outputs

| | Code | Outputs |
|---|---|---|
| Average | `tracker/average.py` (filter in `tracker/methods.py`) | `outputs/average_daily.csv` (Kalman, published), `average_house_effects.csv`, `average_window_daily.csv` (v0.1, comparison and Restore Britain), `average_inputs.csv` |
| Momentum check | `tracker/momentum.py` | `outputs/momentum_latest.json`, `momentum_daily.csv` |
| Replay test | `tracker/replay.py` | `outputs/replay_scores.csv`, `replay_snapshots.csv`, `replay_momentum_flags.csv`, `replay_daily.csv` |
| Charts | `scripts/chart_average.py`, `scripts/chart_replay.py` | `outputs/chart_average.png`, `outputs/chart_replay.png` |

## Which polls go in

Polls start from the day after the 4 July 2024 general election. Earlier polls are kept in the data but left out of the average. The first post-election poll from these firms is BMG's, published 9 August 2024, so the line starts there.


The rules are unchanged from v0.1:
- standard GB voting intention only;
- not commissioned by a party or campaign group;
- weighted data;
- main series only (no MRP, no Find Out Now Restore Britain variant, no Trajectory Feb–May 2026 unweighted polls).

Survation enters on its GB re-based figures. Shares are re-normalised to 100.

## The average: a Kalman filter with house effects (introduced in v0.2)

For each party separately:

- **True opinion is a hidden line that drifts.** It's a random walk with daily variance q = 0.15 (points²), so a standard deviation of about 0.4 points a day, or about 2 points a month.
- **Each firm has a house effect.** It's a lean that's learned from the data. It starts at 0 ± 2.5 points and is allowed to drift slowly (daily variance 0.002), so it can change over months, for example after a method change.
- **Each poll measures** line + house effect + noise. Noise is sampling error (with a design effect of 2) plus 1 point of non-sampling noise.
- **It runs forward only.** Each day uses polls published by that day, so the published line never changes with hindsight.

**Why this responds quickly without assuming stable house effects.** Once a firm's house effect is learned, a new poll moves the line by how far it departs from that firm's own recent level. Several firms all moving against their own previous numbers move the line fast. One odd poll from a firm with a known lean barely moves it. House effects keep updating from recent polls, so a firm whose lean has changed is re-learned rather than corrected with an out-of-date number.

**Output:** a level and standard deviation per day. The shaded band in the chart is ±1.96 sd. It's wider than sampling error alone, because the level depends on what the "average firm" says and that is itself uncertain.

## The momentum check

For each poll published in the last **7 days**, compare it with the same firm's previous poll (if that was within 60 days). For each party, count up and down moves (ignoring changes of 0.5 points or less) and run a two-sided sign test. A party is flagged when:
- at least 4 polls are compared,
- p < 0.05, and
- the mean change is at least 1 point.

House effects cancel because every comparison is within one firm. Output includes a ready sentence, e.g. "Labour up in 9 of the last 9 polls compared with each pollster's previous poll (average +2.4 points)".

## v0.3: steadier without losing the early warning

v0.2 was accurate but looked jumpy. That had two causes:
1. The chart drew the history from each day's real-time estimate.
2. The live estimate moved with every poll.

v0.3 changes three things, all tested by replay (`tracker/replay_v03.py`, `outputs/replay_v03_scores.csv`):

1. **The history is smoothed with later polls.** It uses a Rauch-Tung-Striebel smoother over the same filter. The latest point is still the forward-only live estimate, so the warning is untouched. Past days are revised as new polls arrive, as on any serious tracker.
   - Effect: the drawn line's direction reversals fall from 19–37 per 100 days to 3–11, staying within 0.3–0.6 points of the hindsight benchmark.
2. **Adaptive speed.** The filter runs slow (q = 0.08) normally and fast (q = 0.30) on days the momentum flag is on.
   - The live estimate moves 15–20% less day to day.
   - Prediction error is within 0.02 points of v0.2 in every dataset.
   - Labour on the key campaign dates is within about 0.3 points of v0.2. For example, 20 May 2017: v0.3 32.3, v0.2 31.8, hindsight 33.4.
   - Slower defaults (0.05–0.06) were steadier still but lagged more in 2017 and 2019.
3. **Hysteresis on the momentum flag.** It switches on exactly as before (same first-flag dates in every campaign), and switches off only when the evidence has clearly gone: p > 0.2, mean change under 0.5 points, or a reversal. That means fewer switch-offs mid-move.

**Tried and dropped:** learning each firm's own noise from its residuals. It made no difference to accuracy and slightly increased jumpiness.

### v0.3 replay summary

| Dataset | MAE focus v0.2 / v0.3 | Live change per day v0.2 / v0.3 | Drawn-line reversals per 100 days: v0.2 real-time / v0.3 smoothed |
|---|---|---|---|
| GE2015 | 0.96 / 0.95 | 0.18 / 0.14 | 37 / 6 |
| GE2017 | 1.16 / 1.16 | 0.12 / 0.10 | 19 / 1 |
| GE2019 | 1.25 / 1.27 | 0.21 / 0.18 | 21 / 3 |
| GE2024 | 1.23 / 1.24 | 0.16 / 0.13 | 31 / 5 |
| 2025–26 | 0.97 / 0.97 | 0.13 / 0.10 | 22 / 2 |

`outputs/average_daily.csv` now has:
- `share`, `sd`: the smoothed history; the last day is the live estimate;
- `share_realtime`, `sd_realtime`: what the average said at the time;
- `fast_mode`: 1 on days the momentum flag was on.

`outputs/momentum_daily.csv` has `fires` (the raw check) and `flag_on` (with hysteresis).

## Evidence: the replay test (v0.1 v v0.2)

Each method was replayed day by day using only polls already published. The test data covered the last four general election campaigns, from Wikipedia's poll lists (publication assumed to be fieldwork end + 1 day), plus the tracker's own 2025–26 data. Two scores:

1. **Prediction error.** How far each new poll lands from the method's estimate the day before, plus that firm's usual offset. This measures tracking without chasing noise.
2. **Real-time Labour line against hindsight.** The hindsight line is a centred 15-day mean that uses later polls.

### Mean absolute error predicting the next poll (points, all five parties)

| Dataset | Window average v0.1: whole period | v0.1: campaign / focus | Kalman v0.2: whole period | v0.2: campaign / focus |
|---|---:|---:|---:|---:|
| GE2015 (flat campaign) | 1.02 | 0.94 | 1.03 | 0.96 |
| GE2017 (Labour surge) | 1.18 | 1.26 | 1.10 | 1.15 |
| GE2019 (Labour recovery, Brexit Party collapse) | 1.65 | 1.32 | 1.58 | 1.25 |
| GE2024 (Labour slips, Reform rises) | 1.06 | 1.31 | 1.03 | 1.22 |
| 2025–26 tracker (focus: Burnham takeover) | 1.03 | 0.99 | 1.03 | 0.97 |

- When opinion is moving, the Kalman filter is better by 0.1 points or more.
- When it isn't, it's no worse than v0.1, within 0.03 points.
- Slower settings (q = 0.01, 0.04) lag badly in 2017.
- A faster one (q = 0.5) gains a little in 2017 but loses more in calm periods.
- An adaptive version that sped up when the momentum check fired added nothing.

### Lag on key dates (Labour, real time against hindsight)

- **2017.** On 20 May, hindsight shows 33.4. v0.1 showed 30.3 and the Kalman 31.8.
- **2019.** On 27 November, hindsight shows 31.9. v0.1 showed 30.0 and the Kalman 31.7.
- **2024.** On 17 June, hindsight shows 41.0. v0.1 showed 42.5 and the Kalman 41.8.
- **Where neither helps.** In the first week of a shift, before many firms have published, no method can know. In 2024 the drop shows in hindsight from about 3 June; the first polls showing it arrived over the following week.

### Momentum flags (7-day lookback)

| Campaign | First flag | Notes |
|---|---|---|
| GE2015 | none | no false alarms in a flat campaign |
| GE2017 | Labour up, 3 May | the surge built through May |
| GE2019 | Labour up, 12 Nov | |
| GE2024 | Reform up, 8 Jun (5 days after Farage's 3 June entry); Labour down, 11 Jun | |
| 2025–26 | Labour up, 24 Jul 2026 (Burnham) | 20 flag-days in 623 days |

A 10-day lookback flagged 2017 Labour on 16 May and doubled the calm-period flags. A 5-day lookback was noisier.

## What it doesn't do

- **Industry-wide error.** In 2024 the final polls overstated Labour by about 4–5 points. No averaging method fixes that.
- **Restore Britain.** It's only averaged among firms that name it (v0.1 window method, `RB_named_only`). The prompting split still needs a proper treatment, e.g. a pooled Reform + Restore Britain series.
- **The Wikipedia test sets.** They have no publication dates, so "end + 1 day" flatters every method a little. The live data uses real upload dates where they're plausible.
