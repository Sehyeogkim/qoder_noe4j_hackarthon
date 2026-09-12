"""Synthetic schema fixtures only; no database or real model execution."""
import copy
import pytest
from arma.contracts import GOAL,TASK_NAME
from arma.memory import InMemoryRepository
from scripts.import_instruction_probe import normalize_probe,apply_import


def raw_probe(aid='probe-fixture',success=True):
    def obs(i):return {'observation_id':f'obs{i}','step_index':i,'rgb_ref':f'fixture-{i}.png',
        'evidence_id':f'frame{i}','sha256':str(i)*64,'task_success':bool(success and i==2)}
    windows=[]
    for i in (1,2):
        action={'step_index':i,'raw_policy_action':[0.]*7,'env_action':[0.]*7,
            'resulting_observation_id':f'obs{i}','evidence_id':f'frame{i}','rgb_ref':f'fixture-{i}.png'}
        windows.append({'decision_index':i,'execution':{'execution_id':f'{aid}:{i}',
            'start_step_index':i-1,'end_step_index':i,'observation_before_id':f'obs{i-1}',
            'observation_after_id':f'obs{i}','observation_before':obs(i-1),'observation_after':obs(i),
            'actual_instruction':GOAL,'actions':[action],'task_success':bool(success and i==2),
            'termination_reason':'task_success' if success and i==2 else 'interval_complete',
            'artifact_refs':[f'fixture-{i}.png'],'elapsed_ms':1.}})
    return {'attempt_id':aid,'status':'completed','outcome':'success' if success else 'failure',
        'provenance':'real_execution','execution_provenance':'real_execution','origin':'authored_skill_procedure',
        'condition':'diagnostic_instruction_probe','dataset_split':'memory_build','task_goal':GOAL,'task_id':TASK_NAME,
        'agent_api_calls':0,'external_database_used':False,'memory_snapshot_written':False,
        'manifest':{'policy_id':'fixture-policy'},'policy_id':'fixture-policy','robot_id':'fixture-robot',
        'perception_mode':'fixture-rgb','initial_context':obs(0),'manual_instruction_version':'fixture',
        'schedule':[{'start_step':0,'instruction':GOAL}],'action_budget':2,'step_index':2,
        'init_state_id':19,'seed':7,'success_criteria':{'id':'libero_task_predicate','version':'1'},
        'decisions':windows,'termination_reason':'goal_satisfied' if success else 'step_budget_exhausted'}


def test_authored_probe_import_is_idempotent_and_does_not_invent_agent_or_skill_records():
    raw=raw_probe();original=copy.deepcopy(raw);payload=normalize_probe(raw,'source-hash')
    repo=InMemoryRepository();result=apply_import(repo,payload)
    assert apply_import(repo,payload)==result and raw==original
    assert result['outcome']=='success' and result['origin']=='authored_skill_procedure'
    graph=repo.export_graph()
    assert not any(n['label']=='Skill' for n in graph['nodes'])
    for d in [n['properties'] for n in graph['nodes'] if n['label']=='DecisionStep']:
        assert 'planner' not in d and 'retrieval' not in d
        assert d['evaluation']['subtask_outcome']=='unknown'
        assert d['evaluation']['agent_invoked'] is False
    repo.freeze_snapshot('separate-fixture-calibration',['probe-fixture'])
    candidates=repo.search_experiences({'snapshot_id':'separate-fixture-calibration','task_id':TASK_NAME,
        'robot_id':'fixture-robot','policy_id':'fixture-policy','perception_mode':'fixture-rgb','stage':'approach','contexts':[]})
    assert candidates and all(c['instruction']==GOAL and c['stage'] is None for c in candidates)
    assert candidates[0]['before_evidence_id'] and candidates[0]['after_evidence_id']


def test_import_derives_retry_sequence_only_from_explicit_hashed_protocol():
    raw=raw_probe('second');protocol={'task_name':TASK_NAME,'init_state_id':19,'seed':7,
        'corpus':{'retry_sequence':['first','second']}}
    assert normalize_probe(raw,'source-hash')['start_attempt']['previous_attempt_id'] is None
    payload=normalize_probe(raw,'source-hash',protocol,'protocol-hash')
    assert payload['start_attempt']['previous_attempt_id']=='first'
    assert payload['start_attempt']['import_provenance']['protocol_sha256']=='protocol-hash'
    with pytest.raises(ValueError):normalize_probe(raw,'source-hash',protocol)


@pytest.mark.parametrize('field,value',[('dataset_split','evaluation'),('outcome','unknown'),('agent_api_calls',1)])
def test_import_rejects_relabeling_evaluation_unknown_or_agent_generated_probe(field,value):
    raw=raw_probe();raw[field]=value
    with pytest.raises(ValueError):normalize_probe(raw,'source-hash')


def test_import_rejects_false_success_or_changed_instruction():
    raw=raw_probe();raw['outcome']='failure'
    with pytest.raises(ValueError,match='environment'):normalize_probe(raw,'source-hash')
    raw=raw_probe();raw['decisions'][0]['execution']['actual_instruction']='invented instruction'
    with pytest.raises(ValueError,match='authored schedule'):normalize_probe(raw,'source-hash')
