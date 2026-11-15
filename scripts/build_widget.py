"""Build widget/index.html (a standalone page, for an iframe or a preview) from the paste-in block
widget/poll_tracker_block.html, and check both are ASCII-only (non-ASCII garbles on pages served
without a charset; write special characters as HTML entities or JS \\u escapes).

    python3 scripts/build_widget.py
"""
from pathlib import Path

W = Path(__file__).resolve().parent.parent / "widget"
block = (W / "poll_tracker_block.html").read_text()
bad = [(i + 1, ch) for i, line in enumerate(block.splitlines()) for ch in line if ord(ch) > 127]
if bad:
    raise SystemExit(f"non-ASCII characters in the block (line, char): {bad[:10]}")
page = ("<!doctype html>\n<html lang=\"en-GB\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>The Times poll tracker</title>\n"
        "<style>body{margin:0;padding:16px;background:#fff}</style>\n</head>\n<body>\n" + block + "\n</body>\n</html>\n")
(W / "index.html").write_text(page)
print("widget/index.html built; block is ASCII-only")
