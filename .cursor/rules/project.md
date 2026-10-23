# ServiceWhy — project rules (for humans and agents)

Language: English only in every file, commit message, branch name and PR body.

## Architecture invariants (breaking one is a bug, not a refactor)

1. **The agent never reads `ground_truth`.** The injected-cause file is simulator output, loaded
   only by the scorecard harness, never importable from agent code paths.
2. **Every model call goes through `ModelAdapter`** (OpenAI-compatible client → OpenCode Go).
   One `x-opencode-session` UUID per investigation run. No direct API calls anywhere else.
3. **Every data read goes through `DataAccessAdapter`** → Zetaris federated SQL. Direct store
   connections exist only in the simulator loader and SAMPLE_MODE replay.
4. **Every step is logged** as JSONL to `logs/trace-<run_id>.jsonl` and stdout: role, action,
   query, rows used, verdict, retry count. If it is not in the trace, it did not happen.
5. **The simulator is deterministic by seed.** Never tune simulator parameters after scorecard
   numbers are published.
6. **The Verifier can block.** A blocked claim must be visible in the trace with the reason, then
   retried or answered with "insufficient evidence".
7. **SAMPLE_MODE must always work** with no network and no external services (replays a recorded
   run). Any change that breaks sample mode breaks the submission.
8. **Secrets only via environment variables.** `.env` is gitignored; `.env.example` carries
   placeholders; keys never appear in code, logs, examples, the demo video or slides.
9. **Runs are bounded**: timeouts on external calls, capped retries and loop iterations, a full
   run finishes in minutes.
10. **Decisions by shift, section and process — never individual staff ranking.** No faces, no
    audio; the manager approves every recommended action before it is logged as accepted.

## Workflow

- Small, scoped commits, imperative English messages (`feat: add verifier re-query rule`).
- Never force-push `main`. Push with `git push origin HEAD:main` (submodule detached-HEAD trap).
- The spec (`docs/SPEC.md`) is the source of truth for scope; the scorecard README table is the
  source of truth for measured claims. Do not tune to the scorecard.
