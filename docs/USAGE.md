# CCMD Media Intelligence Dashboard — User Guide

> **UNCLASSIFIED // PROTOTYPE.** Open-source aggregation. Automated
> assessments are decision-support signals, not analytic product. Not
> for operational use.

A walk-through for analysts using the deployed dashboard. Pairs with the
README (design/methodology) and HANDOUT.md (demo talking points). Start
here if you've been handed a URL and a login and told to try it.

---

## 1. What the tool is

The dashboard pulls open-source news from a curated feed list, tags each
article to one or more combatant commands (geographic or functional),
and — on analyst demand — produces an explainable "concern score" that
quantifies misinformation-related structural risks in the article.

Three modules, one app:

1. **Ingest** — RSS/Atom pull, dedupe, persist, audit trail.
2. **Classify** — spaCy-based AOR tagger + two-stage MDM pipeline
   (LLM extraction → deterministic scorer).
3. **Web** — the UI you're looking at.

End users are OSW staff and Marine Corps ICC personnel doing information-
operations and IW planning.

## 2. Getting in

1. Open the deployed URL (for the prototype Fly deployment, this is
   `https://adjahankhah.fly.dev/`). No login required — a localhost-style
   analyst picker in the top right is the only identity boundary.
2. From the **analyst** dropdown (top right of the nav), pick your
   handle. This is just a convenience label; it stamps your notes and
   OIC flags with your name. Not an auth gate.
3. The red bar at the top is the classification banner. It renders on
   every page and every exported PDF. If it's ever missing, something's
   wrong — tell someone.

## 3. Home page — the map + daily briefing

The landing page has three sections:

1. **Hero narrative** — "N article(s) in the last 24 h across 11
   commands. Most active: EUCOM (27)." Tells a watch-floor lead what
   happened since they last logged in, in one sentence.
2. **Satellite map** with permanent narrative labels on each AOR.
3. **Daily briefing grid** with a tile per CCMD: window counts, themes,
   mean MDM concern, click-through to the CCMD tab.

The Leaflet satellite map (Esri World Imagery) draws the six geographic
CCMD AORs as semi-transparent rectangles. Each rectangle carries a
**permanent label** with the CCMD code, the 24-hour narrative
("12 article(s) in the last 24 h — themes: Red Sea, Hormuz; mean MDM
37.5 (requires verification)"), and the top headline. **Color encodes
dominant MDM concern** across the AOR's assessed articles, not raw
volume:

| Color | Meaning |
|---|---|
| green | dominant category is `likely_reliable` |
| amber | `requires_verification` |
| orange | `significant_concerns` |
| red | `high_concern` |
| cyan | no MDM assessments yet |

- **Pan / zoom** the map with the mouse wheel, trackpad, or the
  `+ / -` controls top-left.
- **Click any rectangle** → popup with article count, mean concern
  score, category breakdown, best-guess count, and a link to the CCMD
  tab.
- **Hover** shows a quick tooltip with the CCMD code and article count.
- **Functional commands** (SPACECOM, STRATCOM, CYBERCOM, SOCOM,
  TRANSCOM) sit as chips in the legend row beneath the map; the left
  stripe encodes their own dominant MDM category.
- **"last refresh: X min ago"** pill top-right of the hero tracks the
  most recent completed feed ingestion. Pulsing green dot = the
  background scheduler is alive.
- **Per-CCMD snapshot table** below the map has articles / best-guess
  / reviewed / flagged / MDM-assessed / mean-score / dominant-category
  columns for every CCMD.
- **Unassigned diagnostic bar** appears at the bottom when articles
  couldn't be routed at all — see §6 for the best-guess semantics.

> **Network caveat.** The satellite tiles are served by Esri's public
> ArcGIS Online endpoint. The Fly demo relies on outbound HTTPS for
> this; an air-gap / .mil port would need a local tile cache or must
> fall back to the pre-computed schematic view.

## 4. CCMD tabs — working the articles

Click any CCMD code in the top nav (or on the map) to open that
command's article list.

**Filters** (the row at the top):

| Filter | What it does |
|---|---|
| **from / to** | Publication-date window (inclusive). |
| **tier** | 1 = USG, 2 = trade press, 3 = wire / regional. |
| **state** | Filter for state-affiliated feeds only (TASS, Xinhua, PressTV, KCNA…) or exclude them. |
| **MDM** | By category band — likely_reliable / requires_verification / significant_concerns / high_concern / insufficient_data. Only populated if you've clicked Assess. |
| **search** | Case-insensitive keyword match on title + body. |

Filters combine with AND. Clear with **reset**.

**Article cards** each show:
- Title (links to article detail) and source
- Publication date
- Badges: source tier, state-affiliation (red), matched AOR tags with
  the match score, MDM category (if assessed), `N note(s)` if analyst
  notes exist.
- Matched AOR keywords (why this article landed in this AOR).
- First ~2 sentences of the extracted body.

Paginate at 25 per page.

## 5. Article detail — the analyst's workbench

Click any article title to open the detail page.

**Top banner**: tier + state + AOR badges + MDM badge (if assessed).

**Summary** and **Extracted body** — what the ingest pipeline pulled
from the source. Click the **source link ↗** to verify in the original
publication. Always verify before escalating.

### 5a. MDM assessment (runs automatically)

**MDM assessment is automatic.** Every new article picked up by the
background ingest scheduler is assessed on the next tick — you don't
click anything. The **Re-assess (MDM)** button on the detail page is
only useful if you've edited the scorer weights and want the row
recomputed against the current version.

When it runs, it's two stages:

1. **Stage 1 — LLM extraction.** The classifier (stub or Anthropic,
   depending on deployment) reads the article and pulls out structured
   features: verifiable claims, emotional language, logical fallacies,
   unsourced assertions, temporal claims, source-transparency score,
   anomalies. The prompt is hard-constrained to feature extraction — it
   does not assert truth/falsity.

2. **Stage 2 — Deterministic scorer.** A weighted sum over 8 named
   sub-signals produces a concern score in `[0, 100]` and a category
   band. The weights are code constants, not learned — if you want to
   know why a score is what it is, the `Reasoning breakdown` table on
   the detail page shows every sub-signal's name, value, weight,
   contribution, and a one-sentence explanation. Nothing is hidden.

Re-assessment creates a new MDMAssessment row (audit trail preserved)
and the UI shows the latest. A small diagnostic appears inside the card
if extraction or scoring failed.

Category bands:

| Range | Category | Meaning |
|---|---|---|
| 0–25 | `likely_reliable` | Few or no structural concerns. Still verify. |
| 26–50 | `requires_verification` | Normal reporting but with signals worth checking. |
| 51–75 | `significant_concerns` | Multiple signals; treat with caution. |
| 76–100 | `high_concern` | State-affiliated, low transparency, unsourced claims, etc. |
| — | `insufficient_data` | Extraction or scoring failed; see failure reason in the card. |

**Do not treat a low score as "verified true" or a high score as
"disinformation confirmed."** The score describes structural features,
not truth value.

### 5b. Notes + OIC flagging

Below the MDM card:

- **Add note** form (ATP-2 shape): observation, significance, recommended
  action, action_taken.
- **action_taken** controls routing:
  - `reviewed` — shows up on the Notes tab as "you looked at it".
  - `flagged_for_oic` — populates the OIC Queue tab for watch-officer
    review.
  - `escalated` / `dismissed` — dispositioned.

All notes are immutable once saved. Add a follow-up note if you change
your mind — the audit trail matters more than the neatness.

## 6. Other tabs

- **Unassigned** — every article is assigned to a CCMD by the tagger's
  cascade (keyword match → top below-threshold match → state-affiliation
  mapping → NORTHCOM as catch-all), so this tab is usually empty. It
  only surfaces articles mid-pipeline (ingested but not yet tagged).
  If something is stuck here across multiple scheduler ticks, check
  `fly logs -a <app>` for tagger errors.
- **MDM Queue** — every article that's been assessed. Sortable by score.
- **Analyst Notes** — every note across every article, newest first.
- **OIC Queue** — just the notes with `action_taken = flagged_for_oic`.
  What a watch officer checks at shift start.
- **About** — feeds list (tier + state), full CCMD table, methodology
  + threat-model links, current build + classifier mode.

## 7. Export — daily brief

From the OIC Queue tab (or the export endpoint), generate a PDF brief:

- Grouped by CCMD.
- Classification banner on every page.
- Embedded analyst notes.
- CSV alongside for pivot-table work.

Export reflects current DB state at the moment of generation — not a
scheduled snapshot. If you want tomorrow's brief, hit export tomorrow.

## 8. How data refreshes

Two paths:

1. **Background ingest scheduler** (enabled by default on the Fly
   deployment). Every `CCMD_INGEST_INTERVAL_MINUTES` (default 60) the
   server pulls every active feed, dedupes, persists, and runs the AOR
   tagger over anything new. The "last refresh" chip on the home page
   reflects the most recent pass.
2. **On-demand CLI** (for local dev):
   ```sh
   uv run dashboard ingest         # pull all feeds
   uv run dashboard tag            # run AOR tagger
   ```

MDM never runs in bulk. The analyst triggers it per-article. This is
intentional — bulk auto-scoring conditions analysts to trust the number.

## 9. When something looks wrong

- **Assessment card says "Assessment did not complete cleanly"** — the
  `failure_reason` mono text tells you which stage failed. Stage 1
  failures are usually API-key or schema parse errors; stage 2 failures
  are usually corrupt JSON in the extraction.
- **Same article appearing twice** — shouldn't happen; dedupe runs on
  URL + content hash. If it does, it's a bug — note the URL and file it.
- **No new articles in 24 h** — check the "last refresh" chip. If it's
  stale, the scheduler is stuck; `fly logs -a <app>` will show the last
  run. If it's fresh, the feeds genuinely have nothing new.
- **Map rectangle is the wrong color / count** — the heat bands rescale
  every page load relative to the busiest AOR. After a large pull one
  AOR dominates and others go pale; that's expected.
- **PDF brief won't render** — WeasyPrint needs native libs (Pango,
  Cairo, gdk-pixbuf). The deployed image has them; if you run locally
  on macOS and PDF export fails, `brew install pango cairo gdk-pixbuf`
  then restart the server.

## 10. What the tool is NOT

Read the README sections **Known limitations** and **Threat model** in
full before making any call based on the dashboard. Short version:

- Not a truth oracle.
- Not calibrated — weights are reasonable priors, not ground-truth-
  validated constants.
- Not on a .mil network — this prototype is unclassified-only. The
  schema is ready for a classified port (handling-marking fields,
  STANAG 2022 admiralty code); the UI does not expose them.
- Not real-time — refresh is on an interval, not push.
- Not multi-analyst-safe — the localhost analyst picker is not auth.
  Anyone with the URL sees everything.

## 11. Further reading

- `README.md` — architecture, data model, AOR tagger methodology, MDM
  scoring weights, threat model, port path.
- `docs/HANDOUT.md` — one-page demo walk-through for leadership.
- `config/ccmd_aor.yaml` — the AOR keyword lists. Edit to tune recall
  per CCMD.
- `config/feeds.yaml` — the feed list. Edit to add or disable sources.

For issues, use the repo issue tracker or walk the step-granular commit
history for design rationale.
