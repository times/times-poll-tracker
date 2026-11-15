"""Undecided voters: how many there are, and which way they lean when pushed.

    python3 -m tracker.undecided

1. Undecided share: from each poll's first voting intention question (before don't knows are squeezed or
   dropped), 'don't know' as a share of people who'd vote: DK / (all parties + DK). 'Won't vote' and
   'refused' are left out, so firms that count non-voters differently are comparable. Firms still ask and
   prompt differently (Find Out Now's DK is about three times Freshwater's), so the same Kalman filter as the
   headline average, with a lean per firm, gives the line.
2. Which way they lean: the follow-up ('squeeze') question put only to the undecided, e.g. 'which party are
   you most inclined to support?'. Used only where the follow-up was asked of a minority of the first
   question's sample (so it really is the undecided); YouGov asks its follow-up of everyone, so isn't used.
   Pooled over the last six months, weighted by sample size.

Writes outputs/undecided_inputs.csv, outputs/undecided_daily.csv and outputs/undecided.json.
"""
import csv
import datetime as dt
import glob
import json
from collections import defaultdict

from . import common as C
from .average import START
from .methods import kalman_run, load_tracker
from .widget_data import PARTIES as WIDGET_PARTIES

PARTY = {"CON", "LAB", "LD", "REF", "GRN", "SNP", "PC", "OTH", "RB", "YP"}
MAIN = ["LAB", "CON", "REF", "LD", "GRN"]
# the first voting intention question, per firm: (question_ref, table_base)
FIRST = {"bmg": [("Table2_WouldVoteTodayRevised", "vi_first")], "findoutnow": [("Voting", "vi_first")],
         "ipsos": [("V1AB", "vi_first")],
         "moreincommon": [("votingintention (raw)", "vi_first"), ("votingintention", "vi_first"), ("votingintention(raw)", "vi_first")],
         "opinium": [("V003", "vi_first")], "survation": [("Table_V2_1", "vi_first"), ("Table_GEVI", "vi_first"), ("Table_V2", "vi_first")],
         "freshwater": [("and_if_you_were_to_vote_who_would_you_v", "vi_first")], "trajectory": [("TABLE1", "as_published")],
         "yougov": [("YG_GENERIC", "as_published")]}
# BMG's follow-up table ('WouldVoteTodayUnsure') is misread (SNP at 25% of GB undecideds, rows summing to
# 125%), so it isn't used until its parser is fixed
SQUEEZE = {"ipsos": ["V2"], "moreincommon": ["votingforced", "votingforced (squeeze)"]}
SQUEEZE_MAX_SHARE = 0.5      # follow-up sample must be under half the first question's (asked of the undecided only)
POOL_DAYS = 182             # few polls ask the follow-up, so pool six months
KALMAN_Q = 0.08


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load(poll_ids):
    """poll_id -> (question_ref, table_base) -> {"sh": {code: pct}, "n": unweighted total}"""
    out = defaultdict(lambda: defaultdict(lambda: {"sh": {}, "n": None}))
    for f in sorted(glob.glob(str(C.OUTPUTS / "crosstabs" / "*.csv"))):
        for r in csv.DictReader(open(f, newline="")):
            if r["poll_id"] not in poll_ids or r["break_std"] != "total" or not r["party_code"]:
                continue
            t = out[r["poll_id"]][(r["question_ref"].strip(), r["table_base"])]
            v = _f(r["pct"])
            if v is not None:
                t["sh"][r["party_code"]] = t["sh"].get(r["party_code"], 0) + v
            t["n"] = t["n"] or _f(r["n_unweighted_col"]) or _f(r["n_weighted_col"])
    return out


def main():
    polls = load_tracker(C.OUTPUTS)
    tabs = load({p["poll_id"] for p in polls})
    end = max(p["published"] for p in polls)
    inputs, und_polls, pool, pool_year = [], [], defaultdict(float), defaultdict(float)
    for p in polls:
        t = tabs.get(p["poll_id"], {})
        first = next((t[k] for k in FIRST.get(p["firm"], []) if k in t and "DK" in t[k]["sh"]), None)
        if not first:
            continue
        sh = first["sh"]
        parties = sum(v for k, v in sh.items() if k in PARTY)
        if parties + sh["DK"] <= 0:
            continue
        und = sh["DK"] / (parties + sh["DK"]) * 100
        n = int(first["n"]) if first["n"] else p["n"]
        und_polls.append({**p, "shares": {"UND": und}, "n": n})
        row = {"poll_id": p["poll_id"], "pollster_id": p["firm"], "published": p["published"].isoformat(),
               "undecided": round(und, 1), "n": n or "", "squeeze_n": "", "squeeze_still_dk": ""}
        # the follow-up put to the undecided
        sq = next((v for (q, tb), v in t.items() if q in SQUEEZE.get(p["firm"], []) and tb == "vi_squeeze"), None)
        if sq and sq["n"] and first["n"] and sq["n"] < SQUEEZE_MAX_SHARE * first["n"]:
            s = sq["sh"]
            named = sum(v for k, v in s.items() if k in PARTY)
            still = s.get("DK", 0)
            age = (end - p["published"]).days
            if named + still > 0:
                row.update({"squeeze_n": int(sq["n"]), "squeeze_still_dk": round(still / (named + still) * 100, 1),
                            **{f"lean_{k}": round(s.get(k, 0) / named * 100, 1) if named else "" for k in MAIN}})
                tgt = pool if age <= POOL_DAYS else pool_year if 365 <= age <= 365 + POOL_DAYS else None
                if tgt is not None:
                    w = sq["n"]
                    tgt["_w"] += w
                    tgt["_still"] += w * still / (named + still) * 100
                    for k in PARTY:
                        if named:
                            tgt["OTH" if k not in MAIN else k] += w * s.get(k, 0) / named * 100
                    tgt["_polls"] += 1
        inputs.append(row)
    cols = ["poll_id", "pollster_id", "published", "undecided", "n", "squeeze_n", "squeeze_still_dk"] + [f"lean_{k}" for k in MAIN]
    with (C.OUTPUTS / "undecided_inputs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(inputs)

    und_polls.sort(key=lambda p: (p["published"], p["firm"]))
    r = kalman_run(und_polls, START, end, "UND", q=KALMAN_Q, smooth=True)
    days = sorted(r["smoothed"])
    with (C.OUTPUTS / "undecided_daily.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "undecided", "sd"])
        w.writeheader()
        for d in days:
            lv, sd = r["smoothed"][d]
            w.writerow({"date": d.isoformat(), "undecided": round(lv, 2), "sd": round(sd, 2)})

    def pooled(pl):
        if not pl.get("_w"):
            return None
        return {"polls": int(pl["_polls"]), "still_undecided": round(pl["_still"] / pl["_w"], 1),
                "lean": {k: round(pl.get(k, 0) / pl["_w"], 1) for k in MAIN + ["OTH"]}}

    pick = [d for i, d in enumerate(reversed(days)) if i % 7 == 0][::-1]
    pick = [d for d in pick if d >= START + dt.timedelta(days=35)]
    lv = {d: r["smoothed"][d][0] for d in days}
    year_ago = min(days, key=lambda d: abs((d - (days[-1] - dt.timedelta(days=365))).days))
    sq_firms = sorted({i["pollster_id"] for i in inputs if i.get("squeeze_n") != "" and
                       (end - dt.date.fromisoformat(i["published"])).days <= POOL_DAYS})
    allv = {}
    for row in csv.DictReader((C.OUTPUTS / "average_daily.csv").open()):
        allv.setdefault(row["date"], {})[row["party"]] = float(row["share"])
    allv = allv[max(allv)]
    allv = {**{k: round(allv[k], 1) for k in MAIN}, "OTH": round(100 - sum(allv[k] for k in MAIN), 1)}
    out = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "latest_date": days[-1].isoformat(),
           "all_voters": allv,
           "parties": [{"code": c, "name": n, "colour": col, "text_colour": txt} for c, n, col, txt in WIDGET_PARTIES],
           "latest": round(lv[days[-1]], 1), "year_ago": round(lv[year_ago], 1),
           "dates": [d.isoformat() for d in pick], "series": [round(lv[d], 1) for d in pick],
           "n_polls": len(und_polls), "pollsters": sorted({p["firm"] for p in und_polls}),
           "lean_now": pooled(pool), "lean_year_ago": pooled(pool_year), "lean_pollsters": sq_firms, "lean_months": POOL_DAYS // 30}
    (C.OUTPUTS / "undecided.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"undecided: {len(und_polls)} polls from {len(out['pollsters'])} firms; latest {out['latest']}% "
          f"(a year ago {out['year_ago']}%); lean (last {POOL_DAYS} days, {', '.join(sq_firms)}): {out['lean_now']}; "
          f"a year earlier: {out['lean_year_ago']}")


if __name__ == "__main__":
    main()
