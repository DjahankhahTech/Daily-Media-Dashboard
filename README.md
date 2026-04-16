# CCMD Media Intelligence Dashboard

**UNCLASSIFIED // PROTOTYPE.** Open-source aggregation. Automated assessments
are decision-support signals, not analytic product. Not for operational use.

An unclassified demonstrator built in response to an OSW tasker. End users are
OSW staff and Marine Corps ICC personnel supporting information operations and
IW planning. The prototype will be walked through to OSW leadership to inform a
follow-on decision on production hosting (genai.mil integration, Power BI port,
or formal acquisition).

This README is a placeholder for the step-1 skeleton commit. The full
methodology, threat model, limitations, and port-path documentation ship in
build step 9.

## Quick start

```sh
uv sync --extra dev
uv run alembic upgrade head
uv run dashboard init-db          # seed CCMDs + feeds from config/
uv run dashboard info             # sanity-check resolved settings
uv run pytest -q                  # schema smoke tests
```

## Build status

| # | Stage                                       | Status      |
|---|---------------------------------------------|-------------|
| 1 | Skeleton, configs, SQLModel schema, Alembic | complete    |
| 2 | Ingestion (RSS/Atom, trafilatura, dedupe)   | not started |
| 3 | AOR tagger with eval harness                | not started |
| 4 | FastAPI + HTMX frontend (no LLM yet)        | not started |
| 5 | Classifier interface + stub + Anthropic     | not started |
| 6 | MDM extraction + deterministic scorer + UI  | not started |
| 7 | Analyst workflow: notes, flags, export      | not started |
| 8 | Demo mode with canned dataset               | not started |
| 9 | README / methodology / limitations / port   | not started |

## Layout

```
config/          feeds.yaml, ccmd_aor.yaml — editable by analysts
alembic/         migrations
src/ccmd_dashboard/
  ingest/        step 2
  classify/      steps 3, 5, 6
  web/           step 4
tests/           smoke + eval harness
data/            SQLite DB and cached raw feeds (gitignored)
```
