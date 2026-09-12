import math
import sqlite3
import pytest
from fastapi.testclient import TestClient
from worker.app import create_app
from worker.engine import Engine, WorkerError
from worker.protocol import ExecutionRequest, ResetRequest
from worker.robots import FakeRobot


def ready(tmp_path, success_at=3, fail_at=None, budget=220):
    robot=FakeRobot(success_at=success_at,fail_at=fail_at)
    engine=Engine(robot,tmp_path,action_budget=budget)
    reset=engine.reset(ResetRequest(attempt_id='attempt-1',init_state_id=4))
    request=ExecutionRequest(attempt_id='attempt-1',execution_id='exec-1',expected_step_index=0,
        observation_id=reset['observation']['observation_id'],executed_instruction='pick up the black bowl and place it on the plate',max_actions=min(10,budget))
    return robot,engine,reset,request


def test_success_stops_on_third_fresh_action(tmp_path):
    robot,engine,reset,req=ready(tmp_path)
    result=engine.execute(reset['session_id'],req)
    assert result.end_step_index==3
    assert result.task_success and result.termination_reason=='task_success'
    assert robot.prediction_frames==[0,1,2]
    assert len({e.resulting_observation_id for e in result.actions})==3
    assert reset['manifest']['provenance']=='synthetic_fixture'


def test_duplicate_execution_survives_process_restart(tmp_path):
    robot,engine,reset,req=ready(tmp_path)
    first=engine.execute(reset['session_id'],req)
    assert engine.execute(reset['session_id'],req)==first
    assert robot.step_count==3
    restarted=Engine(FakeRobot(),tmp_path)
    assert restarted.execute(reset['session_id'],req)==first
    assert restarted.status(reset['session_id'],req.execution_id)['status']=='completed'
    with pytest.raises(WorkerError,match='conflict'):
        restarted.execute(reset['session_id'],req.model_copy(update={'executed_instruction':'changed'}))


def test_stale_rejected_without_action(tmp_path):
    robot,engine,reset,req=ready(tmp_path)
    with pytest.raises(WorkerError,match='stale'):
        engine.execute(reset['session_id'],req.model_copy(update={'observation_id':'old'}))
    assert robot.step_count==0


def test_false_predicate_is_running_until_budget(tmp_path):
    robot,engine,reset,req=ready(tmp_path,success_at=None,budget=13)
    a=engine.execute(reset['session_id'],req)
    assert a.termination_reason=='interval_complete' and not a.task_success
    b=engine.execute(reset['session_id'],req.model_copy(update={'execution_id':'exec-2','expected_step_index':10,
        'observation_id':a.observation_after_id,'max_actions':3}))
    assert b.termination_reason=='action_budget_exhausted' and b.end_step_index==13


def test_unknown_cannot_reexecute(tmp_path):
    robot,engine,reset,req=ready(tmp_path,fail_at=2)
    with pytest.raises(WorkerError,match='uncertain'):
        engine.execute(reset['session_id'],req)
    assert engine.status(reset['session_id'],req.execution_id)['status']=='unknown'
    with pytest.raises(WorkerError,match='unresolved'):
        engine.execute(reset['session_id'],req)
    with pytest.raises(WorkerError,match='unknown'):
        engine.execute(reset['session_id'],req.model_copy(update={'execution_id':'other'}))
    assert robot.step_count==2


def test_restart_turns_running_intent_unknown(tmp_path):
    robot,engine,reset,req=ready(tmp_path)
    engine.db.execute('INSERT INTO executions VALUES (?,?,?,?,NULL,NULL)',(req.execution_id,reset['session_id'],engine._digest(req),'running'))
    engine.db.commit()
    restarted=Engine(FakeRobot(),tmp_path)
    assert restarted.status(reset['session_id'],req.execution_id)['status']=='unknown'
    with pytest.raises(WorkerError,match='unresolved'):
        restarted.execute(reset['session_id'],req)


def test_nonfinite_action_never_reaches_environment(tmp_path):
    robot,engine,reset,req=ready(tmp_path)
    robot.predict=lambda _: ([math.nan]*7,[0]*7)
    with pytest.raises(WorkerError,match='uncertain'):
        engine.execute(reset['session_id'],req)
    assert robot.step_count==0


def test_reset_is_idempotent_and_cannot_overwrite_live_session(tmp_path):
    robot,engine,reset,req=ready(tmp_path)
    assert engine.reset(ResetRequest(attempt_id='attempt-1',init_state_id=4))==reset
    with pytest.raises(WorkerError,match='close current'):
        engine.reset(ResetRequest(attempt_id='attempt-2',init_state_id=4))


def test_http_contract(tmp_path):
    engine=Engine(FakeRobot(),tmp_path)
    with TestClient(create_app(engine)) as client:
        assert client.get('/health').json()['provenance']=='synthetic_fixture'
        bad=client.post('/sessions/reset',json={'attempt_id':'a','init_state_id':0,'task_name':'unknown'})
        assert bad.status_code==422
        reset=client.post('/sessions/reset',json={'attempt_id':'a','init_state_id':0}).json()
        sid=reset['session_id']
        body={'attempt_id':'a','execution_id':'e','expected_step_index':0,'observation_id':reset['observation']['observation_id'],'executed_instruction':'goal','max_actions':10}
        result=client.post(f'/sessions/{sid}/execute',json=body)
        assert result.status_code==200 and result.json()['end_step_index']==3
        assert client.get(f'/sessions/{sid}/executions/e').json()['status']=='completed'
        assert client.post(f'/sessions/{sid}/close').json()['closed']


def test_policy_identity_ignores_init_and_seed_but_tracks_weights():
    from worker.robots import stable_policy_id, OPENVLA_SHA, LIBERO_SHA
    base={'checkpoint':'fixed-policy','hf_revision':'revision-a','unnorm_key':'libero_spatial',
          'openvla_commit':OPENVLA_SHA,'libero_commit':LIBERO_SHA,'init_state_id':0,'seed':7}
    assert stable_policy_id(base)==stable_policy_id({**base,'init_state_id':12,'seed':42})
    assert stable_policy_id(base)!=stable_policy_id({**base,'hf_revision':'revision-b'})


def test_close_returns_exported_video_reference(tmp_path):
    robot,engine,reset,req=ready(tmp_path)
    robot.export_video=lambda path:path
    closed=engine.close(reset['session_id'])
    assert closed['video_ref'].endswith('/rollout.mp4')
    assert engine.session is None
