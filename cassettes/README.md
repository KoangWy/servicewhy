# Model cassettes

Recorded model responses for keyless runs (`MODEL_MODE=replay`). One JSON file per call, keyed by sha256 of
(role, system prompt, prompt): a changed prompt is a cassette miss, which fails loudly instead of calling the
network. `pytest` does not read this directory; its tests use the offline fake model.

Only the QA machine records them (keys in its local `.env`); secrets are masked at record time.

| `MODEL_MODE` | Behaviour |
|---|---|
| `record` | always calls the model and overwrites the cassette |
| `record-missing` | replays a cassette when it exists, calls the model and stores it only when it does not |
| `replay` | answers from cassettes; a missing one raises `CassetteMiss` |

Prefer `record-missing` after a prompt change: every answer whose prompt did not change is kept, so a re-recording does
not re-sample the planner or verifier decisions.

## Two recordings, one directory

Evidence ids hash the data backend's source and SQL, so verifier and writer cassettes replay only against the backend that
recorded them. The planner prompt contains neither, so **planner cassettes are shared** by both sets.

| Recorded by | Backend | Replayed by |
|---|---|---|
| `MODEL_MODE=record-missing make record-sample` (`scripts/seed_sample.py`, FULL stack) | Zetaris | `DATA_BACKEND=zetaris MODEL_MODE=replay python scripts/seed_sample.py --out <tmpdir>`: re-runs the canned questions from cassettes and should reproduce the committed answers (the `--out` form leaves the committed bundle alone) |
| `make record-e2e` (`scripts/e2e.py --record`) | local SQLite store | `make e2e`, the keyless proof (replays when this directory holds cassettes, else uses the offline fake model) |

Any change to a prompt, the verifier or writer `SYSTEM` text, the hypothesis library wording, or the data the prompts embed
invalidates the cassettes that carry it. Delete the affected role's files (stale ones are not removed automatically), re-record
with `record-missing`, then run `pytest`, `make e2e` and the Zetaris replay check above.

Several runs can share one verifier prompt, so a cassette holds the last reply for it: replaying a run reproduces its status and
answer, but the verifier's one-line reason may differ from the committed trace.
