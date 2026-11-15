"""Replay test: run each method day by day using only polls published by that day, and score it.

    python3 -m tracker.replay            # both datasets; writes outputs/replay_*.csv

Datasets
- ge2015, ge2017, ge2019, ge2024: Wikipedia polls before each election (testdata/), publication =
  fieldwork end + 1 day; focus = the campaign.
- live:   the tracker's own polls Jan 2025 - now (average inclusion rules), real upload dates.

Scores
1. One-step-ahead error: for each poll from a firm with >=3 earlier polls, how far it lands from
   the method's estimate the day before plus that firm's usual offset. Lower = tracks opinion
   better without chasing noise. Reported overall and for the window of interest.
2. Snapshot on key dates against a hindsight benchmark (centred 15-day mean of all polls by
   fieldwork date, which uses future polls - what a smoother shows after the fact).
3. First day the momentum check flags each party in the window of interest.
"""
import csv
import datetime as dt
import statistics as st

from . import common as C
from .methods import PARTIES, load_testset, load_tracker, momentum, run_kalman, window_average

D = dt.date
SETS = {
    "ge2024": {"start": D(2023, 9, 1), "end": D(2024, 7, 3), "focus": (D(2024, 5, 22), D(2024, 7, 3)),
               "keys": [D(2024, 5, 22), D(2024, 6, 3), D(2024, 6, 10), D(2024, 6, 17), D(2024, 6, 24), D(2024, 7, 3)],
               "label": "2024 campaign (22 May - 3 Jul 2024)"},
    "ge2019": {"start": D(2019, 3, 1), "end": D(2019, 12, 11), "focus": (D(2019, 10, 30), D(2019, 12, 11)),
               "keys": [D(2019, 10, 30), D(2019, 11, 6), D(2019, 11, 13), D(2019, 11, 20), D(2019, 11, 27),
                        D(2019, 12, 4), D(2019, 12, 11)],
               "label": "2019 campaign (30 Oct - 11 Dec 2019)"},
    "ge2017": {"start": D(2016, 11, 1), "end": D(2017, 6, 7), "focus": (D(2017, 4, 18), D(2017, 6, 7)),
               "keys": [D(2017, 4, 18), D(2017, 4, 30), D(2017, 5, 10), D(2017, 5, 20), D(2017, 5, 30), D(2017, 6, 7)],
               "label": "2017 campaign (18 Apr - 7 Jun 2017)"},
    "ge2015": {"start": D(2014, 11, 1), "end": D(2015, 5, 6), "focus": (D(2015, 3, 30), D(2015, 5, 6)),
               "keys": [D(2015, 3, 30), D(2015, 4, 10), D(2015, 4, 20), D(2015, 4, 30), D(2015, 5, 6)],
               "label": "2015 campaign (30 Mar - 6 May 2015)"},
    "live": {"start": D(2025, 3, 1), "end": None, "focus": (D(2026, 6, 15), D(2026, 9, 15)),
             "keys": [D(2026, 6, 30), D(2026, 7, 14), D(2026, 7, 28), D(2026, 8, 11), D(2026, 8, 25), D(2026, 9, 8)],
             "label": "Burnham takeover (15 Jun - 15 Sep 2026)"},
}
KALMAN = {"kalman_slow": {"q": 0.01}, "kalman_mid": {"q": 0.04}, "kalman_fast": {"q": 0.15},
          "kalman_vfast": {"q": 0.5},
          "kalman_adaptive": {"q": 0.02, "adaptive": True}}


def hindsight(polls, day, half=7):
    xs = [p for p in polls if abs((p["end"] - day).days) <= half]
    if len(xs) < 3:
        return None
    return {k: st.mean(p["shares"].get(k, 0) for p in xs) for k in PARTIES}


def window_series(polls, start, end):
    out, d = {}, start
    while d <= end:
        out[d] = window_average(polls, d)
        d += dt.timedelta(days=1)
    return out


def predictive_errors(polls, est_by_day, start, focus):
    """For a level-only method: residual of each poll v (estimate the day before + firm offset,
    offset = mean of that firm's previous residuals, last 6)."""
    hist, errs = {}, {k: {"all": [], "focus": []} for k in PARTIES}
    for p in polls:
        prev_day = p["published"] - dt.timedelta(days=1)
        e = est_by_day.get(prev_day)
        if not e or p["published"] < start:
            continue
        h = hist.setdefault(p["firm"], {k: [] for k in PARTIES})
        for k in PARTIES:
            raw = p["shares"].get(k, 0) - e[k]
            if len(h[k]) >= 3:
                err = raw - st.mean(h[k][-6:])
                errs[k]["all"].append(abs(err))
                if focus[0] <= p["published"] <= focus[1]:
                    errs[k]["focus"].append(abs(err))
            h[k].append(raw)
    return errs


def kalman_errors(polls, start, end, focus, **kw):
    """Run the filter and collect each poll's pre-update residual (house effect included)."""
    from .methods import Kalman, momentum as mom
    import numpy as np
    errs, series = {k: {"all": [], "focus": []} for k in PARTIES}, {}
    for k in PARTIES:
        first = [p for p in polls if p["published"] <= start + dt.timedelta(days=30)]
        kf = Kalman(k, l0=float(np.mean([p["shares"].get(k, 0) for p in first])),
                    **{a: b for a, b in kw.items() if a != "adaptive"})
        by_day = {}
        for p in polls:
            by_day.setdefault(p["published"], []).append(p)
        counts, d = {}, min(p["published"] for p in polls)
        while d <= end:
            scale = 1.0
            if kw.get("adaptive"):
                m = mom(polls, d - dt.timedelta(days=1), parties=[k]).get(k)
                scale = 6.0 if m and m["flag"] else 1.0
            kf.predict_to(d, q_scale=scale)
            for p in by_day.get(d, []):
                resid, _ = kf.update(p)
                c = counts.get(p["firm"], 0)
                if c >= 3 and d >= start:
                    errs[k]["all"].append(abs(resid))
                    if focus[0] <= d <= focus[1]:
                        errs[k]["focus"].append(abs(resid))
                counts[p["firm"]] = c + 1
            if d >= start:
                series.setdefault(d, {})[k] = kf.level
            d += dt.timedelta(days=1)
    return errs, series


def run(name, polls):
    cfg = SETS[name]
    start = cfg["start"]
    end = cfg["end"] or max(p["published"] for p in polls)
    focus = cfg["focus"]
    print(f"\n=== {name}: {len(polls)} polls, {len({p['firm'] for p in polls})} firms; focus {cfg['label']}")
    results, series = {}, {}
    w = window_series(polls, start - dt.timedelta(days=60), end)
    results["window_avg (v0.1)"] = predictive_errors(polls, w, start, focus)
    series["window_avg (v0.1)"] = {d: v for d, v in w.items() if d >= start and v}
    for label, kw in KALMAN.items():
        e, s = kalman_errors(polls, start, end, focus, **kw)
        results[label], series[label] = e, s
    # 1. predictive error table
    print("\nMean absolute error predicting each firm's next poll (points), all parties averaged:")
    print(f"  {'method':22} {'whole period':>13} {'focus window':>13}   per party (focus): " + " ".join(f"{k:>5}" for k in PARTIES))
    rows = []
    for m, e in results.items():
        allm = st.mean(st.mean(e[k]["all"]) for k in PARTIES)
        foc = st.mean(st.mean(e[k]["focus"]) for k in PARTIES if e[k]["focus"])
        per = " ".join(f"{st.mean(e[k]['focus']):5.2f}" for k in PARTIES)
        print(f"  {m:22} {allm:13.2f} {foc:13.2f}   {' ' * 20}{per}")
        rows.append({"dataset": name, "method": m, "mae_all": round(allm, 3), "mae_focus": round(foc, 3),
                     **{f"mae_focus_{k}": round(st.mean(e[k]['focus']), 3) for k in PARTIES},
                     "n_focus": len(e["LAB"]["focus"])})
    # 2. snapshots
    print("\nLabour / populist right (UKIP, Brexit Party, Reform) on key dates, as known that day, v hindsight:")
    print(f"  {'date':10} " + " ".join(f"{m[:16]:>17}" for m in series) + f" {'hindsight':>17}")
    snaps = []
    for d in cfg["keys"]:
        if d > end:
            continue
        hs = hindsight(polls, d)
        cells = []
        for m, s in series.items():
            v = s.get(d)
            cells.append(f"{v['LAB']:5.1f} / {v['REF']:5.1f}" if v else f"{'-':>13}")
            if v:
                snaps.append({"dataset": name, "date": d.isoformat(), "method": m, **{k: round(v[k], 2) for k in PARTIES}})
        if hs:
            snaps.append({"dataset": name, "date": d.isoformat(), "method": "hindsight", **{k: round(hs[k], 2) for k in PARTIES}})
        print(f"  {d.isoformat():10} " + " ".join(f"{c:>17}" for c in cells) + f" {hs['LAB']:7.1f} / {hs['REF']:5.1f}" if hs else "")
    # 3. momentum flags in focus window
    print("\nMomentum check in the focus window (first flag, then days flagged):")
    flags = []
    d = focus[0]
    while d <= min(focus[1], end):
        m = momentum(polls, d)
        for k in PARTIES:
            if m[k]["flag"]:
                flags.append({"dataset": name, "date": d.isoformat(), "party": k,
                              "direction": "up" if m[k]["mean_change"] > 0 else "down",
                              "up": m[k]["up"], "down": m[k]["down"], "n_polls": m[k]["n_polls"],
                              "mean_change": round(m[k]["mean_change"], 2), "p": round(m[k]["p"], 4)})
        d += dt.timedelta(days=1)
    for k in PARTIES:
        fk = [f for f in flags if f["party"] == k]
        if fk:
            f0 = fk[0]
            print(f"  {k:4} first {f0['date']} ({f0['direction']}: {f0['down'] if f0['direction']=='down' else f0['up']} of "
                  f"{f0['n_polls']} polls, mean {f0['mean_change']:+.1f}, p={f0['p']:.3f}); flagged on {len(fk)} days")
        else:
            print(f"  {k:4} never flagged")
    # daily series for charts
    daily = []
    for m, s in series.items():
        for d, v in sorted(s.items()):
            daily.append({"dataset": name, "method": m, "date": d.isoformat(), **{k: round(v[k], 2) for k in PARTIES}})
    d = start
    while d <= end:
        hs = hindsight(polls, d)
        if hs:
            daily.append({"dataset": name, "method": "hindsight", "date": d.isoformat(), **{k: round(hs[k], 2) for k in PARTIES}})
        d += dt.timedelta(days=1)
    return rows, snaps, flags, daily


def write(name, rows):
    if not rows:
        return
    with (C.OUTPUTS / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        w.writeheader()
        w.writerows(rows)


def main():
    out = {"replay_scores.csv": [], "replay_snapshots.csv": [], "replay_momentum_flags.csv": [], "replay_daily.csv": []}
    sets = [(f"ge{y}", load_testset(C.PROJECT / "testdata" / f"wiki_ge{y}_polls.csv")) for y in (2015, 2017, 2019, 2024)]
    for name, polls in sets + [("live", load_tracker(C.OUTPUTS))]:
        for k, v in zip(out, run(name, polls)):
            out[k] += v
    for k, v in out.items():
        write(k, v)


if __name__ == "__main__":
    main()
