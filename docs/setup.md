# Setup and runbook

Run commands from the repository root. Preserve the current `qoder/test` checkout; do not switch branches automatically. The most recent L40S/minimal-demo changes are pending regression verification. Backend commands use Python 3.11; the real robotics worker requires an isolated Python 3.10.13 environment. Do not install the robotics stack into the backend environment.

## Local setup and zero-cost checks

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m arma.cli --artifacts artifacts/synthetic smoke --output replay-output
.venv/bin/python -m http.server 8766 --directory replay-output
```

Open `http://localhost:8766`. Synthetic smoke output is explicitly marked synthetic, excluded from real memory eligibility, and is not an experiment. A portable exported `index.html` also loads its bundle without a backend; keeping all exported files together is required.

## Environment settings

Create `.env` from `.env.example` only if it does not already exist. Preserve any existing credentials. Never commit or paste keys into documentation or logs.

```text
GEMINI_API_KEY=<Google Gemini API key>
GEMINI_MODEL=gemini-3-flash-preview
NEO4J_URI=neo4j+s://<Aura instance host>
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<Aura database password>
NEO4J_DATABASE=neo4j
RUNPOD_API_KEY=<RunPod API key>
ARMA_WORKER_URL=http://127.0.0.1:8001
ARMA_ARTIFACT_ROOT=artifacts/real
```

`doctor` reports setting presence, worker readiness and ledger totals without printing secrets:

```sh
.venv/bin/python -m arma.cli doctor
```

Optional paid Gemini check (charges the same persistent budget ledger):

```sh
.venv/bin/python -m arma.cli --artifacts artifacts/gemini-check smoke-gemini
```

This sends a synthetic white image to the real model and validates a Planner response. It verifies API access and image/JSON handling, not robot perception accuracy or a three-agent real execution.

## Aura Free

Use one Aura Free instance and place its database credentials in `.env`. Confirm connectivity before paid GPU work. Run unique constraints/migrations:

```sh
.venv/bin/python -m arma.cli migrate-memory
```

Do not seed synthetic test records into the real execution snapshot. The in-memory repository is a test implementation, not evidence that Aura transactions or Cypher queries have run successfully.

## Prepare the container before paid GPU time

The previous A40 allocation failed. The user now authorizes one **L40S 48 GB at $0.79/hour**, retaining the $10 total cap. Build the dependency image before provisioning the GPU. Image preparation is a separate gate from GPU validation: a container build does not establish CUDA runtime, EGL rendering or OpenVLA inference success.

Use a trusted CUDA 12.1 **devel** base image with `nvcc`, EGL/GL system libraries, Git, SSH and `uv`. Include the repository under `/workspace/arma` and prepare both backend and worker environments. Run the existing worker setup script during image preparation on a build host:

```sh
bash scripts/setup_worker.sh
```

The script expects a CUDA 12.1 toolchain, clones and pins official sources, creates `/workspace/arma/worker-venv`, installs dependencies, and prepares LIBERO path configuration. It is not a Docker image builder or a pod provisioning command. The prepared image must be built for the Linux GPU host and published with an immutable digest before paid provisioning; no unverified build command is implied here. Follow any checked-in container preparation scripts added for this gate and record the build result.

Do not spend paid GPU time compiling FlashAttention or installing the full dependency tree. Preserve resolved dependency locks and the image digest. Any remaining checkpoint download/storage and GPU warm-up consume the same budget. Recheck L40S availability and price immediately before creation; do not silently substitute hardware or exceed the authorized rate.

After image preparation succeeds, provision at most one L40S with a 60 GB working volume and an explicit shutdown deadline. Bound compute plus storage to $5, API calls to $4, and retain $1 reserve; the deadline is at most six hours and may be shorter. Keep real artifacts on the working volume. Once the pod starts, validate actual CUDA and EGL before loading the policy:

```sh
export ARMA_VENDOR_ROOT=/workspace/arma/vendor
export ARMA_WORKER_VENV=/workspace/arma/worker-venv
export PYTHONPATH=/workspace/arma:/workspace/arma/vendor/openvla
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export CUDA_VISIBLE_DEVICES=0
export MUJOCO_EGL_DEVICE_ID=0
"$ARMA_WORKER_VENV/bin/python" -m worker.smoke
```

The smoke checks CUDA tensor execution, exact task resolution, initialization indices through 12, and a non-empty rendered RGB frame. It does not load policy weights.

Start the real worker in a separate terminal on the pod:

```sh
export ARMA_WORKER_MODE=real
export ARMA_ARTIFACT_DIR=/workspace/arma/artifacts/real/worker
"$ARMA_WORKER_VENV/bin/uvicorn" worker.app:create_app --factory --host 127.0.0.1 --port 8001
```

The real model is loaded lazily when the worker initializes its robot. Run backend CLI commands on the same pod so local RGB references are readable by Gemini and the replay exporter. An SSH tunnel can expose the localhost worker to local diagnostics without publishing the worker endpoint. Do not assume a remote HTTP client can access the pod's filesystem paths.

## Real execution order

With the worker ready and Gemini/Neo4j configured:

```sh
.venv/bin/python -m arma.cli doctor
.venv/bin/python -m arma.cli migrate-memory
.venv/bin/python -m arma.cli --artifacts artifacts/real run --condition baseline --init-state 4 --split smoke
```

Inspect the saved manifest, actions, frames, environment predicate and video before collection. Baseline uses the full official task instruction without Gemini decision calls. A smoke outcome need not be success, but runtime errors, preprocessing mistakes or missing evidence must be resolved before evaluation.

```sh
.venv/bin/python -m arma.cli --artifacts artifacts/real collect
.venv/bin/python -m arma.cli --artifacts artifacts/real compare
.venv/bin/python -m arma.cli --artifacts artifacts/real export --output replay-real
```

The revised `collect` contract uses states 0/1 and at most one optional failed-attempt retry, then freezes `evaluation-v1` and saves `snapshot.json`. The revised `compare` contract targets the no-memory/memory pair on state 10; the state-4 baseline is run separately first. Inspect `comparison.json`: `complete=false` means the intended pair did not finish. These revised defaults must pass the current implementation checks before paid execution; older four-state/nine-episode behavior must not be used accidentally. Commands should not be blindly repeated against an existing frozen snapshot; preserve the original run root and inspect current records first.

The first online export saves `graph.json` beside attempt artifacts. Later export without the database:

```sh
.venv/bin/python -m arma.cli --artifacts artifacts/real export --offline --output replay-real
```

An offline export only contains the saved graph if `graph.json` exists. Empty graph output is not equivalent to a successful Neo4j demonstration.

## Artifact preservation and shutdown

Copy the completed portable replay directory after each export, and synchronize raw attempt directories after each Attempt. Validate copied media hashes and inspect the local replay before deleting any pod storage. Prefer exporting on the pod before copying: exported assets use portable relative paths, while raw execution logs may retain pod-absolute references.

Preserve `.runtime/budget.sqlite` across command invocations: resetting it would reset local reservations. API charges are tracked automatically. Use the verified compute-dispatch guard when available and retain an operator shutdown deadline; a local guard cannot guarantee remote billing stops after a machine or network failure. Reconcile actual provider costs against the cap. After copied artifacts are verified, terminate the pod and remove its disposable storage so storage billing does not continue.

## Verified CPU preparation entrypoint

```sh
bash containers/check_dependencies.sh
```

For the exact pinned image recipe and build command, see [containers/README.md](../containers/README.md). The dependency resolver passed locally; no Docker image was built here. On an amd64 Docker host the recipe installs the isolated environments before GPU allocation. The current machine has no Docker runtime.

The actual three-role SDK connection was checked with explicitly synthetic images. Local regression suite: 67 passed. Aura and real CUDA/EGL/inference gates remain open.
