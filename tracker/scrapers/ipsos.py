"""Ipsos UK Political Monitor (KnowledgePanel, monthly).

Discovery: the ipsos.com search page (server-rendered) for 'voting intention'; each release page
links 'Political Monitor Tables <Month YYYY>.pdf'.

The tables PDF (~60 pages) runs crossbreak columns together when extracted as text, so for now
only the Total (weighted) column is read: the headline from 'V1AB/V2 COMBINED VOTING INTENTION -
LIKELY TO VOTE' plus the verbatim question wording and bases. Crosstabs need a layout-aware
parser (pdfplumber with coordinates) - extraction_status 'headline_only'.
"""
import html as H
import re
import pypdf

from .. import common as C

PID = "ipsos"
SCRAPER = "ipsos@0.2"
SEARCH = "https://www.ipsos.com/en-uk/search?search=voting%20intention&page={page}"
SKIP = re.compile(r"/en-uk/(search|about|contact|our-|careers|news-and-events|insights-hub|"
                  r"solutions|products|privacy|legal|cookie|terms|people|sectors|topics)", re.I)


WIKI = "https://en.wikipedia.org/wiki/Opinion_polling_for_the_next_United_Kingdom_general_election"


def _month_end(ym):
    import calendar
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{ym}-{calendar.monthrange(y, m)[1]:02d}"


def discover(since, pages=15):
    """Ipsos's site search misses some releases, so tables PDFs cited on Wikipedia's polling page
    are used as extra discovery seeds. Wikipedia is only used to find Ipsos's own file; all figures
    come from that file."""
    found = set()
    for d in _discover_search(since, pages):
        found.add(d["url"])
        yield d
    w = C.get(WIKI).text
    for u in dict.fromkeys(H.unescape(x) for x in re.findall(r'https://www\.ipsos\.com/sites/default/files/ct/news/documents/[^"\s<>]+\.pdf', w)):
        if u in found or re.search(r"scot|wales|welsh|london", u, re.I):
            continue
        ym = re.search(r"/documents/(\d{4}-\d{2})/", u).group(1)
        if _month_end(ym) < since:
            continue
        yield {"url": u, "page_url": WIKI + " (citation)", "published_at": _month_end(ym)}


PAGES_FILE = C.PROJECT / "registry" / "pages_seen.txt"
USE_PAGES_SEEN = False  # tracker.update turns this on so release pages aren't re-opened
_pages_seen = None


def _seen_pages():
    global _pages_seen
    if _pages_seen is None:
        _pages_seen = set(PAGES_FILE.read_text().split()) if PAGES_FILE.exists() else set()
    return _pages_seen


def save_pages_seen():
    if _pages_seen is not None:
        PAGES_FILE.write_text("\n".join(sorted(_pages_seen)) + "\n")


def _discover_search(since, pages):
    seen = set()
    for page in range(pages):
        h = C.get(SEARCH.format(page=page)).text
        for path in dict.fromkeys(re.findall(r'href="(/en-uk/[a-z0-9-]{20,})"', h)):
            if path in seen or SKIP.search(path):
                continue
            seen.add(path)
            url = "https://www.ipsos.com" + path
            if USE_PAGES_SEEN and url in _seen_pages():
                continue
            art = C.get(url).text
            _seen_pages().add(url)
            pdf = re.findall(r'href="([^"]*Political[^"]*Monitor[^"]*Tables[^"]*\.pdf)"', art)
            pdf = [u for u in pdf if not re.search(r"scot|wales|welsh|london", u, re.I)]
            if not pdf:
                continue
            pub = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', art) or \
                re.search(r'(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}', art)
            pub = pub.group(1) if pub else None
            if pub and pub < since:
                continue
            yield {"url": H.unescape(pdf[0]), "page_url": url, "published_at": pub}


def _last_num(line):
    m = re.match(r"^(.*?)\s*([A-Z][A-Za-z ()'-]+)$", line.strip())
    if not m:
        return None, None
    nums = re.findall(r"\d+", m.group(1))
    return (m.group(2).strip(), float(nums[-1])) if nums else (None, None)


def parse(path, meta):
    reader = pypdf.PdfReader(path)
    pages = [p.extract_text() or "" for p in reader.pages]
    pg = next((i for i, t in enumerate(pages) if re.search(r"COMBINED VOTING INTENTION\s*-\s*LIKELY TO VOTE", t)), None)
    if pg is None:
        return None
    text = pages[pg]
    fwl = re.search(r"Fieldwork dates\s*-\s*(.+?)\s*(?:\(Base|\.\s*\n|\n)", "\n".join(pages[:3]))
    fw = " ".join(fwl.group(1).split()) if fwl else None
    fs, fe = C.parse_fieldwork(re.sub(r"\(am\)|\(pm\)", "", fw or ""),
                               default_year=int((meta.get("published_at") or "2026")[:4]))
    nbase = re.search(r"Base total\s*=\s*([\d,]+)", "\n".join(pages[:3]))
    poll_id = f"{PID}-{fe.isoformat()}"

    # The page is rotated; its Total (W'td) column comes out as fragments like '165 Conservative'
    # (value and row label in one text run), which are read directly.
    frags = []
    reader.pages[pg].extract_text(visitor_text=lambda t, *a: frags.append(t.strip()) if t.strip() else None)
    rows, seen = [], set()
    for f in frags:
        m = re.fullmatch(r"(\d+)\s+([A-Z][A-Za-z ()'-]+)", f)
        if not m or m.group(2) in seen or m.group(2).endswith("Total"):
            continue
        lab = m.group(2).replace("(Lib", "(Lib Dem)").strip()
        if C.party_code(lab):
            seen.add(m.group(2))
            rows.append((lab, float(m.group(1))))
    denom = sum(v for lab, v in rows if C.party_code(lab) not in ("DK", "WNV", "REFUSED"))
    if not rows or not denom:
        raise ValueError("no Total (W'td) party values found on the likely-to-vote page")
    head, options, results = {}, [], []
    for pos, (lab, v) in enumerate(rows, 1):
        code = C.party_code(lab)
        options.append({"poll_id": poll_id, "question_ref": "V1AB/V2", "position": pos, "label": lab, "party_code": code})
        results.append({"poll_id": poll_id, "question_ref": "V1AB/V2", "table_base": "vi_headline_derived",
                        "break_var": "Total", "break_label": "Total (W'td)", "break_std": "total",
                        "option_label": lab, "party_code": code, "pct": round(v / denom * 100, 4),
                        "n_weighted": v, "n_unweighted_col": None, "n_weighted_col": denom})
        if code not in ("DK", "WNV", "REFUSED"):
            head[code] = round(head.get(code, 0) + v / denom * 100, 4)

    alltext = "\n".join(pages)
    def q(code):
        m = re.search(rf"(?<![\w/]){re.escape(code)}\.\s+(.+?)(?:\n|$)", alltext)
        return m.group(1).strip() if m else None
    base_ltv = re.search(r"Base\s*:\s*(All 9/10.+?)(?:\n|$)", alltext)
    base_v2 = re.search(r"Base\s*:\s*(Those undecided.+?)(?:\n|$)", alltext)
    questions = [
        {"poll_id": poll_id, "question_ref": "V1AB", "stage": "vi_first", "wording": q("V1AB"),
         "base_text": None, "order_in_questionnaire": 1},
        {"poll_id": poll_id, "question_ref": "V2", "stage": "vi_squeeze", "wording": q("V2"),
         "base_text": " ".join(base_v2.group(1).split()) if base_v2 else None, "order_in_questionnaire": 2},
        {"poll_id": poll_id, "question_ref": "V1AB/V2", "stage": "vi_headline_derived",
         "wording": q("V1AB/V2"), "base_text": " ".join(base_ltv.group(1).split()) if base_ltv else None,
         "order_in_questionnaire": 3},
    ]
    # full crosstabs from positioned fragments; keep the simple headline as a cross-check
    xq, xo, xr, problems = crosstabs(reader, poll_id)
    status, note = "headline_only", "Total column only; crosstabs could not be parsed."
    if xr:
        xt = {}
        for r in xr:
            if r["question_ref"] == "V1AB/V2_LIKELY" and r["break_label"] == "Total (W'td)" \
                    and r["party_code"] not in ("DK", "WNV", "REFUSED") and r["pct"] is not None:
                xt[r["party_code"]] = xt.get(r["party_code"], 0) + r["pct"]
        diff = {k: (round(v, 2), round(xt.get(k, 0), 2)) for k, v in head.items() if abs(v - xt.get(k, 0)) > 0.05}
        questions, options, results = xq, xo, xr
        status = "auto"
        if xt:  # Ipsos's own definition: party count over 'Total voting (sub-base)'
            head = {k: round(v, 4) for k, v in xt.items()}
        note = ("Crosstabs read from positioned text fragments of the rotated PDF (weighted counts); percentages "
                "recomputed: parties over 'Total voting (sub-base)', other answers over weighted total. Counts are "
                "printed as whole numbers, so small cells can differ from Ipsos's printed % by 1pt. "
                "First column is the unweighted total. Group names assigned from column labels. " +
                (f"Rows skipped: {problems}. " if problems else "") +
                (f"Headline uses the sub-base; the quick Total-column sum differs by up to "
                 f"{max(abs(a - b) for a, b in diff.values()):.2f}pt ({diff})." if diff else "Headline cross-check OK."))
    poll = C.new_poll(
        PID, poll_id=poll_id, fieldwork_start=fs.isoformat(), fieldwork_end=fe.isoformat(), fieldwork_text=fw,
        published_date=meta.get("published_at"), mode="online_probability_panel",
        panel_provider="Ipsos KnowledgePanel",
        sample_size_total=int(nbase.group(1).replace(",", "")) if nbase else None,
        sample_size_vi_weighted=denom, headline_table_ref="V1AB/V2",
        headline_definition_text=questions[-1]["base_text"], headline_method="squeeze_then_exclude",
        turnout_text=questions[-1]["base_text"],
        source_page_url=meta.get("page_url"), tables_url=meta["url"], raw_file=meta["path"],
        raw_sha256=meta["sha256"], scraper=SCRAPER, extraction_status=status, notes=note,
    )
    return {"poll": poll, "questions": questions, "options": options, "results": results,
            "headline": [{"poll_id": poll_id, "party_code": k, "pct_from_tables": v} for k, v in head.items()]}


# ---------------------------------------------------------------- crosstabs (positional)

GROUP_WORDS = {"Ethnicity", "Social grade", "Age", "Gender", "Qualifications", "Past vote",
               "(2024 General Election)", "ONS Regions", "Tenure", "Work sector", "Government",
               "Working status", "Voting", "(Weighted)", "Total", "UnW", "Tot.", "UnWgt", "Likelihood",
               "to vote", "(General Election)", "Total (W'td)"}
GROUP_RULES = [  # (regex on joined column label, group, sticky): sticky groups keep ambiguous party labels
    (r"Ethnic|White", "Ethnicity"), (r"^(AB|C1|C2|DE|ABC1|C2DE)$", "Social grade"),
    (r"^\d+(-\d+|\+)$", "Age"), (r"^(Men|Women)$", "Gender"),
    (r"Would NOT vote|to 10\)|certain|likelihood|depends", "Likelihood to vote"),
    (r"Degree|qual'", "Qualifications"), (r"Did not vote", "Past vote (2024 General Election)"),
    (r"^(Wales|Scotland|England|Greater London|South|Midlands|North)", "ONS Regions"),
    (r"owner|Owned|Mortgage|renter", "Tenure"), (r"^(Private|Public)$", "Work sector"),
    (r"satisfied", "Government satisfaction"), (r"Not working|Full-time|full-time", "Working status"),
    (r"^Green Party$", "Voting intention"),
]


def _frags(page):
    out = []
    def v(t, cm, tm, fd, fs):
        if t.strip():
            out.append((round(tm[4] * cm[0] + tm[5] * cm[2] + cm[4], 1),
                        round(tm[4] * cm[1] + tm[5] * cm[3] + cm[5], 1), t.strip()))
    page.extract_text(visitor_text=v)
    return out


def _join(parts):
    s = ""
    for p in parts:
        if s.endswith("-") and not s.endswith(" -"):
            s = s[:-1] + p
        elif p.startswith("-") and s:
            s = s + p[1:]
        else:
            s = (s + " " + p).strip()
    s = s.replace("Absol utely", "Absolutely").replace("Mort gage", "Mortgage").replace("work ing", "working")
    return {"Scot": "Scotland", "Liberal Democrats (Lib Dem)": "Liberal Democrats"}.get(s, s)


TOKEN = re.compile(r"^(\d+|-|\*)$")


def _page_table(page):
    """One rotated crosstab page -> dict(title, base, columns, rows) or None."""
    fr = _frags(page)
    title = next((t for x, y, t in fr if re.match(r"^(V\d|V1AB)", t) and y < 60), None)
    if not title:
        return None
    base = next((t for x, y, t in fr if t.startswith("Base") and y < 60), None)
    rows = {}
    for x, y, t in fr:
        rows.setdefault(x, []).append((y, t))
    unw = next((x for x, ys in rows.items() if any(t.endswith("Unweighted Total") for y, t in ys)), None)
    if unw is None:
        return None
    hdr_x = sorted(x for x in rows if 80 < x < unw - 1)
    bottom = sorted(rows[hdr_x[-1]], key=lambda i: -i[0])
    col_y = [y for y, t in bottom]
    labels = {i: [] for i in range(len(col_y))}
    for x in hdr_x:
        for y, t in rows[x]:
            if t in GROUP_WORDS:
                continue
            i = min(range(len(col_y)), key=lambda k: abs(col_y[k] - y))
            if abs(col_y[i] - y) <= 10:
                labels[i].append((x, t))
    names = [_join([t for x, t in sorted(labels[i])]) for i in range(len(col_y))]
    has_unw = any(t in ("UnW", "UnWgt", "Tot.") for x in hdr_x for y, t in rows[x])
    if names and names[0] in ("", "Total"):
        names = names[1:]
    names = (["Total (unweighted)"] if has_unw else []) + names + ["Total (W'td)"]
    groups, cur = [], None
    for k, n in enumerate(names):
        if names[k].startswith("Total ("):
            groups.append("Total")
            continue
        for rx, g in GROUP_RULES:
            if re.search(rx, n):
                cur = g
                break
        groups.append(cur or "Crossbreak")
    data = []
    label_side = {x: t for x, y, t in fr if y < 40 and x >= unw - 1}
    for x in sorted(xx for xx in rows if xx >= unw - 0.5):
        fs = sorted(rows[x], key=lambda i: -i[0])
        if any("%" in t for _, t in fs):
            continue
        toks, label = [], None
        for y, t in fs:
            if y < 40:
                continue
            parts = t.split()
            k = 0
            while k < len(parts) and TOKEN.match(parts[k]):
                toks.append(parts[k])
                k += 1
            if k < len(parts):
                label = " ".join(parts[k:])
        if label is None:
            label = next((t for xx, t in label_side.items() if abs(xx - x) <= 1.5), None)
        if label and toks:
            data.append((label, [0.0 if v in ("-", "*") else float(v) for v in toks]))
    return {"title": title, "base": base, "columns": list(zip(groups, names)), "rows": data}


def crosstabs(reader, poll_id):
    """Counts for every VI-related table, re-expressed as percentages of the right base."""
    questions, options, results, problems = [], [], [], []
    seen, done = {}, set()
    for pg in reader.pages:
        t = _page_table(pg)
        if not t or not re.search(r"VOTING INTENTION|General Election|vote", t["title"], re.I):
            continue
        m = re.match(r"^(\S+)\.\s+(.*)", t["title"])
        code, wording = (m.group(1), m.group(2)) if m else (t["title"][:20], t["title"])
        variant = "LIKELY" if "LIKELY TO VOTE" in wording else ("ALL" if " - ALL - " in wording else "")
        ref = f"{code}{'_' + variant if variant else ''}"
        if ref not in seen:
            seen[ref] = len(questions)
            stage = ("vi_headline_derived" if ref == "V1AB/V2_LIKELY" else
                     "vi_first" if code == "V1AB" else "vi_squeeze" if code == "V2" else
                     "vi_combined_all" if ref == "V1AB/V2_ALL" else "other")
            questions.append({"poll_id": poll_id, "question_ref": ref, "stage": stage, "wording": wording,
                              "base_text": re.sub(r"^Base\s*:\s*", "", t["base"] or "").strip() or None,
                              "order_in_questionnaire": len(questions) + 1})
        cols = t["columns"]
        bases = {lab: v for lab, v in t["rows"] if re.search(r"Total", lab)}
        if any(len(v) != len(cols) for v in bases.values()):
            problems.append(f"{ref}: base rows {[len(v) for v in bases.values()]} v {len(cols)} columns")
            continue
        unw, wtd = bases.get("Unweighted Total"), bases.get("Weighted Total")
        sub = next((v for lab, v in bases.items() if lab.startswith("Total voting")), None)
        for lab, vals in t["rows"]:
            if re.search(r"Total", lab):
                continue
            if len(vals) != len(cols):
                problems.append(f"{ref} {lab}: {len(vals)} values v {len(cols)} columns")
                continue
            code_p = C.party_code(lab.replace("(Lib", "(Lib Dem)"))
            denom = sub if (sub and code_p not in ("DK", "WNV", "REFUSED", None)) else wtd
            if not any(o["question_ref"] == ref and o["label"] == lab for o in options):
                options.append({"poll_id": poll_id, "question_ref": ref,
                                "position": sum(o["question_ref"] == ref for o in options) + 1,
                                "label": lab, "party_code": code_p})
            for k, ((gv, gl), v) in enumerate(zip(cols, vals)):
                if (ref, lab, gv, gl) in done:  # Total columns repeat on every banner page
                    continue
                done.add((ref, lab, gv, gl))
                d = denom[k] if denom else None
                results.append({"poll_id": poll_id, "question_ref": ref, "table_base": questions[seen[ref]]["stage"],
                                "break_var": gv, "break_label": gl, "break_std": C.break_std(gv, gl),
                                "option_label": lab, "party_code": code_p,
                                "pct": round(v / d * 100, 4) if d else None, "n_weighted": v,
                                "n_unweighted_col": unw[k] if unw else None, "n_weighted_col": d})
    return questions, options, results, problems
