"""Replay test for v0.3: can the average be steadier without losing the early warning?

    python3 -m tracker.replay_v03     # writes outputs/replay_v03_scores.csv, replay_v03_flags.csv

Variants (all forward-only for the live estimate):
  fast         v0.2: Kalman, q = 0.15
  fast+noise   v0.2 plus per-firm noise learned from each firm's own past residuals
  adapt a/b    slow by default (q = a), fast (q = b) on days the momentum flag (with hysteresis) is on,
               plus per-firm noise
Each is scored on
  - prediction error (as replay.py: next poll v estimate the day before + firm's house effect);
  - jumpiness of the live estimate: mean absolute daily change, and direction reversals per 100 days;
  - the smoothed history (RTS smoother, revised with later polls): jumpiness and mean absolute gap
    to the hindsight benchmark.
The momentum flag is scored with and without hysteresis: first flag date, days on, and flicker
(number of times it switches off and back on).
"""
import csv
import datetime as dt
import statistics as st

from . import common as C
from .methods import PARTIES, jumpiness, kalman_run, load_testset, load_tracker, momentum, momentum_flags
from .replay import SETS, hindsight

VARIANTS = {
    "fast": dict(q=0.15),
    "fast+noise": dict(q=0.15, firm_noise=True),
    "adapt .05/.30": dict(q=0.05, q_fast=0.30, firm_noise=True, adaptive=True),
    "adapt .08/.30": dict(q=0.08, q_fast=0.30, firm_noise=True, adaptive=True),
    "adapt .05/.50": dict(q=0.05, q_fast=0.50, firm_noise=True, adaptive=True),
    "adapt .08/.30 nn": dict(q=0.08, q_fast=0.30, adaptive=True),
    "adapt .06/.30 nn": dict(q=0.06, q_fast=0.30, adaptive=True),
    "adapt .10/.30 nn": dict(q=0.10, q_fast=0.30, adaptive=True),
}


def flag_stats(flags, a, b, party):
    days = [d for d in sorted(flags) if a <= d <= b]
    on = [flags[d][party] != 0 for d in days]
    first = next((d for d, o in zip(days, on) if o), None)
    switches = sum(1 for x, y in zip(on, on[1:]) if x and not y)
    return first, sum(on), switches


def raw_flags(polls, a, b):
    out, d = {}, a
    while d <= b:
        m = momentum(polls, d - dt.timedelta(days=1))
        out[d] = {k: (1 if m[k]["mean_change"] > 0 else -1) if m[k]["flag"] else 0 for k in PARTIES}
        d += dt.timedelta(days=1)
    return out


def run(name, polls):
    cfg = SETS[name]
    start = cfg["start"]
    end = cfg["end"] or max(p["published"] for p in polls)
    fa, fb = cfg["focus"]
    print(f"\n=== {name} ({len(polls)} polls); focus {cfg['label']}")
    fl_h = momentum_flags(polls, start - dt.timedelta(days=30), end)
    fl_r = raw_flags(polls, start - dt.timedelta(days=30), end)
    hs = {}
    d = start
    while d <= end:
        h = hindsight(polls, d)
        if h:
            hs[d] = h
        d += dt.timedelta(days=1)
    scores = []
    print(f"  {'variant':15} {'MAE all':>8} {'MAE focus':>9} | live: {'chg/day':>7} {'rev/100d':>8} | "
          f"history: {'chg/day':>7} {'rev/100d':>8} {'gap v hindsight':>15}")
    for v, kw in VARIANTS.items():
        kw = dict(kw)
        adaptive = kw.pop("adaptive", False)
        mae_all, mae_f, lj, lr, hj, hr, gap = [], [], [], [], [], [], []
        for k in PARTIES:
            r = kalman_run(polls, start, end, k, flags=fl_h if adaptive else None, smooth=True, **kw)
            res = [abs(x) for d, f, x, n in r["resid"] if n >= 3]
            resf = [abs(x) for d, f, x, n in r["resid"] if n >= 3 and fa <= d <= fb]
            mae_all.append(st.mean(res))
            mae_f.append(st.mean(resf) if resf else float("nan"))
            j, rv = jumpiness(r["filtered"])
            lj.append(j), lr.append(rv)
            j, rv = jumpiness(r["smoothed"])
            hj.append(j), hr.append(rv)
            gap.append(st.mean(abs(r["smoothed"][d][0] - hs[d][k]) for d in hs if d in r["smoothed"]))
        row = {"dataset": name, "variant": v, "mae_all": st.mean(mae_all), "mae_focus": st.mean(mae_f),
               "live_change_per_day": st.mean(lj), "live_reversals_per_100d": st.mean(lr),
               "history_change_per_day": st.mean(hj), "history_reversals_per_100d": st.mean(hr),
               "history_gap_to_hindsight": st.mean(gap)}
        scores.append({k: (round(x, 3) if isinstance(x, float) else x) for k, x in row.items()})
        print(f"  {v:15} {row['mae_all']:8.3f} {row['mae_focus']:9.3f} | {'':6}{row['live_change_per_day']:7.3f} "
              f"{row['live_reversals_per_100d']:8.1f} | {'':9}{row['history_change_per_day']:7.3f} "
              f"{row['history_reversals_per_100d']:8.1f} {row['history_gap_to_hindsight']:15.2f}")
    flags_out = []
    print("  momentum flag in focus window (first / days on / times it switched off):")
    for k in ("LAB", "CON", "REF"):
        r1, h1 = flag_stats(fl_r, fa, fb, k), flag_stats(fl_h, fa, fb, k)
        print(f"    {k}: raw {r1[0] or '-'} / {r1[1]} / {r1[2]}   hysteresis {h1[0] or '-'} / {h1[1]} / {h1[2]}")
        flags_out.append({"dataset": name, "party": k, "raw_first": r1[0], "raw_days": r1[1], "raw_switch_offs": r1[2],
                          "hyst_first": h1[0], "hyst_days": h1[1], "hyst_switch_offs": h1[2]})
    whole = [flag_stats(fl, start, end, k) for fl in (fl_r, fl_h) for k in PARTIES]
    print(f"  whole period, all parties: raw {sum(w[1] for w in whole[:5])} flag-days, {sum(w[2] for w in whole[:5])} switch-offs; "
          f"hysteresis {sum(w[1] for w in whole[5:])} flag-days, {sum(w[2] for w in whole[5:])} switch-offs")
    return scores, flags_out


def main():
    allscores, allflags = [], []
    sets = [(f"ge{y}", load_testset(C.PROJECT / "testdata" / f"wiki_ge{y}_polls.csv")) for y in (2015, 2017, 2019, 2024)]
    for name, polls in sets + [("live", load_tracker(C.OUTPUTS))]:
        s, f = run(name, polls)
        allscores += s
        allflags += f
    for fn, rows in (("replay_v03_scores.csv", allscores), ("replay_v03_flags.csv", allflags)):
        with (C.OUTPUTS / fn).open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
