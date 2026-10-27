# Judge-facing commands (IMPL_SPEC #22). On Windows without make, run the right-hand commands directly.
PY ?= python

.PHONY: full up down seed e2e e2e-full scorecard sample record-sample record-e2e test

full:          ## FULL mode in one command: preflight (.env, Docker, Zetaris, Nightshift) -> compose up -> seed (README: Run it -> B)
	bash scripts/up-full.sh

up:            ## full stack: api, ui, postgres, minio (Zetaris bundle runs from its own compose, see README)
	docker compose up -d --build

down:
	docker compose down

seed:          ## fresh seeded data -> Postgres + Parquet on MinIO -> idempotent Zetaris registration
	$(PY) -m app.sim.load

e2e:           ## keyless proof: local store + recorded model cassettes (offline fake model if none are recorded)
	$(PY) scripts/e2e.py

e2e-full:      ## QA machine: seed + Zetaris + keyed model
	$(PY) scripts/e2e.py --full

scorecard:     ## ten canned questions joined with ground truth -> logs/scorecard.md
	$(PY) -m app.scorecard.harness

sample:        ## serve the recorded run: zero network, zero services
	SAMPLE_MODE=true $(PY) run.py

record-sample: ## re-record logs/examples from the configured backends
	$(PY) scripts/seed_sample.py

record-e2e:    ## QA machine: record the missing cassettes the keyless e2e replays (local store + live model)
	$(PY) scripts/e2e.py --record

test:
	$(PY) -m pytest -q
