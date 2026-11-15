"""Momentum check, live: are polls moving against each firm's own previous poll?

    python3 -m tracker.momentum                 # as of today
    python3 -m tracker.momentum --date 2026-07-20

Writes outputs/momentum_latest.json (for the widget / desk) and outputs/momentum_daily.csv
(history since 2025). Method in tracker/methods.py:momentum and notes/average_method.md.
"""
import argparse
import csv
import datetime as dt
import json

from . import common as C
from .methods import PARTIES, load_tracker, momentum, momentum_flags

NAMES = {"LAB": "Labour", "CON": "the Conservatives", "REF": "Reform UK", "LD": "the Lib Dems", "GRN": "the Greens"}


def sentence(k, m):
    if not m["n_polls"]:
        return None
    up = m["mean_change"] > 0
    moved = m["up"] if up else m["down"]
    return (f"{NAMES[k][0].upper() + NAMES[k][1:]} {'up' if up else 'down'} in {moved} of the last {m['n_polls']} polls "
            f"compared with each pollster's previous poll (average {m['mean_change']:+.1f} points)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args()
    polls = load_tracker(C.OUTPUTS)
    day = dt.date.fromisoformat(a.date) if a.date else min(dt.date.today(), max(p["published"] for p in polls))
    m = momentum(polls, day)
    # flag state with hysteresis: switches on when the check fires, off only once the evidence has
    # clearly gone (p > 0.2, mean change < 0.5 or a reversal). State for `day` uses polls to `day`.
    hist = momentum_flags(polls, dt.date(2024, 7, 12), day + dt.timedelta(days=1))
    state = hist[day + dt.timedelta(days=1)]
    latest = {"as_of": day.isoformat(), "lookback_days": 7,
              "parties": {k: {**{x: (round(v, 3) if isinstance(v, float) else v) for x, v in m[k].items()},
                              "flag_on": state[k] != 0,
                              "sentence": sentence(k, m[k]) if state[k] != 0 else None} for k in PARTIES}}
    (C.OUTPUTS / "momentum_latest.json").write_text(json.dumps(latest, indent=1))
    rows = []
    for d in sorted(hist):
        if d > day:
            continue
        mm = momentum(polls, d)
        nxt = hist.get(d + dt.timedelta(days=1), {})
        for k in PARTIES:
            rows.append({"date": d.isoformat(), "party": k, "n_polls": mm[k]["n_polls"], "up": mm[k]["up"],
                         "down": mm[k]["down"], "mean_change": round(mm[k]["mean_change"], 2),
                         "p": round(mm[k]["p"], 4), "fires": mm[k]["flag"], "flag_on": nxt.get(k, 0) != 0})
    with (C.OUTPUTS / "momentum_daily.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Momentum as of {day} (polls published in the previous 7 days v each firm's previous poll):")
    for k in PARTIES:
        x = m[k]
        print(f"  {k:4} {x['up']:2} up {x['down']:2} down {x['same']:2} same  mean {x['mean_change']:+5.1f}  "
              f"p={x['p']:.3f}  {'FLAG ON: ' + latest['parties'][k]['sentence'] if state[k] else ''}")


if __name__ == "__main__":
    main()
