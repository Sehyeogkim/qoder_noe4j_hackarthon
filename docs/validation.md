# Validation summary

This page separates recorded execution from hypotheses and presentation material. All dates are September 12, 2026.

## What ran

| Check | Result | Establishes |
| --- | --- | --- |
| Local regression suite | 164 tests passed | Contracts, memory operations, replay/export, recovery, and safety behavior |
| RunPod GPU runtime | NVIDIA L40S; CUDA BF16 and EGL rendering passed | The selected container can execute GPU tensors and render LIBERO observations |
| Frozen OpenVLA baseline | Success on LIBERO state 4 after 134 actions / 14 intervals | Real policy inference in simulation with frozen weights |
| Gemini agent roles | Planner, retrieval, and evaluator calls recorded | Real structured multimodal agent calls, not simulated responses |
| Neo4j Aura | Live migrations, transactions, retrieval, graph export, and reconciliation passed | External memory was stored and queried in the real database |
| Real memory corpus reconciliation | 2,600 nodes, 3,248 relationships, 6 Attempts, 109 decision turns, and 1,085 actions reconciled | The local export matched the corresponding Aura graph records |

## Recorded results

- The state-4 baseline succeeded without agent API calls or external memory.
- On state 19, the original instruction exhausted 220 actions while a directly calibrated instruction succeeded in 120 actions with the same initial state and frozen weights.
- Real agents-with-memory evaluation episodes ran, retrieved recorded sources, and changed policy instructions/actions. The recorded evaluation outcomes were failures or unknown, not successes.

## Claim boundary

The recordings demonstrate real OpenVLA execution, external-memory integration, and instruction sensitivity. They do **not** demonstrate general success-rate improvement, held-out generalization, or physical-robot performance. The successful state-19 instruction was calibrated directly and must not be presented as an agent-retrieved success.

Compact public evidence is in [`demo/`](../demo/). The full action-level archive remains local because it is approximately 428 MB.

