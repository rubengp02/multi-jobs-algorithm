#!/usr/bin/env bash
# Start a persistent Chromium profile for the LinkedIn extension.
set -Eeuo pipefail

project_dir="${BOT_MULTI_JOBS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
profile_dir="$project_dir/data/linkedin_chromium_profile"
extension_source_dir="$project_dir/extension"
initial_url="https://www.linkedin.com/feed/"
debug_args=()

# Opt-in localhost diagnostics for maintenance. The normal service exposes no
# remote debugging interface.
if [[ -n "${LINKEDIN_CHROMIUM_DEBUG_PORT:-}" ]]; then
  debug_args+=(
    "--remote-debugging-address=127.0.0.1"
    "--remote-debugging-port=${LINKEDIN_CHROMIUM_DEBUG_PORT}"
  )
fi

if [[ ! -f "$extension_source_dir/manifest.json" ]]; then
  echo "LinkedIn extension not found: $extension_source_dir/manifest.json" >&2
  exit 1
fi

# Chromium can retain an old unpacked extension service worker for a profile
# even after its source files change. A content fingerprint gives each build a
# fresh extension path while retaining the same browser profile and LinkedIn
# cookies. Superseded runtimes are retained for a bounded period for rollback,
# then removed before Chromium starts; the current runtime is always protected.
extension_fingerprint="$(
  find "$extension_source_dir" -type f -print0 \
    | sort -z \
    | xargs -0 sha256sum \
    | sha256sum \
    | awk '{print $1}'
)"
extension_runtime_root="$project_dir/data/linkedin_extension_runtime"
extension_dir="$extension_runtime_root/$extension_fingerprint"
if [[ ! -f "$extension_dir/manifest.json" ]]; then
  mkdir -p "$extension_runtime_root"
  cp -a "$extension_source_dir" "$extension_dir"
fi

if [[ -n "${CHROMIUM_BIN:-}" ]]; then
  chromium_bin="$CHROMIUM_BIN"
elif command -v chromium >/dev/null 2>&1; then
  chromium_bin="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
  chromium_bin="$(command -v chromium-browser)"
else
  echo "Chromium is not installed. Install chromium before starting this service." >&2
  exit 1
fi

mkdir -p "$profile_dir"

# Preserve the browser profile and its LinkedIn cookies. Only regenerateable
# caches, expired timestamped session backups and old extension copies go away.
if [[ -x "$project_dir/.venv/bin/python" ]]; then
  cleanup_python="$project_dir/.venv/bin/python"
else
  cleanup_python="python3"
fi
"$cleanup_python" "$project_dir/browser_profile_cleanup.py" \
  --data-dir "$project_dir/data" \
  --profile "$profile_dir" \
  --backup-retention-days "${BROWSER_SESSION_BACKUP_RETENTION_DAYS:-14}" \
  --extension-runtime-root "$extension_runtime_root" \
  --extension-runtime-retention-days "${BROWSER_EXTENSION_RUNTIME_RETENTION_DAYS:-30}" \
  --keep-extension-runtime "$extension_fingerprint"

# Modern headless keeps a real tab and Manifest V3 extensions without relying
# on an active X11 desktop, so collection continues while the Pi is unattended.
exec "$chromium_bin" \
  --headless=new \
  --user-data-dir="$profile_dir" \
  --disable-extensions-except="$extension_dir" \
  --load-extension="$extension_dir" \
  --no-first-run \
  --no-default-browser-check \
  --password-store=basic \
  "${debug_args[@]}" \
  "$initial_url"
