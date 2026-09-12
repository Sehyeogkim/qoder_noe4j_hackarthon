"""Contract fixtures are synthetic Python objects, never production seed memory."""
import copy
from concurrent.futures import ThreadPoolExecutor

import pytest

from arma.memory import InMemoryRepository, MemoryConflict, MemoryValidationError


def attempt(aid, **kw):
    return {"attempt_id": aid, "task_goal": "pick bowl onto plate", "success_criteria": "env_task_predicate",
            "task_id": "bowl", "robot_id": "panda", "policy_id": "frozen:revision",
            "perception_mode": "rgb+env_task_predicate", "dataset_split": "memory_build",
            "provenance": "real_execution", "initial_context": [], **kw}


def decision(did, start=0, end=1, value="true"):
    return {"decision_id": did, "decision_index": 0, "start_step_index": start, "end_step_index": end,
            "planner": {"stage": "grasp", "skill_id": "pick_place_v1", "skill_version": "1"},
            "retrieval": {"instruction": "pick bowl onto plate", "source_decision_ids": []},
            "evaluation": {"observed_facts": ["bowl visible"], "cause_hypothesis": None},
            "execution": {"actual_instruction": "pick bowl onto plate", "actions": [{"step_index": i+1} for i in range(start,end)]},
            "contexts": [{"kind": "bowl_visible", "value": value}],
            "evidence": [{"evidence_id": "e-" + did, "uri": "fixture://frame", "hash": did}]}


def completed(repo, aid, outcome="failure", **kw):
    repo.start_attempt(attempt(aid, **kw))
    repo.commit_decision(aid, 0, decision("d-"+aid), {"step_index":1, "status":"completed", "outcome":outcome})


def query(**kw):
    return {"snapshot_id":"frozen", "task_id":"bowl", "robot_id":"panda", "policy_id":"frozen:revision",
            "perception_mode":"rgb+env_task_predicate", "stage":"grasp",
            "contexts":[{"kind":"bowl_visible","value":"true"}], **kw}


def test_atomic_idempotent_commit_and_conflicting_reuse():
    r=InMemoryRepository()
    r.start_attempt(attempt("a"))
    d=decision("d")
    result=r.commit_decision("a",0,d,{"step_index":1})
    assert r.commit_decision("a",0,d,{"step_index":1}) == result
    changed=copy.deepcopy(d)
    changed["execution"]["actual_instruction"]="different"
    with pytest.raises(MemoryConflict): r.commit_decision("a",0,changed,{"step_index":1})
    assert len([n for n in r.export_graph()["nodes"] if n["label"]=="DecisionStep"])==1


def test_stale_or_partial_progress_rejected_without_any_write():
    r=InMemoryRepository(); r.start_attempt(attempt("a"))
    with pytest.raises(MemoryConflict): r.commit_decision("a",1,decision("d",1,2),{"step_index":2})
    with pytest.raises(MemoryValidationError): r.commit_decision("a",0,decision("d"),{"step_index":2})
    assert r.get_attempt("a")["step_index"]==0
    assert not [n for n in r.export_graph()["nodes"] if n["label"]=="DecisionStep"]


def test_snapshot_is_frozen_and_test_or_synthetic_records_cannot_leak():
    r=InMemoryRepository(); completed(r,"real")
    r.freeze_snapshot("frozen",["real"])
    completed(r,"test",dataset_split="evaluation")
    completed(r,"fake",provenance="synthetic")
    completed(r,"later")
    assert [c["source_attempt_id"] for c in r.search_experiences(query())]==["real"]
    with pytest.raises(MemoryConflict): r.freeze_snapshot("frozen",["real","later"])
    with pytest.raises(MemoryValidationError): r.freeze_snapshot("test",["test"])
    with pytest.raises(MemoryValidationError): r.freeze_snapshot("fake",["fake"])
    assert r.search_experiences(query(snapshot_id="missing"))==[]


def test_matching_aliases_and_known_conflicts_unknown_not_a_match():
    r=InMemoryRepository()
    for aid,value in (("yes","true"),("no","false"),("unknown","unknown")):
        r.start_attempt(attempt(aid))
        r.commit_decision(aid,0,decision("d-"+aid,value=value),{"step_index":1,"status":"completed","outcome":"success"})
    r.freeze_snapshot("frozen",["yes","no","unknown"])
    candidates=r.search_experiences(query())
    assert [c["source_attempt_id"] for c in candidates]==["yes","unknown"]
    assert candidates[0]["score"]>candidates[1]["score"]
    assert r.search_experiences(query(policy_id="different"))==[]
    assert r.search_experiences(query(perception_mode=None))==[]


def test_retry_paths_filter_every_node_and_stop_after_three_hops():
    r=InMemoryRepository()
    completed(r,"a")
    completed(r,"b",previous_attempt_id="a")
    completed(r,"c",outcome="success",previous_attempt_id="b")
    r.freeze_snapshot("frozen",["a","b","c"])
    c=next(x for x in r.search_experiences(query()) if x["source_attempt_id"]=="c")
    assert c["retry_path"]==["a","b","c"]
    r.freeze_snapshot("gap",["a","c"])
    c=next(x for x in r.search_experiences(query(snapshot_id="gap")) if x["source_attempt_id"]=="c")
    assert c["retry_path"]==[]


def test_concurrent_duplicate_commit_is_single_action_record():
    r=InMemoryRepository(); r.start_attempt(attempt("a"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:r.commit_decision("a",0,decision("d"),{"step_index":1}),range(16)))
    assert all(x["step_index"]==1 for x in results)
    assert len([n for n in r.export_graph()["nodes"] if n["label"]=="StepEvent"])==1


def test_terminal_unknown_is_not_retrievable_and_goals_immutable():
    r=InMemoryRepository(); r.start_attempt(attempt("a"))
    with pytest.raises(MemoryConflict): r.finalize_attempt("a",{"task_goal":"new","status":"completed","outcome":"unknown"})
    r.finalize_attempt("a",{"status":"completed","outcome":"unknown","termination_reason":"worker_lost"})
    with pytest.raises(MemoryValidationError): r.freeze_snapshot("frozen",["a"])
    with pytest.raises(MemoryConflict): r.finalize_attempt("a",{"status":"completed","outcome":"success"})


def test_graph_preserves_instruction_evidence_and_retrieval_edges():
    r=InMemoryRepository(); completed(r,"old")
    r.start_attempt(attempt("new"))
    d=decision("d-new"); d["retrieval"]["source_decision_ids"]=["d-old"]
    d["retrieval"]["candidates"]=[{"source_decision_id":"d-old","adopted":True,"reason":"same visible condition"}]
    r.commit_decision("new",0,d,{"step_index":1})
    graph=r.export_graph()
    assert {n["label"] for n in graph["nodes"]}=={"Run","Task","Attempt","DecisionStep","StepEvent","ContextObservation","Instruction","Evidence","Skill"}
    e=next(e for e in graph["edges"] if e["type"]=="RETRIEVED")
    assert e["target"]=="DecisionStep:d-old" and e["properties"]["adopted"]
    assert all(n["properties"]["provenance"]=="authored_procedure" for n in graph["nodes"] if n["label"]=="Skill")


def test_evidence_identifier_cannot_be_reused_for_changed_artifact():
    r=InMemoryRepository(); r.start_attempt(attempt("a"))
    r.commit_decision("a",0,decision("d"),{"step_index":1})
    second=decision("e",1,2); second["evidence"]=[{"evidence_id":"e-d","uri":"fixture://changed","hash":"changed"}]
    with pytest.raises(MemoryConflict): r.commit_decision("a",1,second,{"step_index":2})
    assert r.get_attempt("a")["step_index"]==1


def test_candidate_distinguishes_episode_failure_from_successful_subtask():
    r=InMemoryRepository();r.start_attempt(attempt('episode'))
    first=decision('episode:1')
    first['evaluation'].update(task_outcome=None,subtask_outcome='success')
    first['execution'].update(observation_before={'observation_id':'before','evidence_id':'e-before'},
                              observation_after={'observation_id':'after','evidence_id':'e-after'})
    r.commit_decision('episode',0,first,{'step_index':1})
    terminal=decision('episode:2',1,2)
    terminal['planner']['stage']='place'
    terminal['evaluation'].update(task_outcome='failure',subtask_outcome='failure')
    r.commit_decision('episode',1,terminal,{'step_index':2,'status':'completed','outcome':'failure'})
    r.freeze_snapshot('frozen',['episode'])
    c=r.search_experiences(query())[0]
    assert c['source_decision_id']=='episode:1'
    assert c['outcome']==c['attempt_outcome']=='failure'
    assert c['step_task_outcome'] is None and c['subtask_outcome']=='success'
    assert (c['start_step_index'],c['end_step_index'])==(0,1)
    assert (c['before_evidence_id'],c['after_evidence_id'])==('e-before','e-after')
    assert (c['observation_before_id'],c['observation_after_id'])==('before','after')


def test_retrieval_collapses_redundant_windows_and_prefers_distinct_attempts():
    r=InMemoryRepository()
    for aid in ['a','b','c']:
        r.start_attempt(attempt(aid))
        count=12 if aid=='a' else 1
        for index in range(count):
            d=decision(f'{aid}:{index+1}',index,index+1)
            d['decision_index']=index+1
            r.commit_decision(aid,index,d,{'step_index':index+1})
        r.finalize_attempt(aid,{'status':'completed','outcome':'success'})
    r.freeze_snapshot('frozen',['a','b','c'])
    candidates=r.search_experiences(query())
    assert len(candidates)==3
    assert {c['source_attempt_id'] for c in candidates}=={'a','b','c'}
    assert next(c for c in candidates if c['source_attempt_id']=='a')['source_decision_id']=='a:12'
    assert r.search_experiences(query())==candidates


def test_diversity_never_overrides_stage_and_known_condition_compatibility():
    r=InMemoryRepository();r.start_attempt(attempt('strong'))
    for index in range(3):
        d=decision(f'strong:{index}',index,index+1)
        d['execution']['actual_instruction']=f'pick bowl onto plate cue {index}'
        r.commit_decision('strong',index,d,{'step_index':index+1})
    r.finalize_attempt('strong',{'status':'completed','outcome':'success'})
    r.start_attempt(attempt('weak'))
    weak=decision('weak:1',value='unknown')
    r.commit_decision('weak',0,weak,{'step_index':1,'status':'completed','outcome':'success'})
    r.freeze_snapshot('frozen',['strong','weak'])
    result=r.search_experiences(query())
    assert len(result)==3 and all(c['source_attempt_id']=='strong' for c in result)


def test_scoped_export_omits_unselected_records_and_dangling_edges():
    r=InMemoryRepository();completed(r,'old')
    r.start_attempt(attempt('new'))
    d=decision('d-new')
    d['retrieval']['source_decision_ids']=['d-old']
    r.commit_decision('new',0,d,{'step_index':1})
    selected=r.export_graph(['new'])
    ids={n['id'] for n in selected['nodes']}
    assert 'Attempt:old' not in ids and 'DecisionStep:d-old' not in ids
    assert all(e['source'] in ids and e['target'] in ids for e in selected['edges'])
    combined=r.export_graph(['old','new'])
    assert any(e['type']=='RETRIEVED' and e['target']=='DecisionStep:d-old' for e in combined['edges'])


def test_progress_hint_preserves_initial_window_and_nearest_equivalent_window():
    r=InMemoryRepository()
    for aid in ['a','b']:
        r.start_attempt(attempt(aid))
        for index in range(12):
            d=decision(f'{aid}:{index+1}',index,index+1)
            r.commit_decision(aid,index,d,{'step_index':index+1})
        r.finalize_attempt(aid,{'status':'completed','outcome':'success'})
    r.freeze_snapshot('frozen',['a','b'])
    at_reset=r.search_experiences(query(based_on_step=0))
    assert {c['source_decision_id'] for c in at_reset}=={'a:1','b:1'}
    midway=r.search_experiences(query(based_on_step=5))
    assert {c['source_decision_id'] for c in midway}=={'a:6','b:6'}
    assert all('0 matching known' not in ';'.join(c['reasons']) for c in midway)
    assert all('not visual evidence' in ';'.join(c['reasons']) for c in midway)


def test_progress_hint_does_not_override_known_conflicts_or_unknown_conditions():
    r=InMemoryRepository()
    for aid,value in [('match','true'),('conflict','false'),('unknown','unknown')]:
        r.start_attempt(attempt(aid))
        r.commit_decision(aid,0,decision(aid,value=value),{'step_index':1,'status':'completed','outcome':'success'})
    r.freeze_snapshot('frozen',['match','conflict','unknown'])
    candidates=r.search_experiences(query(based_on_step=0))
    assert [c['source_attempt_id'] for c in candidates]==['match','unknown']
    assert candidates[0]['score']>candidates[1]['score']
    assert '0 matching known conditions' in candidates[1]['reasons']


@pytest.mark.parametrize('invalid',[-1,1.1,True,'0'])
def test_invalid_progress_hint_is_rejected(invalid):
    r=InMemoryRepository();completed(r,'a');r.freeze_snapshot('frozen',['a'])
    with pytest.raises(MemoryValidationError,match='nonnegative integer'):
        r.search_experiences(query(based_on_step=invalid))
