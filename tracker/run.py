"""Fetch and parse new polls.

    cd times-poll-tracker
    python3 -m tracker.run                      # all scrapers, polls since 2026-01-01
    python3 -m tracker.run yougov opinium --since 2025-07-01
    python3 -m tracker.run --reparse            # re-parse archived files only, no network

Raw files go to data/raw/<pollster>/ (fetched once, hashed, in manifest.csv);
one JSON per poll goes to data/extracted/<pollster>/. Then run tracker.build_tables.
"""
import argparse
import datetime as dt
import json
import re
import traceback

from . import common as C
from .scrapers import bmg, deltapoll, findoutnow, freshwater, ipsos, moreincommon, opinium, survation, trajectory, yougov

SCRAPERS = {m.PID: m for m in (yougov, moreincommon, findoutnow, opinium, survation, bmg, freshwater,
                                trajectory, ipsos, deltapoll)}
ERRLOG = C.DATA / "errors.log"


def log_error(pid, url, exc):
    with ERRLOG.open("a") as f:
        f.write(f"{dt.datetime.now().isoformat(timespec='seconds')}\t{pid}\t{url}\t{exc!r}\n")


def process(mod, meta):
    try:
        d = mod.parse(C.REPO / meta["path"], meta)
    except Exception as e:  # keep going; one bad file shouldn't stop the run
        log_error(mod.PID, meta["url"], e)
        print(f"  ! {mod.PID} parse failed: {meta['url']}\n    {e!r}")
        traceback.print_exc(limit=1)
        return "error"
    if d is None:
        print(f"  - {mod.PID}: not a standard VI file, skipped: {meta['url']}")
        return "skipped"
    C.apply_overrides(d["poll"])
    if not d["poll"].get("overridden"):
        C.sanity_dates(d["poll"], fix_old=getattr(mod, "FIX_OLD_DATES", True))
    pid = d["poll"]["poll_id"]
    for k in ("questions", "options", "results", "headline"):
        for r in d[k]:
            r["poll_id"] = pid
    out = C.EXTRACTED / mod.PID / f"{pid}.json"
    if out.exists():
        old = json.loads(out.read_text())
        newer = re.search(r"updat|correct|revis", d["poll"]["tables_url"], re.I)
        older = re.search(r"updat|correct|revis", old["poll"]["tables_url"], re.I)
        if old["poll"]["tables_url"] != d["poll"]["tables_url"] and older and not newer:
            print(f"  = {pid}: kept the updated file, skipped {meta['url'].split('/')[-1]}")
            return "skipped"
        if old["poll"]["tables_url"] != d["poll"]["tables_url"] and newer and not older:
            d["poll"]["notes"] = ((d["poll"]["notes"] or "") + f" Supersedes {old['poll']['tables_url']}.").strip()
        elif old["poll"]["tables_url"] != d["poll"]["tables_url"]:
            same = ({h["party_code"]: round(h["pct_from_tables"], 1) for h in old["headline"]} ==
                    {h["party_code"]: round(h["pct_from_tables"], 1) for h in d["headline"]})
            if same:
                print(f"  = {pid}: duplicate upload, kept first ({meta['url'].split('/')[-1]})")
                return "skipped"
            pid2 = pid + "-b"
            print(f"  ? {pid}: a second, different file has the same fieldwork end; saved as {pid2}")
            d["poll"]["poll_id"] = pid2
            d["poll"]["notes"] = ((d["poll"]["notes"] or "") + f" Same fieldwork end as {pid}; check which is the published poll.").strip()
            for k in ("questions", "options", "results", "headline"):
                for r in d[k]:
                    r["poll_id"] = pid2
    C.write_extracted(d)
    hl = ", ".join(f"{k} {v:.0f}" for k, v in sorted(((h["party_code"], h["pct_from_tables"]) for h in d["headline"]),
                                                       key=lambda x: -x[1])[:5])
    print(f"  + {d['poll']['poll_id']}  {hl}")
    return "ok"


def yougov_tracker(reparse):
    """Backfill weeks with no results PDF from YouGov's tracker spreadsheet, and check the
    PDF headlines against it (tracker 'Other' = PDF RB + YP + OTH)."""
    if reparse:
        rows = [m for m in C.load_manifest().values() if "tracker_voting-intention" in m["path"]]
        if not rows:
            return
        meta = sorted(rows, key=lambda m: m["path"])[-1]
    else:
        meta = yougov.fetch_tracker()
    have = {}
    for f in (C.EXTRACTED / "yougov").glob("*.json"):
        d = json.loads(f.read_text())
        if d["poll"]["extraction_status"] != "headline_only":
            have[d["poll"]["fieldwork_end"]] = {h["party_code"]: h["pct_from_tables"] for h in d["headline"]}
    polls, checks = yougov.parse_tracker(C.REPO / meta["path"], meta, set(have))
    for d in polls:
        C.write_extracted(d)
    bad = []
    for date, t in checks.items():
        pdf = dict(have[date])
        pdf["OTH"] = sum(pdf.pop(k, 0) for k in ("OTH", "RB", "YP"))
        # OTH is a sum of three separately rounded PDF figures, so allow 1.5pt there
        diff = {k: (t.get(k), pdf.get(k)) for k in set(t) | set(pdf)
                if abs((t.get(k) or 0) - (pdf.get(k) or 0)) > (1.5 if k == "OTH" else 0.5)}
        if diff:
            bad.append((date, diff))
    print(f"  tracker: {len(polls)} headline-only weeks added; {len(checks) - len(bad)}/{len(checks)} PDF polls match the tracker")
    for date, diff in bad:
        print(f"    mismatch {date}: {diff}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pollsters", nargs="*", default=list(SCRAPERS))
    ap.add_argument("--since", default="2026-01-01")
    ap.add_argument("--reparse", action="store_true", help="re-parse archived files, no network")
    a = ap.parse_args()
    for pid in a.pollsters:
        mod = SCRAPERS[pid]
        print(f"== {pid}")
        counts = {"ok": 0, "skipped": 0, "error": 0}
        if a.reparse:
            for f in (C.EXTRACTED / pid).glob("*.json"):
                f.unlink()
            metas = sorted((m for m in C.load_manifest().values()
                            if m["pollster_id"] == pid and "tracker_" not in m["path"]),
                           key=lambda m: m.get("published_at") or "")
        else:
            metas = []
            for found in mod.discover(a.since):
                try:
                    row = C.archive(pid, found["url"], found.get("page_url"), found.get("published_at"))
                except Exception as e:
                    log_error(pid, found["url"], e)
                    print(f"  ! download failed {found['url']}: {e!r}")
                    counts["error"] += 1
                    continue
                metas.append({**row, **{k: v for k, v in found.items() if k not in ("url",)},
                              "page_url": found.get("page_url"), "published_at": found.get("published_at")})
        for meta in metas:
            meta.setdefault("page_url", meta.get("source_page_url"))
            counts[process(mod, meta)] += 1
        if pid == "yougov":
            yougov_tracker(a.reparse)
        print(f"   {pid}: {counts}")


if __name__ == "__main__":
    main()
