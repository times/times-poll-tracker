"""YouGov / Sky / Times weekly voting intention.

Permission: the user confirmed on 13 Nov 2026 that the Times' agreement with YouGov
permits scraping (YouGov's public licence otherwise forbids automated extraction).

Discovery: YouGov's public content API, politics category, articles whose slug starts
'voting-intention-'. Each article links a results PDF (VotingIntention_Results_YYMMDD_w.pdf; Mar-Sep 2026
VotingIntention_MRP[_Results]_YYMMDD_w.pdf).

PDF layout varies by week, so columns are read from each page's own header text:
- crossbreak pages: each question row = [previous-wave Total,] this-wave Total, then breaks;
  sample rows carry one Total.
- Total-only pages: labelled rows carry [previous,] current Total; the break values follow as
  unlabelled rows in the same order (first two are the unweighted/weighted samples).
The headline block is 'projected by YouGov MRP model'.
"""
import re
import pypdf

from .. import common as C

PID = "yougov"
SCRAPER = "yougov@0.1"
API = ("https://api-test.yougov.com/public-content/content?type=article&limit=50&offset={off}"
       "&site=yougov.com&language=en-gb&article_type=ArticlePage&category=politics")
ARTICLE = "https://yougov.com/en-gb/articles/{id}-{slug}"

MULTI = ["Lib Dem", "Reform UK", "Rest of South"]
GROUP_OF = {
    "Con": "Vote in 2024 GE", "Lab": "Vote in 2024 GE", "Lib Dem": "Vote in 2024 GE",
    "Reform UK": "Vote in 2024 GE", "Green": "Vote in 2024 GE", "Other": "Vote in 2024 GE",
    "Remain": "EU Ref 2016", "Leave": "EU Ref 2016", "Male": "Gender", "Female": "Gender",
    "Higher": "Socio-economic classification (NS-SEC)",
    "Intermediate": "Socio-economic classification (NS-SEC)",
    "Routine": "Socio-economic classification (NS-SEC)",
    "ABC1": "Social grade", "C2DE": "Social grade",
    "England": "Country", "Wales": "Country", "Scotland": "Country",
    "North": "Region in England", "Midlands": "Region in England", "London": "Region in England",
    "Rest of South": "Region in England",
}

NUMROW = re.compile(r"^(?P<label>.*?[A-Za-z)\]].*?)\s+(?P<nums>(?:(?:\d+|\*|-)\s*)+)$")


def discover(since):
    """Yield dicts {url, page_url, published_at} for VI articles published on/after `since`."""
    off = 0
    while True:
        d = C.get(API.format(off=off)).json()
        items = d.get("data", [])
        if not items:
            return
        for it in items:
            pub = it["published_at"][:10]
            if it["slug"].startswith("voting-intention") and pub >= since:
                page = ARTICLE.format(id=it["id"], slug=it["slug"])
                html = C.get(page).text
                pdfs = re.findall(r"https://[^\"'\\ ]+/VotingIntention[^\"'\\ /]*\.pdf", html)
                if pdfs:
                    yield {"url": pdfs[0], "page_url": page, "published_at": pub, "title": it["title"]}
                else:
                    print(f"  yougov: no results PDF on {page}")
        if min(it["published_at"][:10] for it in items) < since:
            return
        off += 50


def _group(tok):
    if tok in GROUP_OF:
        return GROUP_OF[tok]
    if re.fullmatch(r"\d+(-\d+|\+)", tok):
        return "Age"
    return "?"


def _tokens(header):
    s = " ".join(header.split())
    for m in MULTI:
        s = s.replace(m, m.replace(" ", "\u00a0"))
    return [t.replace("\u00a0", " ") for t in s.split(" ")]


def _is_col(tok):
    return tok == "Total" or tok in GROUP_OF or re.fullmatch(r"\d+(-\d+|\+)", tok) is not None


TEXT_ONLY = re.compile(r"^(\*|\[|Fieldwork|Sample size|\d{1,2}\s*-\s*\d{1,2}$)", re.I)


def _nums(s):
    return [None if x == "-" else 0.0 if x == "*" else float(x) for x in s.split()]


def _rows(text):
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if TEXT_ONLY.match(line):
            out.append((line, None))
            continue
        m = NUMROW.match(line)
        if m:
            out.append((m.group("label").strip(), _nums(m.group("nums"))))
        elif re.fullmatch(r"(?:(?:\d+|\*|-)\s*)+", line):
            out.append((None, _nums(line)))
        else:
            out.append((line, None))
    return out


QUESTION_STARTS = [
    ("HEADLINE", "YG_HEADLINE"),
    ("If there were a general election held", "YG_GENERIC"),
    ("Now, thinking specifically about your own", "YG_CONSTITUENCY"),
    ("And which of these parties would you vote", "YG_OTHER_FOLLOWUP"),
]
STAGE = {"YG_HEADLINE": "vi_headline_derived", "YG_GENERIC": "vi_first",
         "YG_CONSTITUENCY": "vi_first", "YG_OTHER_FOLLOWUP": "vi_second_screen"}
SAMPLE = re.compile(r"(un)?weighted\s*sample", re.I)


def _split_questions(rows):
    """Group lines into question blocks: {ref, text lines, labelled data rows}."""
    blocks, cur = [], None
    for label, nums in rows:
        if nums is None and label:
            starts = [q for st, q in QUESTION_STARTS if _collapse(label).startswith(_collapse(st))]
            if starts:
                cur = {"ref": starts[0], "text": [label], "rows": []}
                blocks.append(cur)
            elif cur is not None and not cur["rows"]:
                cur["text"].append(label)
            elif label.startswith("*"):
                cur = None
            continue
        if cur is not None and label and not SAMPLE.search(label):
            cur["rows"].append((label, nums))
    return blocks


AGES = ["18-24", "25-49", "50-64", "65+", "18-29", "30-39", "40-49", "50-59", "60+", "25-34", "35-44",
        "45-54", "55-64", "65-74", "75+", "16-24", "18-34", "35-54", "55+", "35-49"]
VOCAB = sorted(["Total"] + list(GROUP_OF) + AGES, key=len, reverse=True)


def _columns(rows):
    """Crossbreak column labels in page order, read from the text-only lines. Works on squashed
    text too ('TotalConLabLib Dem...') by greedy longest-match against the known vocabulary."""
    txt = " ".join(l for l, n in rows if n is None and l and not l.startswith(("*", "["))
                   and not re.fullmatch(r"\d{1,2}\s*-\s*\d{1,2}", l)
                   and not re.match(r"(Fieldwork|Sample size|YouGov|HEADLINE|Westminster|%)", l, re.I))
    txt = re.sub(r"Region in England|Vote in 2024 GE|EU Ref 2016|Gender|Age|Country|"
                 r"Socio-economic classification|\(NS-\s*SEC\)", " ", txt)
    squashed = re.sub(r"\s+", "", txt)
    keys = {v.replace(" ", ""): v for v in VOCAB}
    keys["Reform"] = "Reform UK"  # header sometimes wraps 'UK' onto a later line
    out, i = [], 0
    while i < len(squashed):
        for k in sorted(keys, key=len, reverse=True):
            if squashed.startswith(k, i):
                out.append(keys[k])
                i += len(k)
                break
        else:
            i += 1
    return out


CANON_LABELS = ["Con", "Lab", "Lib Dem", "SNP", "Plaid Cymru", "Reform UK", "Green", "Your Party",
                "Restore Britain", "Other", "Conservative", "Labour", "Liberal Democrat",
                "Scottish National Party (SNP)", "Some other party", "Would not vote", "Don't know",
                "Refused", "Workers Party GB", "Social Democratic Party",
                "Trade Unionist and Socialist Coalition", "Heritage Party", "UK Independence Party (UKIP)",
                "Weighted Sample", "Unweighted Sample"]
CANON = {re.sub(r"\W", "", l).lower(): l for l in CANON_LABELS}
KNOWN_WORDING = {
    "YG_HEADLINE": "HEADLINE VOTING INTENTION Westminster Voting Intention",
    "YG_GENERIC": "If there were a general election held tomorrow, which party would you vote for?",
    "YG_CONSTITUENCY": ("Now, thinking specifically about your own constituency, if there were a general "
                        "election held tomorrow and these were the parties standing, which party would you vote for?"),
    "YG_OTHER_FOLLOWUP": "And which of these parties would you vote for?",
}


def _collapse(s):
    return re.sub(r"\W", "", s or "").lower()


def _rows_layout(text):
    out = []
    numtok = re.compile(r"^(\d+|\*|-)$")
    for line in text.split("\n"):
        if not line.strip():
            continue
        toks = [t for t in re.split(r"\s{2,}", line.strip()) if t]
        i = len(toks)
        while i > 0 and numtok.match(toks[i - 1]):
            i -= 1
        lab_toks, nums = toks[:i], toks[i:]
        label = " ".join(lab_toks)
        if nums and lab_toks and re.search(r"[A-Za-z]", label):
            out.append((CANON.get(_collapse(label), " ".join(label.split())), _nums(" ".join(nums))))
        elif nums and not lab_toks:
            out.append((None, _nums(" ".join(nums))))
        else:
            out.append((" ".join(line.split()), None))
    return out


def _page(rows, pg, poll_id, state):
    """Parse one results page. Returns new records; raises ValueError if the layout doesn't add up."""
    res, opts, qs, head = [], [], [], {}
    seen_q, total_done = set(state["seen_q"]), set(state["total_done"])

    def add(ref, lab, gv, gl, v, nu=None, nw=None):
        if v is None:
            return
        res.append({
            "poll_id": poll_id, "question_ref": ref, "table_base": "as_published",
            "break_var": gv, "break_label": gl, "break_std": C.break_std(gv, gl),
            "option_label": lab, "party_code": C.party_code(lab), "pct": v,
            "n_weighted": None, "n_unweighted_col": nu, "n_weighted_col": nw})

    blocks = _split_questions(rows)
    empty = {"results": [], "options": [], "questions": [], "headline": {}, "seen_q": set(), "total_done": set()}
    if not blocks:
        return empty
    for b in blocks:
        if b["ref"] in seen_q:
            continue
        seen_q.add(b["ref"])
        qtext = " ".join(b["text"])
        base = re.search(r"\[(.*?)\]", qtext)
        wording = re.sub(r"\s*\[.*?\]\s*", " ", qtext).strip()
        if _collapse(wording) == _collapse(KNOWN_WORDING[b["ref"]]):
            wording = KNOWN_WORDING[b["ref"]]
        qs.append({"poll_id": poll_id, "question_ref": b["ref"], "stage": STAGE[b["ref"]],
                   "wording": wording, "base_text": " ".join(base.group(1).split()) if base else None,
                   "order_in_questionnaire": len(state["questions"]) + len(qs) + 1})
        for pos, (lab, _) in enumerate(b["rows"], 1):
            opts.append({"poll_id": poll_id, "question_ref": b["ref"], "position": pos,
                         "label": lab, "party_code": C.party_code(lab)})
    cols = _columns(rows)
    if cols and cols[0] != "Total":
        cols = ["Total"] + [c for c in cols if c != "Total"]
    crossbreak = any(len(n) > 3 for b in blocks for _, n in b["rows"])
    if crossbreak:
        samples = [(l, n) for l, n in rows if n and len(n) >= 4 and (l is None or SAMPLE.search(l))]
        if not samples:
            raise ValueError(f"p{pg+1}: no sample rows")
        ncols = len(samples[0][1])
        if len(cols) != ncols:
            raise ValueError(f"p{pg+1}: columns {cols} vs {ncols} sample values")
        colspec = [("Total", "Total") if c == "Total" else (_group(c), c) for c in cols]
        # 2025 layout: a current-VI block (Con Lab Lib Dem Reform UK) precedes the 2024-vote block
        party = [i for i, (g, c) in enumerate(colspec) if g == "Vote in 2024 GE"]
        labs = [colspec[i][1] for i in party]
        if len(labs) != len(set(labs)):
            seen_l = set()
            for i in party:
                if colspec[i][1] not in seen_l:
                    seen_l.add(colspec[i][1])
                    colspec[i] = ("Voting intention", colspec[i][1])
                else:
                    break
        lab_s = {("unw" if l.lower().startswith("unw") else "w"): n for l, n in samples if l}
        if lab_s:
            nu, nw = lab_s.get("unw"), lab_s.get("w")
        else:  # unlabelled: unweighted first, then weighted
            nu, nw = samples[0][1], samples[1][1] if len(samples) > 1 else samples[0][1]
        nu, nw = nu or [None] * ncols, nw or [None] * ncols
        for b in blocks:
            for lab, nums in b["rows"]:
                if len(nums) == ncols + 1:
                    nums = nums[1:]  # drop previous-wave Total
                elif len(nums) != ncols:
                    raise ValueError(f"p{pg+1} {b['ref']} {lab}: {len(nums)} values, {ncols} cols")
                for (gv, gl), v, a, w in zip(colspec, nums, nu, nw):
                    add(b["ref"], lab, gv, gl, v, a, w)
                total_done.add((b["ref"], lab))
                if b["ref"] == "YG_HEADLINE":
                    code = C.party_code(lab)
                    head[code] = head.get(code, 0) + nums[0]
    else:
        brk = [c for c in cols if c != "Total"]
        k = len(brk)
        labelled = [(b["ref"], lab, nums) for b in blocks for lab, nums in b["rows"]]
        unl = [n for l, n in rows if l is None and n and len(n) == k]
        if len(unl) == len(labelled) + 2:
            nu, nw, unl = unl[0], unl[1], unl[2:]
        elif len(unl) == len(labelled):
            nu = nw = [None] * k
        else:
            raise ValueError(f"p{pg+1}: {len(unl)} rows of {k} breaks vs {len(labelled)} labelled rows")
        for (ref, lab, tot), nums in zip(labelled, unl):
            if (ref, lab) not in total_done:
                add(ref, lab, "Total", "Total", tot[-1])
                total_done.add((ref, lab))
            for gl, v, a, w in zip(brk, nums, nu, nw):
                add(ref, lab, _group(gl), gl, v, a, w)
            if ref == "YG_HEADLINE":
                code = C.party_code(lab)
                head[code] = head.get(code, 0) + tot[-1]
    return {"results": res, "options": opts, "questions": qs, "headline": head,
            "seen_q": seen_q - state["seen_q"], "total_done": total_done}


def parse(path, meta):
    reader = pypdf.PdfReader(path)
    pages = [p.extract_text() or "" for p in reader.pages]
    first = pages[0]
    m = re.search(r"Sample size:\s*([\d,]+)\s+(?:adults in (\w+)|(\w+) adults)", first, re.I)
    n_total = int(m.group(1).replace(",", "")) if m else None
    geo = (m.group(2) or m.group(3)) if m else "GB"
    fw = re.search(r"Fieldwork:\s*(.+)", first).group(1).strip()
    fs, fe = C.parse_fieldwork(fw)
    poll_id = f"{PID}-{fe.isoformat()}"
    client = re.search(r"^(YouGov[^\n]*Survey Results)", first, re.M)

    state = {"results": [], "options": [], "questions": [], "headline": {}, "seen_q": set(),
             "total_done": set(), "layout_pages": []}
    for pg, text in enumerate(pages):
        if not re.search(r"Sample\s*size:", text, re.I) or "Weighting Data" in text or "YouGov weights" in text:
            continue
        try:
            upd = _page(_rows(text), pg, poll_id, state)
        except ValueError as e:
            # some PDFs extract with numbers run together ('Con19 21667'); layout mode keeps
            # them apart but letter-spaces the words, so labels are matched by vocabulary
            lay = reader.pages[pg].extract_text(extraction_mode="layout")
            try:
                upd = _page(_rows_layout(lay), pg, poll_id, state)
            except ValueError as e2:
                raise ValueError(f"{e} | layout retry: {e2}")
            state["layout_pages"].append(pg + 1)
        for k in ("results", "options", "questions"):
            state[k] += upd[k]
        state["seen_q"] |= upd["seen_q"]
        state["total_done"] |= upd["total_done"]
        if upd["headline"] and not state["headline"]:
            state["headline"] = upd["headline"]
    results, options, questions, headline = (state["results"], state["options"], state["questions"],
                                             state["headline"])

    method_page = next((p for p in pages if "YouGov weights" in p), "")
    wt = re.search(r"(YouGov weights GB political surveys.*?carried out online\.)", method_page, re.S)
    bpc = re.search(r"(YouGov is a member of the British Polling Council[^\n]*)", "\n".join(pages))
    hl_note = next((q["base_text"] for q in questions if q["question_ref"] == "YG_HEADLINE"), None)
    poll = C.new_poll(
        PID, poll_id=poll_id, client="Sky / The Times" if client and "Times" in client.group(1) else None,
        commissioner_type="media", fieldwork_start=fs.isoformat(), fieldwork_end=fe.isoformat(),
        published_date=meta.get("published_at"), geography_sampled=geo, geography_vi_base=geo,
        panel_provider="YouGov panel", sample_size_total=n_total,
        weighting_text=" ".join(wt.group(1).split()) if wt else None,
        headline_table_ref="YG_HEADLINE", headline_definition_text=hl_note,
        headline_method="mrp_modelled" if hl_note and "MRP" in hl_note else "direct",
        bpc_statement=bpc.group(1).strip() if bpc else None,
        source_page_url=meta.get("page_url"), tables_url=meta["url"], raw_file=meta["path"],
        raw_sha256=meta["sha256"], scraper=SCRAPER, fieldwork_text=fw,
        notes="Headline shares are YouGov's MRP projection from the constituency question, not a direct tabulation.",
    )
    if not headline:
        poll["extraction_status"] = "auto_no_headline"
    if state["layout_pages"]:
        poll["notes"] += f" Pages {state['layout_pages']} read in pypdf layout mode (default text extraction ran numbers together)."
    return {"poll": poll, "questions": questions, "options": options, "results": results,
            "headline": [{"poll_id": poll_id, "party_code": k, "pct_from_tables": v}
                         for k, v in headline.items()]}


# ---------------------------------------------------------------- tracker spreadsheet backfill

TRACKER = "https://api-test.yougov.com/public-data/v5/uk/trackers/voting-intention/download/"
TRACKER_PAGE = "https://yougov.com/en-gb/trackers/voting-intention"


def fetch_tracker():
    import datetime as dt
    today = dt.date.today().isoformat()
    return C.archive(PID, f"{TRACKER}#asof={today}", TRACKER_PAGE, today,
                     filename=f"tracker_voting-intention_{today}.xlsx", fetch_url=TRACKER)


def parse_tracker(path, meta, have):
    """Headline-only polls from YouGov's tracker download for weeks with no results PDF.
    Columns are dated by fieldwork end; values are rounded headline shares (the MRP headline:
    they match the PDFs), with 'Other' including Restore Britain and Your Party.
    `have` = set of fieldwork_end dates already covered by a PDF. Returns (polls, checks)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = {n: [list(r) for r in wb[n].iter_rows(values_only=True)] for n in wb.sheetnames}
    allr = sheets["All adults"]
    question, dates = allr[0][0], [str(d)[:10] for d in allr[0][1:] if d]
    polls, checks = [], {}
    for j, d in enumerate(dates, 1):
        rows = {r[0]: r[j] for r in allr[1:] if r and r[0]}
        head = {C.party_code(k): round(v * 100, 2) for k, v in rows.items()
                if isinstance(v, (int, float)) and k not in ("Unweighted base", "Base")}
        if d in have:
            checks[d] = head
            continue
        poll_id = f"{PID}-{d}"
        results = []
        for sh, data in sheets.items():
            for r in data[1:]:
                if not r or not r[0] or r[0] in ("Unweighted base", "Base") or j >= len(r) or r[j] is None:
                    continue
                gv = "Total" if sh == "All adults" else ("Vote in 2024 GE" if sh in ("Conservative", "Labour", "Liberal Democrat", "Reform UK")
                                                         else "EU Ref 2016" if "Remain" in sh or "Leave" in sh
                                                         else "Gender" if sh in ("Male", "Female")
                                                         else "Age" if re.match(r"\d", sh)
                                                         else "Social grade" if sh in ("ABC1", "C2DE") else "Region")
                nb = next((x[j] for x in data if x and x[0] == "Unweighted base"), None)
                results.append({"poll_id": poll_id, "question_ref": "YG_TRACKER", "table_base": "tracker_headline",
                                "break_var": gv, "break_label": sh, "break_std": C.break_std(gv, sh),
                                "option_label": r[0], "party_code": C.party_code(r[0]), "pct": round(r[j] * 100, 2),
                                "n_weighted": None, "n_unweighted_col": nb, "n_weighted_col": None})
        poll = C.new_poll(
            PID, poll_id=poll_id, client="Sky / The Times", commissioner_type="media",
            fieldwork_start=None, fieldwork_end=d, published_date=None, panel_provider="YouGov panel",
            sample_size_vi_unweighted=rows.get("Unweighted base"), headline_table_ref="YG_TRACKER",
            headline_definition_text="YouGov voting intention tracker download (headline figures, rounded)",
            headline_method="mrp_modelled_assumed", source_page_url=TRACKER_PAGE, tables_url=TRACKER,
            raw_file=meta["path"], raw_sha256=meta["sha256"], scraper=SCRAPER + "+tracker",
            extraction_status="headline_only",
            notes=("From YouGov's tracker spreadsheet: headline only, rounded, no fieldwork start or "
                   "question detail; Other includes Restore Britain and Your Party. Column date taken "
                   "as fieldwork end. Headline method before 10 Mar 2026 not confirmed."))
        polls.append({"poll": poll, "questions": [{"poll_id": poll_id, "question_ref": "YG_TRACKER",
                      "stage": "vi_headline_derived", "wording": question, "base_text": None,
                      "order_in_questionnaire": 1}], "options": [], "results": results,
                      "headline": [{"poll_id": poll_id, "party_code": k, "pct_from_tables": v} for k, v in head.items()]})
    return polls, checks
