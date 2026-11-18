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
MODE="smoke"
MANIFEST=""
IDLE_MS=""
SETTLE_MS=""
ENTRY_TIMEOUT=""
DETACH=0
COLLECT=0
NAME=""

die() { printf '%s\n' "error: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="${2:-}"; shift 2 ;;
    --entry) ENTRY="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --image) IMAGE="${2:-}"; shift 2 ;;
    --screenshot) SCREENSHOT_NAME="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --manifest) MANIFEST="${2:-}"; shift 2 ;;
    --idle-ms) IDLE_MS="${2:-}"; shift 2 ;;
    --settle-ms) SETTLE_MS="${2:-}"; shift 2 ;;
    --per-entry-timeout) ENTRY_TIMEOUT="${2:-}"; shift 2 ;;
    --detach) DETACH=1; shift ;;
    --collect) COLLECT=1; shift ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --browser-version) BROWSER_VERSION="${2:-}"; shift 2 ;;
    --environment) ENVIRONMENT="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$OUT" ] || die "--out is required"
if [ "$DETACH" = "1" ] || [ "$COLLECT" = "1" ]; then
  [ -n "$NAME" ] || die "--detach/--collect require --name"
fi
# --collect needs neither --root nor --entry nor a manifest: it only retrieves.
if [ "$COLLECT" = "1" ]; then
  # Copy the reports out AND remove the container, so a finished shard frees CPU.
  docker cp "$NAME:/reports/." "$OUT/" >/dev/null 2>&1 || die "cannot copy reports from $NAME"
  # batch runs write into /reports/batch; flatten so callers get one report dir.
  if [ -d "$OUT/batch" ]; then
    cp -R "$OUT/batch/." "$OUT/" 2>/dev/null || true
    rm -rf "$OUT/batch"
  fi
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  printf 'collected reports from %s into %s\n' "$NAME" "$OUT"
  exit 0
fi
[ -n "$ROOT" ] || die "--root is required"
if [ "$MODE" != "batch" ]; then [ -n "$ENTRY" ] || die "--entry is required"; fi
case "$MODE" in
  smoke|gameplay|batch) ;;
  *) die "--mode must be smoke, gameplay or batch" ;;
esac
if [ "$MODE" = "batch" ]; then
  [ -n "$MANIFEST" ] || die "--mode batch requires --manifest"
  [ -f "$MANIFEST" ] || die "manifest not found: $MANIFEST"
  # macOS Docker Desktop mounts nested paths under /private/tmp as empty
  # directories, so the manifest is staged inside the repository instead.
  REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd -P)"
  mkdir -p "$REPO_ROOT/.cache"
  # Stage per container name: concurrent shards must not overwrite each other.
  STAGE_KEY="${NAME:-batch}"
  mkdir -p "$REPO_ROOT/.cache"
  MANIFEST_ABS="$REPO_ROOT/.cache/isolation-manifest-$STAGE_KEY.json"
  cp "$MANIFEST" "$MANIFEST_ABS"
fi
[ -d "$ROOT" ] || die "staged root does not exist: $ROOT"
command -v docker >/dev/null 2>&1 || die "docker is not installed"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "image not found: $IMAGE (build it first)"

# Refuse obvious escapes before the container ever starts.
case "$ENTRY" in
  /*|*..*|*\\*) die "entry must be a repository-relative path without '..'" ;;
esac
if [ "$MODE" = "batch" ]; then ENTRY_PROBE=1; else ENTRY_PROBE="$ENTRY"; fi

ROOT_ABS="$(cd "$ROOT" && pwd -P)"
mkdir -p "$OUT"
OUT_ABS="$(cd "$OUT" && pwd -P)"
[ "$ROOT_ABS" != "$OUT_ABS" ] || die "--root and --out must differ"

# Preflight: on macOS, Docker Desktop only shares some host paths with its VM and
# nested bind mounts under /private/tmp can silently appear empty. Detect that
# here so the failure is actionable instead of a confusing 'entry does not exist'.
if [ "$MODE" = "batch" ]; then
  # Batch mode has no single entry to probe; detect the "mount is empty" failure instead.
  MOUNT_PROBE='test -n "$(ls -A /staged 2>/dev/null)"'
else
  MOUNT_PROBE='test -f "$1"'
fi
if ! docker run --rm -v "$ROOT_ABS:/staged:ro" alpine:3.20 \
     sh -c "$MOUNT_PROBE" sh "/staged/$ENTRY_PROBE" >/dev/null 2>&1; then
  die "container cannot see $ROOT_ABS/$ENTRY_PROBE -- stage the artifact under the repository
       (for example ./.cache/isolated-stage), which is always shared with the Docker VM"
fi

# A reused volume would mix this run's reports with the previous run's.
docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
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

if [ "$MODE" = "batch" ]; then
  REPORT_NAME="summary.json"
  # Reuse the Python batch driver: it already owns per-entry supervision (external
  # `timeout -s KILL`, start_new_session + killpg, child output to a file, and an
  # honest TIMEOUT_ABORTED report). Re-implementing that in shell silently lost the
  # timeout reports, so there is exactly one implementation of the rule now.
  SMOKE_ARGS=(/work/browser_batch_probe.py --root /staged --manifest /manifest.json --out /reports/batch)
  [ -n "$IDLE_MS" ] && SMOKE_ARGS+=(--idle-ms "$IDLE_MS")
  [ -n "$SETTLE_MS" ] && SMOKE_ARGS+=(--settle-ms "$SETTLE_MS")
  [ -n "$ENTRY_TIMEOUT" ] && SMOKE_ARGS+=(--per-entry-timeout "$ENTRY_TIMEOUT")
  CONTAINER_ARGS+=(-v "$MANIFEST_ABS:/manifest.json:ro")
elif [ "$MODE" = "gameplay" ]; then
  REPORT_NAME="gameplay.json"
  SMOKE_ARGS=(/work/browser_gameplay_probe.py --root /staged --entry "$ENTRY" --report "/reports/$REPORT_NAME")
  [ -n "$IDLE_MS" ] && SMOKE_ARGS+=(--idle-ms "$IDLE_MS")
  [ -n "$SETTLE_MS" ] && SMOKE_ARGS+=(--settle-ms "$SETTLE_MS")
else
  REPORT_NAME="smoke.json"
  SMOKE_ARGS=(/work/browser_smoke.py --root /staged --entry "$ENTRY" --report "/reports/$REPORT_NAME")
fi
if [ -n "$SCREENSHOT_NAME" ]; then
  SMOKE_ARGS+=(--screenshot "/reports/$SCREENSHOT_NAME")
fi

if [ "$DETACH" = "1" ]; then
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
  docker volume create "$VOLUME" >/dev/null
  CONTAINER_ARGS+=(--name "$NAME")
  # Drop --rm: the container must outlive the run so --collect can copy reports.
  FILTERED=()
  for arg in "${CONTAINER_ARGS[@]}"; do
    [ "$arg" = "--rm" ] || FILTERED+=("$arg")
  done
  CONTAINER_ARGS=("${FILTERED[@]}")
  printf 'detached isolated batch: container=%s volume=%s\n' "$NAME" "$VOLUME"
  docker run -d "${CONTAINER_ARGS[@]}" "$IMAGE" "${SMOKE_ARGS[@]}"
  exit 0
fi

printf 'running isolated %s test: image=%s entry=%s\n' "$MODE" "$IMAGE" "$ENTRY"
set +e
docker run "${CONTAINER_ARGS[@]}" "$IMAGE" "${SMOKE_ARGS[@]}"
STATUS=$?
set -e

# Copy artifacts out even when the smoke test failed, so failures stay auditable.
CID="$(docker create -v "$VOLUME:/r" alpine:3.20 true)"
docker cp "$CID:/r/." "$OUT_ABS/" >/dev/null 2>&1 || true
docker rm "$CID" >/dev/null
# Batch runs write into /reports/batch; flatten so callers get one report dir.
if [ "$MODE" = "batch" ] && [ -d "$OUT_ABS/batch" ]; then
  cp -R "$OUT_ABS/batch/." "$OUT_ABS/" 2>/dev/null || true
  rm -rf "$OUT_ABS/batch"
fi

if [ -n "$BROWSER_VERSION" ] || [ -n "$ENVIRONMENT" ]; then
  printf '{"browser_version":"%s","environment":"%s"}\n' \
    "$BROWSER_VERSION" "$ENVIRONMENT" > "$OUT_ABS/isolation-metadata.json"
fi

printf 'report written to %s (smoke exit=%s)\n' "$OUT_ABS" "$STATUS"
exit "$STATUS"
