# Poll tracker data model (draft v0.1, 13 Nov 2026)

The rule: **keep everything the pollster published, word for word, before tidying it.** Tidy versions (standard party codes, standard age bands) sit on top as a separate layer. They never replace the original text.

Why: firms ask the question differently. Some name Restore Britain, some don't. Some squeeze don't-knows, some drop them. Some filter on 8/10 likelihood, some on 9/10. If we only keep "Reform 21%", we can never explain or correct for those differences later.

## Three layers

| Layer | What it holds | Where | Public? |
|---|---|---|---|
| 1. Raw | The original file exactly as downloaded (xlsx/pdf/html), plus its SHA-256 hash, source URL and download time | `data/raw/` (gitignored); later a private bucket | No. These are the pollsters' files. Several firms' terms limit redistribution (see `../notes/pollster_audit.md`) |
| 2. Extracted | Every relevant table transcribed verbatim: question text, base text, answer labels in table order, every crossbreak column, weighted and unweighted bases | `extracted/` (one folder per poll) | Headline numbers and question wording yes; full crosstabs to be decided |
| 3. Normalised | Standard party codes, standard poll fields, harmonised crossbreaks, GB re-basing | `normalised/` tables below | Yes. This feeds the average and the widget |

## Layer 2/3 tables

### `polls`: one row per published poll

| Field | Type | Example | Notes |
|---|---|---|---|
| `poll_id` | str | `moreincommon-2026-11-09` | `<pollster_id>-<fieldwork_end>`; add `-b` etc. if two polls end the same day |
| `pollster_id` | str | `moreincommon` | key into `registry/pollsters.json` |
| `client` | str/null | `Daily Telegraph` | as stated in the tables or release |
| `commissioner_type` | enum | `self`, `media`, `party`, `campaign`, `other` | `party`/`campaign` polls are kept but excluded from the average |
| `poll_type` | enum | `standard_vi`, `mrp`, `constituency`, `regional`, `propensity` | Only `standard_vi` goes in the average by default |
| `series` | str | `findoutnow_rb_prompted` | Usually the pollster id. A separate series when a firm runs a variant alongside its main poll |
| `fieldwork_start`, `fieldwork_end` | date | | |
| `fieldwork_text` | str | `6 - 9 November 2026` | verbatim, as printed |
| `published_date` | date | | When the tables appeared, not when we scraped them |
| `geography_sampled` | enum | `GB`, `UK` | Who was interviewed |
| `geography_vi_base` | enum | `GB`, `UK` | Who the headline VI covers (Opinium samples UK but its VI base has 0 NI respondents) |
| `mode` | enum | `online_panel`, `online_probability_panel`, `phone`, `mixed` | |
| `panel_provider` | str/null | `Potentia`, `KnowledgePanel`, `Pick My Postcode` | |
| `sample_size_total` | int | 2013 | all respondents |
| `sample_size_vi_unweighted` | int | 1437 | base of the headline VI table |
| `sample_size_vi_weighted` | float | | |
| `pooled_waves` | bool | | true if the firm blends earlier waves into this poll (Deltapoll's stated method). Such polls are not independent of each other |
| `weighting_variables` | list[str] | `["age×sex","region","GE2024 vote","ethnicity","education"]` | verbatim list in `weighting_text` |
| `weighting_text` | text | | verbatim from tables |
| `turnout_method` | enum | `ltv_threshold`, `ltv_weight`, `binary_would_vote`, `categorical_likely`, `model` | |
| `turnout_threshold` | str/null | `8/10 (9/10 if did not vote 2024)` | |
| `turnout_text` | text | | verbatim |
| `squeeze_asked` | bool | | |
| `dk_treatment` | enum | `excluded`, `squeezed_then_excluded`, `squeezed_then_model`, `squeezed_then_past_vote` | |
| `dk_text` | text | | verbatim |
| `headline_table_ref` | str | `votingintention (headline)` / `HeadlineVI` / `Table_V2` | which table the firm's own headline comes from |
| `headline_definition_text` | text | | verbatim base description of the headline table |
| `methodology_text` | text | | whole cover/methodology sheet, verbatim |
| `bpc_statement` | text/null | | verbatim BPC sentence, if any |
| `source_page_url` | url | | release/article page |
| `tables_url` | url | | direct link to file |
| `raw_file` | path | | layer-1 file |
| `raw_sha256` | str | | |
| `scraped_at` | datetime | | |
| `scraper` | str | `moreincommon@0.1` | parser name and version |
| `headline_method` | str | `mrp_modelled`, `squeeze_plus_model`, `exclude_dk` | how the firm turns answers into its headline |
| `extraction_status` | enum | `auto`, `auto_checked`, `manual`, `headline_only` | `headline_only` = we have the release numbers but couldn't parse tables |
| `notes` | text | | anything odd |

### `questions`: one row per question used to build the headline

| Field | Example |
|---|---|
| `poll_id` | |
| `question_ref` | firm's own code: `V003`, `V003B`, `Table_V2_1`, `WouldVoteTodayUnsure`, `V1AB` |
| `stage` | `turnout`, `vi_first`, `vi_second_screen` (asked only of "another party"), `vi_squeeze`, `vi_headline_derived` |
| `wording` | verbatim, e.g. "And, if a general election was called tomorrow, which party would you vote for?" |
| `base_text` | verbatim, e.g. "Base: All who might vote and giving consent" |
| `asked_of` | plain-English filter |
| `order_in_questionnaire` | int, where known (BPC rules require tables in order asked) |
| `options_randomised` | bool/null, from methodology text |

### `options`: one row per answer option offered

| Field | Example |
|---|---|
| `poll_id`, `question_ref` | |
| `position` | order **in the tables**. Most firms say respondents saw parties in random order, so this is not screen order |
| `label` | verbatim: "The Green Party", "Scottish National Party (SNP)", "Another party/Independent candidate" |
| `party_code` | normalised (list below) |
| `region_restricted` | `Scotland`, `Wales`, `NI` or null (e.g. SNP shown only in Scotland) |

The `options` table is how we know which parties a poll **named**. That's the single biggest comparability problem right now: Restore Britain is named on the first screen by some firms, on a second screen by others, and not at all by the rest.

### `results`: long format, one row per cell

| Field | Example |
|---|---|
| `poll_id`, `question_ref` | |
| `table_base` | which version of the question: `raw`, `squeezed`, `turnout_filtered`, `headline` |
| `break_var` | verbatim crossbreak heading: `Total`, `Age`, `GE24 Vote`, `Region` |
| `break_label` | verbatim column label: `18-24`, `RFM`, `Northern Ireland` |
| `break_std` | normalised (e.g. `age:18-24`, `ge2024:REF`, `nation:NI`) |
| `option_label` | verbatim row label |
| `party_code` | normalised |
| `pct` | as published (0–100, unrounded where the file has it) |
| `n_weighted`, `n_unweighted` | cell or column base where published |

### `headlines`: one row per poll × party

What the firm says its headline is, plus our checks.

| Field | Notes |
|---|---|
| `poll_id`, `party_code` | |
| `pct_published` | as in the release/tables, usually rounded |
| `pct_from_tables` | recomputed from layer 2 |
| `pct_gb` | re-based to GB if the firm's base is UK (Survation: Total minus Northern Ireland column, using weighted counts) |
| `check_ok` | published and recomputed figures within 0.5pt |

## Party codes

| Code | Party |
|---|---|
| `CON` | Conservative |
| `LAB` | Labour |
| `LD` | Liberal Democrats |
| `REF` | Reform UK |
| `GRN` | Green |
| `SNP` | SNP |
| `PC` | Plaid Cymru |
| `RB` | Restore Britain |
| `YP` | Your Party |
| `OTH` | Any other party / independent (keep the verbatim label) |
| `DK` | Don't know / undecided / not sure |
| `WNV` | Would not vote |
| `REFUSED` | Refused / prefer not to say |

When a firm lumps parties together (e.g. JL Partners' "Others"), the code is `OTH` and the label is kept. We never split a lump.

## Crossbreaks to standardise (first pass)

Only the ones nearly every firm publishes:
- **Sex**
- **2024 vote**
- **Region or nation**
- **Age.** Firms cut age differently (18-24/25-34…, 18-29/30-39…, 18-34/35-49…, 65+ v 65-74/75+). Store the verbatim bands. Only harmonise into overlapping groups (e.g. under-35, 65+) where the bands allow it, and flag anything approximate.

Everything else (social grade, education, EU ref, income, tenure, ethnicity) stays verbatim in layer 2 only.
