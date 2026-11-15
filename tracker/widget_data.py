"""Build outputs/widget.json: everything the homepage widget needs, in one small file.

    python3 -m tracker.widget_data

Contents: latest average per party (with change over 7 and 30 days), a weekly series for the
chart (smoothed history ending at the live estimate), the latest polls, momentum flags, and
metadata (update time, method line, sources).
"""
import csv
import datetime as dt
import json

from . import common as C

PARTIES = [("LAB", "Labour", "#da5c5b", "#c5494a"), ("CON", "Conservative", "#5691af", "#437e9c"),
           ("REF", "Reform UK", "#54b3cc", "#398198"), ("LD", "Lib Dem", "#d8ad45", "#957224"),
           ("GRN", "Green", "#72a768", "#4f8247")]
NAMES = {"yougov": "YouGov", "moreincommon": "More in Common", "findoutnow": "Find Out Now", "opinium": "Opinium",
         "survation": "Survation", "bmg": "BMG", "freshwater": "Freshwater Strategy", "trajectory": "Trajectory",
         "ipsos": "Ipsos", "deltapoll": "Deltapoll"}
METHOD = ("The average adjusts each poll for its pollster's usual lean and updates as new polls arrive, "
          "moving steadily when the polls are stable and quickly when several show the same shift.")
N_POLLS = 25


def main():
    avg = {}
    for r in csv.DictReader((C.OUTPUTS / "average_daily.csv").open()):
        avg.setdefault(r["date"], {})[r["party"]] = (float(r["share"]), float(r["sd"]))
    days = sorted(avg)
    last = days[-1]
    ld = dt.date.fromisoformat(last)

    def at(delta):
        d = (ld - dt.timedelta(days=delta)).isoformat()
        return avg.get(d) or avg[min(days, key=lambda x: abs(dt.date.fromisoformat(x) - (ld - dt.timedelta(days=delta))))]

    w7, w30 = at(7), at(30)
    parties = []
    for code, name, col, txt in PARTIES:
        s, sd = avg[last][code]
        parties.append({"code": code, "name": name, "colour": col, "text_colour": txt, "share": round(s, 1),
                        "margin": round(1.96 * sd, 1), "change_7d": round(s - w7[code][0], 1),
                        "change_30d": round(s - w30[code][0], 1)})
    # weekly series (every 7th day back from the latest, so the last point is today's estimate)
    pick = [d for i, d in enumerate(reversed(days)) if i % 7 == 0][::-1]
    series = {"dates": pick, **{code: [round(avg[d][code][0], 1) for d in pick] for code, *_ in PARTIES}}

    polls = {r["poll_id"]: r for r in csv.DictReader((C.OUTPUTS / "polls.csv").open())}
    inputs = {r["poll_id"]: r for r in csv.DictReader((C.OUTPUTS / "average_inputs.csv").open())}
    wide = [r for r in csv.DictReader((C.OUTPUTS / "headlines_wide.csv").open())
            if inputs.get(r["poll_id"], {}).get("included") == "True"]
    wide.sort(key=lambda r: (r["fieldwork_end"], r["published_date"] or ""), reverse=True)
    latest = []
    for r in wide[:N_POLLS]:
        p = polls[r["poll_id"]]
        n = p.get("sample_size_total") or p.get("sample_size_vi_unweighted")
        latest.append({
            "pollster": NAMES.get(r["pollster_id"], r["pollster_id"]), "pollster_id": r["pollster_id"],
            "fieldwork_start": r["fieldwork_start"] or r["fieldwork_end"], "fieldwork_end": r["fieldwork_end"],
            "client": r["client"] or None, "sample": int(float(n)) if n else None,
            "area": r["geography_vi_base"] or "GB",
            "shares": {code: (round(float(r[code])) if r[code] not in ("", None) else None) for code, *_ in PARTIES},
            "source_url": p.get("source_page_url") or p.get("tables_url")})

    mom = json.loads((C.OUTPUTS / "momentum_latest.json").read_text())
    moving = [{"code": k, "sentence": v["sentence"]} for k, v in mom["parties"].items() if v.get("flag_on") and v.get("sentence")]

    out = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "latest_date": last,
           "parties": parties, "series": series, "polls": latest, "moving": moving, "method": METHOD,
           "n_polls_in_average": sum(1 for r in inputs.values() if r["included"] == "True"),
           "pollsters": sorted(NAMES.values())}
    (C.OUTPUTS / "widget.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"widget.json: latest {last}, " + ", ".join(f"{p['code']} {p['share']}" for p in parties) +
          f"; {len(pick)} weekly points; {len(latest)} polls; {len(moving)} moving")


if __name__ == "__main__":
    main()
