"""BMG Research monthly voting intention for The i.

Discovery: WordPress media API, files *-omnibus-tables-for-the-i.xlsx (and other 'the-i' xlsx).
WinCross export: one 'Tables' sheet, tables headed 'Table N'; the VI question appears several
times with successive bases (raw -> likelihood factors -> squeeze -> registration -> DK removed).
The last ('Not sure and prefer not to say removed') is the headline.
"""
import re
import openpyxl

from .. import common as C

PID = "bmg"
SCRAPER = "bmg@0.1"
MEDIA = ("https://bmgresearch.com/wp-json/wp/v2/media?search={q}&per_page=100&page={page}"
         "&after={since}T00:00:00&_fields=id,date,source_url")


def discover(since):
    seen = set()
    for q in ("the-i", "for-the-i", "i-paper", "omni", "voting-intention"):
        page = 1
        while True:
            r = C.get(MEDIA.format(q=q, page=page, since=since))
            items = r.json()
            if not isinstance(items, list) or not items:
                break
            for it in items:
                u = it["source_url"]
                if u in seen or not u.lower().endswith(".xlsx") or not re.search(r"omni|the-i|voting", u, re.I):
                    continue
                seen.add(u)
                yield {"url": u, "page_url": "https://bmgresearch.com/news/", "published_at": it["date"][:10]}
            if page >= int(r.headers.get("X-WP-TotalPages", 1)):
                break
            page += 1


def parse(path, meta):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "Tables" not in wb.sheetnames:
        return None
    msheet = next((n for n in wb.sheetnames if n.lower().startswith("method")), wb.sheetnames[0])
    texts = [str(c).strip() for c in C.cells(wb[msheet]) if isinstance(c, str)]
    fw = C.find_text(texts, r"^Fieldwork dates")
    if not fw:
        return None
    fw = re.sub(r"^Fieldwork dates:\s*", "", fw, flags=re.I)
    fs, fe = C.parse_fieldwork(fw, default_year=int(meta["published_at"][:4]))
    samp = C.find_text(texts, r"^Sample:")
    n = int(re.sub(r"\D", "", re.search(r"[\d,]+", samp).group())) if samp else None
    geo = "GB" if samp and "GB" in samp else "UK" if samp and "UK" in samp else "GB"
    poll_id = f"{PID}-{fe.isoformat()}"

    rows = [list(r) for r in wb["Tables"].iter_rows(values_only=True)]
    tables = C.parse_stacked(rows, lambda r: len(r) > 1 and isinstance(r[1], str) and re.match(r"^Table \d+$", r[1].strip()))
    for t in tables:
        t["question"] = next((x for x in t["texts"] if re.match(r"^\w+: ", x)), t["title"])
        t["base"] = next((x.replace("\xa0", " ").strip() for x in t["texts"] if x.lower().startswith("base")), None)
    vi = [t for t in tables if re.match(r"^WouldVoteToday(Revised)?:", t["question"])]
    if not vi:
        return None
    hl = next((t for t in vi if t["base"] and "removed" in t["base"].lower()), vi[-1])
    plan = []
    for t in tables:
        q = t["question"]
        if re.match(r"^BMG_LHV|likely would you be to vote", q, re.I) and not any(s == "turnout" for _, s in plan):
            plan.append((t, "turnout"))
        elif t is hl:
            plan.append((t, "vi_headline_derived"))
        elif q.startswith("WouldVoteTodayUnsure"):
            plan.append((t, "vi_squeeze"))
        elif t in vi:
            plan.append((t, "vi_first" if not any(s == "vi_first" for _, s in plan) else "vi_intermediate"))

    questions, options, results = [], [], []
    for order, (t, stage) in enumerate(plan, 1):
        code, _, wording = t["question"].partition(": ")
        ref = f"{t['title'].replace(' ', '')}_{code}"  # e.g. Table7_WouldVoteTodayRevised
        questions.append({"poll_id": poll_id, "question_ref": ref, "stage": stage,
                          "wording": wording.strip(), "base_text": t["base"], "order_in_questionnaire": order})
        o, r = C.stacked_to_records(poll_id, ref, stage, t)
        options += o
        results += r
    head = {}
    for o in hl["options"]:
        code = C.party_code(o["label"])
        if code in (None, "DK", "WNV", "REFUSED") or not o["pct"]:
            continue
        head[code] = round(head.get(code, 0) + (o["pct"][0] or 0), 4)

    poll = C.new_poll(
        PID, poll_id=poll_id, client="The i Paper", commissioner_type="media",
        fieldwork_start=fs.isoformat(), fieldwork_end=fe.isoformat(), fieldwork_text=fw,
        published_date=meta.get("published_at"), geography_sampled=geo, geography_vi_base=geo,
        sample_size_total=n,
        sample_size_vi_unweighted=int(hl["n_unweighted"][0]) if hl["n_unweighted"] else None,
        sample_size_vi_weighted=hl["n_weighted"][0] if hl["n_weighted"] else None,
        weighting_text=C.find_text(texts, r"^Weighting"),
        turnout_text=None, dk_text=C.find_text(texts, r"^Voting Intention Adjustments"),
        headline_table_ref=questions[[s for _, s in plan].index("vi_headline_derived")]["question_ref"],
        headline_definition_text=hl["base"], headline_method="squeeze_then_past_vote",
        methodology_text="\n".join(texts), bpc_statement=C.find_text(texts, r"British Polling Council"),
        source_page_url=meta.get("page_url"), tables_url=meta["url"], raw_file=meta["path"],
        raw_sha256=meta["sha256"], scraper=SCRAPER,
        notes=C.find_text(texts, r"^Electoral Registration Adjustment"),
    )
    return {"poll": poll, "questions": questions, "options": options, "results": results,
            "headline": [{"poll_id": poll_id, "party_code": k, "pct_from_tables": v} for k, v in head.items()]}
