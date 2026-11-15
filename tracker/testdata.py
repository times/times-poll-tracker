"""Test sets: GB Westminster polls before the 2015, 2017, 2019 and 2024 elections, from Wikipedia.

    python3 -m tracker.testdata        # writes testdata/wiki_ge{year}_polls.csv

Used only to test averaging methods (how fast each registers the June 2024 narrowing). Not
tracker data: no tables, no question wording. Source: Wikipedia, 'Opinion polling for the YEAR
United Kingdom general election' pages (CC BY-SA 4.0), fetched page archived in data/raw.
Wikipedia gives fieldwork dates only, so publication is assumed to be fieldwork end + 1 day.
"""
import csv
import datetime as dt
import io
import re
import warnings

from . import common as C

ELECTIONS = {
    2024: {"start": "2023-07-01", "right": {"Ref": "REF"}},
    2019: {"start": "2019-01-01", "right": {"Brx": "REF", "UKIP": "OTH"}},
    2017: {"start": "2016-09-01", "right": {"UKIP": "REF"}},
    2015: {"start": "2014-09-01", "right": {"UKIP": "REF"}},
}
BASE = {"Con": "CON", "Lab": "LAB", "LD": "LD", "SNP": "SNP", "Grn": "GRN", "PC": "PC", "Others": "OTH",
        "Chg": "OTH"}
OUTDIR = C.PROJECT / "testdata"


def _url(year):
    return f"https://en.wikipedia.org/wiki/Opinion_polling_for_the_{year}_United_Kingdom_general_election"


def _pct(v):
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*%", str(v))
    return float(m.group(1)) if m else None


def _dates(s, year):
    s = re.sub(r"\[.*?\]", "", str(s)).replace("\u2013", "-").replace("\u2014", "-")
    try:
        return C.parse_fieldwork(s, default_year=year)
    except ValueError:
        return None


def build(year):
    import pandas as pd
    warnings.filterwarnings("ignore")
    cfg = ELECTIONS[year]
    url = _url(year)
    row = C.archive("wikipedia_testset", url + "#asof=" + dt.date.today().isoformat(),
                    filename=f"wiki_ge{year}_{dt.date.today().isoformat()}.html", fetch_url=url)
    tabs = pd.read_html(io.StringIO((C.REPO / row["path"]).read_text()))
    polls = []
    for t in tabs:
        cols = [c[0] if isinstance(c, tuple) else c for c in t.columns]
        if "Lab" in cols and "Con" in cols and any("ollster" in str(c) or "organisation" in str(c) for c in cols) \
                and len(t) > 100:
            t.columns = cols
            polls.append(t)
    mapping = {**BASE, **cfg["right"]}
    start = dt.date.fromisoformat(cfg["start"])
    out = []
    for i, t in enumerate(polls[:3]):
        tyear = year - i  # tables run newest year first
        pcol = next(c for c in t.columns if "ollster" in str(c) or "organisation" in str(c))
        for _, r in t.iterrows():
            raw = re.sub(r"\[.*?\]|\s*Archived .*$", "", str(r.get(pcol, ""))).strip()
            if not raw or raw == "nan" or "election" in raw.lower() or "MRP" in raw:
                continue
            if "Area" in t.columns and str(r.get("Area")) not in ("GB", "UK"):
                continue
            pollster, _, client = raw.partition("/") if "Client" not in t.columns else (raw, "", str(r.get("Client", "")))
            sh = {}
            for col, code in mapping.items():
                if col in t.columns:
                    v = _pct(r.get(col))
                    sh[code] = sh.get(code, 0.0) + (v or 0.0)
            if not sh.get("LAB") or not sh.get("CON"):
                continue
            d = _dates(r[t.columns[0]], tyear)
            if not d:
                continue
            s_, e = d
            if e < start or e.year > year:
                continue
            n = re.sub(r"\D", "", str(r.get("Sample size", "")))
            firm = re.sub(r"[^a-z0-9]+", "", pollster.lower())
            out.append({"poll_id": f"{firm}-{e.isoformat()}", "pollster_id": firm, "pollster": pollster.strip(),
                        "client": client.strip(), "sample_size": n[:6] or None, "fieldwork_start": s_.isoformat(),
                        "fieldwork_end": e.isoformat(), "published_assumed": (e + dt.timedelta(days=1)).isoformat(),
                        **{k: sh.get(k, 0.0) for k in ("CON", "LAB", "LD", "SNP", "GRN", "REF", "PC", "OTH")}})
    seen, uniq = set(), []
    for r in sorted(out, key=lambda r: (r["fieldwork_end"], r["pollster_id"])):
        k = (r["pollster_id"], r["fieldwork_end"], r["LAB"], r["CON"])
        if k in seen:
            continue
        seen.add(k)
        ids = {u["poll_id"] for u in uniq}
        while r["poll_id"] in ids:
            r["poll_id"] += "-b"
        uniq.append(r)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = OUTDIR / f"wiki_ge{year}_polls.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(uniq[0].keys()))
        w.writeheader()
        w.writerows(uniq)
    firms = sorted({r["pollster_id"] for r in uniq})
    print(f"GE{year}: {len(uniq)} polls, {len(firms)} pollsters, {uniq[0]['fieldwork_end']} to {uniq[-1]['fieldwork_end']}")
    return path


def main():
    for y in ELECTIONS:
        build(y)
    (OUTDIR / "README.md").write_text(
        "# Test data\n\nGB/UK Westminster polls before the 2015, 2017, 2019 and 2024 general elections, from "
        "Wikipedia's 'Opinion polling for the YEAR United Kingdom general election' pages (CC BY-SA 4.0). "
        "Used only to test averaging methods (how fast each registers late-campaign shifts). MRPs and "
        "sub-national polls are excluded. Publication date is assumed to be fieldwork end + 1 day. The "
        "populist-right column is UKIP (2015, 2017), the Brexit Party (2019) and Reform UK (2024), stored "
        "as REF; in 2019 UKIP goes to OTH. Built by `python3 -m tracker.testdata`.\n")


if __name__ == "__main__":
    main()
