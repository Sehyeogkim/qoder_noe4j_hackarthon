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

For the real worker and experiment workflow, see [Setup](docs/setup.md), [Experiment Plan](PLAN.md), and the [Implementation Log](docs/implementation-log.md).

## Current status

The local synthetic loop, Gemini role calls, Neo4j Aura transactions, and one real OpenVLA/LIBERO simulation baseline have been validated. The baseline completed state 4 after 134 policy actions. The full three-agent memory loop and controlled memory-vs-no-memory comparison are still pending, so no success-rate improvement is claimed yet.
