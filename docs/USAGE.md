# CCMD Media Intelligence Dashboard — User Guide

> **UNCLASSIFIED // PROTOTYPE.** Open-source aggregation. Automated
> assessments are decision-support signals, not analytic product. Not
> for operational use.

A walk-through for analysts using the deployed dashboard. Pairs with the
README (design / methodology / threat model) and HANDOUT.md (demo
talking points). Start here if you've been handed a URL and told to
try it.

---

## 1. What the tool is

The dashboard pulls open-source news from a curated feed list, assigns
every article to one or more combatant commands (geographic or
functional), and continuously produces an explainable "concern score"
per article — an auditable signal about structural misinformation risk.
A watch-floor lead should be able to glance at `/` and know, in one
sentence, what happened across 11 CCMDs in the last 24 hours.

Three modules, one app:

1. **Ingest** — RSS/Atom pull, dedupe, persist, audit trail.
2. **Classify** — AOR tagger (keyword + NER + source-based cascade) +
   two-stage MDM pipeline (LLM extraction → deterministic scorer).
3. **Web** — the UI you're looking at, plus a background scheduler that
   re-ingests, re-tags, and assesses new articles automatically.

End users are OSW staff and Marine Corps ICC personnel doing
information-operations and IW planning.

## 2. Getting in

1. Open the deployed URL (Fly demo: `https://adjahankhah.fly.dev/`).
   No login — a localhost-style analyst picker in the top right is the
   only identity boundary.
2. From the **analyst** dropdown, pick your handle. It stamps your
   notes and OIC flags with your name. Not an auth gate.
3. The red bar at the top is the classification banner. It renders on
   every page and every exported PDF. If it's ever missing, something's
   wrong — tell someone.

## 3. Home page — map + daily briefing

The landing page is built around three elements:

### 3a. Hero strip

A one-sentence roll-up: *"83 article(s) in the last 24 h across 11
commands. Most active: EUCOM (27)."* Plus a **"last refresh: N min
ago"** pill with a pulsing green dot — if the dot is present the
background scheduler is alive; if the number is stale (hours old)
the scheduler is stuck and you should check the logs.

### 3b. Satellite map with narrative overlay

Leaflet + Esri World Imagery tiles, with the six geographic CCMD AORs
drawn as semi-transparent rectangles. Each rectangle carries a
**permanent label** that says:

```
CENTCOM
12 article(s) in the last 24 h — themes: Red Sea, Hormuz, Houthi;
mean MDM 37.5 (requires verification).
"Houthi ballistic missile targets bulk carrier in Red Sea"
```

**No click required to understand the board.** The label is the brief.

Interactions:

| Action | Result |
|---|---|
| Scroll / pinch | Zoom (2-8). |
| Drag | Pan. |
| Click a rectangle | Popup with top 3 headlines (each with its own MDM badge), theme tags, and a link to the CCMD tab. |
| Click the popup link | Opens the CCMD's article list. |

**Rectangle color** = dominant MDM concern across assessed articles
(not raw volume):

| Color | Meaning |
|---|---|
| green | dominant category is `likely_reliable` |
| amber | `requires_verification` |
| orange | `significant_concerns` |
| red | `high_concern` |
| cyan | no MDM assessments yet |

### 3c. Daily briefing grid

One tile per CCMD (all 11) directly below the map. Each tile shows the
24-hour narrative, an MDM category stripe (left border), window /
total counts, and click-through. Use this as a scrollable replacement
for a morning-stand-up deck.

### 3d. Per-CCMD snapshot table

Bottom of the page. Columns: `Articles (24 h / all)` · `Reviewed` ·
`Flagged` · `MDM assessed` · `Mean score` · `Dominant`. Click a CCMD
code to drill in.

> **Network caveat.** The satellite tiles come from Esri's public
> ArcGIS Online endpoint — the Fly demo relies on outbound HTTPS for
> them. An air-gap / .mil port needs a local tile cache or a
> schematic-only fallback.

## 4. CCMD tabs — working the articles

Click any CCMD code in the top nav (or from the map popup) to open
that command's article list.

**Filters** (the row at the top):

| Filter | What it does |
|---|---|
| **from / to** | Publication-date window (inclusive). |
| **tier** | 1 = USG, 2 = trade press, 3 = wire / regional. |
| **state** | Only / exclude state-affiliated feeds (TASS, Xinhua, PressTV, KCNA…). |
| **MDM** | Filter by MDM category band. |
| **search** | Case-insensitive keyword match on title + body. |

Filters combine with AND. Clear with **reset**.

**Article cards** each show:
- Title (links to article detail) + source name + publication date.
- Badges: source tier, state-affiliation (red), matched AOR tags with
  the match score, MDM category (always present once the scheduler has
  run), `N note(s)` if analyst notes exist.
- Matched AOR keywords (why this article landed in this AOR).
- First ~2 sentences of the extracted body.

Paginate at 25 per page.

## 5. Article detail — the analyst's workbench

Click any article title to open the detail page.

**Top banner**: tier + state + AOR badges + MDM badge.

**Summary** and **Extracted body** — what the ingest pipeline pulled
from the source. Always click the **source link ↗** to verify in the
original publication before escalating.

### 5a. MDM assessment runs automatically

**You do not click to assess.** The background scheduler assesses every
new article on its next tick (default: every 60 min, up to 20 articles
per tick). Every article card should show an MDM badge; every article
detail page should show the reasoning breakdown table already filled
in.

The breakdown table — always present when `latest_mdm.concern_score`
is set — lists every sub-signal: name, value, weight, contribution,
one-sentence explanation. Nothing is hidden. If you want to know why
a score is what it is, read this table top to bottom.

The two stages, for reference:

1. **Stage 1 — LLM extraction.** The classifier (stub or Anthropic,
   per deployment) reads the article and returns structured features:
   verifiable claims, emotional language, logical fallacies, unsourced
   assertions, temporal claims, source-transparency score, anomalies.
   The prompt is hard-constrained to feature extraction — it does not
   assert truth / falsity.
2. **Stage 2 — Deterministic scorer.** A weighted sum over 8 named
   sub-signals produces a concern score in `[0, 100]` and a category
   band. Weights are code constants in `classify/scoring.py`, not
   learned.

**Re-assess (MDM)** button: only useful after you've edited the scorer
weights (or toggled the classifier between stub and Anthropic) and
want the row recomputed against the new version. The button creates a
new MDMAssessment row — audit trail preserved — and the UI shows the
latest. A diagnostic banner appears inside the card if the re-run
fails.

**Category bands:**

| Range | Category | Meaning |
|---|---|---|
| 0–25 | `likely_reliable` | Few or no structural concerns. Still verify. |
| 26–50 | `requires_verification` | Normal reporting with signals worth checking. |
| 51–75 | `significant_concerns` | Multiple signals; treat with caution. |
| 76–100 | `high_concern` | State-affiliated, low transparency, unsourced claims, etc. |
| — | `insufficient_data` | Extraction / scoring failed; see the diagnostic. |

**Do not treat a low score as "verified true" or a high score as
"disinformation confirmed."** The score describes structural features,
not truth value.

### 5b. Notes + OIC flagging

Below the MDM card:

- **Add note** form (ATP-2 shape): observation, significance,
  recommended action, action_taken.
- **action_taken** controls routing:
  - `reviewed` — shows up on the Notes tab as "you looked at it".
  - `flagged_for_oic` — populates the OIC Queue tab for watch-officer
    review.
  - `escalated` / `dismissed` — dispositioned.

Notes are immutable once saved. Add a follow-up note if you change
your mind — the audit trail matters more than the neatness.

## 6. How articles get assigned to CCMDs

Every article gets at least one CCMD tag via this cascade (all tags
look the same in the UI — the distinction is internal):

1. **Keyword + NER match** above `aor_min_match_score`. Matches from
   `config/ccmd_aor.yaml` (countries, regional keywords, functional
   domains, adversary designators). Multi-CCMD articles get multiple
   rows.
2. **Top below-threshold match** if the primary pass returned nothing
   but there was *some* evidence on at least one CCMD.
3. **Source-based** fallback from the feed's `state_affiliation`:
   RU/BY/UA → EUCOM, CN/KP → INDOPACOM, IR/SY → CENTCOM, VE/CU →
   SOUTHCOM.
4. **Catch-all**: NORTHCOM (homeland-defense AOR as least-wrong
   default).

Because every article reaches at least step 4, the **Unassigned** tab
is normally empty. An article only shows up there transiently — after
ingest, before the next scheduler tick runs the tagger. If something
is stuck there across multiple ticks, check `fly logs -a <app>` for
tagger errors.

## 7. Other tabs

- **Unassigned** — transient diagnostic; see §6.
- **MDM Queue** — every assessed article, sortable by score.
- **Analyst Notes** — every note, newest first.
- **OIC Queue** — notes with `action_taken = flagged_for_oic`. What a
  watch officer checks at shift start.
- **About** — feeds list (tier + state), full CCMD table, methodology
  + threat-model links, current build + classifier mode.

## 8. Export — daily brief

From the OIC Queue tab (or the `/export/brief.pdf` endpoint):

- Grouped by CCMD.
- Classification banner on every page.
- Embedded analyst notes.
- CSV alongside for pivot-table work (`/export/brief.csv`).

Export reflects the current DB at the moment of generation — not a
scheduled snapshot. For tomorrow's brief, hit export tomorrow.

## 9. How data refreshes

The deployed app runs a single background scheduler thread that, every
`CCMD_INGEST_INTERVAL_MINUTES` (default 60):

1. Pulls every active feed, dedupes, persists (IngestRun row per feed).
2. Runs the AOR tagger over anything newly ingested → universal
   assignment per §6.
3. Batch-assesses up to `CCMD_MDM_BATCH_PER_TICK` (default 20)
   unassessed articles. Large backlogs drain over successive ticks.

The **"last refresh"** chip on the home page reflects the most recent
successful ingest. Expect to see it increment every ~60 min while the
app is warm.

For local development:

```sh
uv run dashboard ingest        # pull all feeds
uv run dashboard tag           # run AOR tagger
uv run dashboard demo          # offline canned dataset
```

## 10. When something looks wrong

- **"Assessment did not complete cleanly"** on a card — the diagnostic
  mono text shows which stage failed. Stage 1 failures are usually an
  API-key / schema issue; stage 2 failures are usually a corrupt JSON
  extraction. Check `fly logs`.
- **MDM badge missing on an article card** — the article is newer than
  the last scheduler tick. Wait 60 min or hit Re-assess.
- **Same article appears twice** — shouldn't happen; dedupe is on URL
  + content hash. If it does, file it.
- **"last refresh" chip is stale (hours old)** — the scheduler thread
  is stuck or the machine scaled to zero. Confirm `min_machines_running
  = 1` in `fly.toml` and check `fly status`.
- **Map tiles don't load** — the Esri tile endpoint is blocked or the
  page is offline. The inline JSON fallback still shows a diagnostic
  and the daily briefing grid keeps working.
- **PDF brief won't render** — WeasyPrint needs native libs (Pango,
  Cairo, gdk-pixbuf). The deployed image has them; local macOS: `brew
  install pango cairo gdk-pixbuf` then restart.

## 11. Operator controls (env vars)

For the person running the Fly deployment — edit `fly.toml` `[env]`
then `fly deploy`, or `fly secrets set` for anything sensitive:

| Var | Default | What it does |
|---|---|---|
| `CCMD_CLASSIFIER` | `stub` | `stub` (offline, regex-based) or `anthropic` (Claude Opus 4.7). |
| `CCMD_ANTHROPIC_API_KEY` | — | Required if `CCMD_CLASSIFIER=anthropic`. Set via `fly secrets`. |
| `CCMD_ANTHROPIC_MODEL` | `claude-opus-4-7` | Override model. |
| `CCMD_DEMO` | `1` | On first boot, seed 50 canned articles. Flip to `0` once real data has flowed. |
| `CCMD_INGEST_ENABLED` | `1` | Master switch for the background scheduler. |
| `CCMD_INGEST_INTERVAL_MINUTES` | `60` | Scheduler cadence. |
| `CCMD_MDM_AUTO_ENABLED` | `1` | Whether the scheduler also runs MDM after tagging. |
| `CCMD_MDM_BATCH_PER_TICK` | `20` | Cap on MDM assessments per tick. Lower if the VM OOMs. |
| `CCMD_AOR_MIN_MATCH_SCORE` | `0.02` | Threshold for the primary tagger pass. |

## 12. What the tool is NOT

Read the README sections **Known limitations** and **Threat model** in
full before making any call based on the dashboard. Short version:

- Not a truth oracle.
- Not calibrated — MDM weights are reasonable priors, not ground-truth-
  validated constants.
- Not on a .mil network — this prototype is unclassified-only. The
  schema is ready for a classified port (handling-marking fields,
  STANAG 2022 admiralty code); the UI does not expose them.
- Not real-time — refresh is on an interval, not push.
- Not multi-analyst-safe — the localhost analyst picker is not auth.
  Anyone with the URL sees everything.

## 13. Further reading

- `README.md` — architecture, data model, AOR tagger methodology, MDM
  scoring weights, threat model, port path.
- `docs/HANDOUT.md` — one-page demo walk-through for leadership.
- `config/ccmd_aor.yaml` — AOR keyword lists. Edit to tune recall.
- `config/feeds.yaml` — feed list. Edit to add or disable sources.
- `src/ccmd_dashboard/classify/scoring.py` — the MDM weights, in named
  constants at the top. Edit carefully; the home-page MDM aggregates
  recompute from whatever weights the server is running.

For issues, use the repo issue tracker or walk the step-granular commit
history for design rationale.
