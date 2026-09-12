import json
from types import SimpleNamespace
from PIL import Image
from google.genai import types
from arma.agents import GeminiAgents
from arma.budget import Budget
from arma.contracts import EvaluationRecord

def evaluation():
    return dict(attempt_id='test',decision_index=1,based_on_step=0,observation_id='before',
        task_outcome=None,subtask_outcome='unknown',task_judgment_source='simulator_task_predicate',
        subtask_judgment_source='vlm_inference',task_evidence_refs=['after-frame'],
        subtask_evidence_refs=[],observed_facts=[],cause_hypothesis=None,contexts=[],evaluation_degraded=False)

def test_schema_repair_includes_specific_validation_error_and_is_bounded(tmp_path):
    image=tmp_path/'frame.png';Image.new('RGB',(8,8),'white').save(image)
    agent=GeminiAgents.__new__(GeminiAgents)
    agent.types=types;agent.root=tmp_path;agent.model='fixture';agent.calls=[];agent.budget=Budget(tmp_path/'budget.sqlite')
    calls=[]
    def generate_content(**kwargs):
        calls.append(kwargs)
        value=evaluation()
        if len(calls)==1:value['task_judgment_source']='unregistered_source'
        return SimpleNamespace(text=json.dumps(value),usage_metadata=SimpleNamespace(prompt_token_count=100,candidates_token_count=100,thoughts_token_count=0))
    agent.client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    result=agent.call('evaluator',EvaluationRecord,{'original_goal':'fixture'},[str(image)])
    assert result.task_judgment_source=='simulator_task_predicate'
    assert len(calls)==2
    assert 'task_judgment_source' in calls[1]['contents'][-1].text
    assert agent.calls[1]['repair'] is True

def test_evaluator_receives_image_to_evidence_mapping_and_actual_actions():
    agent=GeminiAgents.__new__(GeminiAgents);captured={}
    def call(role,schema,context,images,**kwargs):
        captured.update(context=context,images=images)
    agent.call=call
    dec=SimpleNamespace(model_dump=lambda:{})
    before={'observation_id':'before','evidence_id':'before-frame','step_index':0,'rgb_ref':'b.png'}
    after={'observation_id':'after','evidence_id':'after-frame','step_index':1,'rgb_ref':'a.png'}
    action={'step_index':1,'raw_policy_action':[0]*7,'env_action':[0]*7,'resulting_observation_id':'after','evidence_id':'after-frame'}
    result={'observation_before':before,'observation_after':after,'actions':[action],
        'actual_instruction':'goal','start_step_index':0,'end_step_index':1,'task_success':False,'termination_reason':'interval_complete'}
    agent.evaluate({},dec,dec,result,None)
    assert captured['images']==['b.png','a.png']
    assert captured['context']['execution']['observation_before']['evidence_id']=='before-frame'
    assert captured['context']['execution']['observation_after']['evidence_id']=='after-frame'
    assert captured['context']['execution']['actions']==[action]


def retrieval_fixture(tmp_path, candidates):
    agent=GeminiAgents.__new__(GeminiAgents)
    agent.root=tmp_path;agent.types=types
    current=tmp_path/'current.png';Image.new('RGB',(8,8),'white').save(current)
    captured={}
    agent.call=lambda role,schema,context,images,**kwargs:captured.update(context=context,images=images)
    agent.retrieve({'original_goal':'goal'},SimpleNamespace(model_dump=lambda:{}),candidates,
        {'observation_id':'current','evidence_id':'current-frame','rgb_ref':str(current)})
    return captured


def historical_candidate(tmp_path, name='a'):
    import hashlib
    frame=tmp_path/f'{name}.png';Image.new('RGB',(8,8),'red').save(frame)
    return {'source_decision_id':name,'after_evidence_id':f'{name}-after',
        'observation_after_id':f'{name}-observation','evidence_ids':[f'{name}-after'],
        'observed_facts':['The bowl remains on the table'],
        'evidence':[{'evidence_id':f'{name}-after','uri':str(frame),'type':'image/png',
            'hash':hashlib.sha256(frame.read_bytes()).hexdigest()}]}


def test_retrieval_attaches_only_mapped_top_candidate_after_image(tmp_path):
    first=historical_candidate(tmp_path);second=historical_candidate(tmp_path,'b')
    value=retrieval_fixture(tmp_path,[first,second])
    assert len(value['images'])==2
    assert value['images'][1]==first['evidence'][0]['uri']
    assert value['context']['image_order'][1]=={'image_index':1,'role':'historical_after',
        'source_decision_id':'a','observation_id':'a-observation','evidence_id':'a-after'}
    assert value['context']['candidates'][0]['evidence'][0]['attached'] is True
    assert value['context']['candidates'][1]['evidence'][0]['attached'] is False


def test_retrieval_does_not_guess_missing_after_frame_or_use_corrupt_history(tmp_path):
    candidate=historical_candidate(tmp_path)
    candidate.pop('after_evidence_id')
    assert len(retrieval_fixture(tmp_path,[candidate])['images'])==1
    candidate['after_evidence_id']='a-after';candidate['evidence'][0]['hash']='wrong'
    assert len(retrieval_fixture(tmp_path,[candidate])['images'])==1


def test_retrieval_rejects_outside_root_history_and_bounds_large_candidate_payload(tmp_path):
    outside=historical_candidate(tmp_path)
    root=tmp_path/'confined';root.mkdir()
    assert len(retrieval_fixture(root,[outside])['images'])==1
    candidate=historical_candidate(root)
    huge=historical_candidate(root,'huge');huge['observed_facts']=['x'*50000]
    value=retrieval_fixture(root,[candidate,huge])
    assert len(json.dumps(value['context'],ensure_ascii=False))<28000
    assert value['context']['omitted_candidate_count']==1
    assert [x['source_decision_id'] for x in value['context']['candidates']]==['a']


def test_evaluator_semantic_error_is_repaired_once_and_original_response_saved(tmp_path):
    from arma.contracts import validate_evaluation
    image=tmp_path/'frame.png';Image.new('RGB',(8,8),'white').save(image)
    agent=GeminiAgents.__new__(GeminiAgents)
    agent.types=types;agent.root=tmp_path;agent.model='fixture';agent.calls=[];agent.budget=Budget(tmp_path/'budget.sqlite')
    calls=[];ctx={k:evaluation()[k] for k in ('attempt_id','decision_index','based_on_step','observation_id')}
    def generate_content(**kwargs):
        calls.append(kwargs);value=evaluation()
        if len(calls)==1:value['observation_id']='after'
        return SimpleNamespace(text=json.dumps(value),usage_metadata=SimpleNamespace(prompt_token_count=100,candidates_token_count=100,thoughts_token_count=0))
    agent.client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    result=agent.call('evaluator',EvaluationRecord,ctx,[str(image)],
        validator=lambda value:validate_evaluation(value,ctx,None,{'after-frame'}))
    assert result.observation_id=='before' and len(calls)==2
    assert 'observation_id' in calls[1]['contents'][-1].text
    assert json.loads(agent.calls[0]['response_text'])['observation_id']=='after'
    assert agent.calls[0]['validation_errors'][0]['type']=='semantic_validation'


def test_retrieval_current_frame_citation_with_empty_memory_repairs_before_execution(tmp_path):
    from arma.contracts import RetrievalDecision, GOAL, validate_retrieval
    image=tmp_path/'frame.png';Image.new('RGB',(8,8),'white').save(image)
    agent=GeminiAgents.__new__(GeminiAgents)
    agent.types=types;agent.root=tmp_path;agent.model='fixture';agent.calls=[];agent.budget=Budget(tmp_path/'budget.sqlite')
    ctx={k:evaluation()[k] for k in ('attempt_id','decision_index','based_on_step','observation_id')};ctx['original_goal']=GOAL
    calls=[]
    def generate_content(**kwargs):
        calls.append(kwargs)
        value={**{k:ctx[k] for k in ('attempt_id','decision_index','based_on_step','observation_id')},
            'decision':'keep','executed_instruction':GOAL,'source_decision_ids':[],
            'evidence_ids':[],'candidates':[],'reason':'No historical memory'}
        if len(calls)==1:value.update(evidence_ids=['CURRENT_FRAME'],executed_instruction=GOAL+' approach the black bowl')
        return SimpleNamespace(text=json.dumps(value),usage_metadata=SimpleNamespace(prompt_token_count=100,candidates_token_count=100,thoughts_token_count=0))
    agent.client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    result=agent.call('retrieval',RetrievalDecision,ctx,[str(image)],validator=lambda value:validate_retrieval(value,ctx,[]))
    assert result.evidence_ids==[] and result.executed_instruction==GOAL
    assert len(calls)==2 and 'historical' in calls[1]['contents'][-1].text


def test_retrieval_maps_current_before_after_transition_without_exposing_other_images(tmp_path):
    first=historical_candidate(tmp_path)
    before=historical_candidate(tmp_path,'before')
    first.update(before_evidence_id='before-after',observation_before_id='historical-start')
    first['evidence_ids'].append('before-after');first['evidence']+=before['evidence']
    second=historical_candidate(tmp_path,'second')
    result=retrieval_fixture(tmp_path,[first,second])
    assert len(result['images'])==3
    assert result['images'][1:]==[before['evidence'][0]['uri'],first['evidence'][0]['uri']]
    assert [entry['role'] for entry in result['context']['image_order']]==['current_observation','historical_before','historical_after']
    assert result['context']['candidate_contexts_time']=='before'
    assert result['context']['candidate_observed_facts_time']=='after'
    assert all(e['attached'] for e in result['context']['candidates'][0]['evidence'])
    assert not result['context']['candidates'][1]['evidence'][0]['attached']
