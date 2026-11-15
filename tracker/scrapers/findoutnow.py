"""Find Out Now weekly GB voting intention.

Discovery: WordPress posts API on cms.findoutnow.co.uk, posts titled 'Voting intention: <date>'
(MRP and commissioned posts are skipped); the post body links the 'Full data tables' xlsx.
"""
import html
import re
import openpyxl

from .. import common as C

PID = "findoutnow"
SCRAPER = "findoutnow@0.1"
POSTS = ("https://cms.findoutnow.co.uk/wp-json/wp/v2/posts?search=voting%20intention&per_page=100"
         "&page={page}&after={since}T00:00:00&_fields=id,date,slug,title,content")


def discover(since):
    page = 1
    while True:
        r = C.get(POSTS.format(page=page, since=since))
        items = r.json()
        if not isinstance(items, list) or not items:
            return
        for it in items:
            title = html.unescape(it["title"]["rendered"])
            if not re.match(r"voting intention", title, re.I) or re.search(r"mrp|scotland|scottish|wales|welsh", title, re.I):
                continue
            body = it["content"]["rendered"]
            links = re.findall(r'href="([^"]+\.xlsx)"', body)
            if not links:
                print(f"  findoutnow: no xlsx in post {it['slug']}")
                continue
            yield {"url": links[0], "page_url": f"https://findoutnow.co.uk/blog/{it['slug']}/",
                   "published_at": it["date"][:10], "title": title}
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            return
        page += 1


SHEETS = [("Turnout", "turnout"), ("Voting", "vi_first"), ("Squeeze", "vi_squeeze"),
          ("Headline VI", "vi_headline_derived")]


def parse(path, meta):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    names = {n.lower(): n for n in wb.sheetnames}
    if "headline vi" not in names:
        return None
    kv, texts = C.cover_lookup(wb[wb.sheetnames[0]])
    fw_text = next((v for k, v in kv.items() if k.startswith("fieldwork")), None)
    fs, fe = C.parse_fieldwork(str(fw_text), default_year=int(meta["published_at"][:4]))
    variant = bool(re.search(r"restore", meta["url"].split("/")[-1], re.I))
    poll_id = f"{PID}-{fe.isoformat()}" + ("-rbprompt" if variant else "")
    pop = next((v for k, v in kv.items() if k.startswith("population")), "") or ""

    questions, options, results, headline, hl_grid = [], [], [], {}, None
    order = 0
    for sheet, stage in SHEETS:
        name = names.get(sheet.lower())
        if not name:
            continue
        order += 1
        g = C.parse_grid(wb[name])
        ht = [t for t in g["header_text"] if t.lower() not in (name.lower(), "likelihood to vote", "squeeze question")]
        wording = ht[0] if ht and stage != "vi_headline_derived" else None
        base = ht[0] if ht and stage == "vi_headline_derived" else None
        questions.append({"poll_id": poll_id, "question_ref": name, "stage": stage, "wording": wording,
                          "base_text": base, "order_in_questionnaire": order})
        o, r = C.grid_to_records(poll_id, name, stage, g)
        options += o
        results += r
        if stage == "vi_headline_derived":
            hl_grid, headline = g, C.headline_from_grid(g)

    poll = C.new_poll(
        PID, poll_id=poll_id, fieldwork_start=fs.isoformat(), fieldwork_end=fe.isoformat(),
        published_date=meta.get("published_at"),
        geography_sampled="GB" if "GB" in str(pop) else "UK",
        panel_provider="Pick My Postcode",
        sample_size_total=int(C._num(kv.get("sample size")) or 0) or None,
        sample_size_vi_weighted=round(hl_grid["n_weighted"][0], 1) if hl_grid and hl_grid["n_weighted"] else None,
        weighting_text=next((str(v) for k, v in kv.items() if k.startswith("sample detail")), None),
        turnout_text=next((str(v) for k, v in kv.items() if k.startswith("voting intention methodology")), None),
        dk_text=next((str(v) for k, v in kv.items() if k.startswith("voting intention methodology")), None),
        headline_table_ref="Headline VI",
        headline_definition_text=next((q["base_text"] for q in questions if q["stage"] == "vi_headline_derived"), None),
        headline_method="squeeze_then_exclude",
        methodology_text="\n".join(texts), bpc_statement=C.find_text(texts, r"British Polling Council"),
        source_page_url=meta.get("page_url"), tables_url=meta["url"], raw_file=meta["path"],
        fieldwork_text=str(fw_text) if fw_text else None,
        raw_sha256=meta["sha256"], scraper=SCRAPER,
        notes=("Experimental variant: same method as the weekly tracker but Restore Britain and Your Party "
               "are named options. Separate series; not a second weekly poll." if variant else
               "Restore Britain is not a named option; it sits inside 'Other'."),
    )
    poll["series"] = "findoutnow_rb_prompted" if variant else "findoutnow"
    return {"poll": poll, "questions": questions, "options": options, "results": results,
            "headline": [{"poll_id": poll_id, "party_code": k, "pct_from_tables": v} for k, v in headline.items()]}
