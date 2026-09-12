# Build on an amd64 CPU Docker host; no GPU or model downloads are needed.
# The tag and digest were checked against Docker Hub on 2026-09-12.
FROM runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04@sha256:75bf115d87ee3813f8026fed3e11bae3bf68bfd789a9566878735245b723ef8b
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /usr/local/bin/
ARG ARMA_CUDA_ARCH=8.6
ARG ARMA_EXPECTED_GPU="NVIDIA A40"
ENV DEBIAN_FRONTEND=noninteractive \
    ARMA_VENDOR_ROOT=/opt/arma/vendor \
    ARMA_WORKER_VENV=/opt/venvs/worker \
    LIBERO_CONFIG_PATH=/opt/arma/libero-config \
    TORCH_CUDA_ARCH_LIST=${ARMA_CUDA_ARCH} \
    ARMA_EXPECTED_GPU=${ARMA_EXPECTED_GPU} \
    CUDA_HOME=/usr/local/cuda \
    MAX_JOBS=2 \
    MUJOCO_GL=egl \
    PYOPENGL_PLATFORM=egl \
    ARMA_ARTIFACT_DIR=/workspace/arma/artifacts/worker \
    ARMA_WORKER_MODE=real
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates build-essential pkg-config libegl1 libgl1 libgles2 libglvnd0 \
    libglib2.0-0 ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/arma
COPY worker/requirements.txt worker/requirements.txt
COPY scripts/setup_worker.sh scripts/setup_worker.sh
# setup builds/imports torch metadata for FlashAttention only; it performs no
# CUDA tensor operation, model download, rendering, or robot execution.
RUN bash scripts/setup_worker.sh
COPY pyproject.toml pyproject.toml
COPY arma/ arma/
COPY prompts/ prompts/
COPY configs/ configs/
COPY worker/ worker/
COPY web/ web/
RUN uv venv --python 3.11 /opt/venvs/backend && \
    uv pip install --python /opt/venvs/backend/bin/python . && \
    uv pip check --python /opt/venvs/backend/bin/python && \
    /opt/venvs/worker/bin/python -m compileall -q worker && \
    /opt/venvs/backend/bin/python -m compileall -q arma && \
    uv cache clean
ENV PYTHONPATH=/opt/arma:/opt/arma/vendor/openvla
# Preserve the RunPod parent image's SSH/bootstrap entrypoint. Start the worker
# explicitly after deployment using the command in containers/README.md.
