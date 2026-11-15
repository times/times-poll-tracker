"""Flatten registry/pollsters.json into registry/pollsters.csv (one row per firm).

The JSON is the source of truth and is edited by hand. Run this after editing it:
    python3 scripts/build_register.py
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "registry" / "pollsters.json"
OUT = HERE / "registry" / "pollsters.csv"

COLUMNS = [
    "pollster_id", "name", "proposed_status", "status_reason", "polls_1aug_13nov_2026",
    "cadence", "regular_client", "bpc_member", "mode", "geography_sampled",
    "geography_vi_base", "typical_n", "turnout_method", "turnout_threshold",
    "vi_question", "vi_options_table_order", "second_screen_question", "squeeze_question",
    "dk_treatment", "restore_britain_prompt", "your_party_prompt", "pooled_waves",
    "tables_format", "scrape_difficulty", "tables_index_url", "latest_tables_url",
    "latest_fieldwork", "reuse_terms", "audit_level",
]

VALID_STATUS = {"include", "include_provisional", "include_when_active", "list_only", "inactive"}
VALID_PROMPT = {"first_screen", "second_screen", "not_named", "unknown", None}


def flat(v):
    if isinstance(v, list):
        return " ; ".join(str(x) for x in v)
    if v is None:
        return ""
    return v


def main():
    reg = json.loads(SRC.read_text())
    rows, ids = [], set()
    for p in reg["pollsters"]:
        pid = p["pollster_id"]
        assert pid not in ids, f"duplicate pollster_id {pid}"
        ids.add(pid)
        assert p.get("proposed_status") in VALID_STATUS, f"{pid}: bad proposed_status"
        for k in ("restore_britain_prompt", "your_party_prompt"):
            assert p.get(k) in VALID_PROMPT, f"{pid}: bad {k}"
        rows.append({c: flat(p.get(c)) for c in COLUMNS})
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} pollsters to {OUT.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
