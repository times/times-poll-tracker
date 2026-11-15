# Pollster audit, 13 Nov 2026

Which firms to include, and what each one actually asks. This compares the firms side by side. Per-firm detail (verbatim wording, option lists, URLs) is in `../registry/pollsters.json`.

## How this was done

- Started from Wikipedia's GB table for 1 Aug–13 Nov 2026: 98 polls from 12 firms.
- For each firm, found the latest data tables file on its own site and read it with openpyxl / pypdf. Copies are in `data/raw/` (gitignored), with SHA-256 hashes in `SHA256SUMS`.
- Tables read: More in Common, Find Out Now, Opinium, Survation, BMG, Freshwater, JL Partners, Lord Ashcroft, Trajectory, Ipsos.
- **Not read:**
  - YouGov: tables not located, and its licence bars scraping.
  - Deltapoll: the polls library page returns HTTP 500.
- The BPC's own site returned HTTP 425 to automated requests, so membership comes from each firm's own tables statement.

## Polls since 1 August

| Firm | Polls | Cadence | Client |
|---|---:|---|---|
| Find Out Now | 18 (3 MRP) | weekly | self |
| YouGov | 16 (1 MRP) | weekly | The Times / Sky |
| More in Common | 16 (1 MRP) | weekly | self / Telegraph |
| Opinium | 12 | weekly | Observer |
| Survation | 9 (1 MRP) | ~fortnightly | self |
| Deltapoll | 7 | ~fortnightly | self |
| Trajectory | 4 | monthly | self |
| Freshwater Strategy | 4 | monthly | City AM |
| Lord Ashcroft | 4 | ~monthly | self |
| BMG | 3 | monthly | The i |
| Ipsos | 3 | monthly | self |
| JL Partners | 2 | none since Aug | varies |

The top three firms produce half the polls. A simple poll-weighted average is mostly a Find Out Now / YouGov / More in Common average.

## Proposed inclusion

Rules:
- **R1:** full tables published.
- **R2:** standard GB VI question.
- **R3:** not commissioned by a party or campaign.
- **R4:** 3+ standard VI polls in the last 90 days.

| Firm | BPC (own statement) | Status | Why |
|---|---|---|---|
| More in Common | yes | include | |
| Find Out Now | yes | include | standard weekly VI only; its MRPs and the Restore Britain-commissioned MRP are out (R2, R3) |
| Opinium | yes | include | |
| Survation | yes | include | re-based to GB |
| YouGov | (confirm) | include | data via the Times' commissioning relationship, not scraping |
| Deltapoll | (confirm) | include, provisional | tables not found yet; pools earlier waves |
| Trajectory | yes | include | monthly |
| Freshwater | yes | include | monthly |
| BMG | yes | include | monthly |
| Ipsos | (confirm) | include | monthly; the only probability panel |
| JL Partners | yes | include when active | fails R4 at the moment |
| Lord Ashcroft | **no statement** | list only | fails R2: VI derived from 0–100 propensity scores |

**On the BPC question:**
- Using membership as the rule would give almost the same list. Ashcroft is the only active firm it would drop, and R2 drops it anyway.
- The difference shows up at the edges:
  - membership doesn't exclude party-commissioned polls or MRPs;
  - it doesn't handle a member that has stopped polling (JL Partners, Focaldata, Verian).
- Recommendation: say "BPC members, or firms that publish tables to the same standard", then apply R2–R4.

## The comparability problem: firms aren't asking the same question

### 1. Who's named in the list (the big one right now)

| Restore Britain is... | Firms | RB share in latest tables |
|---|---|---|
| named on the first screen | More in Common, BMG, Survation, Trajectory (also names Your Party) | MiC 6.2%, BMG 5.3%, Trajectory 5%, Survation 2.0% (Oct) |
| only on a second screen after "another party" | Opinium, Ipsos, YouGov | Opinium ~3.5% (64% of a 5.4% Other), Ipsos 3%, YouGov 3% |
| not named at all | Find Out Now, Freshwater, JL Partners, Lord Ashcroft | hidden in "Other" (FON Other = 5.7%) |
| not yet known | Deltapoll | |

Firms that name Restore Britain up front mostly find more of it, though Survation is the exception. That fits the long-standing pattern that prompting matters for new parties (as with Reform/Brexit Party in 2019 and the SDP in the 1980s). But it's four or five polls, so treat it as a lead, not a finding.

**Implication:** the average needs an RB series that only uses firms that name it, and an "Other" that's comparable across firms. Never just "RB where reported".

Per release (not checked against the questionnaire), Ipsos's first screen also leaves out the Greens: they appear only after "another party". If true, it's a Green equivalent of the RB problem.

### 2. What happens to don't-knows

| Treatment | Firms |
|---|---|
| Dropped, no squeeze | Opinium, Survation, Trajectory, JL Partners |
| Squeezed ("if forced to choose"), rest dropped | Find Out Now, Freshwater, Ipsos |
| Squeezed, rest assigned by statistical model | More in Common |
| Squeezed (×0.75), rest assigned by 2024 vote (×0.5) | BMG |

Model or past-vote reallocation pulls 2024 Labour voters who now say "don't know" back towards Labour. That's one reason More in Common and BMG can sit higher for Labour.

### 3. Turnout

| Rule | Firms |
|---|---|
| 8+/10 (9+ for 2024 non-voters) | More in Common |
| 9–10/10 | Freshwater |
| 9–10/10 AND usually votes | Ipsos |
| 6+/10 | Trajectory |
| Weight by likelihood/10 | Survation |
| "Definitely" or "very likely" (2024 non-voters: "definitely") | Find Out Now |
| Says they would vote (yes/no) | JL Partners |
| Not stated in tables | Opinium, BMG (BMG adds an electoral-registration adjustment) |

### 4. Geography

- Survation is UK-wide, including Northern Ireland. Its nation crossbreaks let us recompute GB.
- Opinium and Freshwater sample the UK but their VI is GB only (Opinium's NI VI base is 0; Freshwater filters "GB Only").
- Everyone else samples GB.

### 5. Sample independence

- Deltapoll (since May 2026) blends earlier waves into each poll with declining weights, so consecutive Deltapoll polls share respondents.
- Trajectory's fieldwork runs over about 10 days.
- Find Out Now's runs over a single day.

## Getting the data

| Firm | Format | Where | Difficulty |
|---|---|---|---|
| More in Common | xlsx, sheet per question | one archive page | easy |
| Find Out Now | xlsx, 5 tidy sheets | blog posts | easy |
| Opinium | xlsx, ~70 sheets by question code | paginated archive | easy |
| JL Partners | xlsx | one archive page | easy |
| Lord Ashcroft | xlsx | /latest/ | easy |
| Survation | xlsx, tables stacked in one sheet | yearly archive pages, mixed with constituency polls | medium |
| BMG | xlsx (WinCross, significance rows interleaved) | /news/ | medium |
| Freshwater | xlsx, stacked | insights page mixed with NZ/AU polls | medium |
| Trajectory | pdf (2 pages, clean text) | predictable URL | medium |
| Ipsos | pdf (63 pages; columns merge on extraction) | search / RSS | hard |
| YouGov | pdf per poll + tracker xlsx | content API | medium. Scraped under the Times' agreement (user, 13 Nov 2026) |
| Deltapoll | ? | polls page errors | unknown |

Every firm should also get a hand-entry fallback, the same schema typed in from the release, so a broken scraper never means a missing poll. Wikipedia can serve as an automated "did we miss one?" check, but never as the source.

## Reuse terms (needs a word with legal)

- **YouGov:** CC BY-NC 4.0. Commercial use needs written consent, and automated extraction is explicitly banned without permission. The Times commissions YouGov, so this should be solvable directly.
- **BMG:** site terms forbid commercial use of site content without a licence.
- **Ipsos:** "deemed to be in the public domain" with attribution, but a separate clause bars reproduction without permission.
- **Others:** copyright notices only, or not checked.

Proposed line: the public GitHub repo holds our extracted headline numbers, the question wording and options, and links to the source. Raw files and full crosstabs stay private until we've asked. Headline VI figures are facts every outlet republishes. Wholesale redistribution of crosstab workbooks is different.

## Open questions

1. YouGov: get a sample Times VI tables file and agree a feed.
2. Deltapoll: find the tables; confirm BPC membership.
3. Opinium: turnout rule and whether there's a squeeze (not in tables).
4. Ipsos: confirm from the questionnaire whether the Greens are first- or second-screen.
5. Survation: confirm Restore Britain is first-screen (tables say yes, methodology text says no). Find tables for the 11–12 Nov poll.
6. BPC: get the member list from the BPC directly (the site blocks scripts; try the browser pane or email).

## Update, 13 Nov 2026 (scrapers built)

- **YouGov:** the headline comes from an MRP model run on the constituency question.
  - Turnout is modelled from demographics, not from stated likelihood to vote.
  - Don't-knows are reallocated by the model.
  - Restore Britain and Your Party only appear on the "other party" follow-up.
  - Source: YouGov method note, 10 Mar 2026.
- **Find Out Now** runs an occasional self-funded variant that names Restore Britain and Your Party, with the same method. Four in 2026 so far, stored as a separate series. For example, 15–16 Apr with RB named: Ref 21, RB 9. The weekly poll on 15 Apr without RB named: Ref 26.

## Update, 14 Nov 2026 (Deltapoll)

- Deltapoll's tables are at deltapoll.co.uk/polls-library. The earlier audit only tried /polls, which errors.
- 12 polls since its May 2026 relaunch, all matching Wikipedia.
- Its tables give only the headline, excluding don't-knows and won't-votes, in whole numbers. There's no raw question, option list or squeeze.
- Restore Britain is never shown separately.
- The weighted base usually runs 1.3–1.6× the respondent count, peaking at 2.3× on 24–27 Jul. That's consistent with its stated pooling of earlier waves.
- The May–July Burnham-tagged polls are roughly 1:1, so pooling may not apply to every release.
