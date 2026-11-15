"""Voting intention by group (sex, age, social grade, EU referendum vote, 2024 vote), smoothed the same way
as the main average.

    python3 -m tracker.groups

For every poll in the main average, the crosstab table whose Total column matches the poll's headline
figures (within 1.5 points, after taking out don't knows) is the source; its breaks are mapped to common
groups. Firms cut age differently, so age bands are built only where a firm's own bands add up exactly
(e.g. 18-24 + 25-34 = 18-34); a firm whose bands don't fit a group simply doesn't count towards it.

Each group and party gets the same Kalman filter as the headline average (house effects, history smoothed
with later polls), weighted by the group's own sample size, without the momentum fast mode (subgroups are
too noisy for it).

Writes outputs/groups_inputs.csv (one row per poll x group), outputs/groups_daily.csv and
outputs/groups.json (for the demographics widget).
"""
import csv
import datetime as dt
import glob
import json
import re
from collections import defaultdict

from . import common as C
from .average import START
from .methods import PARTIES, kalman_run, load_tracker
from .widget_data import PARTIES as WIDGET_PARTIES

KALMAN_Q = 0.08                      # same day-to-day flexibility as the headline average's normal mode
COUNTED = {"CON", "LAB", "LD", "REF", "GRN", "SNP", "PC", "OTH", "RB", "YP"}   # shares re-based on these
MATCH_TOL = 1.5                      # max gap (points) between a table's Total and the poll's headline
MIN_N = 40                           # skip a group in a poll if fewer respondents than this

# group id -> (category, button label, short button label, phrase for headlines). Order = order in the widget.
GROUPS = {
    "sex:male": ("Sex", "Men", "Men", "men"),
    "sex:female": ("Sex", "Women", "Women", "women"),
    "age:18-34": ("Age", "18-34", "18-34", "18 to 34-year-olds"),
    "age:35-64": ("Age", "35-64", "35-64", "35 to 64-year-olds"),
    "age:65+": ("Age", "65+", "65+", "over-65s"),
    "grade:abc1": ("Class", "Middle class (ABC1)", "ABC1", "middle-class (ABC1) voters"),
    "grade:c2de": ("Class", "Working class (C2DE)", "C2DE", "working-class (C2DE) voters"),
    "euref:remain": ("2016 vote", "Remain", "Remain", "Remain voters"),
    "euref:leave": ("2016 vote", "Leave", "Leave", "Leave voters"),
    "ge2024:LAB": ("2024 vote", "Labour", "Lab", "2024 Labour voters"),
    "ge2024:CON": ("2024 vote", "Conservative", "Con", "2024 Conservative voters"),
    "ge2024:REF": ("2024 vote", "Reform", "Ref", "2024 Reform voters"),
    "ge2024:LD": ("2024 vote", "Lib Dem", "LD", "2024 Lib Dem voters"),
    "ge2024:GRN": ("2024 vote", "Green", "Grn", "2024 Green voters"),
}
AGE_TARGETS = {"age:18-34": (18, 34), "age:35-64": (35, 64), "age:65+": (65, 200)}
GRADE_KEYS = ("social_grade", "seg", "seg_1", "socioeconomic_group")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def age_band(label):
    """'18-24', '18 to 24', 'aged 18-24' -> (18, 24); '65+', '55 +' -> (65, 200); '<35' -> (18, 34). Else None
    (so generation labels like 'gen z (18 - 28)' are ignored)."""
    s = label.strip().lower()
    s = re.sub(r"^aged\s+", "", s)
    m = re.fullmatch(r"(\d+)\s*(?:-|to)\s*(\d+)", s)
    if m:
        return int(m[1]), int(m[2])
    m = re.fullmatch(r"(\d+)\s*\+", s)
    if m:
        return int(m[1]), 200
    m = re.fullmatch(r"<\s*(\d+)", s)
    if m:
        return 18, int(m[1]) - 1
    return None


def tile(bands, lo, hi):
    """Pick bands that exactly cover lo..hi without overlap, preferring the fewest pieces. bands: {(a,b): x}."""
    inside = sorted((b for b in bands if b[0] >= lo and b[1] <= hi), key=lambda b: (b[0], -b[1]))
    out, at = [], lo
    while at <= hi:
        nxt = [b for b in inside if b[0] == at]
        if not nxt:
            return None
        b = nxt[0]                    # widest band starting here
        out.append(b)
        at = b[1] + 1
        if b[1] >= hi:
            break
    return out if out and out[-1][1] == hi else None


def rebase(shares):
    tot = sum(v for k, v in shares.items() if k in COUNTED and v is not None)
    if not tot:
        return None
    return {k: v / tot * 100 for k, v in shares.items() if k in COUNTED and v is not None}


def load_tables(poll_ids):
    """poll_id -> {(question_ref, table_base): {break_std: {"shares": {party: pct}, "n": unweighted, "w": weighted}}}"""
    tabs = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"shares": {}, "n": None, "w": None})))
    for f in sorted(glob.glob(str(C.OUTPUTS / "crosstabs" / "*.csv"))):
        for r in csv.DictReader(open(f, newline="")):
            if r["poll_id"] not in poll_ids or not r["party_code"]:
                continue
            cell = tabs[r["poll_id"]][(r["question_ref"], r["table_base"])][r["break_std"]]
            cell["shares"][r["party_code"]] = _f(r["pct"])
            cell["n"] = cell["n"] or _f(r["n_unweighted_col"])
            cell["w"] = cell["w"] or _f(r["n_weighted_col"])
    return tabs


def headline_table(tables, headline):
    """The table whose (re-based) Total matches the poll's headline, or None."""
    best = None
    for key, breaks in tables.items():
        tot = breaks.get("total")
        sh = rebase(tot["shares"]) if tot else None
        if not sh or not all(p in sh for p in PARTIES):
            continue
        gap = max(abs(sh[p] - headline.get(p, 0)) for p in PARTIES)
        if gap <= MATCH_TOL and (best is None or gap < best[0]) and len(breaks) > 1:
            best = (gap, key)
    return tables[best[1]] if best else None


def groups_for(breaks, total_n):
    """Map one table's breaks to {group id: (shares, n)}."""
    out = {}

    def put(g, cells):
        cells = [c for c in cells if c and rebase(c["shares"])]
        if not cells:
            return
        wts = [c["w"] or c["n"] or 0 for c in cells]
        if not sum(wts):
            return
        sh = defaultdict(float)
        for c, w in zip(cells, wts):
            for k, v in rebase(c["shares"]).items():
                sh[k] += v * w / sum(wts)
        n = sum(c["n"] or 0 for c in cells) or (sum(c["w"] or 0 for c in cells) or None)
        if n is None or n >= MIN_N:
            out[g] = (dict(sh), n)

    for g in ("sex:male", "sex:female", "euref:remain", "euref:leave"):
        put(g, [breaks.get(g)])
    for p in ("LAB", "CON", "REF", "LD", "GRN"):
        put(f"ge2024:{p}", [breaks.get(f"ge2024:{p}")])
    ages = {}
    for k, c in breaks.items():
        if k.startswith("age:"):
            b = age_band(k[4:])
            if b and b not in ages:
                ages[b] = c
    for g, (lo, hi) in AGE_TARGETS.items():
        cover = tile(ages, lo, hi)
        if cover:
            put(g, [ages[b] for b in cover])
    grade = {}
    for k, c in breaks.items():
        var, _, val = k.partition(":")
        if var in GRADE_KEYS and val not in grade:
            grade[val] = c
    for g, whole, parts in (("grade:abc1", "abc1", ("ab", "c1")), ("grade:c2de", "c2de", ("c2", "de"))):
        if whole in grade:
            put(g, [grade[whole]])
        elif all(x in grade for x in parts):
            put(g, [grade[x] for x in parts])
    return out


def main():
    polls = load_tracker(C.OUTPUTS)
    tabs = load_tables({p["poll_id"] for p in polls})
    by_group, rows, unmatched = defaultdict(list), [], defaultdict(int)
    for p in polls:
        t = headline_table(tabs.get(p["poll_id"], {}), p["shares"])
        if not t:
            unmatched[p["firm"]] += 1
            continue
        for g, (sh, n) in groups_for(t, p["n"]).items():
            by_group[g].append({**p, "shares": sh, "n": int(n) if n else None})
            rows.append({"poll_id": p["poll_id"], "pollster_id": p["firm"], "published": p["published"].isoformat(),
                         "group": g, "n": int(n) if n else "", **{k: round(sh.get(k, 0), 1) for k in PARTIES}})
    with (C.OUTPUTS / "groups_inputs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["poll_id", "pollster_id", "published", "group", "n"] + PARTIES)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["group"], r["published"], r["poll_id"])))

    end = max(p["published"] for p in polls)
    daily, latest = [], {}
    for g in GROUPS:
        ps = sorted(by_group.get(g, []), key=lambda p: (p["published"], p["firm"]))
        if len(ps) < 20:
            continue
        for party in PARTIES:
            r = kalman_run(ps, START, end, party, q=KALMAN_Q, smooth=True)
            for d in sorted(r["smoothed"]):
                lv, sd = r["smoothed"][d]
                daily.append({"date": d.isoformat(), "group": g, "party": party, "share": round(lv, 2), "sd": round(sd, 2)})
    with (C.OUTPUTS / "groups_daily.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "group", "party", "share", "sd"])
        w.writeheader()
        w.writerows(daily)

    # widget file: weekly points ending on the latest day, as in widget.json
    series = defaultdict(dict)
    for r in daily:
        series[r["group"]].setdefault(r["date"], {})[r["party"]] = r["share"]
    days = sorted({r["date"] for r in daily})
    pick = [d for i, d in enumerate(reversed(days)) if i % 7 == 0][::-1]
    first_line = (dt.date.fromisoformat(START.isoformat()) + dt.timedelta(days=35)).isoformat()
    pick = [d for d in pick if d >= first_line]
    groups = []
    for g, (cat, label, short, phrase) in GROUPS.items():
        if g not in series:
            continue
        ps = by_group[g]
        recent = [p for p in ps if (end - p["published"]).days <= 90]
        groups.append({
            "id": g, "category": cat, "label": label, "short": short, "phrase": phrase,
            "latest": {k: round(series[g][days[-1]][k], 1) for k in PARTIES},
            "series": {k: [round(series[g][d][k], 1) if d in series[g] else None for d in pick] for k in PARTIES},
            "first": min(series[g]),
            "n_polls": len(ps), "n_polls_90d": len(recent),
            "pollsters": sorted({p["firm"] for p in ps}),
            "typical_n": int(sorted(p["n"] for p in recent if p["n"])[len([p for p in recent if p["n"]]) // 2]) if any(p["n"] for p in recent) else None,
        })
    overall = {}
    for r in csv.DictReader((C.OUTPUTS / "average_daily.csv").open()):
        overall.setdefault(r["date"], {})[r["party"]] = float(r["share"])
    allv = overall.get(days[-1]) or overall[max(overall)]
    out = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "latest_date": days[-1],
           "parties": [{"code": c, "name": n, "colour": col, "text_colour": txt} for c, n, col, txt in WIDGET_PARTIES],
           "all_voters": {k: round(allv[k], 1) for k in PARTIES},
           "dates": pick, "categories": list(dict.fromkeys(v[0] for v in GROUPS.values())), "groups": groups}
    (C.OUTPUTS / "groups.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))

    print(f"groups: {len(rows)} poll x group rows; polls without a usable crosstab table: "
          + (", ".join(f"{k} {v}" for k, v in sorted(unmatched.items())) or "none"))
    for gr in groups:
        lt = gr["latest"]
        print(f"  {gr['id']:13} {gr['n_polls']:4} polls ({gr['n_polls_90d']:3} in 90d, typical n {gr['typical_n']}), "
              f"{len(gr['pollsters'])} firms | " + ", ".join(f"{k} {lt[k]:.1f}" for k in PARTIES))


if __name__ == "__main__":
    main()
