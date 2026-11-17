#!/usr/bin/env bash
# Run ONE browser smoke test inside a disposable, network-isolated container.
#
# This is the M3 isolation boundary. scripts/browser_smoke.py additionally blocks
# non-loopback HTTP and every WebSocket at the browser layer, but that is only a
# second line of defence: it cannot stop WebRTC/UDP/DNS egress. `--network none`
# is what actually confines the process, so always run untrusted artifacts here.
#
# Usage:
#   bash scripts/isolation/run_isolated_smoke.sh \
#     --root ./staged --entry demos/04-fps/index.html --out ./reports
#
# Build the image first:
#   docker build -f scripts/isolation/Dockerfile.smoke -t awsome-games-smoke .
#
# The staged root is mounted READ-ONLY: a compromised page cannot modify the
# evidence it came from. Reports are written to a named volume and copied out
# afterwards, because macOS bind mounts do not honour the container's uid.
set -euo pipefail

IMAGE="${SMOKE_IMAGE:-awsome-games-smoke}"
VOLUME="${SMOKE_VOLUME:-awsome-games-smoke-reports}"
ROOT=""
ENTRY=""
OUT=""
BROWSER_VERSION="${SMOKE_BROWSER_VERSION:-}"
ENVIRONMENT="${SMOKE_ENVIRONMENT:-}"
SCREENSHOT_NAME=""
MEMORY="${SMOKE_MEMORY:-1g}"
CPUS="${SMOKE_CPUS:-1}"

die() { printf '%s\n' "error: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="${2:-}"; shift 2 ;;
    --entry) ENTRY="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --image) IMAGE="${2:-}"; shift 2 ;;
    --screenshot) SCREENSHOT_NAME="${2:-}"; shift 2 ;;
    --browser-version) BROWSER_VERSION="${2:-}"; shift 2 ;;
    --environment) ENVIRONMENT="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$ROOT" ] || die "--root is required"
[ -n "$ENTRY" ] || die "--entry is required"
[ -n "$OUT" ] || die "--out is required"
[ -d "$ROOT" ] || die "staged root does not exist: $ROOT"
command -v docker >/dev/null 2>&1 || die "docker is not installed"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "image not found: $IMAGE (build it first)"

# Refuse obvious escapes before the container ever starts.
case "$ENTRY" in
  /*|*..*|*\\*) die "entry must be a repository-relative path without '..'" ;;
esac

ROOT_ABS="$(cd "$ROOT" && pwd -P)"
mkdir -p "$OUT"
OUT_ABS="$(cd "$OUT" && pwd -P)"
[ "$ROOT_ABS" != "$OUT_ABS" ] || die "--root and --out must differ"

# Preflight: on macOS, Docker Desktop only shares some host paths with its VM and
# nested bind mounts under /private/tmp can silently appear empty. Detect that
# here so the failure is actionable instead of a confusing 'entry does not exist'.
if ! docker run --rm -v "$ROOT_ABS:/staged:ro" alpine:3.20 \
     test -f "/staged/$ENTRY" >/dev/null 2>&1; then
  die "container cannot see $ROOT_ABS/$ENTRY -- stage the artifact under the repository
       (for example ./.cache/isolated-stage), which is always shared with the Docker VM"
fi

docker volume create "$VOLUME" >/dev/null

CONTAINER_ARGS=(
  --rm
  --network none
  --read-only
  --tmpfs /tmp
  --user 65534:65534
  --cap-drop ALL
  --security-opt no-new-privileges
  --pids-limit 256
  --memory "$MEMORY"
  --cpus "$CPUS"
  -v "$ROOT_ABS:/staged:ro"
  -v "$VOLUME:/reports"
)

SMOKE_ARGS=(/work/browser_smoke.py --root /staged --entry "$ENTRY" --report /reports/smoke.json)
if [ -n "$SCREENSHOT_NAME" ]; then
  SMOKE_ARGS+=(--screenshot "/reports/$SCREENSHOT_NAME")
fi

printf 'running isolated smoke test: image=%s entry=%s\n' "$IMAGE" "$ENTRY"
set +e
docker run "${CONTAINER_ARGS[@]}" "$IMAGE" "${SMOKE_ARGS[@]}"
STATUS=$?
set -e

# Copy artifacts out even when the smoke test failed, so failures stay auditable.
CID="$(docker create -v "$VOLUME:/r" alpine:3.20 true)"
docker cp "$CID:/r/." "$OUT_ABS/" >/dev/null 2>&1 || true
docker rm "$CID" >/dev/null

if [ -n "$BROWSER_VERSION" ] || [ -n "$ENVIRONMENT" ]; then
  printf '{"browser_version":"%s","environment":"%s"}\n' \
    "$BROWSER_VERSION" "$ENVIRONMENT" > "$OUT_ABS/isolation-metadata.json"
fi

printf 'report written to %s (smoke exit=%s)\n' "$OUT_ABS" "$STATUS"
exit "$STATUS"
