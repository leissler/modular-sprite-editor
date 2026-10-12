#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: website/scripts/deploy.sh [--dry-run|--stage-only]

Build, validate and publish the Modular Sprite Editor website from a clean, pushed main.
  --dry-run    Build and inspect prerequisites without uploading.
  --stage-only Upload and verify a release without changing the live symlink.

MODULARSPRITES_DEPLOY_HOST overrides the SSH host for the same site layout.
HELP
}

mode=deploy
case "${1:-}" in
  "") ;;
  --dry-run) mode=dry-run ;;
  --stage-only) mode=stage-only ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
if (( $# > 1 )); then usage >&2; exit 2; fi

site_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
deploy_host="${MODULARSPRITES_DEPLOY_HOST:-v45082.1blu.de}"
remote_root=/var/www/modularsprites.bionic-productions.com
site_url=https://modularsprites.bionic-productions.com/
if [[ ! "$deploy_host" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid SSH host" >&2
  exit 1
fi
cd "$site_dir"
for command_name in git rsync ssh; do
  command -v "$command_name" >/dev/null || { echo "Missing $command_name" >&2; exit 1; }
done
test -x .venv/bin/mkdocs || { echo "Run ./serve.sh to create the build environment." >&2; exit 1; }
test -z "$(git status --porcelain)" || { echo "Commit your changes before deploying." >&2; exit 1; }
test "$(git branch --show-current)" = main || { echo "Production must come from main." >&2; exit 1; }
head_sha="$(git rev-parse HEAD)"
remote_name="$(git config branch.main.remote || echo origin)"
remote_sha="$(git ls-remote "$remote_name" refs/heads/main | awk '{print $1}')"
test "$head_sha" = "$remote_sha" || { echo "Push main before deploying." >&2; exit 1; }

.venv/bin/mkdocs build --strict
.venv/bin/python scripts/check_site.py
.venv/bin/python - "$head_sha" <<'PY'
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
site = Path('site')
(site / 'build-info.json').write_text(json.dumps({
    'product': 'Modular Sprite Editor', 'commit': sys.argv[1],
    'built_at': datetime.now(timezone.utc).isoformat()
}, indent=2) + '\n')
lines = []
for path in sorted(site.rglob('*')):
    if path.is_file() and path.name != 'SHA256SUMS':
        lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(site).as_posix())
(site / 'SHA256SUMS').write_text('\n'.join(lines) + '\n')
PY

release_id="$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD)"
remote_release="$remote_root/releases/$release_id"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$deploy_host" sh -s -- "$remote_root" "$remote_release" <<'REMOTE'
set -eu
sudo -n true
command -v rsync >/dev/null
command -v sha256sum >/dev/null
test -d "$1/releases"
test ! -e "$2"
REMOTE
if [[ "$mode" = dry-run ]]; then
  echo "Dry run passed: $remote_release"
  exit 0
fi

ssh -o BatchMode=yes "$deploy_host" "sudo -n install -d -m 755 '$remote_release'"
rsync -a --chmod=D755,F644 --rsync-path="sudo -n rsync" site/ "$deploy_host:$remote_release/"
ssh -o BatchMode=yes "$deploy_host" "cd '$remote_release' && sudo -n sha256sum --status -c SHA256SUMS"
echo "Verified all files: $remote_release"
if [[ "$mode" = stage-only ]]; then
  echo "Staged only. The live release is unchanged."
  exit 0
fi

previous_release="$(ssh -o BatchMode=yes "$deploy_host" "readlink -f '$remote_root/current' || true")"
ssh -o BatchMode=yes "$deploy_host" sh -s -- "$remote_root" "$remote_release" "$release_id" <<'REMOTE'
set -eu
sudo -n ln -s "$2" "$1/.current-$3"
sudo -n mv -Tf "$1/.current-$3" "$1/current"
test "$(readlink -f "$1/current")" = "$2"
REMOTE

if ! .venv/bin/python - "$site_url" "$head_sha" <<'PY'
import json, sys, urllib.request
base, commit = sys.argv[1:]
with urllib.request.urlopen(base + 'build-info.json?commit=' + commit, timeout=30) as response:
    assert json.load(response)['commit'] == commit, 'Public site has the wrong commit'
for path in ['', 'start/', 'guide/frames/', 'search/search_index.json', 'assets/images/logo.svg',
             'assets/images/art/swordfight.webp']:
    with urllib.request.urlopen(base + path, timeout=30) as response:
        assert response.status == 200, path
print('Public HTTPS checks passed.')
PY
then
  echo "Public checks failed. Restoring previous release." >&2
  ssh -o BatchMode=yes "$deploy_host" sh -s -- "$remote_root" "$previous_release" "$release_id" <<'REMOTE'
set -eu
if [ -n "$2" ] && [ -d "$2" ]; then
  sudo -n ln -s "$2" "$1/.rollback-$3"
  sudo -n mv -Tf "$1/.rollback-$3" "$1/current"
else
  sudo -n unlink "$1/current"
fi
REMOTE
  exit 1
fi
echo "Deployed $head_sha to $site_url"
echo "Release: $remote_release"
