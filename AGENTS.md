# Times poll tracker: instructions for AI assistants

This repo holds the Times Westminster voting intention tracker: polls read from ten pollsters' own data tables, the Times poll average, and the data for the homepage widget. The files in `outputs/` are the master copy, and the homepage widget reads `outputs/widget.json` live from GitHub.

## "Update times polls"

When the user says **"update times polls"** (or "update the poll tracker", "update polls"), run:

```bash
./update.sh
```

It does everything:
1. Pulls the latest copy from GitHub.
2. Checks every pollster for new polls and adds them.
3. Rebuilds the average, momentum check, group averages (for the demographics widget), widget data and chart.
4. Commits and pushes `outputs/` and `registry/` to GitHub, which updates the live widget within about 5 minutes.

It takes a few minutes. Don't interrupt it, and don't run the steps one at a time. As it checks each pollster, it prints a progress line such as `[####------]  4/10  Opinium: nothing new (52s so far)`. Don't pipe the output through `tail` or `grep`, so these lines show up as it goes. If the user asks how it's getting on, read back the latest one.

**Afterwards, tell the user** what the `== Summary` block says:
- how many new polls were added;
- the new average;
- the latest polls;
- any "Moving" line;
- whether it pushed.

If no polls were added, say so plainly; that's normal between polling days.

**Variants:**
- **"update times polls, don't push"** (or "test update") → `./update.sh --no-push`. It updates locally only.
- If the user wants the Datawrapper chart refreshed too, they must set `DW_KEY` in their own shell first. Never ask them to paste the key into chat, and never write it into a file.

## First time on a new machine

If `./update.sh` fails with a missing Python module, run `python3 -m pip install --user -r requirements.txt`, then run `./update.sh` again. Raw downloads are kept locally in `data/`, which is not committed, so a fresh machine starts without them. That's expected and fine.

## If something goes wrong

- **One pollster's scraper fails:** the rest still update. Report which pollster failed and the error line. Don't hand-edit the CSVs in `outputs/`.
- **A poll is wrong** (e.g. a misread figure or wrong date): the fix goes in `registry/overrides.csv`, not in `outputs/`.
- **`git push` is rejected:** run `git pull --rebase` and push again. Don't force-push.
- **Look before you change code.** Don't change scraper code to make an update pass without telling the user what was wrong.

## Rules

- Commit straight to `main`. No branches or pull requests.
- Never commit `data/` (raw files) or any API key.
- The pollster list and inclusion rules are in `registry/pollsters.json` and `notes/pollster_audit.md`. Don't add or drop pollsters unless asked.
- The widgets are `widget/poll_tracker_block.html` (headline tracker) and `widget/demographics_block.html` (groups). After editing either, run `python3 scripts/build_widget.py`, which rebuilds the standalone pages and checks the blocks are ASCII-only.

More detail is in `README.md`.
