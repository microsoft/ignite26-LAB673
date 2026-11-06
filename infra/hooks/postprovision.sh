#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repo_root"
python3 infra/setup-venv.py
.venv/bin/python infra/setup-env.py
.venv/bin/python infra/setup-content-understanding.py

if [ "${RESTORE_INDEX_SNAPSHOTS:-true}" = "true" ]; then
    .venv/bin/python infra/create-knowledge.py
fi

printf '%s\n' 'Lab resources and local environment are ready.'