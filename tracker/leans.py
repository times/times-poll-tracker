"""outputs/leans.json for the pollster-leans widget: how far each pollster's figures sit from the other
firms', by party, as estimated by the average (outputs/average_house_effects.csv).

    python3 -m tracker.leans

A lean is a firm's house effect relative to the mean of all firms (positive = it tends to show the party
higher), with a margin of error from the filter; 'clear' means the lean is bigger than its margin.
"""
import csv
import datetime as dt
import json
from collections import defaultdict

from . import common as C
from .widget_data import NAMES, PARTIES


def main():
    eff = defaultdict(dict)
    as_of = None
    for r in csv.DictReader((C.OUTPUTS / "average_house_effects.csv").open()):
        lean, sd = float(r["lean"]), float(r["lean_sd"])
        eff[r["pollster_id"]][r["party"]] = {"lean": round(lean, 1), "margin": round(1.96 * sd, 1),
                                            "clear": abs(lean) > 1.96 * sd}
        as_of = r["as_of"]
    end = dt.date.fromisoformat(as_of)
    counts, last = defaultdict(int), {}
    for r in csv.DictReader((C.OUTPUTS / "average_inputs.csv").open()):
        if r["included"] != "True":
            continue
        d = dt.date.fromisoformat(r["fieldwork_end"])
        if (end - d).days <= 365:
            counts[r["pollster_id"]] += 1
        last[r["pollster_id"]] = max(last.get(r["pollster_id"], ""), r["fieldwork_end"])
    firms = [{"id": f, "name": NAMES.get(f, f), "polls_12m": counts[f], "last_poll": last.get(f),
              "leans": eff[f]} for f in sorted(eff, key=lambda f: NAMES.get(f, f))]
    out = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "as_of": as_of,
           "parties": [{"code": c, "name": n, "colour": col, "text_colour": txt} for c, n, col, txt in PARTIES],
           "firms": firms}
    (C.OUTPUTS / "leans.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    big = max(((f["name"], k, v["lean"]) for f in firms for k, v in f["leans"].items() if v["clear"]),
              key=lambda x: abs(x[2]), default=None)
    print(f"leans.json: {len(firms)} pollsters as of {as_of}; biggest clear lean: {big}")


if __name__ == "__main__":
    main()
