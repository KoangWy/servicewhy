# ServiceWhy: the agent that explains why a restaurant night went wrong

**Open Agent Hackathon 2026 · Track 02 (The Agent That Can Explain Why) · Team Irigo**

A restaurant manager asks *"why did Saturday dinner revenue drop?"* and gets an evidence-backed
answer built from point-of-sale tickets, table-service events, shift rosters and guest reviews. A
**verifier re-queries every number, then blocks any claim its numbers, sample size or comparison do not support**. It
retries on a wider sample, or answers "insufficient evidence".

> **All data is synthetic.** A seeded discrete-event simulator generates every guest, ticket, shift
> and review. No real guest, staff or customer data is used anywhere, and every UI screen says so.

## Run it in two minutes (no credentials)

SAMPLE mode replays recorded runs through the same API and UI. It makes no network calls, needs no
keys and starts no Zetaris, Postgres or MinIO. **It is a replay, not a live agent:** the API looks up the
stored response for the normalised question text (`app/sample.py`), and every response says so
(`mode.sample_mode`, `recorded_with`). The recordings come from a real FULL-mode run (Zetaris and a live
model), and the traces show every plan, query, verdict, block and retry from that run. To see the agent
execute, use FULL mode below, or `make e2e` (the real orchestrator on a local seeded store, with the
recorded model responses replayed).

```bash
git clone https://github.com/KoangWy/servicewhy && cd servicewhy
docker compose up --build          # no .env needed: SAMPLE_MODE defaults to true
# UI   http://localhost:5173
# API  http://localhost:8000/docs
curl -X POST http://localhost:8000/run -H "Content-Type: application/json" -d @input_examples/example_1.json
```

Without Docker (Python 3.11+):

```bash
pip install -r requirements.txt
SAMPLE_MODE=true python run.py     # API on 0.0.0.0:8000
SAMPLE_MODE=true python run.py ask "Why did Saturday dinner revenue drop 18%?"
```

`GET /health` reports `{"zetaris": "sample", "sample_questions": [...]}`, which lists the questions
that were recorded. A question that was not recorded returns a structured `SampleModeMiss` error, not
a guess.

## Run it for real (FULL mode)

FULL mode needs the Zetaris local bundle, a model key and the two stores. Keys come only from your
local `.env` (`cp .env.example .env`).

1. **Zetaris bundle.** Download `zetaris-platform.zip` from Zetaris Cloud ("Run locally"), then run
   `docker login zetarishackathon.azurecr.io`, `./preflight.sh` and `docker compose up -d` inside it.
   The bundle images are amd64. On Apple Silicon they run emulated, so budget several minutes for
   startup. ServiceWhy reaches the bundle through its published ports: 3000 for login, 8888 for REST.
2. **Our stack:** set `SAMPLE_MODE=false` plus the keys in `.env`, then run:
   ```bash
   docker compose --profile full up -d --build        # api, ui, postgres, minio
   docker compose --profile full run --rm seed        # simulator -> Postgres + Parquet on MinIO -> Zetaris registration
   ```
   The seed job is idempotent: re-running it re-seeds the stores, and the Zetaris registration becomes a no-op.
3. Ask: `curl -X POST localhost:8000/run -H "Content-Type: application/json" -d '{"input":{"query":"Why did Saturday dinner revenue drop 18%?"}}'`.
   The trace is written to `logs/trace-<run_id>.jsonl` and to stdout.

From a Python checkout, `make seed`, `make e2e-full` and `python run.py` do the same steps.

## What the agent does

```text
question ─▶ Planner ─▶ Investigator ─▶ Verifier ──pass──▶ Writer ─▶ answer + findings
             │  ≤3 hypotheses │ federated SQL │  V1..V5    ▲         every number cites
             │  from a YAML   │ via Zetaris   │ block ─────┘retry    an evidence id
             │  library       ▼               ▼ (wider sample, ≤2)
             └──────────▶ World Model (hypotheses · evidence · findings, with provenance)
```

| Role | Job |
|---|---|
| **Planner** | Turns the question into intent, time and segment slots, and at most 3 hypotheses from `app/agent/hypotheses.yaml`. Code enforces policy: a revenue question always carries the demand and spend hypotheses, and a request to rank individual staff is reframed into staffing conditions. |
| **Investigator** | Runs query plans only through the data-access adapter (Zetaris federated SQL that joins PostgreSQL with the Parquet filestore). It computes contrasts: focus vs baseline, cross-section, dose-response across tables per server, bussers on duty, and time window. Each result is stored as a World Model evidence item. |
| **Verifier** | Applies the deterministic rules V1–V5 below, then one structured model judgment (`block`/`pass` plus a reason) that the claim matches what was measured: it blocks a claim whose metric or direction does not match, or that names a cause the data never recorded. The model never recomputes numbers. Confounders that remain are stated as the finding's uncertainty and left to the manager's approval. A block widens the sample to more of the same nights and retries. |
| **Writer** | Writes findings in the fixed contract (cause, evidence, confidence, effect size, uncertainty, recommended action, status) and the answer. A number guard rejects any figure the evidence does not contain. |

Causes are always **staffing or process conditions** (section, shift, time window), never named people. The manager approves or rejects every recommended action (`POST /findings/{id}/approve|reject`), and each decision is logged with role and timestamp.

### The verifier (the differentiator)

| # | Rule | Threshold | Action |
|---|---|---|---|
| V1 | Every value recomputed by an independent second query through the same federated surface: raw rows aggregated in code, with revenue rebuilt from `ticket_items` | mismatch > ±2% | block |
| V2 | Minimum sample per segment | n < 15 blocks; 15 ≤ n < 30 downgrades confidence | block / downgrade |
| V3 | A causal claim needs a contrast (baseline group present) | none found | block |
| V4 | Decoy split: how much of a revenue change fewer parties explain vs revenue per party | volume share ≥ 50% | downgrade service findings and force the split into the answer |
| V5 | Retry budget | > 2 rejections | "insufficient evidence" |

Thresholds live in `app/agent/verifier.py` (`THRESHOLDS`). They are **initial values**, tuned in one pass on real runs before the feature freeze. The same pass covers the verifier's model-judgment prompt (`SYSTEM` in `app/agent/verifier.py`) and the hypothesis library's claim and cause wording (`app/agent/hypotheses.yaml`). The freeze is the commit that publishes the scorecard below: from it on, the thresholds, those prompts and the simulator parameters do not change (UI-only changes may follow). The pass worked from recorded verifier prompts and evidence payloads plus synthetic negative controls, and simulator ground truth was never an input to it. The pass was also checked against the scorecard questions: three live scorecard runs took the baseline from 2/10 to 8/10. **The published 8/10 is therefore an in-sample number** (same seed, same ten questions), not a held-out test.

Runs are bounded: at most 3 hypotheses, 2 retries each, 12 investigate+verify steps per run, 60 s per model call and 40 model calls per run.

## Sponsor technology

- **Zetaris** is the single federated SQL surface. POS tickets, ticket items and table events live in PostgreSQL. Rosters, plate returns and reviews live as Parquet on MinIO. Both are registered by `scripts/init_zetaris.py` (CREATE DATASOURCE, REGISTER DATASOURCE TABLE, CREATE LIGHTNING DATABASE, CREATE LIGHTNING FILESTORE TABLE). Every Investigator query joins the two stores in one statement (`app/metrics.py`). The Verifier's independent V1 re-query goes through Zetaris again. Remove Zetaris and the agent cannot read its data.
- **Meterless** provides the World Model agent engine, implemented in-repo after the Meterless reference architecture (`app/worldmodel/`). `WorldStoreService` is an append-only, replayable store with content-hash ids. `IngestPipelineService` gives idempotent, resumable writes with provenance. `ContextBuilderService` builds the structured payload the Verifier reads (`app/agent/verifier.py`); the Writer reads hypotheses and evidence through the ingest pipeline and does not use the context builder. Meterless' engines are reference architectures, so this is our own implementation of the World Model minimum (the three services above), not a Meterless-hosted service, and model calls do not go through it. Every mutation is a `wm_mutation` trace event and a line in `logs/worldmodel-<run_id>.jsonl`.
- **Cursor** was almost not used. Development was done with Claude as the coding assistant (17 of the 21 commits made before this section was written carry a `Co-Authored-By: Claude` trailer). The repository carries the project rules in `.cursor/rules/`, but the team never received Cursor sponsor credit and did not use Cursor as its development environment. A HackOS chat message told us the Cursor requirement had been dropped. We could not verify it, so we state the facts here and leave the judgement to the reviewers.
- **NVIDIA** is not used in the core build.

## AI and model usage

- **Model:** `deepseek-v4.1-flash` through OpenCode Go (an OpenAI-compatible endpoint, `MODEL_BASE_URL`) for the Planner's hypothesis selection, the Verifier's one structured pass/block judgment and the Writer's prose. An optional backup provider (DeepInfra, also OpenAI-compatible) takes over after repeated transport errors when `MODEL_BACKUP_API_KEY` is set. The model never writes SQL, never recomputes a number and never sees ground truth.
- **Agent framework:** none. The Planner, Investigator, Verifier and Writer and their orchestrator are written in this repository (`app/agent/`, `app/orchestrator.py`). The World Model services (`app/worldmodel/`) are implemented from Meterless' World Model reference architecture.
- **Sponsor technology:** see [Sponsor technology](#sponsor-technology). Cursor was almost not used and NVIDIA is not used.
- **Libraries:** `requirements.txt` (FastAPI, Uvicorn, PyYAML, plus pyarrow, psycopg and minio for the loader only) and `ui/package.json` (React, Vite, Tailwind CSS). Zetaris runs as its own local Docker bundle.
- **Data:** entirely synthetic, generated by the seeded simulator in `app/sim/`. No real people, venue or customer data.
- **AI-assisted coding:** the code was written with Claude as the coding assistant, against specifications the team wrote (`docs/SPEC.md`, `docs/IMPL_SPEC.md`) and checked with the team's own test and QA runs.
- **Fallback:** `SAMPLE_MODE=true` replays recorded runs (see the top of this file). Recorded model responses are committed as cassettes in `cassettes/`.
- **Known limitations:** see [Data and limitations](#data-and-limitations) and the two scorecard misses above.

## API (the UI and judges use the same endpoints)

| Method & path | Purpose |
|---|---|
| `POST /run` | One investigation. Request `{"run_id"?, "input": {"query", "context"?}, "options": {"sample_mode"}}`. Response `{run_id, status, output, agents[], trace_id, log_file, execution_time_seconds}`, or a structured `error` |
| `POST /reports`, `GET /reports/{id}` | Weekly report: summary, 3–5 findings, revenue split and a provenance appendix (a batch run of the same core) |
| `GET /findings/{id}` | One finding (contract above) |
| `POST /findings/{id}/drilldown` | Nested investigation on one finding |
| `POST /findings/{id}/approve` · `/reject` | Manager decision, appended to `logs/approvals.jsonl` |
| `GET /traces/{run_id}` | The run trace (`?format=jsonl` returns the raw file) |
| `GET /health` | `{status, zetaris: up\|down\|sample\|local, model, sample_mode}` |

There are three input/output pairs in `input_examples/` and `output_examples/`: the demo question, a non-cause probe ("No, the kitchen was not slow") and an abstention ("the data does not record menu changes").

## Logs

Each run writes `logs/trace-<run_id>.jsonl` (schema version 1). The event set is `run_start, plan, query, evidence, verify, block, retry, answer, run_end, wm_mutation`. Each event carries the role, action, summaries, SQL, rows used, verdict and retry count. Readable lines also go to stdout. Secrets are masked (`…redacted`).

## Scorecard

`make scorecard` runs the ten canned questions in `app/scorecard/questions.yaml` on a fresh seeded dataset. It joins each trace and World Model log with the simulator's ground truth and prints the table published below. The agent never reads ground truth: only the harness loads it, and a default-suite test greps agent-side modules for any reference. It needs the FULL stack (Zetaris, a model key and the seeded stores), so it cannot run in SAMPLE mode.

The metrics are root-cause hit rate, evidence precision, unsupported claims caught vs wrongly blocked, decoy rejection, abstention correctness and retries per investigation.

**Published scorecard** (one FULL-mode run: 2026-10-27, seed 20261024, Zetaris federated SQL, `deepseek-v4.1-flash`). This is the run on the code committed as `939816b`. Later commits changed the Writer's wording and number guard, the hypothesis library's cause wording, and the cassette tooling. They did not change the verifier rules, thresholds or prompt. Grading the ten recorded runs in the committed sample bundle with the same harness gave 8/10 with the same two misses.

| Metric | Result |
|---|---|
| Root-cause hit rate (top finding names the injected condition and cites its window) | 2/3 (67%) |
| Evidence precision (cited items that support their claim) | 17/24 (71%) |
| Verifier: unsupported claims caught / wrongly blocked | 13 / 0 |
| Decoy rejection rate | 1/1 (100%) |
| Abstention correctness | 2/2 (100%) |
| Retries per investigation | 0.3 |
| Questions passing every check | **8/10 (80%)** |

Two questions miss, and we did not change the product to hide them:

- **Q1 (demo question): the root cause is ranked second.** The answer names the injected section-B condition, but as its second finding. Findings rank by confidence, the staffing finding rests on a small sample (`low`), and the spend finding, which is a symptom of the same night, comes first. Reordering causes above symptoms would satisfy the grader, but we decided it would be tuning to the answer key.
- **Q6 (this week vs last week): no revenue split.** The seeded data holds no week-over-week revenue drop to split, which is what the grader's expectation assumes, and a retry widens "this week vs last week" to two weeks, so the answer covers a different period than the one asked.

The question's "18%" is a manager's guess. The verifier recomputes the change from the data: -39% for Saturday 3 Oct against its baseline (of which fewer parties explain 17%). The agent reports the measured figure and does not adopt the premise.

Simulator parameters, verifier thresholds and the tuned prompts are frozen from the commit that publishes this table.

## Development (keyless)

```bash
pip install -r requirements-dev.txt
python -m pytest -q                 # 84 tests; local seeded store + offline fake model, no keys, no services
python scripts/e2e.py               # make e2e: demo question through POST /run on the local store, replaying the recorded model; asserts every role is in the trace
cd ui && npm ci && npm test && npm run dev   # UI on :5173, proxies /api to :8000
```

| Variable | Values |
|---|---|
| `SAMPLE_MODE` | `true`: replay the bundle in `logs/examples/` |
| `DATA_BACKEND` | `zetaris` (judged path) · `local`: the seeded simulator in SQLite (tests and keyless dev only) |
| `MODEL_MODE` | `live` · `record`: QA machine writes `cassettes/` with secrets masked · `record-missing`: replay a cassette when one exists, record it when not · `replay`: a cassette miss fails loudly · `fake`: offline rules (tests only) |

The sample bundle in `logs/examples/` and the three example pairs were recorded from a FULL-mode run (Zetaris, `deepseek-v4.1-flash`); its `recorded_with` field says so. The model responses behind it are committed as cassettes in `cassettes/`, and replaying them against Zetaris (`DATA_BACKEND=zetaris MODEL_MODE=replay python scripts/seed_sample.py --out <tmpdir>`) reproduces the same answers without model calls. `make e2e` replays a second cassette set recorded on the local store (`make record-e2e`), because evidence ids depend on the data backend; see `cassettes/README.md`. A model call is not perfectly repeatable, so a re-recorded bundle can differ in wording or in which hypotheses the planner picks.

## Clean-machine checklist (SAMPLE mode, zero credentials)

1. `git clone` the repo, `cd servicewhy`, then `docker compose up --build`.
2. `curl localhost:8000/health` returns `"zetaris": "sample"`.
3. `curl -X POST localhost:8000/run -H "Content-Type: application/json" -d @input_examples/example_1.json` returns `status: success`, findings and a revenue split.
4. `curl localhost:8000/traces/sample-q1` shows planner, investigator and verifier events, including a `block` and a `retry`.
5. `http://localhost:5173` shows the report, a finding with approve/reject, and the trace panel. The synthetic-data label is on every screen.
6. `docker compose logs api` shows the replayed trace lines.

## Data and limitations

- The data is synthetic: 1 venue, 20 tables in 4 sections, 5 weeks, lunch and dinner. The injected incidents are I1 (section B runs 7 tables per server, Fri/Sat 19:00–21:00 from 21 Sep) and I4 (one busser after 20:00, Thu–Sat, from 21 Sep), plus the D2 decoy (fewer walk-ins on the last Saturday). Incidents are configured only in `app/sim/incidents.py`.
- Single-night segments are small (about 30 dinner parties), so the verifier often widens the sample before it will pass a claim. That behaviour is intended.
- There is no weather or events feed. The demand-side explanation is inferred from fewer parties, not observed.
- A real deployment would need consent and data-protection review (for example Vietnam's Decree 13/2023 on personal data). ServiceWhy deliberately works on shifts and sections, not individuals, and uses no faces or audio.

## Repository layout

```text
app/agent/        planner, investigator, verifier, writer, hypotheses.yaml, scope (periods)
app/worldmodel/   Meterless World Model: store, ingest pipeline, context builder
app/adapters/     Zetaris data-access adapter, model adapter (live/record/replay/fake)
app/metrics.py    the one metric catalog (SQL per dialect)
app/sim/          simulator, incidents, loader, local keyless store
app/api/ app/report/ app/scorecard/ app/logging/
ui/               Vite + React + TypeScript (report, finding, evidence & trace, drill-down)
scripts/          init_zetaris.py, seed_sample.py, e2e.py, meterless_gate.py
```

## License

MIT, see [LICENSE](LICENSE).
