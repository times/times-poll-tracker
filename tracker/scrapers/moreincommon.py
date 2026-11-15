"""More in Common weekly GB voting intention.

Discovery: WordPress media API (every upload is listed with its date). Keep .xlsx files whose
name mentions voting intention, minus the Northern Ireland / Scotland / Wales / MRP variants.
The workbook decides: only files with a 'votingintention (headline)'-style sheet are parsed.
"""
import re
import openpyxl

from .. import common as C

PID = "moreincommon"
SCRAPER = "moreincommon@0.1"
FIX_OLD_DATES = False  # media API dates are upload dates; old polls get re-uploaded
MEDIA = ("https://www.moreincommon.org.uk/wp-json/wp/v2/media?search={q}&per_page=100&page={page}"
         "&after={since}T00:00:00&_fields=id,date,slug,source_url")
EXCLUDE = re.compile(
    r"northern-ireland|scotland|scottish|wales|welsh|senedd|mrp|london|mayoral|seat|constituenc|members|"
    r"hypothetical|burnham|if-|pop-music|supermarket|milk|segment|school|sexuality|gender-education|"
    r"behind-the|summer|sultana|corbyn|referendum|2023", re.I)
LISTING = "https://www.moreincommon.org.uk/polling-tables/"
_listing = None


def _listing_dates():
    """url -> fieldwork text with year, from the polling-tables page (used when a workbook
    has no cover sheet)."""
    global _listing
    if _listing is None:
        _listing = {}
        html = C.get(LISTING).text
        year = None
        for m in re.finditer(r"(?:(January|February|March|April|May|June|July|August|September|October|"
                             r"November|December) (\d{4}))|href=\"([^\"]+\.xlsx)\"(.*?)<p>\s*\(([^)]*)\)\s*</p>",
                             html, re.S):
            if m.group(2):
                year = int(m.group(2))
            elif m.group(3) and year:
                _listing[m.group(3)] = (m.group(5), year)
    return _listing


LISTING_TITLE = re.compile(r"voting intention|trackers|100 days", re.I)


def _listing_items():
    """(url, title, fieldwork text, year) for every file on the polling-tables page."""
    html = C.get(LISTING).text
    year, out = None, []
    for m in re.finditer(r"(?:(January|February|March|April|May|June|July|August|September|October|November|"
                         r"December) (\d{4}))|href=\"([^\"]+\.xlsx)\"[^>]*>.*?<h5>\s*(.*?)\s*(?:<div|</h5>)"
                         r".*?<p>\s*\(([^)]*)\)\s*</p>", html, re.S):
        if m.group(2):
            year = int(m.group(2))
        elif m.group(3) and year:
            out.append((m.group(3), re.sub(r"\s+", " ", m.group(4)), m.group(5), year))
    return out


def discover(since):
    seen = set()
    # files whose names don't say 'voting intention' (e.g. mic-first-vi.xlsx, 27-november-vi.xlsx,
    # 'Trackers' releases) are found through the polling-tables listing's titles; parse() keeps only
    # workbooks with a headline VI sheet
    for url, title, fw, year in _listing_items():
        if not LISTING_TITLE.search(title) or EXCLUDE.search(url.split("/")[-1]):
            continue
        try:
            fs, fe = C.parse_fieldwork(fw, default_year=year)
        except ValueError:
            continue
        if fe.isoformat() < since:
            continue
        up = re.search(r"/uploads/(\d{4})/(\d{2})/", url)
        seen.add(url)
        yield {"url": url, "page_url": LISTING,
               "published_at": f"{up.group(1)}-{up.group(2)}-28" if up else fe.isoformat()}
    for q in ("voting", "intention"):
        page = 1
        while True:
            r = C.get(MEDIA.format(q=q, page=page, since=since))
            items = r.json()
            if not isinstance(items, list) or not items:
                break
            for it in items:
                u = it["source_url"]
                if u in seen or not u.lower().endswith(".xlsx") or EXCLUDE.search(u):
                    continue
                if not re.search(r"voting.?intention|votingintention", u, re.I):
                    continue
                seen.add(u)
                yield {"url": u, "page_url": "https://www.moreincommon.org.uk/polling-tables/",
                       "published_at": it["date"][:10]}
            if page >= int(r.headers.get("X-WP-TotalPages", 1)):
                break
            page += 1


def _sheet(wb, *pats, exclude=None):
    for name in wb.sheetnames:
        n = name.lower()
        if all(re.search(p, n) for p in pats) and not (exclude and re.search(exclude, n)):
            return name
    return None


def _question(grid, sheet):
    texts = [t for t in grid["header_text"] if t.strip().lower() != sheet.strip().lower()]
    return texts[0] if texts else None


def parse(path, meta):
    if EXCLUDE.search(meta["url"].split("/")[-1]):
        return None  # regional, hypothetical or special-topic VI, not the weekly GB poll
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    hl = _sheet(wb, r"voting", r"headline")
    if not hl:
        return None  # not a standard VI release
    first = wb.sheetnames[0]
    has_cover = not re.search(r"likelihood|voting", first, re.I)
    kv, texts = C.cover_lookup(wb[first]) if has_cover else ({}, [])
    fw_text = next((v for k, v in kv.items() if k.startswith("fieldwork")), None)
    date_note = None
    lt = _listing_dates().get(meta["url"])
    if fw_text and re.search(r"\b(19|20)\d{2}\b", str(fw_text)):
        fs, fe = C.parse_fieldwork(str(fw_text), default_year=int(meta["published_at"][:4]))
    elif fw_text and lt:
        # cover gives day and month only; many old polls were re-uploaded years later, so the
        # upload date can't supply the year - the polling-tables listing (grouped by month) can
        fs, fe = C.parse_fieldwork(lt[0], default_year=lt[1])
        date_note = f"Cover gives '{fw_text}' with no year; year from the polling-tables listing ('{lt[0]}', {lt[1]})."
    elif fw_text:
        fs, fe = C.parse_fieldwork(str(fw_text), default_year=int(meta["published_at"][:4]))
        date_note = f"Cover gives '{fw_text}' with no year and the file isn't on the polling-tables listing; year assumed."
    else:
        if not lt:
            raise ValueError("no fieldwork dates in workbook or on the polling-tables page")
        fs, fe = C.parse_fieldwork(lt[0], default_year=lt[1])
        date_note = f"Fieldwork dates from the polling-tables listing ('{lt[0]}'), not the workbook."
    poll_id = f"{PID}-{fe.isoformat()}"
    pop = next((v for k, v in kv.items() if k.startswith("population")), "") or ""

    plan = [
        (_sheet(wb, r"likelihood"), "turnout"),
        (_sheet(wb, r"^votingintention$") or _sheet(wb, r"voting.*raw") or
         _sheet(wb, r"voting", exclude=r"headline|forced|squeeze|likely"), "vi_first"),
        (_sheet(wb, r"voting.*likely"), "vi_turnout_filtered"),
        (_sheet(wb, r"forced|squeeze"), "vi_squeeze"),
        (hl, "vi_headline_derived"),
    ]
    questions, options, results, headline, hl_grid = [], [], [], {}, None
    for order, (sheet, stage) in enumerate([p for p in plan if p[0]], 1):
        g = C.parse_grid(wb[sheet])
        questions.append({"poll_id": poll_id, "question_ref": sheet, "stage": stage,
                          "wording": _question(g, sheet), "base_text": None,
                          "order_in_questionnaire": order, "weight_name": g["weight_name"]})
        o, r = C.grid_to_records(poll_id, sheet, stage, g)
        options += o
        results += r
        if stage == "vi_headline_derived":
            hl_grid = g
            headline = C.headline_from_grid(g)

    poll = C.new_poll(
        PID, poll_id=poll_id, fieldwork_start=fs.isoformat(), fieldwork_end=fe.isoformat(),
        published_date=meta.get("published_at"),
        geography_sampled="GB" if "GB" in str(pop) else ("UK" if "UK" in str(pop) else "GB"),
        sample_size_total=int(C._num(next((v for k, v in kv.items() if k.startswith("sample size")), None)) or 0) or None,
        sample_size_vi_unweighted=int(hl_grid["n_unweighted"][0]) if hl_grid and hl_grid["n_unweighted"] else None,
        weighting_text=next((str(v) for k, v in kv.items() if k.startswith("sample detail")), None),
        turnout_text=C.find_text(texts, r"^Turnout model"),
        dk_text=C.find_text(texts, r"Undecided voters are asked"),
        headline_table_ref=hl, headline_definition_text=C.find_text(texts, r"^Turnout model"),
        headline_method="squeeze_plus_model",
        methodology_text="\n".join(texts), bpc_statement=C.find_text(texts, r"British Polling Council"),
        source_page_url=meta.get("page_url"), tables_url=meta["url"], raw_file=meta["path"],
        fieldwork_text=str(fw_text) if fw_text else None,
        raw_sha256=meta["sha256"], scraper=SCRAPER, notes=date_note,
    )
    return {"poll": poll, "questions": questions, "options": options, "results": results,
            "headline": [{"poll_id": poll_id, "party_code": k, "pct_from_tables": v} for k, v in headline.items()]}
