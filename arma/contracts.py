from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

TASK_NAME = "pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate"
GOAL = "pick up the black bowl from table center and place it on the plate"
STAGES = {
    "approach": ("approach the black bowl", "target_reached"),
    "grasp": ("grasp and lift the black bowl", "target_lifted"),
    "transport": ("move the black bowl toward the plate", "target_above_plate"),
    "place": ("place the black bowl on the plate and release it", "target_released"),
}
SKILL = {"skill_id": "pick_place_v1", "version": "1", "provenance": "authored_procedure", "goal": GOAL,
         "stages": [{"stage": s, "subtask_goal": v[0], "criterion_id": v[1]} for s,v in STAGES.items()]}

class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt_id: str
    decision_index: int = Field(ge=0)
    based_on_step: int = Field(ge=0)
    observation_id: str

class PlannerDecision(Envelope):
    stage: Literal["approach", "grasp", "transport", "place"]
    subtask_goal: str
    criterion_id: str
    skill_id: Literal["pick_place_v1"] = "pick_place_v1"
    skill_version: Literal["1"] = "1"
    decision: Literal["continue", "set_subtask", "stop"]
    reason: str

class CandidateChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_decision_id: str
    adopted: bool
    reason: str

class RetrievalDecision(Envelope):
    decision: Literal["keep", "adapt", "request_replan"]
    executed_instruction: str = Field(min_length=1, max_length=500)
    source_decision_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    candidates: list[CandidateChoice] = Field(default_factory=list)
    reason: str

class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["target_reached", "target_lifted", "target_above_plate", "target_released"]
    value: Literal["true", "false", "unknown"]
    evidence_ids: list[str]

class EvaluationRecord(Envelope):
    task_outcome: Literal["success", "failure", "unknown"] | None
    subtask_outcome: Literal["running", "success", "failure", "unknown"]
    task_judgment_source: Literal["simulator_task_predicate"] = "simulator_task_predicate"
    subtask_judgment_source: Literal["vlm_inference", "unavailable"] = "vlm_inference"
    task_evidence_refs: list[str]
    subtask_evidence_refs: list[str]
    observed_facts: list[str]
    cause_hypothesis: str | None = None
    contexts: list[Condition] = Field(default_factory=list)
    evaluation_degraded: bool = False

def validate_envelope(value: Envelope, context: dict):
    for key in ("attempt_id", "decision_index", "based_on_step", "observation_id"):
        if getattr(value, key) != context[key]:
            raise ValueError(f"Stale or mismatched agent {key}")

def validate_evaluation(value: EvaluationRecord, context: dict, outcome, evidence_ids: set[str]):
    validate_envelope(value,context)
    if value.task_outcome!=outcome:
        raise ValueError(f'Evaluator task_outcome must equal expected_task_outcome {outcome!r}')
    if not set(value.task_evidence_refs+value.subtask_evidence_refs)<=evidence_ids:
        raise ValueError('Evaluation evidence must reference only attached before/after frames')
    if any(not set(c.evidence_ids)<=evidence_ids for c in value.contexts):
        raise ValueError('Condition evidence must reference only attached before/after frames')
    if any(c.value!='unknown' and not c.evidence_ids for c in value.contexts):
        raise ValueError('Known conditions require visible evidence')
    if len({c.kind for c in value.contexts})!=len(value.contexts):
        raise ValueError('Duplicate condition kinds')
    return value

def validate_planner(value: PlannerDecision, context: dict):
    validate_envelope(value,context)
    if (value.subtask_goal,value.criterion_id)!=STAGES[value.stage]:
        raise ValueError('subtask_goal and criterion_id must exactly match the registered stage')
    if value.decision=='stop':
        raise ValueError('Select or continue a subtask; only the environment task predicate can stop execution')
    return value

def validate_retrieval(value: RetrievalDecision, context: dict, candidates: list[dict]):
    validate_envelope(value,context)
    allowed_ids={c['source_decision_id'] for c in candidates}
    allowed_evidence={e for c in candidates for e in c.get('evidence_ids',[])}
    if not set(value.source_decision_ids)<=allowed_ids or not set(value.evidence_ids)<=allowed_evidence:
        raise ValueError('Retrieval citations must use only allowed historical source/evidence IDs; current observation evidence is not historical memory')
    if any(c.source_decision_id not in allowed_ids for c in value.candidates):
        raise ValueError('Candidate choices must reference supplied historical candidates')
    if {c.source_decision_id for c in value.candidates if c.adopted}!=set(value.source_decision_ids):
        raise ValueError('Adopted candidates must match cited sources')
    goal=context.get('original_goal',GOAL)
    if value.decision=='keep' and value.executed_instruction!=goal:
        raise ValueError('decision=keep requires executed_instruction exactly equal original_goal; no appended stage cue')
    if value.decision=='adapt':
        if not value.source_decision_ids or not value.evidence_ids:
            raise ValueError('Adaptation requires actual supporting historical source and evidence')
        adopted=[c for c in candidates if c['source_decision_id'] in value.source_decision_ids]
        adopted_evidence={e for c in adopted for e in c.get('evidence_ids',[])}
        if not set(value.evidence_ids)<=adopted_evidence:
            raise ValueError('Adapted evidence must belong to adopted sources')
        if any(not set(c.get('evidence_ids',[]))&set(value.evidence_ids) for c in adopted):
            raise ValueError('Each adopted source requires supporting evidence')
    if value.decision!='request_replan' and not value.executed_instruction.startswith(goal):
        raise ValueError('Original goal was changed')
    return value

def expected_outcome(result: dict, action_limit: int = 220):
    if result["task_success"]:
        return "success", "goal_satisfied"
    if result.get("termination_reason") in ("environment_error", "execution_unknown"):
        return "unknown", result["termination_reason"]
    if result["end_step_index"] >= action_limit:
        return "failure", "step_budget_exhausted"
    return None, None
