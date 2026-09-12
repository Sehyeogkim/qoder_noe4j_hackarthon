#!/usr/bin/env bash
set -euo pipefail
ARMA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARMA_CHECK_DIR="$(mktemp -d)"
trap 'rm -rf "$ARMA_CHECK_DIR"' EXIT
curl -fsSL https://raw.githubusercontent.com/openvla/openvla/c8f03f48af692657d3060c19588038c7220e9af9/pyproject.toml > "$ARMA_CHECK_DIR/pyproject.toml"
curl -fsSL https://raw.githubusercontent.com/openvla/openvla/c8f03f48af692657d3060c19588038c7220e9af9/experiments/robot/libero/libero_requirements.txt > "$ARMA_CHECK_DIR/libero-requirements.txt"
uv pip compile --python-version 3.10 --python-platform x86_64-manylinux_2_31 \
    "$ARMA_ROOT/worker/requirements.txt" "$ARMA_CHECK_DIR/pyproject.toml" \
    "$ARMA_CHECK_DIR/libero-requirements.txt" --output-file "$ARMA_CHECK_DIR/resolved.txt" --quiet
printf '%s\n' 'Linux/Python 3.10 dependency resolution passed. No GPU or package installation performed.'
