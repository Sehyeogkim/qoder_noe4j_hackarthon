import json
import pytest
from fastapi.testclient import TestClient
from arma.contracts import GOAL
from arma.robot import RobotClient
from worker.app import create_app
from worker.engine import Engine
from worker.robots import FakeRobot
from scripts.run_instruction_probe import run_probe,validate_schedule


def test_probe_retains_manual_instruction_and_preserves_fresh_rgb_and_early_success(tmp_path):
    fake=FakeRobot(success_at=23);engine=Engine(fake,tmp_path/'worker')
    client=RobotClient();client.client.close();client.client=TestClient(create_app(engine))
    schedule=[{'start_step':0,'instruction':GOAL},{'start_step':10,'instruction':GOAL+'. Lift the bowl before moving toward the plate.'}]
    result=run_probe(client,tmp_path/'probe',schedule,'fixture-v1',max_actions=30,allow_synthetic=True)
    assert result['outcome']=='success' and result['step_index']==23
    assert result['provenance']=='synthetic_fixture'
    assert result['condition']=='diagnostic_instruction_probe'
    assert result['origin']=='authored_skill_procedure' and result['dataset_split']=='memory_build'
    assert result['execution_provenance']=='synthetic_fixture'
    assert result['agent_api_calls']==0 and not result['memory_snapshot_written']
    assert fake.prediction_frames==list(range(23))
    assert result['decisions'][1]['execution']['actual_instruction']==schedule[1]['instruction']
    assert result['decisions'][2]['execution']['actual_instruction']==schedule[1]['instruction']
    assert len(result['decisions'][2]['execution']['actions'])==3
    assert engine.session is None


def test_probe_prevents_accidental_reexecution_in_existing_directory(tmp_path):
    with pytest.raises(FileExistsError):
        run_probe(None,tmp_path,[{'start_step':0,'instruction':GOAL}],'fixture')


@pytest.mark.parametrize('schedule',[[{'start_step':-1,'instruction':GOAL}],[{'start_step':0,'instruction':'changed goal'}],[{'start_step':0,'instruction':GOAL},{'start_step':0,'instruction':GOAL}]])
def test_probe_rejects_bad_schedule_before_actions(schedule):
    with pytest.raises(ValueError):validate_schedule(schedule,220)


def approved_paraphrases():
    from scripts.run_instruction_probe import APPROVED_TASK_PARAPHRASES
    from arma.contracts import TASK_NAME
    return {'version':'diagnostic-goal-paraphrases-v1','task_id':TASK_NAME,'task_goal':GOAL,
        'instructions':list(APPROVED_TASK_PARAPHRASES)}


def test_short_goal_paraphrases_require_explicit_diagnostic_approval():
    approval=approved_paraphrases()
    for instruction in approval['instructions']:
        schedule=[{'start_step':0,'instruction':instruction}]
        with pytest.raises(ValueError,match='explicitly approved'):validate_schedule(schedule,220)
        assert validate_schedule(schedule,220,approval)==schedule


@pytest.mark.parametrize('field,value',[('task_goal','move the red cup'),('task_id','other-task'),('instructions',['pick up the red bowl and place it on the stove']),('version','')])
def test_diagnostic_approval_cannot_change_goal_or_authorize_unregistered_text(field,value):
    from scripts.run_instruction_probe import validate_approval
    approval=approved_paraphrases();approval[field]=value
    with pytest.raises(ValueError):validate_approval(approval)


def test_agent_instruction_prefix_guard_unchanged_by_diagnostic_approval():
    from arma.contracts import RetrievalDecision,validate_retrieval_execution
    ctx={'attempt_id':'a','decision_index':1,'based_on_step':0,'observation_id':'obs','original_goal':GOAL}
    value=RetrievalDecision(**{k:ctx[k] for k in ('attempt_id','decision_index','based_on_step','observation_id')},
        decision='keep',executed_instruction=approved_paraphrases()['instructions'][0],reason='diagnostic only')
    with pytest.raises(ValueError):validate_retrieval_execution(value,ctx,[])
