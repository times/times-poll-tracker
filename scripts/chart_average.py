"""Chart the published average (Kalman, v0.2) with every included poll behind it.

    python3 scripts/chart_average.py     # writes outputs/chart_average.png
"""
import csv
import datetime as dt
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent.parent / "outputs"
P = [("LAB", "Labour", "#E4003B"), ("CON", "Conservative", "#4093B2"), ("REF", "Reform UK", "#12B6CF"),
     ("LD", "Lib Dem", "#FAA61A"), ("GRN", "Green", "#02A95B")]

avg = list(csv.DictReader((OUT / "average_daily.csv").open()))
inp = [r for r in csv.DictReader((OUT / "average_inputs.csv").open()) if r["included"] == "True"]
START = dt.date(2024, 8, 9)  # first post-election poll (BMG)
avg = [r for r in avg if r["date"] >= START.isoformat()]
inp = [r for r in inp if r["fieldwork_end"] >= START.isoformat()]
fig, ax = plt.subplots(figsize=(12, 6.2), dpi=150)
ends = []
for k, name, col in P:
    xs = [dt.date.fromisoformat(r["fieldwork_end"]) for r in inp]
    ax.scatter(xs, [float(r[k]) for r in inp], s=7, color=col, alpha=0.22, linewidths=0)
    rows = [r for r in avg if r["party"] == k]
    d = [dt.date.fromisoformat(r["date"]) for r in rows]
    v = [float(r["share"]) for r in rows]
    sd = [float(r["sd"]) for r in rows]
    ax.fill_between(d, [a - 1.96 * s for a, s in zip(v, sd)], [a + 1.96 * s for a, s in zip(v, sd)], color=col, alpha=0.05, linewidth=0)
    ax.plot(d, v, color=col, linewidth=2.2, solid_capstyle="round")
    ax.scatter([d[-1]], [v[-1]], s=36, color=col, edgecolors="white", linewidths=1.5, zorder=5)
    ends.append([v[-1], name, d[-1]])
ends.sort(reverse=True)
for i in range(1, len(ends)):  # keep end labels at least 1.4 points apart
    if ends[i - 1][0] - ends[i][0] < 1.4:
        ends[i][0] = ends[i - 1][0] - 1.4
for (y, name, d0), (k, n2, col) in zip(ends, [next(x for x in P if x[1] == e[1]) for e in ends]):
    real = float([r for r in avg if r["party"] == k][-1]["share"])
    ax.annotate(f"{name} {real:.0f}", (d0, y), xytext=(8, 0), textcoords="offset points", va="center",
                fontsize=10, color="#333333")
ax.set_ylim(0, 36)
ax.set_xlim(START, dt.date.fromisoformat(avg[-1]["date"]) + dt.timedelta(days=75))
ax.yaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
ax.grid(axis="y", color="#e5e5e5", linewidth=0.8)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.tick_params(axis="both", labelsize=9, colors="#555555", length=0)
ax.axvspan(dt.date(2026, 7, 1), dt.date(2026, 7, 31), color="#999999", alpha=0.08, linewidth=0)
ax.text(dt.date(2026, 7, 3), 34.5, "Burnham takes over (July)", fontsize=8.5, color="#666666")
ax.set_title("Westminster voting intention: Times poll average (v0.3) and every poll, Aug 2024 to Nov 2026",
             loc="left", fontsize=12, color="#222222")
fig.text(0.01, 0.01, f"Kalman filter with house effects; history smoothed with later polls, dot = live estimate; "
         f"shaded = 95% band. {len(inp)} polls from 10 firms, read from each pollster's own tables.", fontsize=8.5, color="#666666")
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(OUT / "chart_average.png")
print(OUT / "chart_average.png")
