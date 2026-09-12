# Frozen-policy instruction calibration

This diagnostic changes only text while using the existing frozen worker, the same task and initialization state19, seed7, the same preprocessing/action adapter, at most220 policy actions and intervals of at most10. The worker supplies a fresh RGB for every policy inference and checks task success after every action. There are no Gemini calls, Neo4j writes, hidden object poses, model changes or training. Before execution, real probes are declared with `provenance=real_execution`, `condition=diagnostic_instruction_probe`, `origin=authored_skill_procedure` and `dataset_split=memory_build`. This is a new, separate authored calibration corpus. These records must never be added to the original frozen evaluation snapshot. A later demonstration using the same state must be labeled same-state recall with authored procedure memory, not held-out improvement or autonomous agent discovery. Test fixtures retain synthetic provenance.

A schedule explicitly specifies when a manual instruction starts; it remains active until the next scheduled change. Each instruction must begin with the exact original goal and fit500 characters. An output directory must be new to prevent accidentally rerunning an old probe. HTTP timeouts use the existing execution-status recovery client, never a blind repeated action POST. Requests are saved before dispatch; execution logs, source manifest, outcome and video reference are retained.

```bash
python scripts/run_instruction_probe.py \
  --schedule /path/to/manual-schedule.json \
  --version manual-retained-procedure-v1 \
  --init-state 19 --max-actions 220 \
  --output artifacts/instruction-probes/new-unique-directory
```

The root experiment controller must choose the actual schedules and run them within the remaining compute budget. The script performs actions when invoked; creating or testing it does not run a real robot episode.

A minimal calibration sequence is:

1. Retain the existing state19 canonical baseline failure as the reference, including its exact policy identity and initial image hash.
2. Test one full-goal instruction with explicit grasp/lift sequencing retained throughout the episode. This tests whether a complete cue can change the outcome without the current agent loop reverting it to the canonical instruction on a later `keep` decision.
3. If warranted, test one alternate authored sequence. Keep state, policy, action budget and source artifacts fixed; report all trials, including failures.
4. A useful diagnostic instruction must be selected and executed through the actual retrieval-agent system in a separate episode before calling it a memory-enabled system success. Reusing state19 and its successful authored probe is explicitly a same-state recall demonstration in a new snapshot. Preserve the raw probe identity, zero agent calls and authored origin.

Manual candidates are hypotheses drawn from the authored `pick_place_v1` procedure. They are not claimed successful historical instructions: the actual source attempts0/1 succeeded with the canonical goal. Examples for the controller to consider, not auto-executed schedules:

- `pick up the black bowl from table center and place it on the plate. Close the gripper around the bowl and lift the bowl before moving toward the plate.`
- `pick up the black bowl from table center and place it on the plate. Secure the bowl in the gripper before lifting it. Carry the bowl above the plate, then lower and release it.`

Multiple sentences can also harm a policy accustomed to a short task label. Their effectiveness is an empirical result. Neither upward arm movement nor a closed gripper proves a successful grasp: inspect actual bowl motion and retain the environment predicate as the whole-task authority.

## Explicit diagnostic paraphrases

The production agent still requires the immutable original-goal prefix. Only the diagnostic probe script can opt into `--approved-instructions configs/probes/approved_goal_paraphrases_v1.json`. This approval names the same task and immutable goal, has an explicit version, and is restricted to a fixed registry of complete-task paraphrases. It cannot authorize arbitrary objects, destinations or instructions. The exact approval is recorded before execution. Supplied retained schedules are `state19_paraphrase_grasp_middle_v1.json`, `state19_paraphrase_put_middle_v1.json` and `state19_paraphrase_pick_center_v1.json`.

The pinned upstream evaluation and worker both use seed7, an environment seeded0, ten stabilization actions, 220 policy actions, the official image rotation/resize/center-crop and gripper conversion. The worker uses the pinned checkpoint's `libero_spatial` normalization with BF16 frozen parameters. Successful real source episodes0/1 demonstrate that the integration can complete this task. These checks do not prove the policy will succeed on state19 or that any paraphrase helps; no numerical action changes are proposed.
