# Times poll tracker

Full instructions are in `AGENTS.md` at the repo root. Read it first.

## "Update times polls"
- **"update times polls"** (or "update the poll tracker") → run `./update.sh`. It pulls from GitHub, checks all ten pollsters for new polls, rebuilds the average, momentum check, widget data and chart, then commits and pushes. Afterwards, tell the user what the `== Summary` block says: new polls added, the new average, the latest polls, and whether it pushed.
- **"update times polls, don't push"** → run `./update.sh --no-push`.

Commit to `main` only. Never commit `data/` or any API key. Fix wrong polls in `registry/overrides.csv`, never by editing `outputs/`.
