import copy
import hashlib
import json
import pytest
from scripts.export_agent_trace import export_trace,write_trace,OPENVLA_COMMIT,CHECKPOINT


def saved_attempt(tmp_path):
    snapshot=tmp_path/'prompt-snapshot-v3';snapshot.mkdir()
    prompt=snapshot/'retrieval_v1.md';prompt.write_text('An exact historical system prompt.\n')
    sha=hashlib.sha256(prompt.read_bytes()).hexdigest()
    output={'attempt_id':'a','decision_index':1,'based_on_step':0,'observation_id':'obs0','decision':'keep','executed_instruction':'Pick Bowl'}
    decision={'decision_id':'a:1','decision_index':1,'planner':{},'retrieval':output,'evaluation':{},
        'execution':{'actual_instruction':'Pick Bowl','start_step_index':0,'end_step_index':10,'task_success':False}}
    call={'role':'retrieval','response_text':json.dumps(output),'prompt_hash':sha,'repair':False,
        'image_hashes':['framehash'],'image_order':[{'image_index':0,'role':'current_observation','evidence_id':'frame'}]}
    a={'attempt_id':'a','status':'completed','outcome':'failure','condition':'agents_memory','task_goal':'Pick Bowl',
        'manifest':{'prompt_hashes':{'retrieval_v1.md':sha},'openvla_commit':OPENVLA_COMMIT,'checkpoint':CHECKPOINT},
        'decisions':[decision],'api_calls':[call]}
    root=tmp_path/'a';root.mkdir();path=root/'attempt.json';path.write_text(json.dumps(a))
    return path,a


def test_export_trace_resolves_exact_prompt_and_labels_request_reconstruction(tmp_path):
    path,a=saved_attempt(tmp_path);trace=export_trace(path)
    assert trace['system_prompts']['retrieval']['status']=='verified_snapshot'
    assert trace['system_prompts']['retrieval']['text']=='An exact historical system prompt.\n'
    assert trace['system_prompts']['evaluator']['text'] is None
    d=trace['decisions'][0]
    assert d['api_calls'][0]['mapping_status']=='response_matches_committed_role_output'
    assert d['api_calls'][0]['image_audit']['order_status']=='recorded'
    assert d['supplied_candidates']['status']=='not_recorded'
    assert d['execution']['vla_prompt_reconstruction']['text']=='In: What action should the robot take to pick bowl?\nOut:'
    assert d['execution']['vla_prompt_reconstruction']['recorded_directly'] is False
    assert trace['provenance']['full_gemini_requests_logged'] is False


def test_trace_never_guesses_mapping_for_invalid_stale_or_missing_responses(tmp_path):
    path,a=saved_attempt(tmp_path);base=a['api_calls'][0]
    bad=copy.deepcopy(base);bad['validation_errors']=[{'msg':'invalid evidence'}]
    stale=copy.deepcopy(base);payload=json.loads(stale['response_text']);payload['attempt_id']='other';stale['response_text']=json.dumps(payload)
    missing=copy.deepcopy(base);missing.pop('response_text')
    repair=copy.deepcopy(base);repair['repair']=True
    a['api_calls']=[bad,stale,missing,repair];path.write_text(json.dumps(a))
    trace=export_trace(path)
    assert len(trace['unmapped_api_calls'])==3
    assert trace['unmapped_api_calls'][0]['record']['response_text']==bad['response_text']
    assert len(trace['decisions'][0]['api_calls'])==1
    assert trace['decisions'][0]['api_calls'][0]['record']['repair'] is True


def test_historical_records_are_not_mislabeled_as_exact_supplied_candidates(tmp_path):
    path,a=saved_attempt(tmp_path)
    a['decisions'][0]['retrieval'].update(source_decision_ids=['source:1'],candidates=[{'source_decision_id':'missing:1','adopted':False}])
    path.write_text(json.dumps(a))
    directory=tmp_path/'source';directory.mkdir()
    (directory/'attempt.json').write_text(json.dumps({'attempt_id':'source','outcome':'success',
        'decisions':[{'decision_id':'source:1','decision_index':1,'execution':{'actual_instruction':'Pick Bowl'},'evaluation':{'subtask_outcome':'unknown'}}]}))
    trace=export_trace(path);refs=trace['decisions'][0]['referenced_sources']
    assert refs[0]['status']=='resolved_historical_record'
    assert refs[0]['historical_record']['attempt_outcome']=='success'
    assert refs[0]['is_exact_supplied_candidate_payload'] is False
    assert refs[1]['status']=='unavailable'


def test_trace_refuses_partial_episode_and_does_not_use_wrong_prompt_hash(tmp_path):
    path,a=saved_attempt(tmp_path);a['manifest']['prompt_hashes']['retrieval_v1.md']='wrong';path.write_text(json.dumps(a))
    assert export_trace(path)['system_prompts']['retrieval']['text'] is None
    a['status']='running';path.write_text(json.dumps(a))
    with pytest.raises(ValueError,match='completed'):export_trace(path)


def test_trace_writes_json_and_local_javascript_sidecar(tmp_path):
    path,_=saved_attempt(tmp_path);trace=export_trace(path)
    output=tmp_path/'viewer'/'trace.json';write_trace(trace,output)
    assert json.loads(output.read_text())['schema_version']=='arma-agent-trace-v1'
    assert output.with_name('trace-data.js').read_text().startswith('window.ARMA_AGENT_TRACE = ')
