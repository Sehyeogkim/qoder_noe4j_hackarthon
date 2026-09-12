from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

TASK_NAME = 'pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate'
CHECKPOINT = 'openvla/openvla-7b-finetuned-libero-spatial'

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class ResetRequest(StrictModel):
    attempt_id: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9_-]+$')
    init_state_id: int = Field(ge=0)
    seed: int = 7
    task_name: Literal['pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate'] = TASK_NAME

class Observation(StrictModel):
    observation_id: str
    step_index: int
    rgb_ref: str
    evidence_id: str
    sha256: str
    task_success: bool

class ExecutionRequest(StrictModel):
    attempt_id: str
    execution_id: str = Field(min_length=1, max_length=160)
    expected_step_index: int = Field(ge=0)
    observation_id: str
    executed_instruction: str = Field(min_length=1, max_length=4000)
    max_actions: int = Field(ge=1, le=10)

class ActionEvent(StrictModel):
    step_index: int
    raw_policy_action: list[float] = Field(min_length=7, max_length=7)
    env_action: list[float] = Field(min_length=7, max_length=7)
    resulting_observation_id: str
    evidence_id: str
    rgb_ref: str

class ExecutionResult(StrictModel):
    execution_id: str
    start_step_index: int
    end_step_index: int
    observation_before_id: str
    observation_after_id: str
    observation_before: Observation
    observation_after: Observation
    actual_instruction: str
    actions: list[ActionEvent]
    task_success: bool
    termination_reason: Literal['interval_complete', 'task_success', 'action_budget_exhausted']
    artifact_refs: list[str]
    elapsed_ms: float
