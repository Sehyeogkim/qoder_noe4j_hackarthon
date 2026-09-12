# Implementation and validation log

## 2026-09-12 — implementation session and revised demo scope

Implementation tool: **Codex**. Intended handoff: **Qoder**. These records do not claim that Qoder has executed or authored this implementation.

This is the chronological engineering log; start with the concise [validation summary](validation.md). The accepted design is [experiment-design.md](experiment-design.md), superseded plans are under [archive/plans](archive/plans/), and the original prototype is under [archive/prototypes](archive/prototypes/). No real robot success or memory improvement is claimed by the presence of code or documentation.

### Implemented components

- Typed agent contracts and distinct Subtask, Retrieval and Evaluation/Writer roles; immutable original goal and separate task/subtask criteria.
- Deterministic runner, ten-action intervals, fresh-observation worker contract, idempotent execution IDs, evidence validation and transactional memory interface.
- Frozen OpenVLA/LIBERO adapter and isolated worker setup script; actual CUDA and baseline inference subsequently passed on the user-provided pod, as recorded below.
- Neo4j constraints, writes, filtered retrieval, retry traversal, snapshot interfaces and an in-memory test repository; live Aura validation subsequently passed, as recorded below.
- Persistent API reservation ledger, CLI smoke/run/collect/compare/export commands, manifest and artifact recording.
- Portable replay inspector with visible provenance, all-attempt results, paired videos, decisions, graph selection and evidence links.

### Checks performed

| Check | Observed result | What it establishes |
| --- | --- | --- |
| Local automated regression suite | 40 tests passed at the earlier integration checkpoint; latest changes pending rerun | Tested local contracts and fixtures; later test totals may grow |
| Gemini image + structured Planner response | Passed with synthetic smoke image; recorded API cost $0.0010995 at that checkpoint | Real API/model access and structured image request handling |
| Portable replay exporter tests | 11 passed, included in local verification | Asset copying, escaping, path validation and portability |
| Replay JavaScript syntax | Passed `node --check` | JavaScript parses |
| Browser empty-state check | Passed | No invented execution metrics are prefilled |
| Browser synthetic replay and node selection | Passed | Inspector renders paired records and selected graph properties; explicitly synthetic |

The Gemini check was not an actual robot observation. Synthetic execution uses a fake policy/environment and cannot establish OpenVLA task performance. Cost is a recorded checkpoint amount, not a guarantee of the final bill.

### Remaining gates

| Stage | Current validation status |
| --- | --- |
| Repository/contracts | Locally implemented and tested |
| Neo4j/skills | Live Aura Free connection, migrations, atomic/idempotent writes, graph export, synthetic snapshot rejection, and retrieval Cypher passed; see live audit below |
| Frozen policy baseline | Passed on user-provided pod `fyweenfgrv95mz`: actual OpenVLA/LIBERO success after 134 policy actions on state 4; earlier failed host and capacity block preserved below |
| Three-agent real interval | Gemini and live Aura components checked separately; real worker + agents + Aura end-to-end pending |
| Memory collection and held-out comparison | Not run; no real success-rate data or improvement claim |
| Portable real-run demo | Actual baseline replay copied and browser QA passed: playable baseline-only video, final interval/result, recorded graph evidence, and all media assets verified; no memory comparison claimed |

At that earlier checkpoint no GPU had been created, and the user authorized L40S 48 GB at $0.79/hour with dependency preparation before GPU execution. Aura credentials were not yet configured. Those historical blockers were subsequently revisited in the live checkpoints below. The $10 cap remains in force; compute/storage usage and shutdown must be controlled during the eventual paid session.

The initial real demo is now five required episodes: baseline smoke on state4, memory collection on states0/1, and a held-out state10 no-memory/memory pair. At most one actual retry is allowed if a collection attempt fails and budget remains. Nine-episode evaluation is deferred. The revised minimal-demo configuration is now included in the latest local verification below. No real comparison data exists yet.

Agent implementation is Python SDK orchestration: `arma/agents.py` loads role prompts from `prompts/`, validates `arma/contracts.py` response types, and is called by `arma/runtime.py`. Prompt files alone do not instantiate autonomous agents. See the directory diagram in [README](../README.md).

Future entries should record exact commits/revisions, commands, test results, actual costs and artifact locations. Keep execution, static checks, synthetic fixtures and real experiments explicitly distinct.

## Earlier local verification checkpoint

- Full regression suite: **67 passed**; worker/setup scripts also pass shell syntax checks.
- `bash containers/check_dependencies.sh`: Linux x86_64/Python 3.10 dependency resolution passed without GPU or installation.
- `containers/Dockerfile` prepares isolated worker/backend environments without checkpoint download or inference. Actual Docker build is unverified because Docker is absent locally.
- Actual Gemini Subtask, Retrieval, and Evaluator calls completed with synthetic worker images. Evaluator schema repair was exercised and succeeded; authoritative synthetic task status was preserved. This is not a real robot experiment.
- API ledger total at this checkpoint: **$0.018499**. Compute charges from this work: **$0**.
- L40S Community Cloud $0.79/hour unavailable; Secure Cloud $1.09/hour listed with stock. Higher-rate choice remains pending; no new pod was created.
- Aura URI/username/password are still absent. Live Neo4j and actual GPU recordings remain pending.
- Requested Notion plan page updated with the revised implementation contract and explicit validation boundaries.

## Live L40S execution started

On 2026-09-12T21:21:30Z, created this task's pod `3vogqdvw83hytw`, `arma-astras-l40s-b39957a4`, Community Cloud NVIDIA L40S at $0.79/hour. Direct SSH confirmed NVIDIA L40S and 46068 MiB VRAM. Existing unrelated stopped pods were untouched. A persistent local watchdog tracks the attributed pod and compute/storage budget. Runtime installation is in progress in the official CUDA12.1/PyTorch2.2.0 base container; no custom image build is claimed.


## Live Aura Free verification — 2026-09-12T21:26:55Z

The existing **ARMA-Memory** instance (`acc8693d`) was confirmed as running **AuraDB Free** with no initial nodes or relationships. Its downloaded credential file was parsed into the local `.env`; credential values were not printed. No password was changed, no duplicate instance was created, and the unrelated Professional trial instance was untouched.

The actual Neo4j Python driver verified connectivity and ran repository migrations. A uniquely identified **synthetic** contract fixture exercised these operations:

- Attempt creation followed by one atomic decision/action/progress transaction.
- Exact duplicate commit retry, confirming no additional execution record.
- Committed outcome read and graph export: nine entity nodes and eight relationships.
- Rejection of the synthetic Attempt from a frozen real-experience snapshot.
- Execution of the real historical retrieval and bounded three-hop retry Cypher against the filtered corpus, confirming server-side syntax and runtime compatibility.

All checks passed. Only the fixture's exact node IDs were deleted afterward; the database returned to **zero nodes** and retained **ten uniqueness constraints** and the eligibility index. First-use warnings about previously absent property/relationship tokens were informational, not query failures.

Evidence: [neo4j-smoke.json](../artifacts/neo4j-smoke.json). This validates database behavior, not robot performance or successful retrieval from a real experience corpus. No synthetic fixture was labelled `real_execution`.

## L40S hardware failure and verified deletion — 2026-09-12T21:36:54Z

The L40S pod `3vogqdvw83hytw` exposed its GPU to `nvidia-smi`, but failed the required runtime smoke check: CUDA driver `cuInit` returned **999**, `torch.cuda.is_available()` was false, and a GPU tensor could not be created. The container had PyTorch `2.2.0+cu121`; the host reported driver `550.163.01`. Device visibility and explicit CUDA library checks did not resolve initialization. Host drivers were not modified.

No model action was executed, and no complete checkpoint download or VLA inference occurred on this pod. Worker dependency installation was interrupted. The separate backend setup was stopped while waiting for `uv`; backend installation had not started. Slow download probes were also recorded, but CUDA initialization failure was sufficient to reject the host.

The owned pod was deleted. RunPod's exact-pod GET returned **404**, verified at `2026-09-12T21:36:54.878035+00:00`. Unrelated resources were preserved. Evidence: [failure audit](../artifacts/pod-failure-3vogqdvw83hytw.json) and the local attributed-pod deletion proof under `.runtime/owned-pod.json.deletion-proof.json`. Budget reservations and measured charges are tracked separately; an outstanding reservation must not be presented as actual spend.

The user has now authorized an **A40 replacement** within the remaining project budget. The subsequent replacement creation attempt was capacity-blocked, as recorded below; no replacement readiness or inference result is claimed here. Backend requirements were independently checked against PyPI metadata: all forty pinned packages have compatible Linux CPython 3.11 wheels, totaling **19.50 MiB** excluding Python, `uv`, and editable-build tooling.

The latest targeted CLI and memory regression run passed **15 tests**, including baseline independence from Gemini credentials, unknown-result nonzero exit, and idempotent outbox recovery without calling the robot or an LLM. This targeted run supplements the earlier full-suite checkpoint; it is not a new full-suite count.

**Evidence boundary at that earlier checkpoint:** live Gemini requests and live Aura transactions had been verified separately. No actual OpenVLA action or LIBERO episode had run yet. The subsequent verified baseline is recorded below; memory collection/comparison remain separate gates.


## A40 replacement capacity blocker — 2026-09-12

After explicit user authorization, the root agent attempted the eligible **NVIDIA A40 48 GB** replacement in **CA-MTL-1** at the **$0.49/hour** ceiling. The create request returned **HTTP 400: no available instances**. A fresh catalog still reported global availability `NONE`; the regional `LOW` entry had not translated into an allocatable pod. No replacement pod was created.

`PLAN.md`, `README.md`, and `configs/demo.yaml` now select A40/$0.49 rather than the previously authorized L40S/$0.79. Historical L40S allocation, failure, and deletion evidence remain intact. The **$10 total cap**, five required real episodes, and at most one budget-permitted actual retry are unchanged. No GPU substitution, higher-rate deployment, or real VLA inference is implied by this configuration update.


## User-provided GPU baseline verified — 2026-09-12T21:56:21Z

The user supplied a different running pod, **`fyweenfgrv95mz`**, reached at `root@195.26.232.162` on SSH port `34074`. It reports **NVIDIA L40S, 46068 MiB VRAM**, with host driver `570.195.03`. CUDA and BF16 passed on this host. No lifecycle operation or external database configuration was performed as part of this GPU-only setup; the user is handling Neo4j in a separate session.

The isolated backend environment uses Python **3.11.13**. Its **41 packages** pass `uv pip check`; imports and source compilation pass. Actual resolved requirements and their verified hash are preserved in [backend-resolved-requirements.txt](../artifacts/gpu-runtime/backend-resolved-requirements.txt) and [backend-readiness.json](../artifacts/gpu-runtime/backend-readiness.json). Backend verification did not read `.env`, contact a database, or invoke a model.

The worker environment subsequently passed dependencies, EGL rendering, and frozen checkpoint loading. Base-image nginx already occupied port 8001 and was left untouched. ARMA serves only **`127.0.0.1:18001`** through `python -m worker.serve`, which loads one model before serving HTTP. The health response after the baseline reported `ready=true`, `model_loaded=true`, `model_training=false`, and `trainable_parameter_count=0`. Its environment session was closed after the episode; `session_ready=false` and a noninitialized renderer at that point do not mean the policy was unloaded.

### Actual baseline result

| Field | Recorded value |
| --- | --- |
| Attempt ID | `7322c85983954b37a9a1bee1113371df` |
| Task | Pick up the black bowl from table center and place it on the plate |
| Initialization state | `4` |
| Provenance | `real_execution` — actual OpenVLA actions in LIBERO simulation |
| Outcome | `success` |
| Judgment | `simulator_task_predicate` |
| Termination | `goal_satisfied` |
| Policy actions / intervals | `134 / 14` |
| Runner elapsed time | `36.57284161262214` seconds |
| Agent API calls | `0` |
| External database used | `false` |

The root agent ran `scripts/run_gpu_baseline.py`, which explicitly uses `BaselineAgents` and `InMemoryRepository`. It does not load `.env` or contact Gemini/Neo4j, so concurrent credential changes in the user's other session cannot redirect this baseline into a database. The script exported replay media and records under `/workspace/arma/artifacts/gpu-baseline/replay/`; the raw video is `worker/10c6d164-46e0-42de-8063-ca4c9c55278d/rollout.mp4` within the same artifact root.

The remote `baseline-summary.json`, Attempt record, and live read-only `/health` response were inspected to verify these values. The root agent subsequently completed local archive integrity and execution-record checks, as recorded in the following checkpoint. API cost zero for this baseline is not a claim of zero GPU cost.

This is a verified frozen-policy baseline in **simulation**, not a physical hardware robot trial, memory-enabled comparison, or claim of improved success rate. The three-agent system and historical retrieval have not yet been exercised together on these actual observations. Current connection and restart commands are in [gpu-pod-setup.md](gpu-pod-setup.md).


### Local baseline evidence and full regression checkpoint

The actual baseline archive was transferred locally and verified at **17,134,893 bytes** with SHA-256 `6775384cad1a68080d874083cddc9efc34fe0577ba17585b89479281e334012b`. The root's audit confirmed **134 unique action observations**, contiguous action indices, **14 intervals**, and **four actions in the final interval**, which stopped on environment-confirmed success. All recorded action vectors were finite and seven-dimensional. Hashes matched for **15 interval-boundary frames**. The before/after images were visually inspected.

Evidence: [local-verification.json](../artifacts/gpu-baseline/local-verification.json), [baseline-summary.json](../artifacts/gpu-baseline/baseline-summary.json), and the copied [replay](../artifacts/gpu-baseline/replay/index.html). The latest full local regression run passed **76 tests**. Baseline-only replay presentation and final browser QA passed. The video decoded at 256×256 and played all 6.75 seconds; the final interval shows actions 130–134 and task success. All 136 media assets match their content hashes, all graph endpoints resolve, and the final frame opens from its evidence node. See [QA record](../artifacts/gpu-runtime/baseline-replay-qa.json), [baseline screenshot](../artifacts/gpu-runtime/baseline-replay-qa.png), and [graph evidence screenshot](../artifacts/gpu-runtime/baseline-graph-evidence-qa.png). No memory comparison or database integration is inferred from these validated local artifacts.
