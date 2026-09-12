# First paired video: frozen policy versus agents plus memory

This recording compares **frozen OpenVLA with its original instruction** against **the three-agent system with memory**, from the exact same initial state. It is distinct from the no-memory-agent versus memory-agent ablation: a difference here cannot isolate memory retrieval from agent orchestration. Actual outcomes determine the story; do not fabricate a failure, hide a failed memory run, or claim generalized improvement from one pair.

## Inputs and validation

Wait for both real episodes to finish and export portable `bundle.json` files with their media assets. `scripts/render_first_demo.py` validates the same task, immutable goal, robot, policy ID, seed, initialization index, initial RGB hash, and 20 Hz simulator frame rate. It requires completed `baseline` and `agents_memory` attempts and a named memory snapshot. Frame/action indices must be contiguous. An absent pair, changed initialization, or missing media is an error, not permission to substitute another run.

The movie uses the exact recorded RGB observations (initial frame plus one frame per action), synchronized by simulator action index. It does not interpolate motion or include Gemini waiting time. The shorter side visibly holds its final frame after it finishes. Outcome labels change only when that side reaches its recorded terminal step. After both runs finish, their actual final frames remain on screen for three additional seconds, labeled `FINAL FRAME HELD`; the displayed simulator clock remains at the last actual action. Use `--final-hold-seconds` to change this presentation duration.

Overlays show the original goal, each actual instruction sent to OpenVLA, action counts, final outcome, and memory source/citation counts and source IDs. The accompanying JSON preserves full candidate adoption/rejection reasons, cited step/evidence IDs, and any matching source nodes included in the export. Empty retrieval is labeled as empty; it is not presented as successful memory use.

At the first selected adaptation, playback pauses for two explicit reading cards: six seconds for the recorded planner output and candidate choices, then eight seconds for cited evidence and explanation. These presentation durations are not measured agent latency. The evidence card shows a cited historical frame beside the current RGB and separates three recorded Retrieval Agent fields: `memory_summary`, `current_comparison`, and `adaptation_reason`. Each structured item retains its text, historical source/evidence IDs, current evidence IDs, and agent-provided grounding label (`visible`, `recorded`, or `uncertain`) in the sidecar. These labels do not independently verify the interpretation. The full actual OpenVLA instruction and raw added cue are displayed separately.

The card selects the earliest recorded ADAPT interval with a cited source, otherwise the earliest cited interval, otherwise the first interval. It uses only a cited frame belonging to a cited historical step. Missing historical media is explicitly unavailable. Legacy bundles show only their recorded rationale; the renderer does not invent structured explanations. Long explanatory text is visibly marked as an excerpt, while the exact VLA instruction is never truncated. The card is labeled as static explanation outside the robot timeline. Use `--memory-intro-seconds 0` to omit it, or another duration to adjust reading time; this duration is recorded separately from simulator playback and the final hold.

Explanatory fields can cite different sources, including rejected candidates. Each field shows source aliases and the agent's grounding labels. The displayed historical image identifies its own source alias; the footer explicitly limits it to that source. The sidecar maps every alias to the full source ID and retains item-level evidence references. A displayed frame must not be presented as proof of claims citing another source.

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
- `-memory-story.png`: the static cited-evidence and explanation card.
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

The selected memory attempt must appear exactly once in `agent-progress.json`'s evaluation list. `evaluation-results.json` retains **every evaluation row in original order**, including unsuccessful trials, trials that kept the existing instruction, and unknown outcomes. It also records the explicitly selected trial ID, the original baseline scan, optional `moving-baseline-scan.json`, collection rows, and a hash of the progress file. Both baseline scans have separate Markdown tables. Where the saved attempt record exists, the exporter checks its outcome/action fields against the progress row and adds actual retrieval-decision counts, a keep-only flag, instruction-change counts, prompt hashes, wall time, and API cost. An unavailable attempt record remains listed and explicitly marked unavailable.

`memory-and-prompts.md` presents every evaluation row in a table before the selected instruction timeline. The same full summary is embedded in `memory-selected/bundle.json`; this bundle keeps only the selected memory video as its rendering input. The selection note identifies it as an **exploratory selected case** and a **frozen-policy versus full-agent-system comparison**, not an isolated retrieval ablation. Keep-only describes recorded retrieval decisions; it does not mean the planner or evaluator was disabled. Different prompt versions or planning behavior must not be described as a controlled measurement of memory alone.

Do not remove unsuccessful rows when selecting a more illustrative movie. The chosen movie and a separately recorded successful memory trial do not establish an overall success-rate improvement.

The replay inspector also separates the exact policy input from the agent's memory explanation and shows historical/current evidence thumbnails. Agent-selected stages and agent subtask judgments are labeled as such. Raw evaluator observations remain retained but are not presented as independently verified facts.

Physical footage highlights `VLA EXECUTE` in the displayed process; it does not pretend the LLM is running while the simulator steps. Agent-selected stage, criterion, decision index and action count are shown from their records. `--decision-card-seconds` adjusts the planner/candidate reading card. `--agent-trace path/to/trace.json` optionally attaches the audited role outputs and prompt provenance for the exact chosen memory attempt; a mismatched attempt is rejected. Existing trials did not save exact supplied candidate request JSON, so the viewer and cards distinguish stored source records and model-reported candidate choices from that unavailable payload. Explanation-validation degradation is shown explicitly; missing rich explanations are never synthesized.

Prompt provenance is resolved by content hash, not a hard-coded folder version. The exporter records each attempt's manifest prompt hashes, retrieval-input version, and matching files under `prompt-snapshot*/` (including `prompt-snapshot-v3/` where present). Different backend/prompt versions remain separate exploratory trials. If a bounded search finds no moving baseline failure, report that result and retain the original state-11 case rather than manufacture a new failure.

## Current preparation boundary

The local renderer environment contains Pillow 10.4.0 and imageio-ffmpeg 0.6.0; its bundled macOS arm64 FFmpeg identifies itself as version 7.1. The first real baseline already exists, but rendering the actual pair must wait for the root agent's matching agents-with-memory episode. A prepared script alone is not a completed paired video.

## Same-state calibrated recall protocol

For the separate protocol `configs/same_state_recall_v1.json`, use `--comparison-scope same_state_calibrated_recall`. The video title and sidecar explicitly identify same-state experience recall; the footer says the memory was calibrated on this state and this is not held-out generalization. This remains a full-system comparison, not an isolated retrieval ablation. Keep the original task goal immutable. A recorded full instruction rewording is shown verbatim and labeled as a full instruction variant; this label does not certify semantic equivalence.

The state-19 baseline is `artifacts/first-demo/baseline-moving-selected/bundle.json`, attempt `83cdfc31a1354b80adf58289fbe5b617` (environment failure after 220 actions). `artifacts/instruction-calibration-v2/put_middle/attempt.json`, attempt `probe-64fef87b772f4c2f9d0576bb5990137c`, is a **direct instruction calibration probe**, not an agent memory recall trial. Its recorded instruction is `put the black bowl in the middle of the table on the plate`; the environment recorded success at action 120. Do not pass this probe off as an `agents_memory` recording. The separate recall experiment lives under `artifacts/same-state-recall-v1`; wait for its actual completed episode, retrieved sources, snapshot membership and policy instruction before exporting or pairing it.

`artifacts/instruction-calibration-v2/video-readiness-audit.json` records full decoding of the baseline (221 frames) and calibration (121 frames), both at 20 fps and 256×256, plus exact video hashes and paths. Task, goal, robot, policy, seed, initial state, checkpoint revision, perception mode, environment seed and initial RGB hash match. These checks establish matched recordings; they do not establish memory benefit. No new comparison video was generated from this readiness check.
