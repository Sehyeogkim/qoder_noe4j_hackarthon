#!/usr/bin/env bash
set -euo pipefail
# Install prebuilt CUDA 12.1 wheels in an isolated worker environment.
# A newer host toolkit is supported; source compilation specifically needs 12.1.
# No GPU execution, checkpoint download, or pod provisioning occurs here.
# uv and system EGL/GL libraries must be installed in the pod image.
ARMA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARMA_VENDOR_ROOT="${ARMA_VENDOR_ROOT:-/workspace/arma/vendor}"
ARMA_WORKER_VENV="${ARMA_WORKER_VENV:-/workspace/arma/worker-venv}"
# The pinned CUDA 12.1 PyTorch wheels carry their runtime libraries; a newer
# host toolkit (e.g. CUDA 12.8) is fine when installing the prebuilt FA wheel.
# Only an explicitly requested source build needs the matching devel toolkit.
if [[ "${ARMA_ALLOW_FLASH_SOURCE_BUILD:-0}" == 1 ]]; then
  command -v nvcc >/dev/null || { echo 'CUDA devel toolkit missing'; exit 1; }
  [[ "$(nvcc --version)" == *'release 12.1'* ]] || { echo 'CUDA toolkit 12.1 required for source build'; exit 1; }
fi
command -v uv >/dev/null
mkdir -p "$ARMA_VENDOR_ROOT"
uv venv --python 3.10.13 "$ARMA_WORKER_VENV"
ARMA_PYTHON="$ARMA_WORKER_VENV/bin/python"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/arma/uv-cache}"
export HF_HOME="${HF_HOME:-/workspace/arma/hf-cache}"
mkdir -p "$UV_CACHE_DIR" "$HF_HOME"
for ARMA_REPO in openvla LIBERO; do
  if [[ ! -d "$ARMA_VENDOR_ROOT/$ARMA_REPO/.git" ]]; then
    if [[ "$ARMA_REPO" == openvla ]]; then
      git clone https://github.com/openvla/openvla.git "$ARMA_VENDOR_ROOT/$ARMA_REPO"
    else
      git clone https://github.com/Lifelong-Robot-Learning/LIBERO.git "$ARMA_VENDOR_ROOT/$ARMA_REPO"
    fi
  fi
done
git -C "$ARMA_VENDOR_ROOT/openvla" checkout --detach c8f03f48af692657d3060c19588038c7220e9af9
git -C "$ARMA_VENDOR_ROOT/LIBERO" checkout --detach 8f1084e3132a39270c3a13ebe37270a43ece2a01
uv pip install --python "$ARMA_PYTHON" torch==2.2.0 torchvision==0.17.0 torchaudio==2.2.0 --index-url https://download.pytorch.org/whl/cu121
uv pip install --python "$ARMA_PYTHON" -r "$ARMA_ROOT/worker/requirements.txt" -r "$ARMA_VENDOR_ROOT/openvla/experiments/robot/libero/libero_requirements.txt" -e "$ARMA_VENDOR_ROOT/openvla" -e "$ARMA_VENDOR_ROOT/LIBERO"
uv pip install --python "$ARMA_PYTHON" packaging ninja setuptools wheel
# Official v2.5.5 release wheel: upstream also chooses cu122 for all CUDA 12.x.
# Avoid silently spending GPU time compiling when the known wheel is available.
ARMA_FLASH_WHEEL="https://github.com/Dao-AILab/flash-attention/releases/download/v2.5.5/flash_attn-2.5.5%2Bcu122torch2.2cxx11abiFALSE-cp310-cp310-linux_x86_64.whl"
if ! uv pip install --python "$ARMA_PYTHON" "$ARMA_FLASH_WHEEL" --no-deps; then
  if [[ "${ARMA_ALLOW_FLASH_SOURCE_BUILD:-0}" != 1 ]]; then
    echo 'FlashAttention wheel unavailable; source build disabled to preserve demo budget.'
    exit 1
  fi
  TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.6}" MAX_JOBS="${MAX_JOBS:-2}" \
    uv pip install --python "$ARMA_PYTHON" flash-attn==2.5.5 --no-build-isolation --no-deps
fi
uv pip check --python "$ARMA_PYTHON"
# LIBERO otherwise prompts interactively on first import. Set its documented path config.
mkdir -p "${LIBERO_CONFIG_PATH:-$HOME/.libero}"
ARMA_VENDOR_ROOT="$ARMA_VENDOR_ROOT" "$ARMA_PYTHON" - <<'PY'
import os
from pathlib import Path
import yaml
root=Path(os.environ['ARMA_VENDOR_ROOT'])/'LIBERO'
config=Path(os.environ.get('LIBERO_CONFIG_PATH',str(Path.home()/'.libero')))/'config.yaml'
if not config.exists():
    config.write_text(yaml.safe_dump({'benchmark_root':str(root/'libero/libero'),'bddl_files':str(root/'libero/libero/bddl_files'),'init_states':str(root/'libero/libero/init_files'),'datasets':str(root/'datasets'),'assets':str(root/'libero/libero/assets')}))
PY
# LIBERO's legacy setup.py discovers no top-level namespace package under
# modern PEP 660 editable installs. Add source roots explicitly without editing
# the pinned upstream checkout (and preserve experiments.* helper imports).
ARMA_VENDOR_ROOT="$ARMA_VENDOR_ROOT" "$ARMA_PYTHON" - <<'PYROOTS'
import os,sysconfig
from pathlib import Path
root=Path(os.environ['ARMA_VENDOR_ROOT'])
(Path(sysconfig.get_path('purelib'))/'arma_vendor_roots.pth').write_text(str(root/'LIBERO')+'\n'+str(root/'openvla')+'\n')
PYROOTS
uv pip freeze --python "$ARMA_PYTHON" > "$ARMA_WORKER_VENV/resolved-requirements.txt"
printf '%s\n' 'Setup complete. Next run renderer smoke before loading the model:'
printf '%s\n' "PYTHONPATH=$ARMA_ROOT:$ARMA_VENDOR_ROOT/openvla MUJOCO_GL=egl PYOPENGL_PLATFORM=egl $ARMA_PYTHON -m worker.smoke"
printf '%s\n' "ARMA_VENDOR_ROOT=$ARMA_VENDOR_ROOT PYTHONPATH=$ARMA_ROOT:$ARMA_VENDOR_ROOT/openvla $ARMA_PYTHON -m worker.serve --port 18001"
