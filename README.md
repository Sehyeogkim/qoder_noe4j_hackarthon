# ARMA — Agentic Robot Memory Architecture

> An external memory layer that helps a frozen VLA learn from prior robot attempts—without retraining its weights.

![How memory changes a VLA](assets/readme/vla-memory.png)

## What is ARMA?

A baseline VLA predicts actions only from the current image and instruction. **ARMA** stores successful and failed attempts in Neo4j, retrieves relevant experience for the current scene, and refines the instruction before the frozen OpenVLA predicts its next action.

The goal is simple: **use experience as context so a robot can avoid repeating the same mistake without GPU-heavy retraining.**

## Architecture

![ARMA agent architecture](assets/slides/arma-agent-architecture-v2.png)

ARMA coordinates three agents around one frozen robot policy:

1. **Task Planner Agent** — chooses the next subtask from the goal and current observation.
2. **Memory Retrieval Agent** — searches Neo4j for relevant attempts and refines the VLA instruction.
3. **Memory Writer Agent** — evaluates the outcome and records the attempt, evidence, and result.

```text
Task + Observation → Plan → Retrieve Memory → Frozen OpenVLA → Robot
        ↑                       Neo4j                       ↓
        └──────────── New Observation ← Evaluate & Record ─┘
```

## Stack

- **Robot policy:** OpenVLA (frozen weights)
- **Simulation:** LIBERO · MuJoCo · robosuite · Franka Panda
- **Memory:** Neo4j graph + vector retrieval
- **Agents:** Gemini-based planner, retrieval, and evaluator roles
- **Backend:** Python · FastAPI

## Quick start

The local contract demo uses fake agents and a fake robot, so it requires no GPU, API key, or database:

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m arma.cli --artifacts artifacts/synthetic smoke --output replay-output
.venv/bin/python -m http.server 8766 --directory replay-output
```

Then open `http://localhost:8766`.

## Run on RunPod (real GPU)

Use a GPU Pod with persistent `/workspace` storage and a CUDA-enabled Ubuntu image. The tested GPU was an **NVIDIA L40S 48 GB**. The RunPod image supplies the NVIDIA driver/CUDA runtime, so do not reinstall CUDA manually.

### 1. Clone and install

```sh
cd /workspace
git clone --branch qoder/test --single-branch \
  https://github.com/Sehyeogkim/qoder_noe4j_hackarthon.git arma
cd arma

nvidia-smi
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Keep the backend and robotics dependencies isolated.
bash scripts/setup_backend.sh
bash scripts/setup_worker.sh
```

### 2. Validate CUDA and headless rendering

```sh
export ARMA_VENDOR_ROOT=/workspace/arma/vendor
export ARMA_WORKER_VENV=/workspace/arma/worker-venv
export PYTHONPATH=/workspace/arma:/workspace/arma/vendor/openvla
export HF_HOME=/workspace/arma/hf-cache
export MUJOCO_GL=egl PYOPENGL_PLATFORM=egl
export CUDA_VISIBLE_DEVICES=0 MUJOCO_EGL_DEVICE_ID=0

python worker/gpu_preflight.py --expected-gpu "NVIDIA L40S"
"$ARMA_WORKER_VENV/bin/python" -m worker.smoke
```

`nvidia-smi` only confirms GPU visibility. Both checks above must pass before loading the 7B policy.

### 3. Start the frozen OpenVLA worker

Run one worker in a dedicated Pod terminal. The checkpoint is downloaded on the first start.

```sh
export ARMA_WORKER_MODE=real
export ARMA_ARTIFACT_DIR=/workspace/arma/artifacts/gpu-baseline/worker
export ARMA_HF_REVISION=962318cec55ac10993ff0f5f43eda9a270b4c873

"$ARMA_WORKER_VENV/bin/python" -m worker.serve \
  --host 127.0.0.1 --port 18001
```

Keep port `18001` private. In a second Pod terminal, check health and run the baseline:

```sh
cd /workspace/arma
curl --fail --silent http://127.0.0.1:18001/health

/workspace/arma/backend-venv/bin/python scripts/run_gpu_baseline.py \
  --worker-url http://127.0.0.1:18001 \
  --artifacts artifacts/gpu-baseline \
  --init-state 4
```

For Gemini + Neo4j memory experiments, create `.env` from `.env.example` and follow the [full setup and experiment runbook](docs/setup.md). Never commit API keys.

<details>
<summary>Optional: build a reusable RunPod image with Docker BuildKit</summary>

```sh
DOCKER_BUILDKIT=1 docker build --platform linux/amd64 \
  --build-arg ARMA_CUDA_ARCH=8.9 \
  --build-arg "ARMA_EXPECTED_GPU=NVIDIA L40S" \
  -f containers/Dockerfile -t arma-worker:l40s .
```

Build and push this image before renting GPU time. This repository contains the recipe, but the image build itself has not been verified in this checkout. See [container notes](containers/README.md).

</details>

For the experiment design, see the [Experiment Plan](PLAN.md) and [Implementation Log](docs/implementation-log.md).

## Current status

The local synthetic loop, Gemini role calls, Neo4j Aura transactions, and one real OpenVLA/LIBERO simulation baseline have been validated. The baseline completed state 4 after 134 policy actions. The full three-agent memory loop and controlled memory-vs-no-memory comparison are still pending, so no success-rate improvement is claimed yet.
