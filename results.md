# Results

Last updated: 2026-11-13

Scrapers are running for ten firms: YouGov, More in Common, Find Out Now, Opinium, Survation, BMG, Freshwater, Trajectory, Ipsos and Deltapoll. Sections 2 and 3 are still one poll per firm, from the scoping audit.

## 0) Scraper coverage and checks

### Headline
481 polls from ten firms since the 2024 election (plus a few pre-election), scraped from their own tables. July–December 2024: all 28 polls Wikipedia lists for these firms are in and match. Against Wikipedia, 228 of 232 polls fielded in 2026 match on every main party within rounding. The other four are explained below. Wikipedia lists two 2026 polls from these firms that we haven't found a tables file for.

### Evidence table

| Firm | Series | Polls | Fieldwork range | Wikipedia check (2026) |
|---|---|---:|---|---|
| YouGov | weekly (full tables) | 37 | 10 Mar–9 Nov 2026 | all match |
| YouGov | weekly (headline only, tracker xlsx) | 59 | 13 Jan 2025–2 Mar 2026 | all match |
| More in Common | weekly | 95 | 26 Sep 2024–9 Nov 2026 | 45/45 |
| Find Out Now | weekly | 46 | 31 Dec 2025–12 Nov 2026 | 45/46 |
| Find Out Now | Restore Britain + Your Party named | 4 | 21 Feb–16 Apr 2026 | 2 not on Wikipedia |
| Opinium | weekly (Observer) | 30 | 9 Jan–6 Nov 2026 | 30/30 |
| Survation | ~fortnightly (UK-wide; GB re-based too) | 16 | 14 Jan–12 Nov 2026 | 15/16; 5 Mar poll not found |
| BMG | monthly (The i) | 10 | 29 Jan–29 Oct 2026 | 10/10 |
| Freshwater | monthly (City AM) | 11 | 11 Jan–1 Nov 2026 | 11/11 |
| Trajectory | monthly | 9 | 12 Feb–12 Nov 2026 | 9/9 |
| Ipsos | monthly (full crosstabs) | 8 | 27 Jan–22 Oct 2026 | 8/8 within rounding |
| Deltapoll | ~fortnightly since May (headline tables only; pooled waves) | 12 | 1 May–9 Nov 2026 | 12/12 |

The four 2026 polls that don't match Wikipedia exactly:

| Poll | Issue |
|---|---|
| findoutnow-2026-04-29 | Tables: Lab 15.6%. Wikipedia: 17%. All other parties match. The FON post shows its numbers as an image, so check by eye. |
| survation-2026-09-04 | The 38 Degrees MRP (n=8,124). We have the raw tables; Wikipedia shows the modelled MRP headline. Flagged `poll_type=mrp`, `commissioner_type=campaign`. |
| moreincommon-2026-06-29 | Tables say fieldwork 26–29 June; Wikipedia says 26–28 June. The figures match. |
| findoutnow-2026-02-21-rbprompt, -03-04-rbprompt | FON's Restore Britain–named variant. Not listed on Wikipedia (later ones are). |

Two things to know before building an average:
- **Trajectory's Feb–May 2026 polls are unweighted.** The tables say "Data are collected using quotas. Unweighted." They're flagged `weighted=false`. Weighting to 2024 vote starts in July.
- **Deltapoll blends earlier waves into each poll.** Its weighted base is usually 1.3–1.6× its respondent count (2,773 v 2,023 on 6–9 Nov; 2.3× on 24–27 Jul), so consecutive Deltapoll polls aren't independent samples. The May–July Burnham-tagged polls are roughly 1:1. It also publishes only the headline table, with no question wording or option list. Two polls (May, June) carry a hypothetical 'with Andy Burnham as Labour leader' question, stored separately: Labour 28 and 26 v 20 on the standard question.
- **Survation publishes UK-wide figures.** The GB re-based shares are in `headlines_wide.csv` as `*_gb` columns. Taking Northern Ireland out mostly shrinks "Other" (3.2% to 0.5% in October) and lifts each GB party by roughly 0.5pt.

Data problems found and handled (all recorded in each poll's `notes`):
- More in Common re-uploads old polls, some under the same filename. The archive prefixes filenames with the upload month.
- Cover-sheet date errors, fixed in `registry/overrides.csv`:
  - More in Common, 20–23 Feb 2026, reads "20 - 13 February".
  - Freshwater, 4–6 Sep 2026, reads "4 - 6 August".
- Missing or wrong years: 7 polls corrected against the upload/publication date.
- Opinium "Updated" tables supersede the originals.
- File naming drifts at Survation, Opinium and Ipsos. Discovery looks broadly and the parser decides whether a file is a national VI poll.
- Ipsos is found partly through PDF links cited on Wikipedia, because ipsos.com search misses releases. The figures still come from Ipsos's own PDF.

Source files:
- outputs/polls.csv, headlines_wide.csv
- data/raw/manifest.csv (every file, URL, SHA-256)

## 0b) The average: why a Kalman filter, and how fast it sees a shift

### Headline
A forward-only Kalman filter with house effects tracks real shifts faster than a windowed average without being noisier. It's better by 0.1pt or more in prediction error during the 2017, 2019 and 2024 campaigns and the 2026 Burnham shift, and level in the flat 2015 campaign. A momentum check (each firm against its own previous poll, 7-day sign test) flagged Labour's 2017 surge on 3 May and the 2024 slide on 11 June, with no false alarms in 2015.

### Evidence table

| Dataset | v0.1 window MAE (focus) | v0.2 Kalman MAE (focus) | First momentum flag |
|---|---:|---:|---|
| GE2015 | 0.94 | 0.96 | none |
| GE2017 | 1.26 | 1.15 | Labour up, 3 May |
| GE2019 | 1.32 | 1.25 | Labour up, 12 Nov |
| GE2024 | 1.31 | 1.22 | Reform up 8 Jun; Labour down 11 Jun |
| 2026 Burnham | 0.99 | 0.97 | Labour up, 24 Jul |

v0.3 (14 Nov) adds three things: a smoothed history (the drawn line reverses direction 1–6 times per 100 days instead of 19–37), slow-by-default/fast-when-flagged speed (live line 15–20% steadier, accuracy unchanged), and hysteresis on the flag.

Latest average (13 Nov 2026): Lab 29.2, Con 21.6, Ref 21.6, LD 9.9, Grn 9.1 (±2.2).

Source files:
- outputs/replay_scores.csv, replay_v03_scores.csv, replay_momentum_flags.csv, average_daily.csv
- notes/average_method.md

## 1) BPC membership is nearly the right list, but not the right rule

### Headline
Ten of the twelve firms polling since August state BPC membership in their tables or on their poll pages, or are long-standing members still to be confirmed. Lord Ashcroft is the active exception. Membership doesn't screen out MRPs, party-commissioned polls or dormant firms, so the rule should be "publishes BPC-standard tables" plus three filters.

### Evidence table

| Firm | Polls 1 Aug–13 Nov | BPC statement | Proposed |
|---|---:|---|---|
| Find Out Now | 18 | yes | include (not MRPs / commissioned) |
| YouGov | 16 | to confirm | include |
| More in Common | 16 | yes | include |
| Opinium | 12 | yes | include |
| Survation | 9 | yes | include (GB re-based) |
| Deltapoll | 7 | to confirm | include, provisional |
| Trajectory | 4 | yes | include |
| Freshwater | 4 | yes | include |
| Lord Ashcroft | 4 | none | list only |
| BMG | 3 | yes | include |
| Ipsos | 3 | to confirm | include |
| JL Partners | 2 | yes | include when active |

Source files:
- registry/pollsters.csv
- data/raw/ (tables files)

## 2) Firms disagree on whether Restore Britain is even an option

### Headline
Four firms name Restore Britain on the first screen, two only on a second screen, and four don't name it at all. Where it's named up front, its share is mostly higher. This is tentative: one poll per firm, and Survation doesn't fit.

### Evidence table

| Firm | How RB is offered | RB share (latest tables) |
|---|---|---:|
| More in Common (6–9 Nov) | first screen | 6.2% |
| BMG (28–29 Oct) | first screen | 5.3% |
| Trajectory (3–12 Nov) | first screen (also Your Party) | 5% |
| Survation (2–5 Oct) | first screen | 2.0% |
| Opinium (4–6 Nov) | second screen after "another party" | ~3.5% |
| Ipsos (15–22 Oct) | second screen | 3% |
| Find Out Now (4 Nov) | not named (in Other) | Other 5.7% |
| Freshwater, JL Partners, Ashcroft | not named | n/a |

Source files:
- data/raw/moreincommon_2026-11-09_vi.xlsx (sheet 'votingintention (headline)')
- data/raw/bmg_2026-10-29_vi.xlsx (WouldVoteTodayRevised, final base: 50.5 of 946.5 weighted)
- data/raw/trajectory_2026-11-12_vi.pdf (Table 1, likely-to-vote column)
- data/raw/survation_2026-10-05_vi.xlsx (Table_V2: 33 of 1,691 weighted)
- data/raw/opinium_2026-11-06_vi.xlsx (V003B: RB = 64.1% of Other; HeadlineVI Other = 5.4%)
- data/raw/ipsos_2026-10-22_vi.pdf (V1AB/V2 combined, likely to vote)

## 3) Don't-know and turnout handling varies four ways

### Headline
Four firms simply drop don't-knows. Three squeeze then drop. More in Common assigns the rest by model, and BMG by 2024 vote. Turnout cut-offs run from "would vote: yes" to 9–10/10 plus usual voting. These are house effects the average has to absorb.

### Evidence table

| Firm | Don't-knows | Turnout |
|---|---|---|
| Opinium | dropped | not stated |
| Survation | dropped | weighted by likelihood/10 |
| Trajectory | dropped | 6+/10 |
| JL Partners | dropped | would vote (yes/no) |
| Find Out Now | squeeze, then dropped | definitely / very likely |
| Freshwater | squeeze, then dropped | 9–10/10 |
| Ipsos | squeeze, then dropped | 9–10/10 and usually votes |
| More in Common | squeeze, then model | 8+/10 (9+ for 2024 non-voters) |
| BMG | squeeze ×0.75, rest by 2024 vote ×0.5 | not stated; registration adjustment |

Source files:
- registry/pollsters.json (verbatim dk_text / turnout fields)

## TBC

- Deltapoll tables (wording, options, method).
- Scraper for JL Partners (dormant since Aug).
- Deltapoll question wording and prompt list (not published in its tables).
- Back-fill Opinium and Find Out Now before 2026.
- Whether the prompting pattern in section 2 holds over many polls once scraped. That needs the time series.
- Reuse permissions (YouGov licence, BMG terms) before publishing crosstabs.
