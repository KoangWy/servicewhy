#!/usr/bin/env bash
# One command for the FULL stack on the synthetic data: `make full`.
# Preflight (.env, Docker, Zetaris, Meterless Nightshift) -> compose up -> health wait -> seed -> URLs.
#   scripts/up-full.sh            run everything, stop at the first failed preflight step
#   scripts/up-full.sh --check    preflight only: run every step, report each, start nothing
#   scripts/up-full.sh --no-docker  skip the Docker step (for --check on a machine without Docker)
# Secret values from .env are never printed.
set -u

cd "$(dirname "$0")/.." || exit 1

CHECK_ONLY=0
SKIP_DOCKER=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --no-docker) SKIP_DOCKER=1 ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'; else RED=""; GREEN=""; YELLOW=""; RESET=""; fi
FAILED=0
ok()   { printf '%s[ok]%s   %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '%s[warn]%s %s\n' "$YELLOW" "$RESET" "$1"; }
info() { printf '       %s\n' "$1"; }
# fail <what is wrong> <exact fix>: prints both; stops here unless --check, which carries on to the next step
fail() {
  printf '%s[FAIL]%s %s\n' "$RED" "$RESET" "$1"
  printf '       fix: %s\n' "$2"
  FAILED=1
  [ "$CHECK_ONLY" -eq 1 ] || exit 1
}

# cfg NAME: the shell environment wins (as in docker compose), then .env. .env is parsed, never sourced.
cfg() {
  local name="$1" val
  if [ -n "${!name:-}" ]; then printf '%s' "${!name}"; return; fi
  val=$(grep -E "^[[:space:]]*${name}=" .env 2>/dev/null | tail -n 1 | sed -E "s/^[[:space:]]*${name}=//; s/[[:space:]]+#.*\$//; s/^[\"']//; s/[\"']\$//")
  printf '%s' "$val"
}

# http_code URL [curl args...]: prints the HTTP status, or 000 when nothing answered
http_code() {
  local url="$1"; shift
  curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$@" "$url" 2>/dev/null || true
}

echo "ServiceWhy FULL mode: preflight"

# ── 1. .env ──────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  printf '%s[FAIL]%s .env did not exist; I created it from .env.example.\n' "$RED" "$RESET"
  info "fill these variables in .env, then run this again:"
  info "  METERLESS_RUNTIME_TOKEN   Nightshift Console -> Runtime API key (the model provider key goes in Nightshift, not here)"
  info "  ZETARIS_USER, ZETARIS_PASSWORD, ZETARIS_API_KEY, ZETARIS_ORG_ID   from your local Zetaris bundle"
  info "  (to use OpenCode Go instead of Nightshift: MODEL_PROVIDER=opencode and MODEL_API_KEY)"
  exit 1
fi
ok ".env found"

PROVIDER=$(cfg MODEL_PROVIDER); PROVIDER=${PROVIDER:-meterless}
case "$PROVIDER" in
  meterless)
    TOKEN=$(cfg METERLESS_RUNTIME_TOKEN)
    if [ -z "$TOKEN" ] || [ "$TOKEN" = "your-nightshift-runtime-token-here" ]; then
      fail "METERLESS_RUNTIME_TOKEN is empty or still the placeholder in .env." \
           "open the Nightshift Console, copy the Runtime API key, and set METERLESS_RUNTIME_TOKEN in .env"
    else
      ok "MODEL_PROVIDER=meterless, METERLESS_RUNTIME_TOKEN is set"
    fi ;;
  opencode)
    KEY=$(cfg MODEL_API_KEY)
    if [ -z "$KEY" ] || [ "$KEY" = "your-opencode-go-key-here" ]; then
      fail "MODEL_API_KEY is empty or still the placeholder in .env (MODEL_PROVIDER=opencode)." \
           "set MODEL_API_KEY to your OpenCode Go key in .env, or set MODEL_PROVIDER=meterless"
    else
      ok "MODEL_PROVIDER=opencode, MODEL_API_KEY is set"
    fi ;;
  *)
    fail "MODEL_PROVIDER=$PROVIDER is not valid in .env." "set MODEL_PROVIDER=meterless (default) or MODEL_PROVIDER=opencode" ;;
esac

if [ "$(cfg SAMPLE_MODE)" = "true" ]; then
  fail "SAMPLE_MODE=true in .env: the API would replay recordings and ignore Zetaris and the model." \
       "set SAMPLE_MODE=false in .env (the template does)"
fi
for var in ZETARIS_API_KEY ZETARIS_ORG_ID; do
  case "$(cfg "$var")" in your-*-here|"") warn "$var is empty or a placeholder in .env; fill it if your Zetaris bundle needs it" ;; esac
done

# ── 2. Docker ────────────────────────────────────────────────────────────────
if [ "$SKIP_DOCKER" -eq 1 ]; then
  warn "Docker check skipped (--no-docker)"
elif docker info >/dev/null 2>&1; then
  ok "Docker daemon is running"
else
  fail "the Docker daemon is not reachable (docker info failed)." "start Docker Desktop (or the docker service), wait until it is ready, then run this again"
fi

# ── 3. Zetaris ───────────────────────────────────────────────────────────────
ZLOGIN=$(cfg ZETARIS_LOGIN_URL); ZLOGIN=${ZLOGIN:-http://localhost:3000/api}
ZREST=$(cfg ZETARIS_REST_URL); ZREST=${ZREST:-http://localhost:8888/api/v1.0}
ZETARIS_OK=1
for url in "$ZLOGIN" "$ZREST"; do
  # any HTTP answer (even 401 or 404) proves the port is served; 000 means nothing answered
  if [ "$(http_code "$url")" = "000" ]; then
    ZETARIS_OK=0
    fail "Zetaris does not answer at $url." \
         "start the Zetaris local bundle (README -> Run it -> B -> step 1: docker login, ./preflight.sh, docker compose up -d inside the bundle), wait for it to finish starting, then run this again"
  fi
done
[ "$ZETARIS_OK" -eq 1 ] && ok "Zetaris answers at $ZLOGIN and $ZREST"

# ── 4. Meterless Nightshift ──────────────────────────────────────────────────
if [ "$PROVIDER" != "meterless" ]; then
  warn "Nightshift check skipped (MODEL_PROVIDER=$PROVIDER)"
else
  BASE=$(cfg METERLESS_BASE_URL); BASE=${BASE:-http://127.0.0.1:8088/v1}; BASE=${BASE%/}
  APP=$(cfg METERLESS_APP); APP=${APP:-servicewhy}
  MODEL=$(cfg METERLESS_MODEL); MODEL=${MODEL:-meterless/auto}
  BODY=$(mktemp); trap 'rm -f "$BODY"' EXIT
  # the token goes to curl on stdin so it never shows up in the process list
  CODE=$(printf 'header = "Authorization: Bearer %s"\n' "${TOKEN:-}" | \
         curl -s -K - -o "$BODY" -w '%{http_code}' --max-time 8 \
           -H "meterless-app: $APP" -H "meterless-scope: user" "$BASE/models" 2>/dev/null || true)
  case "$CODE" in
    000|"")
      fail "Nightshift does not answer at $BASE/models (connection refused or timed out)." \
           "start the Nightshift desktop app and check the Nightshift URL in its Console; if it differs from $BASE, set METERLESS_BASE_URL in .env" ;;
    401|403)
      fail "Nightshift rejected the Runtime token (HTTP $CODE)." \
           "copy the Runtime API key from the Nightshift Console into METERLESS_RUNTIME_TOKEN in .env" ;;
    200)
      IDS=$(grep -oE '"id"[[:space:]]*:[[:space:]]*"[^"]*"' "$BODY" | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')
      if [ -z "$IDS" ]; then
        fail "Nightshift answers but lists no models: no model lane is connected." \
             "in Nightshift, open the Providers tab, add your provider key (for example NVIDIA) and connect a model; /healthz being OK does not prove a model is connected"
      else
        ok "Nightshift answers at $BASE with $(printf '%s\n' "$IDS" | wc -l | tr -d ' ') model(s) listed"
        if [ "$MODEL" != "meterless/auto" ] && ! printf '%s\n' "$IDS" | grep -qxF "$MODEL"; then
          warn "METERLESS_MODEL=$MODEL is not in Nightshift's model list; set it to a listed id or to meterless/auto"
        fi
        info "this checks the model list only; the Settings screen's Test connection button sends one real chat request"
      fi ;;
    *)
      fail "Nightshift answered HTTP $CODE at $BASE/models (expected 200)." \
           "check METERLESS_BASE_URL in .env against the Nightshift URL in the Console (it should end in /v1)" ;;
  esac
  info "the api container reaching Nightshift on the host is UNVERIFIED; if it cannot, run the API on the host: SAMPLE_MODE=false python run.py"
fi

if [ "$FAILED" -ne 0 ]; then
  echo "Preflight failed: fix the items marked FAIL above."
  exit 1
fi
echo "Preflight passed."
[ "$CHECK_ONLY" -eq 1 ] && exit 0

# ── 5. Start, wait, seed ─────────────────────────────────────────────────────
echo "Starting the stack (docker compose --profile full up -d --build) ..."
docker compose --profile full up -d --build || { echo "[FAIL] docker compose up failed; see the output above." >&2; exit 1; }

echo "Waiting for http://localhost:8000/health (up to 180 s) ..."
DEADLINE=$((SECONDS + 180))
until curl -sf --max-time 5 http://localhost:8000/health >/dev/null 2>&1; do
  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    echo "[FAIL] the API did not become healthy within 180 s." >&2
    echo "       fix: run 'docker compose logs api' to see why, then run this again" >&2
    exit 1
  fi
  sleep 3
done
ok "API is healthy"

echo "Seeding (docker compose --profile full run --rm seed) ..."
docker compose --profile full run --rm seed || { echo "[FAIL] the seed job failed; see the output above (the seed is idempotent, so you can re-run this)." >&2; exit 1; }

echo
echo "ServiceWhy is up (synthetic data)."
echo "  UI        http://localhost:5173   (Settings screen: model URL, token, Test connection)"
echo "  API docs  http://localhost:8000/docs"
echo "  Stop      make down"
