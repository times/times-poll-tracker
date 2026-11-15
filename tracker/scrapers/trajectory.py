"""Trajectory Partnership monthly voting intention (Optimism Index).

Discovery: WordPress posts API (search 'optimism index'); each monthly post links
/mp-files/voting-intention-<month>-<year>.pdf/.

The PDF (2 pages, exported from Excel) has one question in two crossbreak tables. Text
extraction drops empty cells, so a row is only used where its value count equals the column
count (party rows always are; 'Would not vote'/'Don't know' rows have blanks under the VI-base
columns and are kept for the Total column only). Each option is a counts line followed by a
percentages line. Column order is fixed (validated by count and by Male+Female ~= Total).
Headline = 'All likely to vote (6/10+)', the figure Trajectory and Wikipedia report.
"""
import re
import pypdf

from .. import common as C

PID = "trajectory"
SCRAPER = "trajectory@0.1"
POSTS = ("https://trajectorypartnership.com/wp-json/wp/v2/posts?search=optimism%20index&per_page=100"
         "&page={page}&after={since}T00:00:00&_fields=date,slug,link,content")

COLS1 = [("Base", "All giving voting intention"), ("Base", "All likely to vote (6/10+)"), ("Total", "Total"),
         ("Likelihood to vote", "Registered to vote"), ("Likelihood to vote", "Certain to vote (10/10)"),
         ("Likelihood to vote", "8 to 10"), ("Likelihood to vote", "6-10"), ("Gender", "Male"),
         ("Gender", "Female"), ("Age", "18-24"), ("Age", "25-34"), ("Age", "35-44"), ("Age", "45-54"),
         ("Age", "55-64"), ("Age", "65+"), ("Social grade", "AB"), ("Social grade", "C1"),
         ("Social grade", "C2"), ("Social grade", "DE"), ("Ethnicity", "White"), ("Ethnicity", "Ethnic minority")]
COLS1_EARLY = [c for c in COLS1 if c[0] != "Base"]  # Feb-Apr 2026: no VI-base columns
COLS2 = [("Total", "Total"), ("Region", "London"), ("Region", "South (ex. London)"), ("Region", "Midlands"),
         ("Region", "North"), ("Region", "Scotland"), ("Region", "Wales"), ("Employment", "FT/PT"),
         ("Employment", "Retired"), ("Employment", "Not working"), ("Vote in 2024", "Conservative"),
         ("Vote in 2024", "Labour"), ("Vote in 2024", "Liberal Democrat"), ("Vote in 2024", "Reform"),
         ("Vote in 2024", "Green"), ("Vote in 2024", "SNP"), ("Vote in 2024", "Plaid Cymru"),
         ("Vote in 2024", "Other"), ("Vote in 2024", "Didn't vote / DK / Won't say")]
NUM = re.compile(r"^(?P<label>[A-Za-z(][^\d%]*?)\s+(?P<nums>(?:\d+\s*)+)$")
PCT = re.compile(r"^(?:\d+%\s*)+$")


def discover(since):
    page = 1
    seen = set()
    while True:
        r = C.get(POSTS.format(page=page, since=since))
        items = r.json()
        if not isinstance(items, list) or not items:
            return
        for it in items:
            for u in re.findall(r'href="([^"]*voting-intention[^"]*\.pdf/?)"', it["content"]["rendered"]):
                if u not in seen:
                    seen.add(u)
                    yield {"url": u, "page_url": it["link"], "published_at": it["date"][:10]}
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            return
        page += 1


def _table(text, cols, page_no):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    q = next((l for l in lines if l.startswith("Voting Intention")), None)
    out, n_unw, n_w = [], None, None
    for i, l in enumerate(lines):
        m = NUM.match(l)
        if not m:
            continue
        label, nums = m.group("label").strip(), [float(x) for x in m.group("nums").split()]
        pct = None
        if i + 1 < len(lines) and PCT.match(lines[i + 1]):
            pct = [float(x.rstrip("%")) for x in lines[i + 1].split()]
        if label.startswith("Total (unweighted)"):
            n_unw = nums
        elif label.startswith("Total (weighted)"):
            n_w = nums
        elif pct is not None:
            out.append((label, nums, pct))
    if isinstance(cols, dict):  # choose layout by column count
        cols = cols.get(len(n_unw or []))
        if cols is None:
            raise ValueError(f"p{page_no}: {len(n_unw or [])} sample values, no known layout")
    if not n_unw or len(n_unw) != len(cols):
        raise ValueError(f"p{page_no}: {len(n_unw or [])} sample values, expected {len(cols)}")
    return q, out, n_unw, n_w or n_unw, cols


def parse(path, meta):
    reader = pypdf.PdfReader(path)
    pages = [p.extract_text() or "" for p in reader.pages]
    if not pages or "Voting Intention" not in pages[0]:
        return None
    fw = re.search(r"Fieldwork:\s*(.+)", pages[0]).group(1).strip()
    fs, fe = C.parse_fieldwork(fw, default_year=int(meta["published_at"][:4]))
    samp = re.search(r"([\d,]+) GB Adults[^\n]*", pages[0])
    method = re.search(r"([\d,]+ GB Adults.*?)(?:\n|$)", pages[0])
    poll_id = f"{PID}-{fe.isoformat()}"

    unweighted = bool(re.search(r"Unweighted\.", pages[0]))
    q, rows1, nu1, nw1, cols1 = _table(pages[0], {len(COLS1): COLS1, len(COLS1_EARLY): COLS1_EARLY}, 1)
    gi = cols1.index(("Total", "Total"))
    mi = cols1.index(("Gender", "Male"))
    if abs(nu1[mi] + nu1[mi + 1] - nu1[gi]) > 15:
        raise ValueError(f"column check failed: Male+Female {nu1[mi] + nu1[mi + 1]} vs Total {nu1[gi]}")
    tables = [(rows1, nu1, nw1, cols1)]
    if len(pages) > 1 and "Voting Intention" in pages[1]:
        try:
            _, rows2, nu2, nw2, _ = _table(pages[1], COLS2, 2)
            tables.append((rows2, nu2, nw2, COLS2))
        except ValueError:
            pass

    wording = re.sub(r"^Voting Intention\s*-\s*", "", q or "").strip()
    questions = [{"poll_id": poll_id, "question_ref": "TABLE1", "stage": "vi_first", "wording": wording,
                  "base_text": "All GB adults; columns give the VI bases (all giving VI; likely to vote 6/10+)",
                  "order_in_questionnaire": 1}]
    options, results, seen_opt, partial = [], [], set(), []
    for rows, nu, nw, cols in tables:
        for label, nums, pct in rows:
            code = C.party_code(label)
            if label not in seen_opt:
                seen_opt.add(label)
                options.append({"poll_id": poll_id, "question_ref": "TABLE1", "position": len(seen_opt),
                                "label": label, "party_code": code})
            if len(pct) == len(cols):
                use = list(zip(cols, pct, nums if len(nums) == len(cols) else [None] * len(cols), nu, nw))
            else:  # blanks dropped: only the Total column can be placed (it is never blank)
                partial.append(label)
                continue
            for (gv, gl), p, cnt, a, w in use:
                base = "vi_headline_derived" if gl == "All likely to vote (6/10+)" else "as_published"
                results.append({"poll_id": poll_id, "question_ref": "TABLE1", "table_base": base,
                                "break_var": gv, "break_label": gl, "break_std": C.break_std(gv, gl),
                                "option_label": label, "party_code": code, "pct": p, "n_weighted": cnt,
                                "n_unweighted_col": a, "n_weighted_col": w})
    # headline: party shares of the party counts in the likely-to-vote column
    hcol = ("Base", "All likely to vote (6/10+)") if ("Base", "All likely to vote (6/10+)") in cols1 \
        else ("Likelihood to vote", "6-10")
    acol = ("Base", "All giving voting intention") if ("Base", "All giving voting intention") in cols1 \
        else ("Total", "Total")
    def shares(col):
        j = cols1.index(col)
        party = [(C.party_code(l), n[j]) for l, n, _ in rows1
                 if len(n) == len(cols1) and C.party_code(l) not in (None, "DK", "WNV", "REFUSED")]
        tot = sum(v for _, v in party)
        out = {}
        for code, v in party:
            out[code] = round(out.get(code, 0) + v / tot * 100, 4)
        return out, tot
    head, hn = shares(hcol)
    head_all, _ = shares(acol)
    hi = cols1.index(hcol)

    poll = C.new_poll(
        PID, poll_id=poll_id, fieldwork_start=fs.isoformat(), fieldwork_end=fe.isoformat(), fieldwork_text=fw,
        published_date=meta.get("published_at"), panel_provider="Potentia",
        sample_size_total=int(samp.group(1).replace(",", "")) if samp else None,
        sample_size_vi_unweighted=int(nu1[hi]), sample_size_vi_weighted=hn,
        weighting_text=method.group(1).strip() if method else None,
        turnout_text=f"Headline column: {hcol[1]}",
        headline_table_ref="TABLE1", headline_definition_text=f"{hcol[1]}, party shares (DK/WNV/refused excluded)",
        headline_method="ltv_threshold_exclude_dk", methodology_text="\n".join(pages)[:4000],
        bpc_statement=None, source_page_url=meta.get("page_url"), tables_url=meta["url"],
        raw_file=meta["path"], raw_sha256=meta["sha256"], scraper=SCRAPER,
        weighted=not unweighted,
        notes=(("UNWEIGHTED DATA (tables say 'Data are collected using quotas. Unweighted.'). " if unweighted else "") +
               f"Headline computed from counts in the '{hcol[1]}' column. "
               f"Alternative headline ({acol[1]}): " +
               ", ".join(f"{k} {v:.1f}" for k, v in sorted(head_all.items(), key=lambda x: -x[1])) +
               (f". Rows with blank cells kept out of crossbreaks: {sorted(set(partial))}." if partial else ".")),
    )
    return {"poll": poll, "questions": questions, "options": options, "results": results,
            "headline": [{"poll_id": poll_id, "party_code": k, "pct_from_tables": v} for k, v in head.items()]}
