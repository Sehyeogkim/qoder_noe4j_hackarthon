# First paired video: frozen policy versus agents plus memory

This recording compares **frozen OpenVLA with its original instruction** against **the three-agent system with memory**, from the exact same initial state. It is distinct from the no-memory-agent versus memory-agent ablation: a difference here cannot isolate memory retrieval from agent orchestration. Actual outcomes determine the story; do not fabricate a failure, hide a failed memory run, or claim generalized improvement from one pair.

## Inputs and validation

Wait for both real episodes to finish and export portable `bundle.json` files with their media assets. `scripts/render_first_demo.py` validates the same task, immutable goal, robot, policy ID, seed, initialization index, initial RGB hash, and 20 Hz simulator frame rate. It requires completed `baseline` and `agents_memory` attempts and a named memory snapshot. Frame/action indices must be contiguous. An absent pair, changed initialization, or missing media is an error, not permission to substitute another run.

The movie uses the exact recorded RGB observations (initial frame plus one frame per action), synchronized by simulator action index. It does not interpolate motion or include Gemini waiting time. The shorter side visibly holds its final frame after it finishes. Outcome labels change only when that side reaches its recorded terminal step. After both runs finish, their actual final frames remain on screen for three additional seconds, labeled `FINAL FRAME HELD`; the displayed simulator clock remains at the last actual action. Use `--final-hold-seconds` to change this presentation duration.

Overlays show the original goal, each actual instruction sent to OpenVLA, action counts, final outcome, and memory source/citation counts and source IDs. The accompanying JSON preserves full candidate adoption/rejection reasons, cited step/evidence IDs, and any matching source nodes included in the export. Empty retrieval is labeled as empty; it is not presented as successful memory use.

## Local rendering commands

The separate rendering environment is ignored by Git and does not change the robotics or backend environment:

```sh
uv venv --python 3.11 .runtime/demo-renderer
uv pip install --python .runtime/demo-renderer/bin/python Pillow==10.4.0 imageio-ffmpeg==0.6.0
.runtime/demo-renderer/bin/python scripts/render_first_demo.py \
  --baseline-bundle artifacts/<baseline-export>/bundle.json \
  --memory-bundle artifacts/<memory-export>/bundle.json \
  --output artifacts/first-demo/baseline-vs-agents-memory.mp4
```

Add `--baseline-attempt <id>` and/or `--memory-attempt <id>` when a bundle contains multiple runs of a condition. Add `--font /path/to/readable.ttf` when neither the default macOS Arial nor Linux DejaVu Sans font is installed. The renderer uses the package's bundled FFmpeg and does not call a paid model or the GPU worker.

Outputs:

- `.mp4`: 1920×1080 side-by-side recording, 20 fps, no audio.
- `.png`: final composite frame for inspection.
- `.json`: source bundle/video hashes, initial observation hash, exact outcomes, time basis, memory references and output hash. Recorded duration and final hold duration are separate. Each side includes its recorded `wall_elapsed_ms` and `agent_api_cost_usd`; API cost excludes GPU/storage, and missing values remain null. The agent system comprises the Subtask Agent, Memory Retrieval Agent, and Evaluation and Memory Writer Agent.

Verify playback and inspect overlays before sharing. Keep both source exports alongside the movie so every citation remains auditable. `--allow-synthetic` exists only for distinctly labeled renderer tests; never use its output as the actual project demo.

## Preserve the full exploratory evaluation history

Once a real memory trial is complete, export its recorded evidence and the complete evaluation history before rendering:

```sh
.venv/bin/python scripts/export_first_demo.py \
  --root artifacts/first-demo \
  --baseline-id <actual-baseline-attempt-id> \
  --memory-id <actual-selected-memory-attempt-id> \
  --selection-reason "Explain the actual exploratory selection and any revised prompts or planning behavior."
```

The selected memory attempt must appear exactly once in `agent-progress.json`'s evaluation list. `evaluation-results.json` retains **every evaluation row in original order**, including unsuccessful trials, trials that kept the existing instruction, and unknown outcomes. It also records the explicitly selected trial ID, the baseline scan, collection rows, and a hash of the progress file. Where the saved attempt record exists, the exporter checks its outcome/action fields against the progress row and adds actual retrieval-decision counts, a keep-only flag, instruction-change counts, prompt hashes, wall time, and API cost. An unavailable attempt record remains listed and explicitly marked unavailable.

`memory-and-prompts.md` presents every evaluation row in a table before the selected instruction timeline. The same full summary is embedded in `memory-selected/bundle.json`; this bundle keeps only the selected memory video as its rendering input. The selection note identifies it as an **exploratory selected case** and a **frozen-policy versus full-agent-system comparison**, not an isolated retrieval ablation. Keep-only describes recorded retrieval decisions; it does not mean the planner or evaluator was disabled. Different prompt versions or planning behavior must not be described as a controlled measurement of memory alone.

Do not remove unsuccessful rows when selecting a more illustrative movie. The chosen movie and a separately recorded successful memory trial do not establish an overall success-rate improvement.

## Current preparation boundary

The local renderer environment contains Pillow 10.4.0 and imageio-ffmpeg 0.6.0; its bundled macOS arm64 FFmpeg identifies itself as version 7.1. The first real baseline already exists, but rendering the actual pair must wait for the root agent's matching agents-with-memory episode. A prepared script alone is not a completed paired video.
