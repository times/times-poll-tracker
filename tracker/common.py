"""Shared plumbing for the poll scrapers: polite HTTP, raw-file archive, date parsing,
party and crossbreak codes, and a parser for the common 'grid' crosstab sheet layout."""
import csv
import datetime as dt
import difflib
import hashlib
import json
import re
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=".*OpenSSL.*")
import requests  # noqa: E402

REPO = Path(__file__).resolve().parents[1]     # repository root
PROJECT = REPO
DATA = REPO / "data"                           # local only (gitignored): raw downloads, per-poll JSON
RAW = DATA / "raw"
EXTRACTED = DATA / "extracted"
MANIFEST = RAW / "manifest.csv"
OUTPUTS = REPO / "outputs"                     # committed: the master files

UA = "Mozilla/5.0 (compatible; poll-tracker/0.1)"
DELAY = 1.0  # seconds between requests to the same site
_session = requests.Session()
_session.headers["User-Agent"] = UA
_last = {}


class _CurlResponse:
    """Minimal stand-in for requests.Response, for hosts whose TLS the system Python
    (LibreSSL 2.8) can't negotiate (e.g. ipsos.com)."""
    def __init__(self, url):
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile() as hdr:
            out = subprocess.run(["curl", "-sSL", "-m", "90", "-A", UA, "-D", hdr.name, url],
                                 capture_output=True, check=True)
            heads = Path(hdr.name).read_text(errors="replace").split("\r\n\r\n")
        self.content = out.stdout
        last = [h for h in heads if h.startswith("HTTP/")][-1].split("\r\n")
        self.status_code = int(last[0].split()[1])
        self.headers = {k.strip(): v.strip() for k, _, v in (l.partition(":") for l in last[1:]) if k}
        self.text = self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for {self.url if hasattr(self, 'url') else ''}")


def get(url, **kw):
    host = url.split("/")[2]
    wait = DELAY - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    for attempt in range(3):
        try:
            r = _session.get(url, timeout=60, **kw)
            _last[host] = time.time()
            if r.status_code >= 500 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.SSLError:
            r = _CurlResponse(url)
            _last[host] = time.time()
            r.raise_for_status()
            return r
        except requests.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"failed {url}")


# ---------------------------------------------------------------- raw archive

MANIFEST_COLS = ["pollster_id", "url", "source_page_url", "path", "sha256", "bytes", "fetched_at", "published_at"]


def load_manifest():
    if not MANIFEST.exists():
        return {}
    with MANIFEST.open() as f:
        return {r["url"]: r for r in csv.DictReader(f)}


def archive(pollster_id, url, source_page_url=None, published_at=None, filename=None, fetch_url=None):
    """Download url once into data/raw/<pollster>/ and record it in the manifest.
    Returns the manifest row. Files already fetched are not downloaded again. For a file that
    changes at a fixed address, pass a dated key as `url` and the real address as `fetch_url`."""
    man = load_manifest()
    if url in man and (REPO / man[url]["path"]).exists():
        return man[url]
    r = get(fetch_url or url)
    name = filename or re.sub(r"[^A-Za-z0-9._-]", "_", url.rstrip("/").split("/")[-1])
    up = re.search(r"/uploads/(\d{4})/(\d{2})/", url)
    if up and not filename:  # WordPress reuses basenames across months
        name = f"{up.group(1)}-{up.group(2)}_{name}"
    d = RAW / pollster_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    taken = {r["path"]: u for u, r in man.items()}
    if str(p.relative_to(REPO)) in taken and taken[str(p.relative_to(REPO))] != url:
        p = d / f"{hashlib.sha1(url.encode()).hexdigest()[:8]}_{name}"  # never overwrite another URL's file
    p.write_bytes(r.content)
    row = {
        "pollster_id": pollster_id,
        "url": url,
        "source_page_url": source_page_url or "",
        "path": str(p.relative_to(REPO)),
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "bytes": len(r.content),
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "published_at": published_at or "",
    }
    new = not MANIFEST.exists()
    with MANIFEST.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        if new:
            w.writeheader()
        w.writerow(row)
    return row


def write_extracted(poll):
    pid = poll["poll"]["poll_id"]
    d = EXTRACTED / poll["poll"]["pollster_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}.json").write_text(json.dumps(poll, indent=1, ensure_ascii=False, default=str))
    return d / f"{pid}.json"


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- dates

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9


def _month(word):
    """Month number for a word, tolerating typos ('Match 2026')."""
    if word in MONTHS:
        return MONTHS[word]
    if len(word) >= 4:
        m = difflib.get_close_matches(word, [k for k in MONTHS if len(k) > 3], n=1, cutoff=0.75)
        if m:
            return MONTHS[m[0]]
    return None


def sanity_dates(poll, fix_old=True):
    """Catch year errors in fieldwork dates by checking against the publication date, and fix
    them with a note (never silently):
    - fieldwork after publication is impossible -> move back a year (covers covers with no year);
    - fieldwork >150 days before publication -> assume a year typo and move forward, unless
      fix_old=False (sites whose 'published' date is really an upload date, e.g. re-uploads)."""
    pub = poll.get("published_date")
    if not pub or not poll.get("fieldwork_end"):
        return poll
    pub = dt.date.fromisoformat(pub[:10])
    fs, fe = dt.date.fromisoformat(poll["fieldwork_start"]), dt.date.fromisoformat(poll["fieldwork_end"])

    def shift(years):
        try:
            return fs.replace(year=fs.year + years), fe.replace(year=fe.year + years)
        except ValueError:  # 29 Feb
            return fs + dt.timedelta(days=365 * years), fe + dt.timedelta(days=365 * years)

    new = None
    if fe > pub + dt.timedelta(days=1):
        new = shift(-1)
    elif fix_old and fe < pub - dt.timedelta(days=150):
        k = pub.year - fe.year
        cand = shift(k)
        new = cand if cand[1] <= pub + dt.timedelta(days=1) else shift(k - 1)
    if new:
        note = (f"Fieldwork dates corrected from {fs}..{fe} to {new[0]}..{new[1]} "
                f"(inconsistent with publication/upload date {pub}).")
        poll["notes"] = ((poll.get("notes") or "") + " " + note).strip()
        poll["fieldwork_start"], poll["fieldwork_end"] = new[0].isoformat(), new[1].isoformat()
        suffix = re.sub(r"^.*?-\d{4}-\d{2}-\d{2}", "", poll["poll_id"])
        poll["poll_id"] = f"{poll['pollster_id']}-{new[1].isoformat()}{suffix}"
        poll["date_corrected"] = True
    return poll


def parse_fieldwork(text, default_year=None):
    """'6 - 9 November 2026', '31 October - 1 November 2026', '4th November 2026',
    '28th-29th October 2026', '8th - 9th November 2026' -> (start, end) dates."""
    t = text.lower().replace("–", "-").replace("—", "-")
    toks = re.findall(r"(\d{1,2})(?:st|nd|rd|th)?\b|([a-z]+)|(\d{4})", t)
    days, cur = [], None
    parts = []  # list of [day, month, year]
    for d, word, yr in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\b|\b([a-z]{3,9})\b|\b(\d{4})\b", t):
        if d:
            parts.append([int(d), None, None])
        elif word and parts and _month(word):
            for p in parts:
                if p[1] is None:
                    p[1] = _month(word)
        elif yr and parts:
            for p in parts:
                if p[2] is None:
                    p[2] = int(yr)
    parts = [p for p in parts if p[1]]
    if not parts:
        raise ValueError(f"no dates in {text!r}")
    for p in parts:
        if p[2] is None:
            p[2] = default_year
    start, end = parts[0], parts[-1]
    s = dt.date(start[2], start[1], start[0])
    e = dt.date(end[2], end[1], end[0])
    if s > e:  # e.g. '30 December - 2 January 2027'
        s = dt.date(start[2] - 1, start[1], start[0])
    return s, e


# ---------------------------------------------------------------- codes

_PARTY_RULES = [
    (r"restore britain", "RB"),
    (r"^your party", "YP"),
    (r"^reform|^ref\b|^rfm$", "REF"),
    (r"^conservative|^con\b|^cons\b|^conservatives$", "CON"),
    (r"^labour|^lab\b", "LAB"),
    (r"^lib(eral)? ?dem|^liberal democrat|^ld$", "LD"),
    (r"green|^grn$", "GRN"),
    (r"scottish national|^snp", "SNP"),
    (r"plaid|^pc$", "PC"),
    (r"don.?t know|undecided|not sure|unsure|^dk$", "DK"),
    (r"would not vote|wouldn.?t vote|will not vote|not vote|did not vote", "WNV"),
    (r"refus|prefer not|pnts", "REFUSED"),
    (r"other|another|independent|^oth$|ukip|uk independence|social democratic|workers party|"
     r"alba|heritage|trade unionist|yorkshire|rejoin|^liberal$", "OTH"),
]


def party_code(label):
    if label is None:
        return None
    s = str(label).strip().lower()
    for pat, code in _PARTY_RULES:
        if re.search(pat, s):
            return code
    return None


def break_var_std(group):
    g = (group or "").strip().lower()
    if g in ("", "total", "all"):
        return "total"
    if g in ("gender", "sex"):
        return "sex"
    if g.startswith("age"):
        return "age"
    if "2024" in g or g.startswith("ge2024"):
        return "ge2024"
    if "2019" in g:
        return "ge2019"
    if "eu" in g:
        return "euref"
    if "region" in g:
        return "region"
    if "country" in g or "nation" in g:
        return "nation"
    if "headline" in g or "voting intention" in g:
        return "current_vi"
    return re.sub(r"[^a-z0-9]+", "_", g).strip("_")


def break_std(group, label):
    v = break_var_std(group)
    lab = str(label).strip()
    if v == "total":
        return "total"
    if v in ("ge2024", "ge2019", "current_vi"):
        c = party_code(lab)
        return f"{v}:{c or lab.lower()}"
    if v == "sex":
        return f"sex:{'male' if lab.lower().startswith('m') else 'female' if lab.lower().startswith(('f', 'w')) else lab.lower()}"
    return f"{v}:{lab.lower()}"


# ---------------------------------------------------------------- grid sheets

N_ROW_NAMES = {"unweighted n", "filtered n", "weighted n", "unweighted base", "weighted base"}
STOP_ROWS = {"weight", "return to index"}


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("%", "")
    if s in ("-", "*"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def parse_grid(ws):
    """Parse a crosstab sheet laid out as:
        title / question text rows
        group header row   (e.g. '', 'gender', '', 'age_grouped', ...)
        label row          (first cell anything, second cell 'All' or 'Total')
        optional 'Base: ...' rows
        option rows (proportions), optionally each followed by a count row with a blank label
        'Unweighted N' / 'Filtered N' row, 'Weight' row
    Proportions are returned as percentages."""
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    hit = next(((i, c) for i, r in enumerate(rows) for c in (1, 2, 3)
                if len(r) > c and str(r[c]).strip() in ("All", "Total")), None)
    if hit is None:
        raise ValueError(f"sheet {ws.title!r}: no 'All'/'Total' header row")
    li, c0 = hit
    if c0 > 1:  # data starts further right: drop the empty leading columns
        rows = [[next((x for x in r[:c0] if x not in (None, "")), None)] + list(r[c0:]) for r in rows]
    labels = rows[li]
    ncol = max(i for i, v in enumerate(labels) if v not in (None, "")) + 1
    groups, cur = [], "Total"
    grow = rows[li - 1] if li > 0 else []
    for c in range(1, ncol):
        g = grow[c] if c < len(grow) else None
        if g not in (None, ""):
            cur = str(g).strip()
        groups.append(cur if c > 1 else "Total")
    cols = [{"break_var": groups[c - 1], "break_label": str(labels[c]).strip()} for c in range(1, ncol)]
    header_text = [str(c).strip() for r in rows[:li - 1] for c in r if isinstance(c, str) and c.strip()]
    out = {"header_text": header_text, "columns": cols, "bases": [], "options": [],
           "n_unweighted": None, "n_weighted": None, "weight_name": None}
    i = li + 1
    while i < len(rows):
        r = rows[i] + [None] * ncol
        lab = r[0]
        key = str(lab).strip().lower() if lab is not None else ""
        if key in STOP_ROWS:
            if key == "weight":
                out["weight_name"] = r[1]
            break
        if key.startswith("base"):
            vals = [_num(v) for v in r[1:ncol]]
            out["bases"].append({"text": str(lab).strip(), "values": vals})
            if "unweighted" in key:
                out["n_unweighted"] = vals
            elif "weighted" in key:
                out["n_weighted"] = vals
        elif key in N_ROW_NAMES:
            vals = [_num(v) for v in r[1:ncol]]
            if "unweighted" in key:
                out["n_unweighted"] = vals
            else:
                out["n_weighted"] = vals
        elif lab not in (None, "") and any(_num(v) is not None for v in r[1:ncol]):
            pct = [None if _num(v) is None else round(_num(v) * 100, 4) for v in r[1:ncol]]
            opt = {"label": str(lab).strip(), "pct": pct, "count": None}
            nxt = rows[i + 1] + [None] * ncol if i + 1 < len(rows) else None
            if nxt is not None and nxt[0] in (None, "") and any(_num(v) is not None for v in nxt[1:ncol]):
                opt["count"] = [_num(v) for v in nxt[1:ncol]]
                i += 1
            out["options"].append(opt)
        i += 1
    return out


def grid_to_records(poll_id, question_ref, table_base, grid):
    """Turn a parsed grid into options + long results records."""
    options, results = [], []
    for pos, o in enumerate(grid["options"], 1):
        code = party_code(o["label"])
        options.append({"poll_id": poll_id, "question_ref": question_ref, "position": pos,
                        "label": o["label"], "party_code": code})
        for ci, col in enumerate(grid["columns"]):
            p = o["pct"][ci] if ci < len(o["pct"]) else None
            if p is None:
                continue
            results.append({
                "poll_id": poll_id, "question_ref": question_ref, "table_base": table_base,
                "break_var": col["break_var"], "break_label": col["break_label"],
                "break_std": break_std(col["break_var"], col["break_label"]),
                "option_label": o["label"], "party_code": code, "pct": p,
                "n_weighted": (o["count"][ci] if o["count"] else None),
                "n_unweighted_col": (grid["n_unweighted"][ci] if grid["n_unweighted"] else None),
                "n_weighted_col": (grid["n_weighted"][ci] if grid["n_weighted"] else None),
            })
    return options, results


def headline_from_grid(grid, label_map=None):
    """Total-column shares of the headline table, keyed by party code (OTH summed)."""
    out = {}
    for o in grid["options"]:
        code = (label_map or {}).get(o["label"]) or party_code(o["label"])
        if code in (None, "DK", "WNV", "REFUSED"):
            continue
        out[code] = round(out.get(code, 0) + (o["pct"][0] or 0), 4)
    return out


def cover_lookup(ws):
    """Key/value pairs from a cover sheet: first non-empty cell -> next non-empty cell,
    plus every long string kept verbatim."""
    kv, texts = {}, []
    for r in ws.iter_rows(values_only=True):
        cells = [c for c in r if c not in (None, "")]
        if not cells:
            continue
        for c in cells:
            if isinstance(c, str) and c.strip():
                texts.append(c.strip())
        if len(cells) >= 2 and isinstance(cells[0], str):
            kv[cells[0].strip().rstrip(":").strip().lower()] = cells[1]
    return kv, texts


def find_text(texts, pattern):
    rx = re.compile(pattern, re.I)
    return next((t for t in texts if rx.search(t)), None)


def new_poll(pollster_id, **kw):
    base = {
        "poll_id": None, "pollster_id": pollster_id, "client": None, "commissioner_type": "self",
        "poll_type": "standard_vi", "fieldwork_start": None, "fieldwork_end": None,
        "published_date": None, "geography_sampled": "GB", "geography_vi_base": "GB",
        "mode": "online_panel", "panel_provider": None, "sample_size_total": None,
        "sample_size_vi_unweighted": None, "sample_size_vi_weighted": None, "pooled_waves": False,
        "weighting_text": None, "turnout_text": None, "dk_text": None, "headline_table_ref": None,
        "headline_definition_text": None, "headline_method": "direct", "methodology_text": None,
        "bpc_statement": None, "source_page_url": None, "tables_url": None, "raw_file": None,
        "raw_sha256": None, "scraped_at": now(), "scraper": None, "extraction_status": "auto",
        "notes": None, "series": pollster_id, "fieldwork_text": None, "weighted": True,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------- manual overrides

OVERRIDES = PROJECT / "registry" / "overrides.csv"


def apply_overrides(poll):
    """Hand corrections from registry/overrides.csv, matched on tables_url. Each is noted."""
    if not OVERRIDES.exists():
        return poll
    with OVERRIDES.open() as f:
        for r in csv.DictReader(f):
            if r["tables_url"] == poll["tables_url"]:
                old = poll.get(r["field"])
                poll[r["field"]] = r["value"]
                poll["notes"] = ((poll.get("notes") or "") +
                                 f" Override {r['field']}: {old} -> {r['value']} ({r['reason']}).").strip()
                if r["field"] == "fieldwork_end":
                    suffix = re.sub(r"^.*?-\d{4}-\d{2}-\d{2}", "", poll["poll_id"])
                    poll["poll_id"] = f"{poll['pollster_id']}-{r['value']}{suffix}"
                poll["overridden"] = True
    return poll


# ---------------------------------------------------------------- stacked tables (one sheet, many tables)

N_NAMES = re.compile(r"^(unweighted|weighted)( total| n| row| base)?$|^base: total$", re.I)
STOP = re.compile(r"^(weight:|filter:|back to toc|return to index)", re.I)


def _is_num(v):
    return isinstance(v, (int, float)) or (isinstance(v, str) and v.strip() in ("-", "*"))


def parse_stacked(rows, is_title, headerless_total_col=None):
    """Split a sheet holding many crosstabs into tables. Handles the layouts seen so far:
    - Survation: 'Total' sits in the group row; break labels on the row below; each option is
      a row of weighted counts followed by an unlabelled row of proportions.
    - BMG (WinCross): group row, then label row with 'Total'; counts row, proportions row, then
      a row of significance letters.
    - Freshwater: no group row; label row with 'Total'; option rows are proportions.
    Returns [{title, texts, columns:[{break_var, break_label}], n_unweighted, n_weighted,
              options:[{label, pct, count}]}] with pct in 0-100."""
    starts = [i for i, r in enumerate(rows) if is_title(r)]
    tables = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(rows)
        blk = rows[s:e]
        title = next(str(c).strip() for c in blk[0] if c not in (None, ""))
        ti = next((i for i, r in enumerate(blk) if any(isinstance(c, str) and c.strip() == "Total" for c in r)), None)
        if ti is None and headerless_total_col is not None:
            # no column-header row at all (seen in Freshwater, Jan 2026): first value column is
            # Total, the rest are unlabelled. Insert a synthetic label row after the title.
            width = max(len(r) for r in blk)
            synth = [None] * width
            synth[headerless_total_col] = "Total"
            for j in range(headerless_total_col + 1, width):
                if any(j < len(r) and _is_num(r[j]) for r in blk[1:]):
                    synth[j] = f"Unlabelled column {j}"
            blk = [blk[0], synth] + blk[1:]
            ti = 1
        if ti is None:
            continue
        tc = next(j for j, c in enumerate(blk[ti]) if isinstance(c, str) and c.strip() == "Total")
        nxt = blk[ti + 1] if ti + 1 < len(blk) else []
        later = lambda r: [j for j, c in enumerate(r) if j > tc and isinstance(c, str) and c.strip()]
        if len(later(nxt)) > len(later(blk[ti])):      # Survation: Total row is the group row
            grow, lrow, li = blk[ti], nxt, ti + 1
            labels = {tc: "Total", **{j: str(nxt[j]).strip() for j in later(nxt)}}
        else:
            grow = blk[ti - 1] if ti > 0 and later(blk[ti - 1]) else []
            lrow, li = blk[ti], ti
            labels = {j: str(blk[ti][j]).strip() for j in [tc] + later(blk[ti])}
        cols = sorted(labels)
        groups, cur = {}, "Total"
        for j in range(tc, max(cols) + 1):
            g = grow[j] if j < len(grow) else None
            if isinstance(g, str) and g.strip():
                cur = g.strip()
            groups[j] = "Total" if j == tc else cur
        lc = max((j for j in range(tc) if any(isinstance(r[j], str) and r[j].strip()
                                             for r in blk[li + 1:] if j < len(r))), default=0)
        texts = [str(c).strip() for r in blk[:li] for c in r if isinstance(c, str) and c.strip()]
        t = {"title": title, "texts": texts, "label_col": lc,
             "columns": [{"break_var": groups[j] if grow else _guess_group(labels[j]), "break_label": labels[j]}
                         for j in cols],
             "n_unweighted": None, "n_weighted": None, "options": []}
        vals = lambda r: [r[j] if j < len(r) else None for j in cols]
        last = None
        for r in blk[li + 1:]:
            lab = r[lc] if lc < len(r) else None
            if isinstance(lab, (int, float)):  # scale points stored as numbers (0-10 likelihood)
                lab = str(int(lab)) if float(lab).is_integer() else str(lab)
            lab = lab.strip() if isinstance(lab, str) else lab
            if isinstance(lab, str) and STOP.match(lab):
                t["texts"].append(lab)
                if lab.lower().startswith(("back", "return")):
                    break
                continue
            v = vals(r)
            if lab and N_NAMES.match(lab):
                nums = [_num(x) for x in v]
                if lab.lower().startswith("unweighted"):
                    t["n_unweighted"] = nums
                else:
                    t["n_weighted"] = nums
                last = "n"
                continue
            if lab and isinstance(lab, str) and lab.lower().startswith("base"):
                t["texts"].append(lab)
                continue
            if lab and any(_is_num(x) for x in v):
                nums = [_num(x) for x in v]
                o = {"label": lab, "pct": None, "count": None}
                if all(x is None or x <= 1.0 for x in nums):
                    o["pct"] = [None if x is None else round(x * 100, 4) for x in nums]
                else:
                    o["count"] = nums
                t["options"].append(o)
                last = "opt"
                continue
            if not lab and last == "opt" and any(isinstance(x, (int, float)) for x in v):
                o = t["options"][-1]
                nums = [_num(x) for x in v]
                if o["pct"] is None and all(x is None or x <= 1.0 for x in nums):
                    o["pct"] = [None if x is None else round(x * 100, 4) for x in nums]
                last = "pct"
        for o in t["options"]:  # counts only (no proportion row): derive from weighted base
            if o["pct"] is None and o["count"] and t["n_weighted"]:
                o["pct"] = [round(c / n * 100, 4) if c is not None and n else None
                            for c, n in zip(o["count"], t["n_weighted"])]
        tables.append(t)
    return tables


def _guess_group(label):
    l = label.lower()
    if l == "total":
        return "Total"
    if l in ("male", "female", "men", "women"):
        return "Gender"
    if re.search(r"\d+\s*(-|to)\s*\d+|\d+\+|aged", l) and "£" not in l:
        return "Age"
    if "£" in l or "income" in l:
        return "Income"
    if l in REGIONS:
        return "Region"
    if party_code(label) in ("CON", "LAB", "LD", "REF", "GRN", "SNP", "PC", "OTH", "RB", "YP"):
        return "Party (unlabelled)"
    return "Crossbreak"


REGIONS = {"london", "north east", "north west", "yorkshire and the humber", "east midlands",
           "west midlands", "east of england", "east england", "south east", "south west", "scotland",
           "wales", "northern ireland", "north", "midlands", "south"}


def stacked_to_records(poll_id, question_ref, stage, t):
    """Same output as grid_to_records, for a parse_stacked table."""
    g = {"columns": t["columns"], "n_unweighted": t["n_unweighted"], "n_weighted": t["n_weighted"],
         "options": [{"label": o["label"], "pct": o["pct"] or [], "count": o["count"]} for o in t["options"]]}
    return grid_to_records(poll_id, question_ref, stage, g)


def cells(ws):
    """Every non-empty cell value in reading order (for cover sheets laid out side by side)."""
    return [c for r in ws.iter_rows(values_only=True) for c in r if c not in (None, "")]


# ---------------------------------------------------------------- crosstab files

CROSSTABS = OUTPUTS / "crosstabs"
CROSSTAB_COLS = ["poll_id", "question_ref", "table_base", "break_var", "break_label", "break_std", "option_label",
                 "party_code", "pct", "n_weighted", "n_unweighted_col", "n_weighted_col"]


def crosstab_file(poll_id):
    """outputs/crosstabs/<pollster>_<year>.csv, year from the poll id's fieldwork end date."""
    m = re.match(r"^(.+?)-(\d{4})-\d{2}-\d{2}", poll_id)
    return CROSSTABS / f"{m.group(1)}_{m.group(2)}.csv"


def write_crosstabs(rows, replace_ids=None):
    """Write crosstab rows into the per-pollster-year files. With replace_ids, merge: rows for
    those polls are replaced and every other row in the touched files is kept."""
    CROSSTABS.mkdir(parents=True, exist_ok=True)
    groups = {}
    for r in rows:
        groups.setdefault(crosstab_file(r["poll_id"]), []).append(r)
    if replace_ids is not None:
        for pid in replace_ids:
            groups.setdefault(crosstab_file(pid), [])
    for path, add in groups.items():
        keep = []
        if replace_ids is not None and path.exists():
            with path.open() as f:
                keep = [r for r in csv.DictReader(f) if r["poll_id"] not in replace_ids]
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CROSSTAB_COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(keep + add)
    return len(groups)
