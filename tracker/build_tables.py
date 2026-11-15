"""Combine per-poll JSON (data/extracted/) into flat tables.

Committed (outputs/): polls.csv, headlines.csv (long), headlines_wide.csv, questions.csv, options.csv
Also committed: outputs/crosstabs/<pollster>_<year>.csv, the full crosstabs (long format).

    python3 -m tracker.build_tables
"""
import csv
import json

from . import common as C

PARTIES = ["LAB", "CON", "REF", "LD", "GRN", "SNP", "PC", "RB", "YP", "OTH"]


def write(path, rows, cols=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = cols or list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows):>6} rows  {path.relative_to(C.REPO)}")


def main():
    polls, heads, qs, opts, res = [], [], [], [], []
    for p in sorted(C.EXTRACTED.glob("*/*.json")):
        d = json.loads(p.read_text())
        poll = d["poll"]
        poll["extracted_json"] = str(p.relative_to(C.REPO))
        polls.append(poll)
        heads += d["headline"]
        qs += d["questions"]
        opts += d["options"]
        res += d["results"]
    polls.sort(key=lambda r: (r["fieldwork_end"], r["pollster_id"]))
    write(C.OUTPUTS / "polls.csv", polls)
    write(C.OUTPUTS / "headlines.csv", heads)
    by, by_gb = {}, {}
    for h in heads:
        if h.get("pct_gb") is not None:
            by_gb.setdefault(h["poll_id"], {})[h["party_code"]] = round(h["pct_gb"], 2)
    for h in heads:
        by.setdefault(h["poll_id"], {})[h["party_code"]] = round(h["pct_from_tables"], 2)
    wide = []
    for p in polls:
        row = {k: p[k] for k in ("poll_id", "pollster_id", "fieldwork_start", "fieldwork_end",
                                 "published_date", "geography_vi_base", "sample_size_total",
                                 "headline_method", "client")}
        row.update({k: by.get(p["poll_id"], {}).get(k) for k in PARTIES})
        gb = by_gb.get(p["poll_id"])
        if gb:  # firms reporting UK-wide (Survation): GB re-based shares alongside
            row.update({f"{k}_gb": gb.get(k) for k in PARTIES})
        named = {o["party_code"] for o in opts if o["poll_id"] == p["poll_id"] and o["party_code"] == "RB"}
        row["rb_named"] = bool(named)
        wide.append(row)
    write(C.OUTPUTS / "headlines_wide.csv", wide)
    write(C.OUTPUTS / "questions.csv", qs)
    write(C.OUTPUTS / "options.csv", opts)
    for f in C.CROSSTABS.glob("*.csv"):
        f.unlink()
    n = C.write_crosstabs(res)
    print(f"wrote {len(res):>6} rows  outputs/crosstabs/ ({n} files, one per pollster per year)")


if __name__ == "__main__":
    main()
