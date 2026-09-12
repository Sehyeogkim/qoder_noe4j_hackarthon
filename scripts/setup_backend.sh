#!/usr/bin/env bash
set -euo pipefail
ARMA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARMA_BACKEND_VENV="${ARMA_BACKEND_VENV:-/workspace/arma/backend-venv}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/arma/uv-cache}"
uv venv --python 3.11 "$ARMA_BACKEND_VENV"
uv pip install --python "$ARMA_BACKEND_VENV/bin/python" -r "$ARMA_ROOT/requirements.lock.txt"
uv pip install --python "$ARMA_BACKEND_VENV/bin/python" --no-deps -e "$ARMA_ROOT"
uv pip check --python "$ARMA_BACKEND_VENV/bin/python"
uv pip freeze --python "$ARMA_BACKEND_VENV/bin/python" > "$ARMA_BACKEND_VENV/resolved-requirements.txt"
"$ARMA_BACKEND_VENV/bin/python" -m compileall -q "$ARMA_ROOT/arma"
