"""Datawrapper poll-tracker chart: average lines plus every poll as dots. Creates or updates a
DRAFT (never publishes).

    DW_KEY=... python3 scripts/datawrapper_tracker.py            # create, or update the chart in
                                                                 # outputs/datawrapper_chart_ids.json
    DW_KEY=... python3 scripts/datawrapper_tracker.py --data-only  # later refreshes: data only, so
                                                                 # hand edits made in Datawrapper stay

Chart type d3-lines. Data: one row per day with the five average lines (smoothed history,
ending at the live estimate); every poll adds a row on its fieldwork-end date carrying that poll's
party shares in five 'poll' columns, drawn as dots with the line hidden.
The API key is read from the environment and never written anywhere.
"""
import csv
import json
import os
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "outputs"
IDS = OUT / "datawrapper_chart_ids.json"
API = "https://api.datawrapper.de/v3"
P = [("LAB", "Labour", "#E4003B"), ("CON", "Conservative", "#0087DC"), ("REF", "Reform UK", "#12B6CF"),
     ("LD", "Lib Dem", "#FAA61A"), ("GRN", "Green", "#02A95B")]
START = "2024-07-05"


def call(method, path, body=None, ctype="application/json"):
    key = os.environ["DW_KEY"]
    data = None
    if body is not None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        return json.loads(raw) if raw and r.headers.get("Content-Type", "").startswith("application/json") else raw


def build_csv():
    avg = {}
    for r in csv.DictReader((OUT / "average_daily.csv").open()):
        if r["date"] >= START:
            avg.setdefault(r["date"], {})[r["party"]] = float(r["share"])
    polls = [r for r in csv.DictReader((OUT / "average_inputs.csv").open())
             if r["included"] == "True" and r["fieldwork_end"] >= START]
    by_day = {}
    for p in polls:
        by_day.setdefault(p["fieldwork_end"], []).append(p)
    header = ["Date"] + [n for _, n, _ in P] + [f"{n} poll" for _, n, _ in P]
    rows = []
    for d in sorted(avg):
        line = [f"{avg[d].get(k, ''):.1f}" if k in avg[d] else "" for k, _, _ in P]
        day_polls = by_day.get(d, [])
        if not day_polls:
            rows.append([d] + line + [""] * len(P))
        for p in day_polls:
            rows.append([d] + line + [f"{float(p[k]):.0f}" for k, _, _ in P])
    out = [",".join(header)] + [",".join(r) for r in rows]
    return "\n".join(out) + "\n", len(polls), max(avg)


def metadata(n_polls, last):
    lines = {}
    for _, name, col in P:
        lines[name] = {"width": "style1", "symbols": {"enabled": False}, "directLabel": True}
        lines[f"{name} poll"] = {"width": "invisible", "opacity": 0.35, "directLabel": False,
                                 "symbols": {"on": "every", "size": 3, "style": "fill", "enabled": True,
                                             "opacity": 0.35}}
    colors = {name: col for _, name, col in P}
    colors.update({f"{name} poll": col for _, name, col in P})
    return {
        "describe": {
            "intro": "Westminster voting intention, % (the Times poll average and every poll since the 2024 general election)",
            "source-name": "YouGov, More in Common, Find Out Now, Opinium, Survation, BMG, Freshwater Strategy, "
                           "Trajectory, Ipsos, Deltapoll; Times analysis",
            "byline": "",
        },
        "annotate": {
            "notes": (f"Dots are individual polls ({n_polls} since 5 July 2024), read from each pollster's own data "
                      "tables. Lines are the Times average: a Kalman filter that allows for each pollster's house "
                      "effect, with the history smoothed using later polls. Latest: "
                      f"{last}. Great Britain."),
        },
        "visualize": {
            "custom-colors": colors,
            "lines": lines,
            "y-grid-format": "0",
            "custom-range-y": [0, 40],
            "y-grid": "on",
            "x-grid": "off",
            "interpolation": "linear",
            "label-colors": True,
            "show-tooltips": True,
            "legend": {"enabled": False},
            "plotHeightMode": "fixed",
            "plotHeightFixed": 420,
        },
        "publish": {"blocks": {"logo": {"enabled": False}}},
    }


def main():
    data_only = "--data-only" in sys.argv
    csvtext, n_polls, last = build_csv()
    ids = json.loads(IDS.read_text()) if IDS.exists() else {}
    cid = ids.get("poll_tracker")
    if not cid:
        cid = call("POST", "/charts", {"title": "The Times poll tracker", "type": "d3-lines"})["id"]
        ids["poll_tracker"] = cid
        IDS.write_text(json.dumps(ids, indent=1) + "\n")
        data_only = False
    call("PUT", f"/charts/{cid}/data", csvtext, ctype="text/csv")
    if not data_only:
        call("PATCH", f"/charts/{cid}", {"language": "en-GB", "metadata": metadata(n_polls, last)})
    print(f"chart {cid}: {csvtext.count(chr(10)) - 1} rows, {n_polls} polls, latest {last} "
          f"({'data only' if data_only else 'data + settings'}); draft, not published")
    print(f"edit: https://app.datawrapper.de/chart/{cid}/visualize")
    try:
        png = call("GET", f"/charts/{cid}/export/png?width=900&zoom=2&plain=false")
        (OUT / "datawrapper_tracker_preview.png").write_bytes(png)
        print("preview: outputs/datawrapper_tracker_preview.png")
    except Exception as e:
        print(f"no preview export ({e})")


if __name__ == "__main__":
    main()
