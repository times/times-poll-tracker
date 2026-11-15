"""Deltapoll voting intention (relaunched May 2026).

Discovery: https://deltapoll.co.uk/polls-library (paginated /page/N, not in date order); VI polls are
/polls/voteint-YYMMDD (plus occasional variants such as vi-ar-...). Each poll page gives
'Date Published', 'Client', a methodology sentence and a 'Download PDF' link.

The PDF publishes only the headline ('General Election Voting Intention [Excluding 'Don't know'
and 'Would not vote']'), as whole-number percentages, with crossbreaks on several pages: page 1
gender/age/generation with labels glued to the first value ('Conservative20% 19% ...'); later
pages give the break columns as unlabelled rows (weighted n, unweighted n, then one row per
party in the same order). The raw question wording and full option list are not published.

The weighted sample exceeds the unweighted one (e.g. 2,773 v 2,023): Deltapoll blends earlier
waves into each poll (method note, May 2026), so consecutive polls are not independent.
"""
import html as H
import re
import pypdf

from .. import common as C

PID = "deltapoll"
SCRAPER = "deltapoll@0.2"   # 0.2: later-page columns named from the page's own header, never by count
LIB = "https://deltapoll.co.uk/polls-library"

FIRST = [("Total", "Total"), ("Gender", "Male"), ("Gender", "Female"), ("Age", "18 to 24"), ("Age", "25 to 34"),
         ("Age", "35 to 54"), ("Age", "55 to 64"), ("Age", "65+"), ("Generation", "Generation Z"),
         ("Generation", "Millennials"), ("Generation", "Generation X"), ("Generation", "Baby Boomers")]
WIDE_COLS = {12: FIRST, 8: FIRST[:8]}          # page 1: with or without the generation columns
PAGE_COLS = {
    7: [("EU Ref Vote", "Remain"), ("EU Ref Vote", "Leave"), ("GE 2024 Vote", "Con"), ("GE 2024 Vote", "Lab"),
        ("GE 2024 Vote", "Lib Dem"), ("GE 2024 Vote", "Reform"), ("GE 2024 Vote", "Other")],
    8: [("Region", "London"), ("Region", "Rest of South"), ("Region", "Midlands"), ("Region", "North"),
        ("Region", "Wales"), ("Region", "Scotland"), ("Social Grade", "ABC1"), ("Social Grade", "C2DE")],
}


def discover(since):
    page, seen = 1, set()
    while True:
        url = LIB if page == 1 else f"{LIB}/page/{page}"
        try:
            h = C.get(url).text
        except Exception:
            return
        links = list(dict.fromkeys(re.findall(r'href="(https://deltapoll\.co\.uk/polls/[^"]+)"', h)))
        if not links:
            return
        def sdate(link):
            m = re.search(r"(\d{6})", link.rstrip("/").split("/")[-1])
            return f"20{m.group(1)[:2]}-{m.group(1)[2:4]}-{m.group(1)[4:6]}" if m else None
        dates = [d for d in map(sdate, links) if d]
        if dates and max(dates) < since:
            return  # a whole page older than the start date: done (pages are only loosely ordered)
        for link in links:
            slug = link.rstrip("/").split("/")[-1]
            if sdate(link) and sdate(link) < since:
                continue
            if link in seen:
                continue
            seen.add(link)
            try:
                ph = C.get(link).text
            except Exception as e:
                print(f"  deltapoll: could not open {link}: {e}")
                continue
            txt0 = H.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", ph)))
            tags = (re.search(r"Tags\s+(.+?)\s+Client", txt0) or re.search(r"(.)^", "")) and \
                re.search(r"Tags\s+(.+?)\s+Client", txt0).group(1)
            if not (re.match(r"(voteint|vi-)", slug, re.I) or
                    re.search(r"voting intention|politics|labour|burnham|election", tags or "", re.I)):
                continue
            pdf = re.findall(r'href="([^"]+\.pdf)"', ph)
            if not pdf:
                print(f"  deltapoll: no PDF on {link}")
                continue
            txt = H.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", ph)))
            pub = re.search(r"Date Published\s+(\d{2})/(\d{2})/(\d{4})", txt)
            pub = f"{pub.group(3)}-{pub.group(2)}-{pub.group(1)}" if pub else None
            client = re.search(r"Client\s+(.+?)\s+Methodology", txt)
            meth = re.search(r"Methodology\s+(.+?)\s+Download PDF", txt)
            up = re.search(r"/uploads/(\d{4})/(\d{2})/", pdf[0])
            if up:  # 'Date Published' on the page can precede fieldwork; the upload month can't
                import calendar
                y, mth = int(up.group(1)), int(up.group(2))
                bound = f"{y}-{mth:02d}-{calendar.monthrange(y, mth)[1]:02d}"
                page_date, pub = pub, bound
            if pub and pub < since:
                continue
            yield {"url": pdf[0], "page_url": link, "published_at": pub, "page_date": locals().get("page_date"),
                   "tags": tags,
                   "client": client.group(1).strip() if client else None,
                   "method": meth.group(1).strip() if meth else None}
        page += 1  # the library isn't in date order, so walk every page


ROW = re.compile(r"^(?P<label>[A-Za-z][A-Za-z ’'()]*?)\s*(?P<vals>(?:\d+%?\s*)+)$")  # % absent in 2024 PDFs
NUMS = re.compile(r"^(?:\d+\s+)*\d+$")
PCTS = re.compile(r"^(?:\d+%\s*)+$")
SAMPLE_W = re.compile(r"^(Weighted Sample|All GB Adults|All Adults in Great Britain[^\d]*?|Vote(?: \(Weighted N\))?)\s*(\d[\d ]*)$")
SAMPLE_U = re.compile(r"^(Unweighted[^\d]*?Sample)\s*(\d[\d ]*)$")
VOCAB = {  # Deltapoll crossbreak labels (squashed form -> (group, label))
    "Male": ("Gender", "Male"), "Female": ("Gender", "Female"),
    "18to24": ("Age", "18 to 24"), "25to34": ("Age", "25 to 34"), "35to54": ("Age", "35 to 54"),
    "55to64": ("Age", "55 to 64"), "65+": ("Age", "65+"),
    "GenerationZ": ("Generation", "Generation Z"), "GenZ": ("Generation", "Generation Z"),
    "Millennials": ("Generation", "Millennials"), "Mille-nnials": ("Generation", "Millennials"),
    "GenerationX": ("Generation", "Generation X"), "GenX": ("Generation", "Generation X"),
    "BabyBoomers": ("Generation", "Baby Boomers"),
    "London": ("Region", "London"), "RestofSouth": ("Region", "Rest of South"),
    "Midlands": ("Region", "Midlands"), "North": ("Region", "North"), "Wales": ("Region", "Wales"),
    "Scotland": ("Region", "Scotland"),
    "England(LocalElectionArea)": ("Region", "England (Local Election Area)"),
    "England(Other)": ("Region", "England (Other)"),
    "NotUniversity": ("Education", "Not University"), "University": ("Education", "University"),
    "Remain": ("EU Ref Vote", "Remain"), "Leave": ("EU Ref Vote", "Leave"),
    "Con": ("GE 2024 Vote", "Con"), "Lab": ("GE 2024 Vote", "Lab"), "LibDem": ("GE 2024 Vote", "Lib Dem"),
    "Reform": ("GE 2024 Vote", "Reform"), "ABC1": ("Social Grade", "ABC1"), "C2DE": ("Social Grade", "C2DE"),
    "Green": ("GE 2024 Vote", "Green"), "Other": ("GE 2024 Vote", "Other"),
    "Conservative": ("GE 2024 Vote", "Con"), "Labour": ("GE 2024 Vote", "Lab"), "ReformUK": ("GE 2024 Vote", "Reform"),
    "White": ("Ethnicity", "White"), "Non-White": ("Ethnicity", "Non-White"),
    "Under\u00a314k": ("Income", "Under \u00a314k"), "\u00a314kto\u00a321k": ("Income", "\u00a314k to \u00a321k"),
    "\u00a321kto\u00a334k": ("Income", "\u00a321k to \u00a334k"), "\u00a334kto\u00a348k": ("Income", "\u00a334k to \u00a348k"),
    "Morethan\u00a348k": ("Income", "More than \u00a348k"),
}
# group headings can be printed among the labels; skipped when matching
SKIP = {"Generation", "EURefVote", "GE2024Vote", "Region", "SocialGrade", "VotingIntention", "Education", "Gender", "Age"}
# group headings printed under the column labels on later pages
GROUP_HEADS = {"Gender", "Age", "Generation", "EU Ref Vote", "GE 2024 Vote", "Region", "Social Grade",
               "Voting Intention", "Education"}
PARTY_LABELS = {"Con", "Lab", "Lib Dem", "Reform", "Green", "Other"}


def _page_header_cols(page):
    """Column labels of a later crossbreak page, read from the page's own header text (it isn't in
    extract_text's output, but the text pieces are there). Returns [(group, label)] in column order, or []
    if none found. Party-name columns belong to 'GE 2024 Vote' or, on pages that crossbreak by current
    vote, 'Voting Intention', in the order those headings are printed."""
    frags = []
    page.extract_text(visitor_text=lambda t, *a: frags.append(t.strip()) if t.strip() else None)
    if "Total" not in frags:
        return []
    after = frags[frags.index("Total") + 1:]
    heads = [f for f in after if f in GROUP_HEADS]
    labels = []
    for f in after:                # the labels sit between 'Total' and the first number (then counts, %s, footer)
        if re.match(r"^[\d%. ]+$", f):
            break
        labels.append(f)
    # drop spreadsheet column letters (a run of 3+ pieces like L, M, ... AA, AB); a lone 'Z' in 'Generation' 'Z' stays
    letter = [bool(re.fullmatch(r"[A-Z]{1,2}", f)) and f != "UK" for f in labels]
    keep, i = [True] * len(labels), 0
    while i < len(labels):
        j = i
        while j < len(labels) and letter[j]:
            j += 1
        if j - i >= 3:
            keep[i:j] = [False] * (j - i)
        i = max(j, i + 1)
    labels = [f for f, k in zip(labels, keep) if k]
    sq = re.sub(r"\s+", "", "".join(labels))
    keys = sorted(list(VOCAB) + list(SKIP), key=len, reverse=True)
    out, i = [], 0
    while i < len(sq):
        k = next((k for k in keys if sq.startswith(k, i)), None)
        if not k:
            return []              # something unrecognised in the header: don't guess
        if k not in SKIP:
            out.append(VOCAB[k])
        i += len(k)
    party_groups = [h for h in heads if h in ("GE 2024 Vote", "Voting Intention")]
    run, res, prev_party = -1, [], False
    for g, lab in out:
        is_party = lab in PARTY_LABELS
        if is_party and not prev_party:
            run += 1
        if is_party:
            g = party_groups[min(run, len(party_groups) - 1)] if party_groups else g
        res.append((g, lab))
        prev_party = is_party
    return res


def _header_cols(lines):
    """Crossbreak labels from the header lines above the first sample row (greedy vocab match)."""
    fw = next(i for i, l in enumerate(lines) if "Fieldwork:" in l)
    hdr = []
    for l in lines[fw + 1:]:
        if SAMPLE_W.match(l) or SAMPLE_U.match(l) or l.startswith("General Election"):
            break
        hdr.append(l)
    sq = re.sub(r"\s+", "", " ".join(hdr))
    out, i = [], 0
    keys = sorted(VOCAB, key=len, reverse=True)
    while i < len(sq):
        k = next((k for k in keys if sq.startswith(k, i)), None)
        if k:
            out.append(VOCAB[k])
            i += len(k)
        else:
            i += 1
    return out


def _blocks(lines):
    """VI blocks on a page: [(question_text, rows)] in order. A block starts after an
    '[Excluding ...]' line; its question text is the text since the previous block."""
    blocks, i, prev_end = [], 0, 0
    def starts(k):
        l = lines[k]
        nxt = lines[k + 1] if k + 1 < len(lines) else ""
        return bool(ROW.match(nxt)) and (l.startswith("[Excluding") or "Voting Intention" in l
                                         or l.rstrip().endswith("vote for?"))
    while i < len(lines):
        if starts(i):
            q = " ".join(l for l in lines[prev_end:i] if not (SAMPLE_W.match(l) or SAMPLE_U.match(l))
                         and not NUMS.match(l) and not l.startswith(("Deltapoll Survey", "Sample", "New Sample",
                                                                      "Fieldwork", "New Fieldwork", "Prepared")))
            rows, j = [], i + 1
            while j < len(lines) and ROW.match(lines[j]):
                m = ROW.match(lines[j])
                rows.append((m.group("label").strip(), [float(x) for x in re.findall(r"\d+", m.group("vals"))]))
                j += 1
            blocks.append((q.strip(), rows, lines[i] if lines[i].startswith("[") else None))
            prev_end, i = j, j
        else:
            i += 1
    return blocks


def parse(path, meta):
    reader = pypdf.PdfReader(path)
    pages = [p.extract_text() or "" for p in reader.pages]
    if not pages or "Voting Intention" not in pages[0]:
        return None
    p0 = pages[0]
    lines0 = [l.strip() for l in p0.split("\n") if l.strip()]
    fw = re.search(r"Fieldwork:\s*(.+)", p0).group(1).strip()
    fs, fe = C.parse_fieldwork(fw, default_year=int((meta.get("published_at") or "2026")[:4]))
    n = re.search(r"Sample [Ss]ize:\s*([\d,]+)\s+[Aa]dults in (?:the )?(.+)", p0)
    client = re.search(r"Prepared by Deltapoll for (?:the )?(.+)", p0)
    poll_id = f"{PID}-{fe.isoformat()}"

    blocks = _blocks(lines0)
    # keep only Westminster VI tables (a US-election or leader question can sit under a
    # 'Voting Intention' crossbreak heading)
    blocks = [bk for bk in blocks
              if len({C.party_code(l) for l, _ in bk[1]} & {"CON", "LAB", "LD", "REF", "GRN"}) >= 3]
    if not blocks or not blocks[0][1]:
        return None
    cols_hdr = _header_cols(lines0)
    sw = [list(map(float, m.group(2).split())) for m in (SAMPLE_W.match(l) for l in lines0) if m]
    su = [list(map(float, m.group(2).split())) for m in (SAMPLE_U.match(l) for l in lines0) if m]
    results, options, questions, head, notes = [], [], [], {}, []
    for bi, (qtext, rows, excl) in enumerate(blocks):
        ref = "GEVI" if bi == 0 else f"GEVI_ALT{bi}"
        stage = "vi_headline_derived" if bi == 0 else "vi_hypothetical"
        nvals = len(rows[0][1])
        cols = [("Total", "Total")] + cols_hdr if len(cols_hdr) == nvals - 1 else None
        if cols is None:
            cols = [("Total", "Total")]
            notes.append(f"{ref}: {nvals - 1} crossbreak columns not matched to labels ({len(cols_hdr)} found); Total only")
        a = su[bi] if bi < len(su) else [None] * nvals
        w = sw[bi] if bi < len(sw) else [None] * nvals
        qbase, _, qword = qtext.partition("If there were")
        qword = ("If there were" + qword).strip() if qword else qtext
        questions.append({"poll_id": poll_id, "question_ref": ref, "stage": stage,
                          "wording": None if bi == 0 else (qword or None),
                          "population_text": qbase.strip() or None,
                          "base_text": excl.strip("[]") if excl else "All adults in GB who intend to vote (no exclusion note printed)",
                          "order_in_questionnaire": bi + 1})
        for pos, (lab, vals) in enumerate(rows, 1):
            code = C.party_code(lab)
            options.append({"poll_id": poll_id, "question_ref": ref, "position": pos, "label": lab, "party_code": code})
            for (gv, gl), v, x, y in zip(cols, vals, a, w):
                results.append(_res(poll_id, gv, gl, lab, v, x, y, ref, stage))
            if bi == 0 and code not in ("DK", "WNV", "REFUSED"):
                head[code] = head.get(code, 0) + vals[0]
    order = [lab for lab, _ in blocks[0][1]]
    # later pages of the standard format: break columns as unlabelled rows, same option order
    for pg, text in enumerate(pages[1:], 2):
        if "General Election Voting Intention" not in text or len(_blocks([l.strip() for l in text.split("\n") if l.strip()])) > 1:
            continue
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        cnt = [list(map(float, l.split())) for l in lines if NUMS.match(l) and len(l.split()) > 1]
        pct = [[float(x.rstrip("%")) for x in l.split()] for l in lines if PCTS.match(l) and len(l.split()) > 1]
        if not pct:
            continue
        # name the columns from the page's own header; the column count alone is not enough
        # (a 'VI etc.' file can have 8 columns that are social grade + current vote, not regions + grade)
        cols = _page_header_cols(reader.pages[pg - 1])
        if not cols or len(pct) != len(order) or any(len(r) != len(cols) for r in pct):
            notes.append(f"page {pg}: {len(pct[0])} crossbreak columns, {len(cols)} labels read; columns skipped")
            continue
        a, w = (cnt[1], cnt[0]) if len(cnt) >= 2 else ([None] * len(cols), [None] * len(cols))
        for lab, vals in zip(order, pct):
            for (gv, gl), v, x, y in zip(cols, vals, a, w):
                results.append(_res(poll_id, gv, gl, lab, v, x, y, "GEVI", "vi_headline_derived"))
    w_n = sw[0][0] if sw else None
    u_n = su[0][0] if su else None
    cl = client.group(1).strip() if client else (None if (meta.get("client") or "Internal") == "Internal" else meta.get("client"))
    poll = C.new_poll(
        PID, poll_id=poll_id, client=cl, commissioner_type="media" if cl else "self",
        fieldwork_start=fs.isoformat(), fieldwork_end=fe.isoformat(), fieldwork_text=fw,
        published_date=meta.get("published_at"), pooled_waves=True,
        geography_sampled="UK" if n and "United Kingdom" in n.group(2) else "GB", geography_vi_base="GB",
        sample_size_total=int(n.group(1).replace(",", "")) if n else None,
        sample_size_vi_unweighted=u_n, sample_size_vi_weighted=w_n,
        weighting_text=meta.get("method"), headline_table_ref="GEVI",
        headline_definition_text="Excluding 'Don't know' and 'Would not vote'", headline_method="pooled_waves_exclude_dk",
        methodology_text=meta.get("method"), source_page_url=meta.get("page_url"), tables_url=meta["url"],
        raw_file=meta["path"], raw_sha256=meta["sha256"], scraper=SCRAPER,
        notes=("Headline-only tables (whole numbers); raw question wording and option list not published; "
               "Restore Britain not shown separately (in Other). " +
               (f"Weighted base {w_n:.0f} vs unweighted {u_n:.0f}: Deltapoll blends earlier waves into each poll. "
                if w_n and u_n and w_n > u_n * 1.05 else "") +
               (f"{len(blocks) - 1} hypothetical VI table(s) stored separately. " if len(blocks) > 1 else "") +
               "; ".join(notes)).strip(),
    )
    return {"poll": poll, "questions": questions, "options": options, "results": results,
            "headline": [{"poll_id": poll_id, "party_code": k, "pct_from_tables": v} for k, v in head.items()]}


def _res(poll_id, gv, gl, lab, v, a, w, ref="GEVI", stage="vi_headline_derived"):
    return {"poll_id": poll_id, "question_ref": ref, "table_base": stage,
            "break_var": gv, "break_label": gl, "break_std": C.break_std(gv, gl), "option_label": lab,
            "party_code": C.party_code(lab), "pct": v, "n_weighted": None, "n_unweighted_col": a, "n_weighted_col": w}
