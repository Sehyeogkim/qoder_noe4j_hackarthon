# Recorded agent trace export

`export_agent_trace.py` is a local, standard-library-only exporter. It makes no model calls, connects to no database, and never changes an execution record.

```bash
python scripts/export_agent_trace.py \
  --attempt artifacts/first-demo/ATTEMPT_ID/attempt.json \
  --source-root artifacts/first-demo \
  --prompt-root artifacts/first-demo \
  --graph artifacts/memory-demo/graph.json \
  --output artifacts/agent-trace/trace.json
```

`--graph` is optional. It supplies historical DecisionStep records and the exported `evidence_assets` map, including portable image references. Without it, the exporter resolves referenced decisions from immediate `*/attempt.json` children beneath `--source-root`. Missing source records remain explicitly unavailable. `trace-data.js` is written beside `trace.json` as `window.ARMA_AGENT_TRACE` for a local viewer.

The `arma-agent-trace-v1` contract contains:

- `attempt`, `manifest`, `provenance`, and exact hash-matched `system_prompts`.
- `decisions[]`: committed `planner`, `retrieval`, `evaluator`, actual execution instruction/action range and actions, referenced historical records, and matched API call records.
- `unmapped_api_calls[]`: missing, invalid, stale, or uncommitted response envelopes retained without guessing a decision assignment.
- `evidence_assets`: Evidence node properties from an optional graph export.

API calls map to a decision only using a parseable response envelope with the correct Attempt ID and committed decision index. Rejected validation outputs remain unmapped; successful repairs retain their repair flag. An envelope match whose output differs from the committed record is labeled `envelope_match_only_output_differs`. This is not a claim that the output was accepted unchanged.

System prompt text is returned only when a file beneath a `prompt-snapshot*` directory exactly matches the recorded SHA-256. A missing matching snapshot yields no text; the current prompt is never substituted. The VLA formatted text is explicitly labeled an exact reconstruction from the pinned OpenVLA implementation and recorded instruction, not a captured inference request. Unknown policy adapters yield no reconstructed text.

The full Gemini request payload was not logged. `supplied_candidates` therefore remains `not_recorded`; `referenced_sources` exposes stored source records and model-reported references, not a purported exact candidate payload. `context_reconstruction` is separately labeled. Logged image order and hashes are preserved; missing image order is not invented. Image descriptions and subtask judgments remain VLM interpretations; only the environment whole-task predicate is authoritative.
