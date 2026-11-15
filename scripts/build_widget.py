"""Build the standalone pages (for an iframe or a preview) from the paste-in blocks, and check every block is
ASCII-only (non-ASCII garbles on pages served without a charset; write special characters as HTML entities
or JS \\u escapes).

    python3 scripts/build_widget.py

    widget/poll_tracker_block.html   -> widget/index.html          (headline tracker)
    widget/demographics_block.html   -> widget/demographics.html   (how different groups would vote)
    widget/flows_block.html          -> widget/flows.html          (where 2024 voters have gone)
    widget/leans_block.html          -> widget/leans.html          (how each pollster leans)
    widget/undecided_block.html      -> widget/undecided.html      (undecided voters)
"""
from pathlib import Path

W = Path(__file__).resolve().parent.parent / "widget"
PAGES = {"poll_tracker_block.html": ("index.html", "The Times poll tracker"),
         "demographics_block.html": ("demographics.html", "How different groups would vote"),
         "flows_block.html": ("flows.html", "Where 2024 voters have gone"),
         "leans_block.html": ("leans.html", "How each pollster leans"),
         "undecided_block.html": ("undecided.html", "Undecided voters")}
for src, (dest, title) in PAGES.items():
    if not (W / src).exists():
        continue
    block = (W / src).read_text()
    bad = [(i + 1, ch) for i, line in enumerate(block.splitlines()) for ch in line if ord(ch) > 127]
    if bad:
        raise SystemExit(f"{src}: non-ASCII characters (line, char): {bad[:10]}")
    page = ("<!doctype html>\n<html lang=\"en-GB\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>" + title + "</title>\n"
            "<style>body{margin:0;padding:16px;background:#fff}</style>\n</head>\n<body>\n" + block + "\n</body>\n</html>\n")
    (W / dest).write_text(page)
    print(f"widget/{dest} built from {src}; ASCII-only")
