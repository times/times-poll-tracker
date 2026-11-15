# The Times poll tracker

Westminster voting intention polls since the July 2024 general election, read directly from ten pollsters' own data tables, with the Times poll average and a homepage widget.

**The files in `outputs/` are the master copy.** Raw downloads stay on whichever machine fetched them (in `data/`, not committed).

## Updating

```bash
./update.sh
```

This does the following:
1. Checks every pollster for new polls. It looks back 45 days from each pollster's latest poll and skips anything already listed in `registry/files_seen.csv`.
2. Downloads and reads only the new files.
3. Adds the new polls to the master files.
4. Rebuilds the average, momentum check, widget data and chart.
5. Commits and pushes `outputs/` and `registry/` to GitHub.

It works on any machine with a copy of this repo, even with none of the old raw files. Use `./update.sh --no-push` to update without pushing. If you set `DW_KEY` (your Datawrapper key) in the shell first, it also refreshes the Datawrapper chart's data. It never publishes, and never changes titles or styling.

**First time on a new machine:**

```bash
python3 -m pip install --user -r requirements.txt
```

## The ten pollsters

YouGov, More in Common, Find Out Now, Opinium, Survation, BMG, Freshwater Strategy, Trajectory, Ipsos and Deltapoll.

A pollster is included if it meets all four conditions:
1. It publishes full data tables.
2. It asks a standard GB voting intention question.
3. The poll isn't commissioned by a party or campaign group.
4. It polls regularly (3+ polls in 90 days).

The full register, including exact question wording, is in `registry/pollsters.json`, with the reasoning in `notes/pollster_audit.md`.

## The average, in one line

The average adjusts each poll for its pollster's usual lean and updates as new polls arrive, moving steadily when the polls are stable and quickly when several show the same shift.

It's a Kalman filter with house effects. It runs faster when a "momentum check" (each pollster against its own previous poll) shows a real move. The history is smoothed with later polls, while today's figure only uses polls already published. The method was chosen by replaying the 2015, 2017, 2019 and 2024 campaigns. Details and evidence are in `notes/average_method.md`.

## Output files (`outputs/`)

| File | What's in it |
|---|---|
| `headlines_wide.csv` | **One row per poll**: dates, pollster, client, sample, every party's share |
| `polls.csv` | Everything known about each poll: method text, turnout and don't-know handling, sources, file hashes, corrections |
| `questions.csv`, `options.csv` | Exact question wording and every answer option offered |
| `crosstabs/<pollster>_<year>.csv` | Full crosstabs (age, region, past vote and so on), long format |
| `average_daily.csv` | The average, day by day. `share` is the smoothed history, `share_realtime` is what it said at the time |
| `average_inputs.csv` | Which polls fed the average, and why any were left out |
| `average_house_effects.csv` | Each pollster's estimated lean, by party |
| `momentum_latest.json`, `momentum_daily.csv` | The momentum check |
| `widget.json` | Everything the homepage widget needs, in one small file |
| `chart_average.png` | Quick-look chart |

## Homepage widget (`widget/`)

- `poll_tracker_block.html`: paste the whole file into a custom HTML block (homepage / Shorthand).
- `index.html`: the same widget as a standalone page, for an iframe.

It reads `outputs/widget.json` live from this repo (the `data-src` attribute). It shows the headline averages large, a simplified chart (past year or since the election), any momentum flag, and the latest polls. The fonts and styles are those of the Times budget calculators. The file is ASCII-only: rebuild `index.html` with `python3 scripts/build_widget.py` after editing the block.

## Datawrapper

Chart `3Jawe` (draft). It shows the average lines plus every poll as dots, and is built by `scripts/datawrapper_tracker.py`. Use `--data-only` for refreshes so hand edits in Datawrapper stay.

## Rebuilding from scratch (needs the raw files)

```bash
python3 -m tracker.run --since 2024-07-01   # discover and download everything (slow)
python3 -m tracker.run --reparse            # re-read archived files after a parser change
python3 -m tracker.build_tables             # rebuild outputs from per-poll JSON
python3 -m tracker.update --seed            # rebuild registry/files_seen.csv from the local archive
python3 -m tracker.testdata && python3 -m tracker.replay && python3 -m tracker.replay_v03   # method tests
```

## Code (`tracker/`)

| File | What it does |
|---|---|
| `scrapers/<pollster>.py` | How each pollster's polls are found and read |
| `common.py` | Downloads, archive, dates, party codes, table parsers |
| `update.py` | The incremental updater |
| `average.py`, `methods.py` | The average, the Kalman filter and the momentum check |
| `momentum.py` | Momentum check outputs |
| `widget_data.py` | `widget.json` |
| `replay*.py`, `testdata.py` | Method tests on past elections (Wikipedia poll lists, test use only) |

## Notes

- **YouGov** is scraped under the Times' agreement with YouGov.
- **Survation** reports UK-wide figures. GB re-based shares are in the `*_gb` columns.
- **Trajectory**'s February–May 2026 polls were unweighted, so they're flagged and left out of the average.
- **Hand corrections** go in `registry/overrides.csv`.
