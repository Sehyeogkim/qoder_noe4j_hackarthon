# Current GPU pod handoff

This document covers only the user-provided GPU pod. Neo4j work is paused here and continues in the user's other session. These commands do not configure database credentials or change pod lifecycle settings.

## Connection and verified state

| Item | Current value |
| --- | --- |
| RunPod pod ID | `fyweenfgrv95mz` |
| SSH address | `root@195.26.232.162` |
| SSH port | `34074` |
| Local SSH key | `/Users/jeff/.ssh/id_ed25519_runpod` |
| GPU | NVIDIA L40S, 46068 MiB reported VRAM |
| Host driver | `570.195.03` |
| Project directory | `/workspace/arma` |
| Backend Python | `/workspace/arma/backend-venv/bin/python` — Python 3.11.13 |
| Worker Python | `/workspace/arma/worker-venv/bin/python` — isolated worker installation |
| Source checkouts | `/workspace/arma/vendor/openvla`, `/workspace/arma/vendor/LIBERO` |
| Hugging Face cache | `/workspace/arma/hf-cache` |
| Dependency cache | `/workspace/arma/uv-cache` |
| Initial baseline artifact root | `/workspace/arma/artifacts/gpu-baseline` |
| GPU-specific rate record | `configs/gpu-smoke.yaml` — user-provided L40S, $1.09/hour |

This is a different pod from the earlier deleted L40S host. The root agent verified CUDA and BF16 on this pod. Backend installation completed: 41 installed packages pass `uv pip check`, required SDK modules import, and actual source modules compile. A credential-free baseline CLI dispatch fixture passed with zero robot, model, or database calls; that fixture is not VLA inference.

Worker dependencies, EGL rendering, checkpoint loading, and actual OpenVLA inference have now passed. The definitive installed versions are recorded in the worker's resolved dependency file. The baseline below is an actual frozen-policy execution in LIBERO simulation, not a fake worker test or a physical hardware robot trial.

### Verified baseline — 2026-09-12T21:56:21Z

- Attempt: `7322c85983954b37a9a1bee1113371df`, initialization state **4**.
- Result: **success**, from the simulator task predicate; termination reason `goal_satisfied`.
- Executed **134 policy actions** across **14 intervals**; recorded runner elapsed time **36.57 seconds**.
- **Zero agent API calls** and **no external database use**. The reported API cost of zero does not include GPU rental.
- Worker remains model-loaded and ready at `127.0.0.1:18001`, with `model_training=false` and `trainable_parameter_count=0`.
- Replay: `/workspace/arma/artifacts/gpu-baseline/replay/index.html`. Raw video: `/workspace/arma/artifacts/gpu-baseline/worker/10c6d164-46e0-42de-8063-ca4c9c55278d/rollout.mp4`.

This verifies the GPU baseline. It does not establish memory improvement or a completed three-agent comparison. The local archive was copied and SHA-256 verified: **17,134,893 bytes**, digest `6775384cad1a68080d874083cddc9efc34fe0577ba17585b89479281e334012b`. The local audit confirmed 134 unique action observations, contiguous actions, 14 intervals with four actions in the final interval, finite seven-dimensional actions, and matching hashes for 15 interval-boundary frames. Evidence: [local-verification.json](../artifacts/gpu-baseline/local-verification.json). The latest full local regression suite passed **76 tests**; final browser QA of the baseline-only replay passed: the 6.75-second video played to completion, the final interval shows actions 130–134 and task success, all 136 media assets pass content hashes, and the final observation opens from the recorded graph. See [replay QA](../artifacts/gpu-runtime/baseline-replay-qa.json) and [screenshot](../artifacts/gpu-runtime/baseline-replay-qa.png).

Connect from the local machine:

```sh
ssh -i /Users/jeff/.ssh/id_ed25519_runpod -p 34074 root@195.26.232.162
```

## Worker commands on the pod

Installation is complete and a worker is already running. The commands below are the restart/runbook commands; do not start a second worker alongside it. Use the worker environment for robotics dependencies and the backend environment for the orchestrator; the base container's Python is not either environment.

```sh
cd /workspace/arma
export ARMA_VENDOR_ROOT=/workspace/arma/vendor
export ARMA_WORKER_VENV=/workspace/arma/worker-venv
export PYTHONPATH=/workspace/arma:/workspace/arma/vendor/openvla
export HF_HOME=/workspace/arma/hf-cache
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export CUDA_VISIBLE_DEVICES=0
export MUJOCO_EGL_DEVICE_ID=0
export ARMA_HF_REVISION=962318cec55ac10993ff0f5f43eda9a270b4c873
```

Verify the renderer before allocating the policy model:

```sh
"$ARMA_WORKER_VENV/bin/python" -m worker.smoke
```

This smoke must produce a valid GPU operation and a nonempty rendered RGB frame. It does not establish policy inference.

Start the worker in a dedicated pod terminal:

```sh
export ARMA_WORKER_MODE=real
export ARMA_ARTIFACT_DIR=/workspace/arma/artifacts/gpu-baseline/worker
"$ARMA_WORKER_VENV/bin/python" -m worker.serve \
  --host 127.0.0.1 --port 18001
```

`worker.serve` reserves its loopback address first, loads one frozen model, and starts serving HTTP only after loading finishes. It reuses that same model for subsequent resets. Keep one process; do not start a second model copy. Port 8001 belongs to the base image's nginx process, which is left untouched. ARMA uses port **18001** instead. The worker binds to loopback and accepts only `127.0.0.1` as its host. Do not expose port 18001 publicly or change its bind address to `0.0.0.0`.

In another pod terminal, inspect status:

```sh
curl --fail --silent http://127.0.0.1:18001/health
```

With `worker.serve`, the listener appears only after model loading completes. `/health` reports `ready` from `model_loaded`; `session_ready: false` is expected before a reset and after an episode is closed. After the verified baseline, the closed environment may report `renderer: not_initialized` while the loaded policy remains ready. The ready health response also reports actual `model_training` and `trainable_parameter_count`; the frozen-policy expectation is `false` and `0`. A loaded model is not yet evidence of a successful action or completed episode. The selected checkpoint is `openvla/openvla-7b-finetuned-libero-spatial`; weights remain frozen.

## Local diagnostics through SSH

Keep this tunnel open in a local terminal:

```sh
ssh -N -i /Users/jeff/.ssh/id_ed25519_runpod -p 34074 \
  -L 18001:127.0.0.1:18001 root@195.26.232.162
```

Then the local diagnostic command is:

```sh
curl --fail --silent http://127.0.0.1:18001/health
```

If local port 18001 is occupied, use `-L 18002:127.0.0.1:18001` and query local port 18002. The worker remains bound to the pod's loopback interface.

An HTTP tunnel does not make pod filesystem paths available locally. Run the baseline orchestrator on the pod so observation files resolve. The initial baseline uses `scripts/run_gpu_baseline.py`, which explicitly constructs `InMemoryRepository` and deterministic `BaselineAgents`. It does not load `.env` or invoke Gemini or Neo4j, even if the other session changes credentials. The script automatically exports the recorded replay afterward. The root agent used this command for the verified baseline. It starts a new episode if repeated:

```sh
cd /workspace/arma
/workspace/arma/backend-venv/bin/python scripts/run_gpu_baseline.py \
  --worker-url http://127.0.0.1:18001 \
  --artifacts artifacts/gpu-baseline \
  --init-state 4
```

`configs/gpu-smoke.yaml` describes this user-provided L40S pod at $1.09/hour. The separate `configs/demo.yaml` A40 plan is preserved to avoid changing the other session's work. Keep the worker artifacts inside `artifacts/gpu-baseline/worker` so a subsequent strict replay export can resolve every frame within its artifact root. Do not run the baseline twice or start a competing worker. The verified result above belongs to one recorded baseline episode; a second command invocation is a new experiment.

## Backend verification and logs

Backend packages are installed in the isolated Python 3.11 environment. Recheck compatibility without network or model calls:

```sh
cd /workspace/arma
uv pip check --python /workspace/arma/backend-venv/bin/python
/workspace/arma/backend-venv/bin/python -m compileall -q arma
```

The installation log is `/workspace/arma/backend-setup.log`; its initial compile pass encountered macOS AppleDouble `._*.py` metadata from the transferred archive. Those metadata files were removed by the root agent and ordinary `compileall` subsequently passed. The exact resolved package list is `/workspace/arma/backend-venv/resolved-requirements.txt`.

Future source archives should use `COPYFILE_DISABLE=1` when creating the tar file on macOS. Do not transfer credentials as part of a project archive. Keep real execution manifests, frames, action logs, and videos together under the artifact root for later download and inspection.
