#!/usr/bin/env bash
set -euo pipefail
umask 077

LOCK_FILE="/var/lock/vektryn-pg-backup.lock"
ENV_FILE="/opt/vektryn/.env"
LOG_FILE="/var/log/vektryn-backup.log"

START_EPOCH="$(date -u +%s)"
CURRENT_STAGE="init"
TMP_FILE=""
SENTRY_DSN=""
BACKUP_BUCKET=""

log() {
  local line
  line="$(date -u +%Y-%m-%dT%H:%M:%SZ) | $*"
  printf '%s\n' "${line}" | tee -a "${LOG_FILE}"
}

send_sentry_error() {
  local stage="$1"
  local detail="$2"
  local exit_code="$3"
  if [ -z "${SENTRY_DSN}" ]; then
    return 0
  fi
  SENTRY_DSN_VAL="${SENTRY_DSN}" \
  BACKUP_STAGE="${stage}" \
  BACKUP_DETAIL="${detail}" \
  BACKUP_EXIT_CODE="${exit_code}" \
  BACKUP_BUCKET_VAL="${BACKUP_BUCKET}" \
  python3 - <<'PY_EOF' || true
import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid

dsn = os.environ.get("SENTRY_DSN_VAL", "").strip()
if not dsn:
    raise SystemExit(0)

parsed = urllib.parse.urlparse(dsn)
public_key = parsed.username
project_id = parsed.path.strip("/").split("/")[-1]
if not public_key or not project_id or not parsed.hostname:
    raise SystemExit(0)

port_suffix = f":{parsed.port}" if parsed.port else ""
envelope_url = f"{parsed.scheme}://{parsed.hostname}{port_suffix}/api/{project_id}/envelope/"
event_id = uuid.uuid4().hex
now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
stage = os.environ.get("BACKUP_STAGE", "unknown")
detail = os.environ.get("BACKUP_DETAIL", "Backup script failed")[:500]
exit_code = os.environ.get("BACKUP_EXIT_CODE", "1")
bucket = os.environ.get("BACKUP_BUCKET_VAL", "")

header = {"event_id": event_id, "sent_at": now_iso, "dsn": dsn}
item_header = {"type": "event"}
payload = {
    "event_id": event_id,
    "timestamp": now_iso,
    "level": "error",
    "platform": "other",
    "environment": "production",
    "logger": "vektryn.pg_backup",
    "message": {
        "formatted": f"PostgreSQL backup failed at stage={stage} (exit={exit_code}): {detail}"
    },
    "tags": {
        "service": "pg-backup",
        "environment": "production",
        "stage": stage,
    },
    "extra": {
        "exit_code": exit_code,
        "bucket": bucket,
    },
}
body = (
    json.dumps(header) + "\n" + json.dumps(item_header) + "\n" + json.dumps(payload) + "\n"
).encode("utf-8")

req = urllib.request.Request(
    envelope_url,
    data=body,
    headers={
        "Content-Type": "application/x-sentry-envelope",
        "X-Sentry-Auth": (
            f"Sentry sentry_version=7, sentry_key={public_key}, "
            "sentry_client=vektryn-pg-backup/1.0"
        ),
    },
    method="POST",
)
with urllib.request.urlopen(req, timeout=10):
    pass
PY_EOF
}

cleanup() {
  if [ -n "${TMP_FILE}" ] && [ -f "${TMP_FILE}" ]; then
    rm -f "${TMP_FILE}"
  fi
}

on_error() {
  local exit_code="$?"
  local msg="Command failed at stage=${CURRENT_STAGE} (exit=${exit_code})"
  log "ERROR: ${msg}" >&2
  send_sentry_error "${CURRENT_STAGE}" "${msg}" "${exit_code}"
  exit "${exit_code}"
}

trap cleanup EXIT
trap on_error ERR

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  log "SKIP: Another backup is already running (${LOCK_FILE} locked)."
  exit 0
fi

read_env_var() {
  local key="$1"
  if [ ! -f "${ENV_FILE}" ]; then
    return 0
  fi
  python3 -c '
import sys
key = sys.argv[1]
path = sys.argv[2]
with open(path, encoding="utf-8") as fh:
    for line in fh:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        if k.strip() == key:
            print(v.strip().strip("\"\x27"))
            break
' "${key}" "${ENV_FILE}"
}

SENTRY_DSN="$(read_env_var SENTRY_DSN)"
BACKUP_BUCKET="${GCS_DB_BACKUPS_BUCKET:-$(read_env_var GCS_DB_BACKUPS_BUCKET)}"

if [ -z "${BACKUP_BUCKET}" ]; then
  CURRENT_STAGE="config"
  log "ERROR: GCS_DB_BACKUPS_BUCKET is not configured" >&2
  false
fi

if [ "${BACKUP_SIMULATE_FAILURE:-0}" = "1" ]; then
  CURRENT_STAGE="simulated_failure"
  log "ERROR: Simulated backup failure triggered for Sentry verification" >&2
  false
fi

TIMESTAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OBJECT_NAME="daily/vektryn-pg-${TIMESTAMP}.dump"
TMP_FILE="$(mktemp /tmp/vektryn-pg-backup.XXXXXX.dump)"

CURRENT_STAGE="pg_dump"
nice -n 19 ionice -c 3 docker exec vektryn-postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --compress=6 --no-owner --no-privileges' \
  > "${TMP_FILE}"

CURRENT_STAGE="verify_size"
if [ ! -s "${TMP_FILE}" ]; then
  log "ERROR: pg_dump produced an empty archive" >&2
  false
fi

CURRENT_STAGE="verify_integrity"
docker exec -i vektryn-postgres pg_restore --list < "${TMP_FILE}" >/dev/null

CURRENT_STAGE="metadata_token"
ACCESS_TOKEN="$(curl --fail-with-body -sS -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")"

CURRENT_STAGE="gcs_upload"
ENCODED_OBJECT="$(python3 -c "import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=''))" "${OBJECT_NAME}")"
curl --fail-with-body -sS --retry 3 --retry-delay 5 \
  -X POST \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "@${TMP_FILE}" \
  "https://storage.googleapis.com/upload/storage/v1/b/${BACKUP_BUCKET}/o?uploadType=media&name=${ENCODED_OBJECT}&ifGenerationMatch=0" \
  >/dev/null

SIZE_BYTES="$(wc -c < "${TMP_FILE}")"
DURATION_SEC="$(( $(date -u +%s) - START_EPOCH ))"
log "OK: Uploaded gs://${BACKUP_BUCKET}/${OBJECT_NAME} (size=${SIZE_BYTES} bytes, duration=${DURATION_SEC}s)"
