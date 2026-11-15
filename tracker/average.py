"""Polling average.

    python3 -m tracker.average

Writes
- outputs/average_daily.csv: the published average (v0.3), one row per day x party.
  share/sd: the history, smoothed with all polls published so far (revised as polls arrive); the
  latest day is the live, forward-only estimate. share_realtime/sd_realtime: what the average
  said on that day at the time. fast_mode: 1 on days the momentum flag was on (filter runs fast).
- outputs/average_house_effects.csv: each firm's estimated lean at the latest date.
- outputs/average_window_daily.csv: the v0.1 windowed firm average below, kept for comparison
  and for Restore Britain (averaged only over firms that name it).
- outputs/average_inputs.csv: every poll, whether it was used and why not.
Why these settings: replay tests across the 2015, 2017, 2019, 2024 campaigns and 2026
(tracker/replay.py, tracker/replay_v03.py; notes/average_method.md).

v0.1 windowed average:

Method (deliberately simple and explainable; see notes/average_method.md):
1. Polls in: standard GB VI, not party/campaign-commissioned, weighted, main series only
   (Find Out Now's Restore Britain-named variant and MRPs excluded). Survation uses its GB
   re-based shares. Shares are re-normalised to 100 over parties.
2. Each firm gets one vote per day. Its estimate on day d is the mean of its polls with fieldwork
   ending in the previous 28 days, weighted by recency (half-life 7 days).
3. Firms are combined with weights that fade with the age of their latest poll (half-life 14 days),
   so a firm polling weekly and one polling monthly count equally when both are fresh.
4. Days with fewer than 3 firms contributing are left blank.
Restore Britain is averaged only over firms that name it; for the others it sits inside Other.
No house-effect adjustment yet.
"""
import csv
import datetime as dt
import math

from . import common as C

PARTIES = ["LAB", "CON", "REF", "LD", "GRN", "SNP", "PC", "RB", "YP", "OTH"]
MAIN = ["LAB", "CON", "REF", "LD", "GRN"]
WINDOW, HALF_POLL, HALF_FIRM, MIN_FIRMS = 28, 7.0, 14.0, 3
START = dt.date(2024, 7, 5)  # day after the 2024 general election


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def inputs():
    polls = {r["poll_id"]: r for r in csv.DictReader((C.OUTPUTS / "polls.csv").open())}
    out = []
    for w in csv.DictReader((C.OUTPUTS / "headlines_wide.csv").open()):
        p = polls.get(w["poll_id"])
        if not p or not w["fieldwork_end"]:
            continue
        why = None
        if w["fieldwork_end"] < START.isoformat():
            why = "before the 2024 general election"
        elif p.get("series") and p["series"] != p["pollster_id"]:
            why = "variant series"
        elif p.get("poll_type") not in (None, "", "standard_vi"):
            why = p["poll_type"]
        elif p.get("commissioner_type") in ("party", "campaign"):
            why = f"commissioned ({p['commissioner_type']})"
        elif str(p.get("weighted")).lower() == "false":
            why = "unweighted"
        gb = {k: _f(w.get(f"{k}_gb")) for k in PARTIES}
        sh = gb if any(v is not None for v in gb.values()) else {k: _f(w.get(k)) for k in PARTIES}
        sh = {k: (v or 0.0) for k, v in sh.items()}
        tot = sum(sh.values())
        if tot <= 0:
            why = why or "no headline"
        else:
            sh = {k: v / tot * 100 for k, v in sh.items()}
        out.append({"poll_id": w["poll_id"], "pollster_id": p["pollster_id"], "end": dt.date.fromisoformat(w["fieldwork_end"]),
                    "rb_named": str(w.get("rb_named")).lower() == "true", "shares": sh, "excluded": why})
    return out


def daily(polls, until=None):
    use = [p for p in polls if not p["excluded"]]
    until = until or max(p["end"] for p in use)
    rows = []
    d = START
    while d <= until:
        firms = {}
        for p in use:
            age = (d - p["end"]).days
            if 0 <= age < WINDOW:
                firms.setdefault(p["pollster_id"], []).append((age, p))
        if len(firms) >= MIN_FIRMS:
            est = {k: 0.0 for k in PARTIES}
            wsum, rb_num, rb_den, npolls = 0.0, 0.0, 0.0, 0
            for f, lst in firms.items():
                pw = [(0.5 ** (a / HALF_POLL), p) for a, p in lst]
                tw = sum(x for x, _ in pw)
                fe = {k: sum(x * p["shares"][k] for x, p in pw) / tw for k in PARTIES}
                fw = 0.5 ** (min(a for a, _ in lst) / HALF_FIRM)
                for k in PARTIES:
                    est[k] += fw * fe[k]
                wsum += fw
                npolls += len(lst)
                named = [(x, p) for x, p in pw if p["rb_named"]]
                if named:
                    rb_num += fw * sum(x * p["shares"]["RB"] for x, p in named) / sum(x for x, _ in named)
                    rb_den += fw
            est = {k: v / wsum for k, v in est.items()}
            rb = rb_num / rb_den if rb_den else None
            for k in PARTIES:
                rows.append({"date": d.isoformat(), "party": k, "share": round(est[k], 2),
                             "n_firms": len(firms), "n_polls": npolls})
            rows.append({"date": d.isoformat(), "party": "RB_named_only", "share": round(rb, 2) if rb is not None else "",
                         "n_firms": sum(1 for lst in firms.values() if any(p["rb_named"] for _, p in lst)),
                         "n_polls": ""})
        d += dt.timedelta(days=1)
    return rows


# v0.3 settings, chosen by replay (notes/average_method.md): slow and steady normally, fast on days
# the momentum flag (with hysteresis) is on; history smoothed with later polls, live edge forward-only
KALMAN_Q, KALMAN_Q_FAST = 0.08, 0.30


def kalman_daily():
    import datetime as _dt
    from .methods import PARTIES as KP, kalman_run, load_tracker, momentum_flags
    polls = load_tracker(C.OUTPUTS)
    end = max(p["published"] for p in polls)
    flags = momentum_flags(polls, START - _dt.timedelta(days=30), end)
    rows, house = [], []
    for k in KP:
        r = kalman_run(polls, START, end, k, q=KALMAN_Q, q_fast=KALMAN_Q_FAST, flags=flags, smooth=True)
        for d in sorted(r["filtered"]):
            lv, sd = r["smoothed"][d]
            lv_rt, sd_rt = r["filtered"][d]
            rows.append({"date": d.isoformat(), "party": k, "share": round(lv, 2), "sd": round(sd, 2),
                         "share_realtime": round(lv_rt, 2), "sd_realtime": round(sd_rt, 2),
                         "fast_mode": int(flags.get(d, {}).get(k, 0) != 0)})
        kf = r["kf"]
        # leans relative to the other firms: centre the house effects, and take their uncertainty from the
        # filter's covariance (the uncertainty shared by every firm, about the overall level, cancels out)
        import numpy as _np
        hs = _np.array(list(kf.house().values()))
        m = len(hs)
        A = _np.eye(m) - _np.ones((m, m)) / m
        cov = A @ kf.P[1:, 1:] @ A.T
        lean = A @ hs
        for i, f in enumerate(kf.house()):
            house.append({"as_of": end.isoformat(), "party": k, "pollster_id": f, "house_effect": round(float(hs[i]), 2),
                          "lean": round(float(lean[i]), 2), "lean_sd": round(float(cov[i, i]) ** 0.5, 2)})
    return rows, house


def main():
    polls = inputs()
    krows, house = kalman_daily()
    with (C.OUTPUTS / "average_daily.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "party", "share", "sd", "share_realtime", "sd_realtime", "fast_mode"])
        w.writeheader()
        w.writerows(krows)
    with (C.OUTPUTS / "average_house_effects.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["as_of", "party", "pollster_id", "house_effect", "lean", "lean_sd"])
        w.writeheader()
        w.writerows(house)
    last = max(r["date"] for r in krows)
    print(f"Kalman average, {last}: " + ", ".join(f"{r['party']} {r['share']:.1f} (±{1.96 * r['sd']:.1f})"
                                                for r in krows if r["date"] == last))
    rows = daily(polls)
    with (C.OUTPUTS / "average_window_daily.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "party", "share", "n_firms", "n_polls"])
        w.writeheader()
        w.writerows(rows)
    with (C.OUTPUTS / "average_inputs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["poll_id", "pollster_id", "fieldwork_end", "included", "excluded_reason"] + PARTIES)
        w.writeheader()
        for p in sorted(polls, key=lambda p: p["end"]):
            w.writerow({"poll_id": p["poll_id"], "pollster_id": p["pollster_id"], "fieldwork_end": p["end"].isoformat(),
                        "included": not p["excluded"], "excluded_reason": p["excluded"] or "",
                        **{k: round(v, 2) for k, v in p["shares"].items()}})
    last = max(r["date"] for r in rows)
    latest = {r["party"]: r["share"] for r in rows if r["date"] == last}
    nf = next(r["n_firms"] for r in rows if r["date"] == last)
    print(f"Window average (v0.1), {last} ({nf} firms): " +
          ", ".join(f"{k} {latest[k]:.1f}" for k in MAIN + ["RB_named_only"] if latest.get(k) not in (None, "")))
    print(f"inputs: {sum(not p['excluded'] for p in polls)} polls included, "
          f"{sum(bool(p['excluded']) for p in polls)} excluded")


if __name__ == "__main__":
    main()
