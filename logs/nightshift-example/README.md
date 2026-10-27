# One live run through Zetaris and Meterless Nightshift

Evidence of a FULL-mode run, kept apart from the SAMPLE bundle in `logs/examples/` (which replays older recordings).

| | |
|---|---|
| When | 2026-10-27, about 20:38 UTC |
| How | clean clone of `servicewhy` at `23004f7`, `make full`, Docker Desktop for Mac (Apple M2 Pro), Zetaris local bundle and Meterless Nightshift running on the host |
| Question | "Why did greeting times get longer in section B on Friday nights?" (not in the recorded list) |
| Result | success in 79.83 s; 3 model calls, one verifier block and one retry; synthetic data only |
| Data path | every `query` event says `Zetaris federated SQL (REST)` |
| Model path | the `run_end` event lists each model request with `requested_model` and `routed_model`: all three were answered by `nvidia/nemotron-3-ultra-550b-a55b` through Nightshift |

Files: `trace-ui-vfy00002.jsonl` (the run trace) and `worldmodel-ui-vfy00002.jsonl` (the World Model mutations with content-hash ids).
No token or key appears in either file (checked by searching for the Runtime token and `Bearer`).
