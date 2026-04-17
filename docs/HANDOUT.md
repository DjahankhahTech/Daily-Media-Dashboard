# CCMD Media Intelligence Dashboard — OSW demo handout

> **UNCLASSIFIED // PROTOTYPE.** Open-source aggregation. Automated
> assessments are decision-support signals, not analytic product. Not
> for operational use.

## What it is

A 15-minute walkable prototype that ingests open-source media, tags
articles to combatant commands, and produces an explainable
decision-support score for each article. Built in response to an OSW
tasker. End users are OSW staff and Marine Corps ICC personnel.

## What to show in the demo

1. **Home tab** — per-CCMD article counts, reviewed + flagged + assessed
   columns, unassigned diagnostic bar. This is what a watch-floor lead
   sees at shift start.
2. **Any CCMD tab** — filter by tier, state-affiliation, MDM category,
   keyword, date. Note the tier badges and the red `state: RU/CN/IR/KP`
   badges on state-affiliated feeds.
3. **Article detail → Assess** — one click, reasoning table expands.
   Every sub-signal: name, value, weight, contribution, explanation.
   Walk down it line by line.
4. **Analyst note** — observation / significance / recommended action
   (ATP-2 form). Flag for OIC. The OIC queue tab populates.
5. **Export → PDF** — daily brief, grouped by CCMD, banner on every
   page, analyst notes embedded.
6. **About** — methodology, feeds, CCMDs, limitations.

## Key design choices

| Choice | Why |
|---|---|
| MDM = extraction + deterministic scorer | No black-box confidence. Every weight is visible code. |
| Classifier is an interface | Swap Anthropic for genai.mil or any other LLM with no UI change. |
| On-demand assessment | Analyst decides what to assess — decision-support, not autolabel. |
| Schema-ready handling markings | Nullable today; classified port writes into existing columns. |
| ATP-2 note fields | Mirrors how analysts already write. |
| Three modules, one DB | Ingest / Classify / Web are independently replaceable. |
| Persistent classification banner | Compile-time constant; every template extends the base. |

## What it doesn't do (by design)

- No claim of truth / falsity — surfaces signals, not verdicts.
- No paste-in text analysis — invites arbitrary input and noise.
- No real-time alerting, no multi-lingual processing, no social-media.
- No auth beyond a localhost analyst picker.

## Port path, ranked

1. **genai.mil** — swap the Anthropic SDK call, expose handling-marking
   fields, re-ATO.
2. **Power BI** — keep the data model; re-render as Power BI reports.
3. **Acquisition / FastAPI + Postgres** — production port with RBAC,
   background task queue, proper auth.

## Top risks / limitations

- Weights in the MDM scorer are reasonable priors, not calibrated
  constants. Need a labeled red-team eval set to tune.
- 18 of 34 feeds need URL verification before real ingestion.
- Corroboration is in-DB only; production needs a broader corpus.
- No cost guardrail on the Anthropic path beyond SDK retries.

## If you ask about…

- **Cost.** Opus 4.7 with prompt caching on the stable system block;
  per-article cost ≈ a few cents. Switch to Sonnet 4.6 for a volume
  port. Stub is free.
- **Classification.** Prototype is unclassified-only; schema ready for a
  classified port (STANAG 2022 admiralty code already modeled).
- **Why on-demand MDM.** Analysts should choose what to escalate. Bulk
  auto-scoring conditions them to trust the number.
- **Why the banner is red.** So it's the first thing you see on every
  page and on every exported PDF. Clutter is by design.
