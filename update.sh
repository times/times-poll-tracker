#!/bin/sh
# One command to update the Times poll tracker:
#   ./update.sh            get the latest copy from GitHub, check every pollster, add new polls, rebuild the
#                          average, widget data and chart, then commit and push the outputs to GitHub
#   ./update.sh --no-push  the same, without committing or pushing
# Set DW_KEY in your shell first if you also want the Datawrapper chart's data refreshed (draft, not published).
set -e
cd "$(dirname "$0")"
PUSH=1
for a in "$@"; do [ "$a" = "--no-push" ] && PUSH=0; done

count_polls() { python3 -c "import csv; print(sum(1 for _ in csv.DictReader(open('outputs/headlines_wide.csv'))))"; }

echo "== Getting the latest copy from GitHub"
git pull -q --rebase --autostash || echo "   (couldn't reach GitHub; carrying on with the local copy)"
BEFORE=$(count_polls)

echo "== Checking pollsters for new polls"
python3 -u -m tracker.update
echo "== Rebuilding the average, momentum check, group averages, pollster leans, undecided and widget data"
python3 -m tracker.average
python3 -m tracker.momentum
python3 -m tracker.widget_data
python3 -m tracker.groups > /dev/null
python3 -m tracker.leans > /dev/null
python3 -m tracker.undecided > /dev/null
python3 scripts/chart_average.py > /dev/null
if [ -n "$DW_KEY" ]; then python3 scripts/datawrapper_tracker.py --data-only; fi

AFTER=$(count_polls)
echo "== Summary"
echo "   New polls added: $((AFTER - BEFORE)) (total $AFTER)"
python3 - <<'EOF'
import json
w = json.load(open("outputs/widget.json"))
print("   Average on " + w["latest_date"] + ": " + ", ".join(f"{p['name']} {p['share']}" for p in w["parties"]))
for p in w["polls"][:5]:
    s = p["shares"]
    print(f"   {p['pollster']} ({p['fieldwork_end']}): Lab {s['LAB']}, Con {s['CON']}, Ref {s['REF']}, LD {s['LD']}, Grn {s['GRN']}")
for m in w.get("moving", []):
    print("   Moving: " + m["sentence"])
EOF

if [ "$PUSH" = "1" ]; then
  git add outputs registry
  if git diff --cached --quiet; then echo "== Nothing new to commit"; else
    git commit -q -m "Update polls $(date +%Y-%m-%d)" && git push -q && echo "== Pushed to GitHub"; fi
fi
