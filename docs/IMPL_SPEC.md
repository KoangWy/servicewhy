# ServiceWhy — Implementation Spec (ticket-tracked)

**Status: derived 2026-10-24 evening. Canonical parent: `docs/SPEC.md` (agreed, D1–D16).**
Where this document and `docs/SPEC.md` disagree on detail, SPEC.md wins until a new
strategy-repo decision record says otherwise. Workflow of record: strategy-repo `decisions/0004`
(Khoa implements everything keyless; Huy owns specs + the FULL-mode QA gate; demo deferred).
Questionnaire of record (answers baked in below): strategy-repo
`track/to-questionnaire-servicewhy-impl.md`, filled 2026-10-24.

This spec is published as the epic issue on this repository's tracker; tickets are its sub-issues.
Triage label `ready-for-agent` marks work ready to pick up.

---

## Problem Statement

The agreed product spec (`docs/SPEC.md`) describes ServiceWhy completely at the design level, but
almost none of it is built: after the day-1 gates only the simulator, the Zetaris access adapter,
the World Model skeleton and the model adapter exist. One developer (Khoa) must implement the
rest of the system — data pipeline, agent core, API, UI, packaging — before the feature freeze
(EOD 2026-10-25) and submission (2026-10-27 23:45 UTC), **without access to the model API key,
Zetaris credentials, or the only fully configured machine** (Huy's). Meanwhile the only
integration environment must not sit idle behind a "big bang" handoff at the end.

## Solution

Implement ServiceWhy exactly as `docs/SPEC.md` defines it, in a build order that puts the data
foundation first and keeps every later ticket testable **keyless**: model responses are recorded
as cassettes by Huy and replayed at the ModelAdapter boundary, Zetaris access is faked in unit
tests and exercised for real only during Huy's QA runs, and the entire behavior of the system is
verified through the public REST API (the single high test seam). Khoa closes tickets against
tests; Huy runs the same end-to-end proof in FULL mode on his machine the evening of 10-25, then
tunes and freezes on 10-26. Demo production comes after QA passes.

## User Stories

### Data foundation

1. As Khoa, I want the simulator wired to a loader that writes Postgres rows and Parquet files
   and uploads them to MinIO, so that every later ticket queries real-shaped data.
2. As Khoa, I want an idempotent Zetaris init script (bucket, parquet upload, datasource + table
   registration), so that a fresh environment can be provisioned repeatedly without drift.
3. As Huy, I want a run manifest with a content hash per table, so that I can prove the dataset
   is deterministic per seed.
4. As a judge, I want one command to seed the whole environment, so that I can reproduce the
   dataset without understanding the internals.
5. As Khoa, I want the incident configuration to stay a data file, so that restoring I2/I3/D1
   later means appending entries, not editing simulator code.

### Agent core

6. As the restaurant manager, I want to ask "why did Saturday dinner revenue drop 18%?" and get
   an evidence-backed answer, so that I can act on causes instead of guesses.
7. As the system, I want a Planner that turns the question into at most three hypotheses from a
   data-defined hypothesis library, so that scope per run is bounded and extensible.
8. As the Investigator, I want to execute query plans only through the data-access adapter and
   record every result as an evidence item with provenance, so that no number enters the system
   unaccounted for.
9. As the Verifier, I want deterministic checks (independent re-query, minimum n, contrast
   requirement, decoy share) plus one structured model judgment, so that unsupported claims are
   blocked before reaching the manager.
10. As the Writer, I want to produce findings that reference evidence ids for every numeric
    claim, so that the answer is auditable.
11. As the orchestrator, I want a hard cap on loop steps and verifier retries, so that a run
    always terminates with a trace.
12. As Huy, I want every World Model mutation logged as JSONL, so that Meterless's role in the
    loop is visible to judges.
13. As Khoa, I want the metric catalog in one shared module, so that Investigator contrasts,
    Verifier re-queries and the scorecard never disagree on a formula.

### API and reports

14. As a UI consumer, I want the documented REST surface (run, reports, findings, drill-down,
    approve/reject, traces, health), so that every screen is wired to the same contracts judges
    test.
15. As the manager, I want a period report (summary paragraph + 3–5 findings + provenance
    appendix), so that I get the week at a glance.
16. As the manager, I want to approve or reject a finding, so that the system records my
    decision with timestamp and role.
17. As the manager, I want drill-down ("why" on one finding), so that I can chase a specific
    cause further.
18. As a judge, I want input/output example pairs shipped in the repo, so that I can see the
    contract without running anything.

### UI

19. As the manager, I want a report screen listing findings with confidence, so that I can
    triage my week.
20. As the manager, I want a finding-detail screen with evidence, uncertainty and the
    approve/reject control, so that I can act from one place.
21. As a judge, I want an evidence & trace panel showing queries, rows, verdicts and the retry
    chain, so that I can verify the agent did real work.
22. As a judge, I want a visible synthetic-data label on every screen, so that I never mistake
    the demo data for production data.

### Keyless development (the workflow)

23. As Khoa, I want recorded model cassettes replayed at the ModelAdapter boundary, so that I
    can build and test the whole agent core without an API key.
24. As Khoa, I want a fake data-access adapter serving canned federated results, so that unit
    tests run without Zetaris.
25. As Khoa, I want SAMPLE_MODE replay serving the same endpoints from a recorded trace, so that
    I can build the UI and packaging with zero services.
26. As Huy, I want cassette recording to happen on my machine from real runs, so that Khoa's
    tests run against genuinely real model behavior.
27. As Huy, I want keys never to leave my local env, so that the submission stays clean.

### QA, scorecard, freeze

28. As Huy, I want a one-command end-to-end proof (fresh seed → run → trace contains planner,
    investigator and verifier events), so that the 10-25 checkpoint is mechanical, not manual.
29. As Huy, I want the scorecard harness joining traces with ground truth on the ten canned
    questions, so that quality is a published number, not a claim.
30. As a judge, I want the scorecard markdown in the README with tuned thresholds and their
    date, so that I can check the tuning-immutability promise.
31. As Huy, I want a test that bans ground-truth imports from agent-side modules, so that the
    scorecard cannot be gamed accidentally.
32. As a judge, I want a clean clone → `docker compose up` → checklist path, so that I can
    evaluate without credentials (SAMPLE mode) and with them (FULL mode).

### Process

33. As Khoa, I want tickets with explicit dependencies on the tracker, so that I always know the
    next unblocked ticket.
34. As either teammate, I want a ticket closed with the commit hash in the issue, so that the
    tracker doubles as the build record.
35. As the team, I want the freeze marked by the scorecard-publish commit, so that "no tuning
    after publication" has a mechanical anchor.

## Implementation Decisions

### Workflow (binding, from `decisions/0004`)

1. **Khoa is the sole implementer** of backend, agent core, UI, compose, scripts and README,
   starting from the committed gate skeletons (simulator, Zetaris adapter, World Model skeleton,
   ModelAdapter).
2. **Huy owns specs and the QA gate.** He records model cassettes, runs the 10-25 evening FULL
   smoke, tunes thresholds and simulator parameters, publishes the scorecard (freeze), and
   verifies the clean-machine FULL path. Keys never leave Huy's `.env`.
3. **Demo production is deferred** until after QA passes (10-26 late / 10-27), before the
   unchanged deadline.
4. **Khoa's first pickup**: accept the pending repo invite; clone; read SPEC.md, this spec, and
   the ticket epic; run the test suite and a SAMPLE-mode boot to confirm a green baseline on his
   machine; then take the first unblocked ticket.

### Test architecture (confirmed with Huy)

5. **The REST API is the single high seam.** All behavior tests — component and end-to-end —
   enter through the API using the FastAPI test client. No test mocks agent-internal modules.
6. **One new seam: model cassettes at the ModelAdapter boundary.** The adapter gains a
   record/replay mode selected by environment: in replay mode, a call whose (role, prompt)
   matches a recorded cassette returns the recorded response; a miss is a hard test failure, not
   a network call. Cassettes are JSON fixtures committed to the repo, produced only by Huy's
   recording runs, and contain no secrets (secrets masked at record time).
7. **A fake DataAccessAdapter** serves canned federated-query results for unit tests; the real
   adapter is exercised only in Huy's FULL runs. The existing three gate-test files are prior
   art and stay green throughout.
8. **SAMPLE_MODE stays as specified** (SPEC §9): same endpoints, recorded trace, zero services —
   the packaging and UI track builds on it from day one.

### Build order and dependencies (freeze EOD 2026-10-25)

9. **Data foundation first**: loader → Postgres/MinIO writes → idempotent Zetaris init →
   determinism manifest. Everything downstream queries it; nothing else starts before it.
10. Then **API + orchestrator + loop skeleton** (health, run endpoint with trace emission,
    SAMPLE wiring), so the e2e harness exists before the agent logic lands.
11. Then **Planner → Investigator** (hypothesis library, metric catalog, evidence items in the
    World Model), proven by the cassette-mode e2e run.
12. Then **report generation + UI screens** (wire to SAMPLE replay; OpenAPI schema
    auto-generated from the API module is the UI's contract artifact), in parallel with
    **Verifier** and **scorecard harness code** (the harness runs in Huy's QA, but its code is a
    ticket like any other).
13. **10-25 evening: Huy's FULL smoke** — the SPEC §13 checkpoint (one full why-answer via the
    run endpoint, trace complete) is proven cassette-mode by Khoa and re-proven FULL-mode by
    Huy. First cassette batch + exemplar trace + example pairs are recorded from this run.
14. **10-26: Huy tunes** (V1–V5 thresholds, simulator parameters; once), **publishes the
    scorecard = freeze**; Khoa lands QA fixes, README, examples, clean-machine check; demo only
    after both.

### Component decisions (bake-ins from the questionnaire)

15. **Hypothesis library is data**: a YAML file in the agent module — id, family (volume, check
    size, service delay by stage, staffing, external/decoy), statement template, default
    metric × segment × comparison plan. Restoring I2/I3/D1 = appending entries.
16. **Metric catalog is one shared module** (metric id, formula, required source columns),
    imported by Investigator, Verifier and scorecard. This refines the SPEC §3 module sketch,
    which placed it under scorecard; not a decision-register change.
17. **World Model stable ids**: sha256 of canonical JSON (sorted keys, no whitespace) of the
    entity's content, prefixed by entity type. Same content → same id → idempotent re-ingest
    after a crash.
18. **Trace event schema**: owned by the trace module — a `schema_version` field and an
    enumerated event set (run_start, plan, query, evidence, verify, block, retry, answer,
    run_end, wm_mutation). The scorecard harness refuses traces with an unknown version.
19. **Determinism manifest**: per table, row count + sha256 of the sorted-row-content canonical
    JSON (content hash, not parquet bytes). A determinism test re-runs the simulator with the
    same seed (small test-sized dataset via config) and asserts an identical manifest.
20. **Scorecard "root-cause hit"**: per scored question, the top finding both (a) names the
    ground-truth incident's condition in its cause hypothesis and (b) cites at least one
    evidence item whose query covers the incident's affected window. Encoded per question in the
    canned question set.
21. **Ground-truth ban as a test**: a pytest greps agent-side modules (planner/investigator/
    verifier/writer, adapters, world model) for the ground-truth literal and fails on any hit;
    it runs in the default suite.
22. **Makefile surface (judge-facing)**: `up`, `down`, `seed`, `e2e`, `scorecard`, `sample`.
    `make e2e` = fresh seed → run the demo question → assert the trace contains planner,
    investigator and verifier events; cassette-mode on Khoa's machine, FULL-mode on Huy's.
23. **API contracts** are SPEC §8 verbatim; the finding contract is SPEC §6 verbatim. Structured
    errors follow the Technical Execution Guide JSON contract.
24. **DeepInfra backup model id** is picked by Khoa at wiring time (keyless to list), verified in
    Huy's QA run (SPEC §15).

### Definition of done and conventions

25. **Every code ticket closes with a passing pytest** (unit or integration, through the seams
    above). Exempt tickets (compose, README, examples, UI screens) close with a written manual
    checklist inside the ticket; UI screens additionally get a light component test.
26. **Commits go straight to main until freeze**; a ticket closes via the tracker with the
    closing commit hash in a comment. After freeze: fixes only, still referenced to tickets.
27. **Freeze is mechanical**: the commit that publishes the scorecard markdown + threshold table
    to the README. From that commit, simulator parameters and verifier thresholds are immutable
    (stated in the README itself).

## Testing Decisions

- **Good tests assert external behavior** at the seams — what the API returns, what the trace
  records, what the scorecard prints — never the internals of a planner or writer. If a test
  needs to peek inside an agent module, the seam is wrong.
- **The suite must pass keyless on any machine.** Any test that would need real keys or live
  Zetaris is either cassette/fake-backed or lives behind the FULL-mode make target that only Huy
  runs.
- **Prior art**: the three existing gate test files (simulator determinism, World Model ingest,
  Zetaris adapter) — new tests extend these patterns rather than inventing new harnesses.
- **Cassette discipline**: cassette misses fail loudly; cassettes are regenerated only by Huy's
  recording runs; a changed prompt invalidates the cassette (hash-keyed), which is the desired
  friction — prompt changes become visible decisions.
- **Determinism test uses a small seeded dataset** (configurable length) so the suite stays fast;
  the full 30-day dataset determinism is asserted by the manifest during real seed runs.

## Out of Scope

- Everything SPEC §1 excludes (multi-turn free-form Q&A, incidents I2/I3/D1, floor-plan replay,
  NVIDIA vision, real-data adapter, 2.5D rendering, per-employee scoring, audio, cameras).
- Demo video production (deferred per `decisions/0004`, not dropped — it happens after QA, before
  the deadline).
- Model-call budget tuning and DeepInfra id selection beyond the wiring pick (SPEC §15 items).
- Any change to the SPEC.md decision register D1–D16 — that requires a new strategy-repo
  decision record.

## Further Notes

- **Critical-path risk**: Khoa's pending collaborator invite blocks all implementation; Huy
  nudges tonight (2026-10-24).
- **Late-integration risk**: the first FULL run of Khoa's code is Huy's 10-25 evening smoke —
  mitigated by cassettes (real model behavior in Khoa's tests) and by the smoke landing a full
  day before submission.
- **Known environment quirk**: the model endpoint rejects Python's default User-Agent
  (Cloudflare error 1010) — the adapter already sets its own; keep it when extending.
- **Known hardware quirk**: the Zetaris bundle is amd64; on Apple Silicon it runs emulated and
  starts slowly. Clean-machine checks must budget startup time.
- Reference chain: `docs/SPEC.md` (canonical) → this document → tracker epic + tickets.
  Questionnaire with rationale: strategy repo `track/to-questionnaire-servicewhy-impl.md`.
