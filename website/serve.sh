#!/usr/bin/env bash
# Preview the website locally: http://127.0.0.1:8000/ (MODULARSPRITES_DOCS_ADDR picks another address).
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="$project_dir/.venv/bin/python"

if [[ ! -x "$python_bin" ]]; then
  python3 -m venv "$project_dir/.venv"
fi

if ! "$python_bin" -c 'import material, mkdocs' >/dev/null 2>&1; then
  "$python_bin" -m pip install --disable-pip-version-check \
    -r "$project_dir/requirements.txt"
fi

cd "$project_dir"
exec "$python_bin" -m mkdocs serve \
  --dev-addr "${MODULARSPRITES_DOCS_ADDR:-127.0.0.1:8000}"
