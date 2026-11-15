"""Replay chart: Labour as each method saw it in real time v the hindsight line, four campaigns.

    python3 scripts/chart_replay.py    # needs outputs/replay_daily.csv and replay_momentum_flags.csv
"""
import csv
import datetime as dt
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent.parent / "outputs"
D = dt.date
PANELS = [("ge2017", "2017: Labour surge", D(2017, 4, 10), D(2017, 6, 7)),
          ("ge2019", "2019: Labour recovery", D(2019, 10, 20), D(2019, 12, 11)),
          ("ge2024", "2024: Labour slips", D(2024, 5, 15), D(2024, 7, 3)),
          ("live", "2026: Burnham takes over", D(2026, 6, 15), D(2026, 9, 15))]
STYLE = {"hindsight": ("Hindsight (uses later polls)", "#999999", (0, (4, 3)), 1.6),
         "window_avg (v0.1)": ("Old average (v0.1)", "#E89AA8", "-", 2.0),
         "kalman_fast": ("New average (Kalman)", "#E4003B", "-", 2.4)}

rows = list(csv.DictReader((OUT / "replay_daily.csv").open()))
flags = list(csv.DictReader((OUT / "replay_momentum_flags.csv").open()))
fig, axes = plt.subplots(2, 2, figsize=(12, 7.5), dpi=150)
for ax, (ds, title, a, b) in zip(axes.flat, PANELS):
    for m, (lab, col, ls, lw) in STYLE.items():
        pts = [(D.fromisoformat(r["date"]), float(r["LAB"])) for r in rows
               if r["dataset"] == ds and r["method"] == m and a.isoformat() <= r["date"] <= b.isoformat()]
        if pts:
            ax.plot(*zip(*pts), color=col, linestyle=ls, linewidth=lw, label=lab)
    f = sorted(r["date"] for r in flags if r["dataset"] == ds and r["party"] == "LAB" and a.isoformat() <= r["date"] <= b.isoformat())
    if f:
        fd = D.fromisoformat(f[0])
        ax.axvline(fd, color="#333333", linewidth=0.8, linestyle=":")
        ax.text(fd, ax.get_ylim()[1], " momentum flag", fontsize=8, color="#333333", va="top")
    ax.set_title(title, loc="left", fontsize=11, color="#222222")
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%-d %b"))
    ax.grid(axis="y", color="#e5e5e5", linewidth=0.8)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(labelsize=8.5, colors="#555555", length=0)
axes.flat[0].legend(frameon=False, fontsize=8.5, loc="lower right")
fig.suptitle("Labour share as each method showed it at the time, v hindsight", x=0.01, ha="left", fontsize=12.5, color="#222222")
fig.text(0.01, 0.01, "Replay using only polls published by each day (Wikipedia poll lists for 2017-2024, publication assumed fieldwork end + 1 day; "
         "the tracker's own data for 2026). Momentum flag: Labour moved the same way against each firm's previous poll in most polls of the past 7 days.",
         fontsize=7.5, color="#666666", wrap=True)
fig.tight_layout(rect=(0, 0.04, 1, 0.96))
fig.savefig(OUT / "chart_replay.png")
print(OUT / "chart_replay.png")
