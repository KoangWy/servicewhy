# Model cassettes

Recorded model responses for keyless development and tests (`MODEL_MODE=replay`). One JSON file per
call, keyed by sha256 of (role, system prompt, prompt): a changed prompt is a cassette miss, which fails
loudly instead of calling the network.

Only the QA machine records them (`MODEL_MODE=record`, FULL stack, keys in its local `.env`); secrets are
masked at record time. Until the first FULL smoke lands, this directory is empty and `make e2e` falls back
to the offline fake model (`MODEL_MODE=fake`).
