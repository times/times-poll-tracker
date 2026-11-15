"""Freshwater Strategy monthly UK polling for City AM.

Discovery: WordPress media API, files Data-Tables-City-AM-Freshwater-Strategy-UK-Polling-DDMMYY.xlsx.
One 'Tables' sheet; each table follows a 'Back to TOC' row. VI chain: raw question ->
'Vote Intentions (squeezed)' -> 'Vote Intentions (squeezed) VALID' (headline, GB only, 9-10 LTV).
"""
import re
import openpyxl

from .. import common as C

PID = "freshwater"
SCRAPER = "freshwater@0.1"
MEDIA = ("https://freshwaterstrategy.com/wp-json/wp/v2/media?search=City-AM&per_page=100&page={page}"
         "&after={since}T00:00:00&_fields=id,date,source_url")


def discover(since):
    page = 1
    while True:
        r = C.get(MEDIA.format(page=page, since=since))
        items = r.json()
        if not isinstance(items, list) or not items:
            return
        for it in items:
            u = it["source_url"]
            if re.search(r"City-AM.*UK.*\.xlsx$", u, re.I):
                yield {"url": u, "page_url": "https://freshwaterstrategy.com/insights-media/",
                       "published_at": it["date"][:10]}
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            return
        page += 1


def parse(path, meta):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "Tables" not in wb.sheetnames:
        return None
    msheet = next((n for n in wb.sheetnames if n.lower().startswith("method")), None)
    texts = [str(c).strip() for c in C.cells(wb[msheet]) if isinstance(c, str)] if msheet else []
    fw = C.find_text(texts, r"^Fieldwork dates")
    if not fw:
        return None
    fw = re.sub(r"^Fieldwork dates:\s*", "", fw, flags=re.I)
    fs, fe = C.parse_fieldwork(fw, default_year=int(meta["published_at"][:4]))
    samp = C.find_text(texts, r"^Sample:")
    n = int(re.sub(r"\D", "", re.search(r"[\d,]+", samp).group())) if samp else None
    poll_id = f"{PID}-{fe.isoformat()}"

    rows = [list(r) for r in wb["Tables"].iter_rows(values_only=True)]
    title_ids = {id(rows[i]) for i in range(1, len(rows))
                 if rows[i - 1] and rows[i - 1][0] == "Back to TOC" and rows[i] and isinstance(rows[i][0], str)}
    tables = C.parse_stacked(rows, lambda r: id(r) in title_ids, headerless_total_col=1)
    strip = lambda s: re.sub(r"\s+by CAM-FS CROSSBREAKS\s*$", "", s).strip()
    plan = []
    for t in tables:
        q = strip(t["title"])
        if re.search(r"how likely", q, re.I) and re.search(r"vote", q, re.I):
            plan.append((t, "turnout", q))
        elif re.search(r"who would you vote for\?( \(GB only\))?$", q, re.I):
            plan.append((t, "vi_first", q))
        elif re.search(r"Vote Intentions", q, re.I) and re.search(r"valid", q, re.I):
            plan.append((t, "vi_headline_derived", q))
        elif re.search(r"Vote Intentions", q, re.I):
            plan.append((t, "vi_intermediate", q))
    if not any(s == "vi_headline_derived" for _, s, _ in plan):
        return None

    questions, options, results, head, hl = [], [], [], {}, None
    for order, (t, stage, q) in enumerate(plan, 1):
        ref = re.sub(r"\W+", "_", q)[:40].strip("_")
        filt = next((x for x in t["texts"] if x.lower().startswith("filter")), None)
        questions.append({"poll_id": poll_id, "question_ref": ref, "stage": stage,
                          "wording": q if stage in ("turnout", "vi_first") else None,
                          "base_text": filt, "order_in_questionnaire": order})
        o, r = C.stacked_to_records(poll_id, ref, stage, t)
        options += o
        results += r
        if stage == "vi_headline_derived":
            hl = (t, ref, filt)
            for opt in t["options"]:
                code = C.party_code(opt["label"])
                if code not in (None, "DK", "WNV", "REFUSED") and opt["pct"]:
                    head[code] = round(head.get(code, 0) + (opt["pct"][0] or 0), 4)

    t, ref, filt = hl
    poll = C.new_poll(
        PID, poll_id=poll_id, client="City AM", commissioner_type="media",
        fieldwork_start=fs.isoformat(), fieldwork_end=fe.isoformat(), fieldwork_text=fw,
        published_date=meta.get("published_at"), geography_sampled="UK" if samp and "UK" in samp else "GB",
        geography_vi_base="GB", sample_size_total=n,
        sample_size_vi_unweighted=int(t["n_unweighted"][0]) if t["n_unweighted"] else None,
        sample_size_vi_weighted=t["n_weighted"][0] if t["n_weighted"] else None,
        weighting_text=C.find_text(texts, r"^Weighting"), turnout_text=filt,
        dk_text=C.find_text(texts, r"^Voting Intention Adjustments"),
        headline_table_ref=ref, headline_definition_text=filt, headline_method="squeeze_then_exclude",
        methodology_text="\n".join(texts), bpc_statement=C.find_text(texts, r"British Polling Council"),
        source_page_url=meta.get("page_url"), tables_url=meta["url"], raw_file=meta["path"],
        raw_sha256=meta["sha256"], scraper=SCRAPER,
        notes="Sample is UK adults; VI tables filtered to GB and 9-10/10 likelihood to vote.",
    )
    return {"poll": poll, "questions": questions, "options": options, "results": results,
            "headline": [{"poll_id": poll_id, "party_code": k, "pct_from_tables": v} for k, v in head.items()]}
