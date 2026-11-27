"""Check every pollster for new polls and add them to the master files, without re-downloading
or re-parsing anything already known.

    cd times-poll-tracker
    python3 -m tracker.update                 # all firms
    python3 -m tracker.update opinium yougov  # some firms
    python3 -m tracker.update --dry-run       # list new files, download nothing
    python3 -m tracker.update --lookback 90   # look further back than the default 45 days

How it stays cheap:
- Master files (committed): outputs/polls.csv, headlines.csv, headlines_wide.csv, questions.csv,
  options.csv. registry/files_seen.csv lists every tables file ever looked at (URL, hash, what
  happened to it, which poll it became).
- For each firm, discovery only looks back `lookback` days from that firm's latest poll in
  polls.csv (catching late uploads and re-uploads), and any URL already in files_seen.csv is
  skipped before download. Ipsos release pages already checked are listed in
  registry/pages_seen.txt so they aren't re-opened.
- New polls are merged into the master CSVs by poll_id (replacing a poll if it was re-parsed),
  so this works on a fresh clone that has none of the raw files.
Full rebuild from every archived file is still `python3 -m tracker.run --reparse` then
`python3 -m tracker.build_tables`.
"""
import argparse
import csv
import datetime as dt
import json
import time

from . import common as C
from .build_tables import PARTIES
from .run import SCRAPERS, log_error, process
from .widget_data import NAMES

SEEN = C.PROJECT / "registry" / "files_seen.csv"
SEEN_COLS = ["pollster_id", "url", "source_page_url", "published_at", "sha256", "status", "poll_id",
             "first_seen", "extra"]
DEFAULT_START = "2024-07-05"


def load_seen():
    if not SEEN.exists():
        return {}
    with SEEN.open() as f:
        return {r["url"]: r for r in csv.DictReader(f)}


def save_seen(seen):
    rows = sorted(seen.values(), key=lambda r: (r["pollster_id"], r.get("published_at") or "", r["url"]))
    with SEEN.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SEEN_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def latest_by_firm():
    p = C.OUTPUTS / "polls.csv"
    out = {}
    if p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                if r.get("extraction_status") != "headline_only" or r["pollster_id"] != "yougov":
                    out[r["pollster_id"]] = max(out.get(r["pollster_id"], ""), r["fieldwork_end"] or "")
    return out


def _read(path):
    if not path.exists():
        return [], []
    with path.open() as f:
        rd = csv.DictReader(f)
        return list(rd), rd.fieldnames or []


def merge(new_polls):
    """Merge freshly extracted polls into the master CSVs (replace by poll_id)."""
    if not new_polls:
        return
    ids = {d["poll"]["poll_id"] for d in new_polls}
    tables = {
        "polls.csv": [d["poll"] for d in new_polls],
        "headlines.csv": [h for d in new_polls for h in d["headline"]],
        "questions.csv": [q for d in new_polls for q in d["questions"]],
        "options.csv": [o for d in new_polls for o in d["options"]],
    }
    for name, add in tables.items():
        rows, cols = _read(C.OUTPUTS / name)
        rows = [r for r in rows if r.get("poll_id") not in ids] + add
        cols = list(dict.fromkeys(cols + [k for r in add for k in r]))
        if name == "polls.csv":
            rows.sort(key=lambda r: (r.get("fieldwork_end") or "", r.get("pollster_id") or ""))
        with (C.OUTPUTS / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    # wide headlines: rebuild from the merged long table + polls
    polls, _ = _read(C.OUTPUTS / "polls.csv")
    heads, _ = _read(C.OUTPUTS / "headlines.csv")
    opts, _ = _read(C.OUTPUTS / "options.csv")
    by, by_gb = {}, {}
    for h in heads:
        by.setdefault(h["poll_id"], {})[h["party_code"]] = round(float(h["pct_from_tables"]), 2)
        if h.get("pct_gb"):
            by_gb.setdefault(h["poll_id"], {})[h["party_code"]] = round(float(h["pct_gb"]), 2)
    rb = {o["poll_id"] for o in opts if o["party_code"] == "RB"}
    wide = []
    for p in polls:
        row = {k: p.get(k) for k in ("poll_id", "pollster_id", "fieldwork_start", "fieldwork_end", "published_date",
                                     "geography_vi_base", "sample_size_total", "headline_method", "client")}
        row.update({k: by.get(p["poll_id"], {}).get(k) for k in PARTIES})
        if p["poll_id"] in by_gb:
            row.update({f"{k}_gb": by_gb[p["poll_id"]].get(k) for k in PARTIES})
        row["rb_named"] = p["poll_id"] in rb
        wide.append(row)
    cols = list(dict.fromkeys(k for r in wide for k in r))
    with (C.OUTPUTS / "headlines_wide.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(wide)
    # crosstabs: merge into the per-pollster-year files
    C.write_crosstabs([r for d in new_polls for r in d["results"]], replace_ids=ids)


def seed():
    """Record every archived file (and the poll it became) so update never re-fetches it."""
    by_url = {}
    for f in C.EXTRACTED.glob("*/*.json"):
        p = json.loads(f.read_text())["poll"]
        by_url.setdefault(p["tables_url"], []).append(p["poll_id"])
    seen = load_seen()
    for url, m in C.load_manifest().items():
        if url in seen:
            continue
        ids = by_url.get(url, [])
        seen[url] = {"pollster_id": m["pollster_id"], "url": url, "source_page_url": m.get("source_page_url", ""),
                     "published_at": m.get("published_at", ""), "sha256": m["sha256"],
                     "status": "ok" if ids else "skipped_or_duplicate", "poll_id": ";".join(sorted(ids)),
                     "first_seen": (m.get("fetched_at") or "")[:10], "extra": ""}
    save_seen(seen)
    print(f"files_seen.csv: {len(seen)} files ({sum(1 for r in seen.values() if r['status'] == 'ok')} became polls)")


def yougov_tracker_weeks(mod, last):
    """YouGov weeks with an article but no results PDF yet: headline (and the spreadsheet's breaks) from
    YouGov's tracker download. Stored as headline_only; the PDF replaces it if it appears later."""
    try:
        meta = mod.fetch_tracker()
    except Exception as e:
        log_error("yougov", "tracker", e)
        print(f"  ! yougov tracker download failed: {e!r}")
        return []
    have = set()
    for f in (C.EXTRACTED / "yougov").glob("*.json"):
        have.add(json.loads(f.read_text())["poll"]["fieldwork_end"])
    polls, _ = mod.parse_tracker(C.REPO / meta["path"], meta, have)
    out = []
    for d in polls:
        if last and d["poll"]["fieldwork_end"] <= last:
            continue
        C.write_extracted(d)
        f = C.EXTRACTED / "yougov" / f"{d['poll']['poll_id']}.json"
        d["poll"]["extracted_json"] = str(f.relative_to(C.REPO))
        out.append(d)
        hl = ", ".join(f"{h['party_code']} {h['pct_from_tables']:.0f}"
                       for h in sorted(d["headline"], key=lambda h: -h["pct_from_tables"])[:5])
        print(f"  + {d['poll']['poll_id']}  {hl}  (headline only, from YouGov's tracker download)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pollsters", nargs="*", default=list(SCRAPERS))
    ap.add_argument("--lookback", type=int, default=45, help="days before each firm's latest poll to re-check")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", action="store_true",
                    help="(once) build registry/files_seen.csv from the local archive and extracted polls")
    a = ap.parse_args()
    if a.seed:
        return seed()
    SCRAPERS["ipsos"].USE_PAGES_SEEN = True
    seen, latest = load_seen(), latest_by_firm()
    man = C.load_manifest()
    today = dt.date.today().isoformat()
    new_polls, summary = [], []
    total, t0 = len(a.pollsters), time.time()

    def progress(i, pid, msg):
        # one line per pollster as it finishes, e.g.  [####------]  4/10  Opinium: 1 new file (52s so far)
        bar = "#" * i + "-" * (total - i)
        print(f"[{bar}] {i:>2}/{total}  {NAMES.get(pid, pid)}: {msg} ({time.time() - t0:.0f}s so far)", flush=True)

    for i, pid in enumerate(a.pollsters, 1):
        mod = SCRAPERS[pid]
        last = latest.get(pid)
        since = ((dt.date.fromisoformat(last) - dt.timedelta(days=a.lookback)).isoformat() if last else DEFAULT_START)
        print(f"== {pid}: checking files since {since} (latest poll {last or 'none'})")
        found_new = 0
        try:
            candidates = list(mod.discover(since))
        except Exception as e:
            log_error(pid, "discover", e)
            print(f"  ! discovery failed: {e!r}")
            summary.append((pid, "discovery failed"))
            progress(i, pid, "check FAILED (see above)")
            continue
        for found in candidates:
            if found["url"] in seen:
                continue
            found_new += 1
            if a.dry_run:
                print(f"  new: {found['url']}")
                continue
            try:
                row = man.get(found["url"]) or C.archive(pid, found["url"], found.get("page_url"), found.get("published_at"))
            except Exception as e:
                log_error(pid, found["url"], e)
                print(f"  ! download failed {found['url']}: {e!r}")
                continue  # not recorded as seen, so it is retried next time
            meta = {**row, **{k: v for k, v in found.items() if k != "url"},
                    "page_url": found.get("page_url"), "published_at": found.get("published_at")}
            before = {f.name for f in (C.EXTRACTED / pid).glob("*.json")} if (C.EXTRACTED / pid).exists() else set()
            status = process(mod, meta)
            after = {f.name: f for f in (C.EXTRACTED / pid).glob("*.json")} if (C.EXTRACTED / pid).exists() else {}
            made = [after[n] for n in after if n not in before] or \
                   ([f for f in after.values() if json.loads(f.read_text())["poll"]["tables_url"] == found["url"]]
                    if status == "ok" else [])
            poll_ids = []
            for f in made:
                d = json.loads(f.read_text())
                d["poll"]["extracted_json"] = str(f.relative_to(C.REPO))
                new_polls.append(d)
                poll_ids.append(d["poll"]["poll_id"])
            extra = {k: v for k, v in found.items() if k not in ("url", "page_url", "published_at") and v}
            seen[found["url"]] = {"pollster_id": pid, "url": found["url"], "source_page_url": found.get("page_url") or "",
                                  "published_at": found.get("published_at") or "", "sha256": row["sha256"],
                                  "status": status, "poll_id": ";".join(poll_ids), "first_seen": today,
                                  "extra": json.dumps(extra, ensure_ascii=False) if extra else ""}
        if pid == "yougov" and getattr(mod, "MISSING_PDF", None) and not a.dry_run:
            added = yougov_tracker_weeks(mod, last)
            new_polls.extend(added)
            found_new += len(added)
        summary.append((pid, f"{found_new} new file(s)"))
        progress(i, pid, "nothing new" if not found_new else f"{found_new} new file{'s' if found_new > 1 else ''}")
    if not a.dry_run:
        merge(new_polls)
        save_seen(seen)
        if hasattr(SCRAPERS["ipsos"], "save_pages_seen"):
            SCRAPERS["ipsos"].save_pages_seen()
    print("\nSummary:")
    for pid, s in summary:
        print(f"  {pid:13} {s}")
    if new_polls:
        print("\nNew or updated polls:")
        for d in sorted(new_polls, key=lambda d: d["poll"]["fieldwork_end"]):
            hl = ", ".join(f"{h['party_code']} {h['pct_from_tables']:.0f}"
                           for h in sorted(d["headline"], key=lambda h: -h["pct_from_tables"])[:5])
            print(f"  {d['poll']['poll_id']:32} {hl}")
    elif not a.dry_run:
        print("\nNo new polls.")


if __name__ == "__main__":
    main()
