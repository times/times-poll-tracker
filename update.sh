#!/bin/sh
# One command to update the Times poll tracker:
#   ./update.sh            check every pollster, add new polls, rebuild the average, widget data and chart,
#                          then commit and push the outputs to GitHub
#   ./update.sh --no-push  the same, without committing or pushing
# Set DW_KEY in your shell first if you also want the Datawrapper chart's data refreshed (draft, not published).
set -e
cd "$(dirname "$0")"
PUSH=1
for a in "$@"; do [ "$a" = "--no-push" ] && PUSH=0; done
echo "== Checking pollsters for new polls"
python3 -m tracker.update
echo "== Rebuilding the average, momentum check and widget data"
python3 -m tracker.average
python3 -m tracker.momentum
python3 -m tracker.widget_data
python3 scripts/chart_average.py > /dev/null
if [ -n "$DW_KEY" ]; then python3 scripts/datawrapper_tracker.py --data-only; fi
if [ "$PUSH" = "1" ]; then
  git add outputs registry
  if git diff --cached --quiet; then echo "== Nothing new to commit"; else
    git commit -q -m "Update polls $(date +%Y-%m-%d)" && git push -q && echo "== Pushed to GitHub"; fi
fi
