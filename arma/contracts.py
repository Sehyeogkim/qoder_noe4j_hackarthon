from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .task_instructions import TASK_NAME, GOAL, APPROVED_TASK_PARAPHRASES
INSTRUCTION_CONTROLLER_VERSION = "retain-verified-task-instruction-v3"
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

class GroundedExplanation(BaseModel):
    """Brief user-facing evidence justification, separate from robot commands."""
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1,max_length=600)
    source_decision_ids: list[str] = Field(default_factory=list,max_length=3)
    evidence_ids: list[str] = Field(default_factory=list,max_length=8)
    current_evidence_ids: list[str] = Field(default_factory=list,max_length=1)
    grounding: Literal["visible","recorded","uncertain"]

class RetrievalDecision(Envelope):
    decision: Literal["keep", "adapt", "request_replan"]
    executed_instruction: str = Field(min_length=1, max_length=500)
    source_decision_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    candidates: list[CandidateChoice] = Field(default_factory=list)
    reason: str
    explanation_degraded: bool = False
    explanation_errors: list[str] = Field(default_factory=list,max_length=8)
    memory_summary: list[GroundedExplanation] = Field(default_factory=list,max_length=3)
    current_comparison: list[GroundedExplanation] = Field(default_factory=list,max_length=3)
    adaptation_reason: list[GroundedExplanation] = Field(default_factory=list,max_length=3)

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

def validate_retrieval_execution(value: RetrievalDecision, context: dict, candidates: list[dict]):
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
    active=context.get('current_instruction') or goal
    if not isinstance(active,str) or (not active.startswith(goal) and active not in APPROVED_TASK_PARAPHRASES) or len(active)>500:
        raise ValueError('Committed current_instruction must preserve the original goal and fit the instruction limit')
    if value.decision=='keep' and value.executed_instruction!=active:
        raise ValueError('decision=keep requires executed_instruction exactly equal current_instruction (original_goal initially); do not reset or paraphrase it')
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
        if value.executed_instruction not in APPROVED_TASK_PARAPHRASES:
            raise ValueError('Original goal was changed; unregistered task paraphrase')
        if value.decision=='adapt':
            exact_sources=[c for c in candidates if c['source_decision_id'] in value.source_decision_ids
                and c.get('instruction')==value.executed_instruction
                and c.get('attempt_outcome',c.get('outcome'))=='success']
            if not exact_sources:
                raise ValueError('Registered task paraphrase requires exact reuse from an adopted successful historical instruction')
    return value


def validate_retrieval_explanation(value: RetrievalDecision, context: dict, candidates: list[dict]):
    if value.explanation_degraded:
        if any(getattr(value,f) for f in ('memory_summary','current_comparison','adaptation_reason')) or not value.explanation_errors:
            raise ValueError('Degraded explanation must be empty and include recorded errors')
        return value
    if value.explanation_errors:
        raise ValueError('Non-degraded explanation cannot carry fallback errors')
    allowed_ids={c['source_decision_id'] for c in candidates}
    allowed_evidence={e for c in candidates for e in c.get('evidence_ids',[])}
    # Historical rationale can discuss rejected candidates, but adoption rationale
    # must be grounded in the sources actually used to change the instruction.
    current_ids=set(context.get('allowed_current_evidence_ids',[]))
    visible_ids=context.get('visible_historical_evidence_ids')
    by_id={c['source_decision_id']:set(c.get('evidence_ids',[])) for c in candidates}
    for field in ('memory_summary','current_comparison','adaptation_reason'):
        for claim in getattr(value,field):
            sources=set(claim.source_decision_ids);historical=set(claim.evidence_ids)
            if not sources<=allowed_ids or not historical<=allowed_evidence:
                raise ValueError('Explanation cites unknown historical source or evidence')
            if bool(sources)!=bool(historical):
                raise ValueError('Historical explanation requires both source and evidence citations')
            if sources and (not historical<=set().union(*(by_id[s] for s in sources)) or
                            any(not by_id[s]&historical for s in sources)):
                raise ValueError('Explanation evidence must belong to each cited source')
            if current_ids and not set(claim.current_evidence_ids)<=current_ids:
                raise ValueError('Explanation cites an unseen current observation')
            if field=='memory_summary' and not historical:
                raise ValueError('Memory summary requires cited historical experience')
            if field=='current_comparison' and not claim.current_evidence_ids:
                raise ValueError('Current comparison requires current image evidence')
            if field=='adaptation_reason' and value.decision=='adapt':
                if not sources or not sources<=set(value.source_decision_ids) or not historical<=set(value.evidence_ids):
                    raise ValueError('Adaptation explanation must cite adopted sources and evidence')
            if not historical and not claim.current_evidence_ids:
                raise ValueError('Explanation requires historical or current evidence')
            if claim.grounding=='visible' and visible_ids is not None and not historical<=set(visible_ids):
                raise ValueError('Visible explanation cites a historical frame not attached to this call')
    if context.get('require_memory_explanations'):
        if not value.current_comparison or not value.adaptation_reason:
            raise ValueError('Provide a concise cited current comparison and instruction justification')
        if candidates and not value.memory_summary:
            raise ValueError('Summarize at least one supplied historical experience with citations')
    return value

def validate_retrieval(value: RetrievalDecision, context: dict, candidates: list[dict]):
    validate_retrieval_execution(value,context,candidates)
    return validate_retrieval_explanation(value,context,candidates)


def validate_model_retrieval(value: RetrievalDecision, context: dict, candidates: list[dict]):
    if value.explanation_degraded or value.explanation_errors:
        raise ValueError('The model cannot set explanation degradation markers; return a cited explanation')
    return validate_retrieval(value,context,candidates)


def degrade_retrieval_explanation(value: RetrievalDecision, context: dict, candidates: list[dict], errors):
    # Deterministic fallback only after a failed repair. Never fixes execution
    # identifiers, evidence, the instruction or a model-authored bypass marker.
    if value.explanation_degraded or value.explanation_errors:
        raise ValueError('Model-authored degradation marker is not authorized')
    validate_retrieval_execution(value,context,candidates)
    return value.model_copy(update={'memory_summary':[],'current_comparison':[],
        'adaptation_reason':[],'explanation_degraded':True,'explanation_errors':[str(e)[:600] for e in errors[:8]]})


def expected_outcome(result: dict, action_limit: int = 220):
    if result["task_success"]:
        return "success", "goal_satisfied"
    if result.get("termination_reason") in ("environment_error", "execution_unknown"):
        return "unknown", result["termination_reason"]
    if result["end_step_index"] >= action_limit:
        return "failure", "step_budget_exhausted"
    return None, None
