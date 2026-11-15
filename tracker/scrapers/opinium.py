"""Opinium / Observer weekly voting intention.

Discovery: WordPress media API; tables files are named VI-YYYY-MM-DD-...xlsx.
Questions are located through the workbook's Index sheet (code -> question text), so a change
of question codes between waves doesn't break the parser.
"""
import re
import openpyxl

from .. import common as C

PID = "opinium"
SCRAPER = "opinium@0.1"
MEDIA = ("https://www.opinium.com/wp-json/wp/v2/media?search={q}&per_page=100&page={page}"
         "&after={since}T00:00:00&_fields=id,date,slug,source_url,post")
POST = "https://www.opinium.com/wp-json/wp/v2/posts/{id}?_fields=link"


def discover(since):
    """Observer VI tables are named VI-YYYY-MM-DD-..., Observer-VI-YYYY-MM-DD-... or
    Opinium-Observer-Tables-...; parse() keeps only workbooks with a HeadlineVI sheet."""
    seen = set()
    for q in ("VI-", "Observer"):
        page = 1
        while True:
            r = C.get(MEDIA.format(q=q, page=page, since=since))
            items = r.json()
            if not isinstance(items, list) or not items:
                break
            for it in items:
                u = it["source_url"]
                if u in seen or not re.search(r"/(VI-\d{4}-\d{2}-\d{2}|Observer-VI-\d{4}|Opinium-Observer)[^/]*\.xlsx$", u, re.I):
                    continue
                seen.add(u)
                page_url = None
                if it.get("post"):
                    try:
                        page_url = C.get(POST.format(id=it["post"])).json().get("link")
                    except Exception:
                        pass
                yield {"url": u, "page_url": page_url or "https://www.opinium.com/polling-tables-archive/",
                       "published_at": it["date"][:10]}
            if page >= int(r.headers.get("X-WP-TotalPages", 1)):
                break
            page += 1


def _index(wb):
    out = {}
    if "Index" not in wb.sheetnames:
        return out
    for r in wb["Index"].iter_rows(values_only=True):
        cells = [c for c in r if c not in (None, "")]
        if len(cells) >= 2 and isinstance(cells[0], str) and cells[0] in wb.sheetnames:
            out[cells[0]] = str(cells[1]).strip()
    return out


def parse(path, meta):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    idx = _index(wb)
    vi_codes = {k: v for k, v in idx.items() if re.match(r"V\d", k)}  # VI section of the questionnaire
    find = lambda pat: next((k for k, v in vi_codes.items() if re.search(pat, v, re.I)), None)
    plan = [
        (find(r"how likely .*vote|likelihood to vote"), "turnout"),
        (find(r"general election tomorrow, (for )?which party"), "vi_first"),
        (find(r"vote for another party"), "vi_second_screen"),
        (find(r"if you had to choose|leaning|inclined|forced"), "vi_squeeze"),
        ("HeadlineVI" if "HeadlineVI" in wb.sheetnames else find(r"^headline vi"), "vi_headline_derived"),
    ]
    plan = [(s, st) for s, st in plan if s]
    if not any(st == "vi_headline_derived" for _, st in plan):
        return None
    cover = wb["FRONT PAGE"] if "FRONT PAGE" in wb.sheetnames else wb[wb.sheetnames[0]]
    kv, texts = C.cover_lookup(cover)
    fs, fe = C.parse_fieldwork(str(kv.get("field dates")), default_year=int(meta["published_at"][:4]))
    poll_id = f"{PID}-{fe.isoformat()}"
    sample = str(kv.get("sample", ""))

    questions, options, results, headline, hl_grid = [], [], [], {}, None
    order = 0
    for sheet, stage in plan:
        try:
            g = C.parse_grid(wb[sheet])
        except ValueError:
            if stage == "vi_headline_derived":
                raise
            continue
        order += 1
        qline = g["header_text"][0] if g["header_text"] else idx.get(sheet)
        wording = re.sub(r"^Q:\s*[\w ()]+\.\s*", "", qline or "").strip() or None
        questions.append({"poll_id": poll_id, "question_ref": sheet, "stage": stage,
                          "wording": None if stage == "vi_headline_derived" else wording,
                          "base_text": g["bases"][0]["text"] if g["bases"] else None,
                          "order_in_questionnaire": order})
        o, r = C.grid_to_records(poll_id, sheet, stage, g)
        options += o
        results += r
        if stage == "vi_headline_derived":
            hl_grid, headline = g, C.headline_from_grid(g)

    ni = [r for r in results if r["question_ref"] == (hl_grid and plan[-1][0]) and r["break_label"] == "Northern Ireland"]
    poll = C.new_poll(
        PID, poll_id=poll_id, client="The Observer" if C.find_text(texts, r"Observer") else None,
        commissioner_type="media" if C.find_text(texts, r"Observer") else "self",
        fieldwork_start=fs.isoformat(), fieldwork_end=fe.isoformat(), published_date=meta.get("published_at"),
        geography_sampled="UK" if "UK" in sample else "GB",
        geography_vi_base="GB" if not any(r["n_unweighted_col"] for r in ni) else "UK",
        sample_size_total=int(re.sub(r"\D", "", sample.split()[0])) if sample else None,
        sample_size_vi_unweighted=int(hl_grid["n_unweighted"][0]) if hl_grid and hl_grid["n_unweighted"] else None,
        sample_size_vi_weighted=hl_grid["n_weighted"][0] if hl_grid and hl_grid["n_weighted"] else None,
        weighting_text=str(kv.get("weighting")) if kv.get("weighting") else None,
        headline_table_ref=plan[-1][0],
        headline_definition_text=hl_grid["bases"][0]["text"] if hl_grid and hl_grid["bases"] else None,
        headline_method="exclude_dk",
        methodology_text="\n".join(texts), bpc_statement=C.find_text(texts, r"British Polling Council"),
        source_page_url=meta.get("page_url"), tables_url=meta["url"], raw_file=meta["path"],
        fieldwork_text=str(kv.get("field dates")) if kv.get("field dates") else None,
        raw_sha256=meta["sha256"], scraper=SCRAPER,
    )
    return {"poll": poll, "questions": questions, "options": options, "results": results,
            "headline": [{"poll_id": poll_id, "party_code": k, "pct_from_tables": v} for k, v in headline.items()]}
