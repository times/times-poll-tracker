"""Survation national voting intention (UK-wide incl. Northern Ireland).

Discovery: WordPress media API, files Survation_VI_YYYY-MM-DD_Tables*.xlsx.
Tables are stacked in one 'Tables' sheet with Table_ codes; the Contents sheet lists them.
The published headline is UK-wide; a GB figure is recomputed from the nation columns
(Total minus Northern Ireland, on weighted counts) and stored as pct_gb.
"""
import re
import openpyxl

from .. import common as C

PID = "survation"
SCRAPER = "survation@0.1"
MEDIA = ("https://www.survation.com/wp-json/wp/v2/media?per_page=100&page={page}"
         "&after={since}T00:00:00&_fields=id,date,source_url")
# file names are inconsistent (Survation_VI_..., Survaton_VI_..., Survation_Voter_Intention_...,
# client-named national polls), so all xlsx are considered except clearly non-national ones;
# parse() keeps only UK/GB samples with a Westminster VI table.
EXCLUDE = re.compile(r"members|mrp|workbook|scot|holyrood|senedd|wales|welsh|london|mayor|diffley|"
                     r"constituenc|seat|council|_NI_|northern.?ireland", re.I)


def discover(since):
    page = 1
    while True:
        r = C.get(MEDIA.format(page=page, since=since))
        items = r.json()
        if not isinstance(items, list) or not items:
            return
        for it in items:
            u = it["source_url"]
            name = u.split("/")[-1]
            if name.lower().endswith(".xlsx") and not EXCLUDE.search(name):
                yield {"url": u, "page_url": "https://www.survation.com/archive/",
                       "published_at": it["date"][:10]}
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            return
        page += 1


def _after(cells, key, pred):
    i = next((k for k, c in enumerate(cells) if isinstance(c, str) and c.strip().lower() == key), None)
    if i is None:
        return None
    return next((c for c in cells[i + 1:i + 12] if pred(c)), None)


def parse(path, meta):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "Tables" not in wb.sheetnames:
        return None
    cover = wb[wb.sheetnames[0]]
    cl = C.cells(cover)
    texts = [str(c).strip() for c in cl if isinstance(c, str)]
    fw = _after(cl, "fieldwork dates", lambda c: isinstance(c, str) and re.search(r"\d", c)
                and re.search(r"[A-Za-z]{3}", c))
    fs, fe = C.parse_fieldwork(fw, default_year=int(meta["published_at"][:4]))
    n = _after(cl, "sample size", lambda c: isinstance(c, (int, float)))
    pop = _after(cl, "population sampled", lambda c: isinstance(c, str) and re.search(r"aged|adults|residents|18\+", c, re.I))
    if not pop or not re.search(r"\b(UK|GB|Great Britain|United Kingdom)\b", pop) or \
            re.search(r"Scotland|Wales|London|constituenc|members", pop, re.I):
        return None  # not a national adult sample
    poll_id = f"{PID}-{fe.isoformat()}"
    name = meta["url"].split("/")[-1]
    own = re.match(r"Survat?ion_", name, re.I)
    client = None if own else re.split(r"[_-]", name)[0]

    rows = [list(r) for r in wb["Tables"].iter_rows(values_only=True)]
    tables = C.parse_stacked(rows, lambda r: bool(r) and isinstance(r[0], str) and r[0].startswith("Table_"))
    vi = [t for t in tables if re.search(r"for which party", t["title"], re.I)]
    to = [t for t in tables if re.search(r"how likely would you be to vote", t["title"], re.I)
          and not re.search(r"for which party", t["title"], re.I)]
    if not vi:
        return None
    hl = next((t for t in vi if any("removed" in x for x in t["texts"])), vi[-1])
    plan = [(t, "turnout") for t in to[:1]] + [(t, "vi_first") for t in vi[:1]] + \
           [(t, "vi_turnout_filtered") for t in vi[1:] if t is not hl] + [(hl, "vi_headline_derived")]

    questions, options, results = [], [], []
    for order, (t, stage) in enumerate(plan, 1):
        m = re.match(r"(Table_\w+)\.\s*(.*)", t["title"], re.S)
        ref, wording = (m.group(1), m.group(2).strip()) if m else (t["title"][:40], t["title"])
        base = next((x for x in t["texts"] if x.lower().startswith("base")), None)
        questions.append({"poll_id": poll_id, "question_ref": ref, "stage": stage,
                          "wording": None if stage == "vi_headline_derived" else wording,
                          "base_text": base, "order_in_questionnaire": order})
        o, r = C.stacked_to_records(poll_id, ref, stage, t)
        options += o
        results += r

    # headline as published (UK) and re-based to GB
    labels = [c["break_label"] for c in hl["columns"]]
    ni = labels.index("Northern Ireland") if "Northern Ireland" in labels else None
    head = []
    nw = hl["n_weighted"]
    for o in hl["options"]:
        code = C.party_code(o["label"])
        if code in (None, "DK", "WNV", "REFUSED"):
            continue
        uk = o["pct"][0]
        gb = None
        if ni is not None and o["count"] and nw:
            gb = round((o["count"][0] - (o["count"][ni] or 0)) / (nw[0] - (nw[ni] or 0)) * 100, 4)
        head.append({"poll_id": poll_id, "party_code": code, "pct_from_tables": uk, "pct_gb": gb})

    method = " ".join(texts)
    big = bool(n and n >= 5000)  # e.g. the 38 Degrees MRP: raw tables of an MRP fieldwork
    campaign = bool(client and re.search(r"38D|38Degrees|campaign|union|party", client, re.I))
    poll = C.new_poll(
        PID, poll_id=poll_id, client=client,
        commissioner_type="self" if own else ("campaign" if campaign else "other"),
        poll_type="mrp" if big else "standard_vi",
        fieldwork_start=fs.isoformat(), fieldwork_end=fe.isoformat(),
        fieldwork_text=fw, published_date=meta.get("published_at"),
        geography_sampled="UK" if pop and "UK" in pop else "GB", geography_vi_base="UK",
        sample_size_total=int(n) if n else None,
        sample_size_vi_unweighted=int(hl["n_unweighted"][0]) if hl["n_unweighted"] else None,
        sample_size_vi_weighted=hl["n_weighted"][0] if hl["n_weighted"] else None,
        weighting_text=C.find_text(texts, r"^Data were weighted by"),
        turnout_text=C.find_text(texts, r"likelihood to vote was then used"),
        dk_text=C.find_text(texts, r"undecided.*removed"),
        headline_table_ref=questions[-1]["question_ref"], headline_definition_text=questions[-1]["base_text"],
        headline_method="ltv_weighted_exclude_dk", methodology_text="\n".join(texts),
        bpc_statement=C.find_text(texts, r"British Polling Council"),
        source_page_url=meta.get("page_url"), tables_url=meta["url"], raw_file=meta["path"],
        raw_sha256=meta["sha256"], scraper=SCRAPER,
        notes=(("Large sample (n>=5000), treated as MRP fieldwork; these are the raw tables, not the MRP "
                "headline. " if big else "") +
               ("Published headline is UK-wide incl. Northern Ireland; pct_gb recomputed from weighted counts "
                "excluding the Northern Ireland column." if ni is not None else
                "Published headline is UK-wide; no Northern Ireland column found to re-base to GB.")),
    )
    return {"poll": poll, "questions": questions, "options": options, "results": results, "headline": head}
