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
    agent.types=types;agent.root=tmp_path;agent.model='gemini-3-flash-preview';agent.calls=[];agent.budget=Budget(tmp_path/'budget.sqlite')
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
    agent.types=types;agent.root=tmp_path;agent.model='gemini-3-flash-preview';agent.calls=[];agent.budget=Budget(tmp_path/'budget.sqlite')
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
    agent.types=types;agent.root=tmp_path;agent.model='gemini-3-flash-preview';agent.calls=[];agent.budget=Budget(tmp_path/'budget.sqlite')
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


def explained_retrieval():
    from arma.contracts import RetrievalDecision, GOAL
    ctx={'attempt_id':'a','decision_index':1,'based_on_step':0,'observation_id':'current',
        'original_goal':GOAL,'allowed_current_evidence_ids':['current-frame'],
        'visible_historical_evidence_ids':['old-before','old-after'],'require_memory_explanations':True}
    candidates=[{'source_decision_id':'old','evidence_ids':['old-before','old-after']},
                {'source_decision_id':'rejected','evidence_ids':['rejected-frame']}]
    historical={'text':'The prior interval used the full goal while approaching the bowl.',
        'source_decision_ids':['old'],'evidence_ids':['old-before'],'grounding':'visible'}
    value=RetrievalDecision(**{k:ctx[k] for k in ('attempt_id','decision_index','based_on_step','observation_id')},
        decision='adapt',executed_instruction=GOAL+'. Approach the bowl before closing the gripper.',
        source_decision_ids=['old'],evidence_ids=['old-before'],
        candidates=[{'source_decision_id':'old','adopted':True,'reason':'Compatible starting state'}],reason='Evidence-backed guidance',
        memory_summary=[historical],current_comparison=[{**historical,'text':'The target is visible in both starting images.',
            'current_evidence_ids':['current-frame']}],adaptation_reason=[{**historical,'text':'Retain the target and destination while making the approach explicit.'}])
    return ctx,candidates,value


def test_cited_memory_explanations_are_separate_from_actual_instruction():
    from arma.contracts import validate_retrieval
    ctx,candidates,value=explained_retrieval()
    result=validate_retrieval(value,ctx,candidates)
    assert result.memory_summary[0].evidence_ids==['old-before']
    assert result.current_comparison[0].current_evidence_ids==['current-frame']
    assert 'prior interval' not in result.executed_instruction
    assert len(result.executed_instruction)<=500


def test_explanations_reject_cross_source_or_unseen_visual_claims():
    import pytest
    from arma.contracts import validate_retrieval
    ctx,candidates,value=explained_retrieval()
    value.memory_summary[0].evidence_ids=['rejected-frame']
    with pytest.raises(ValueError,match='each cited source'):
        validate_retrieval(value,ctx,candidates)
    ctx,candidates,value=explained_retrieval()
    ctx['visible_historical_evidence_ids']=[]
    with pytest.raises(ValueError,match='not attached'):
        validate_retrieval(value,ctx,candidates)
    # Reporting a stored judgment is permitted when explicitly attributed.
    for field in ('memory_summary','current_comparison','adaptation_reason'):
        for claim in getattr(value,field):claim.grounding='recorded'
    assert validate_retrieval(value,ctx,candidates) is value


def test_explanations_reject_invented_current_frame_and_rejected_adaptation_source():
    import pytest
    from arma.contracts import validate_retrieval
    ctx,candidates,value=explained_retrieval()
    value.current_comparison[0].current_evidence_ids=['unseen']
    with pytest.raises(ValueError,match='unseen current'):
        validate_retrieval(value,ctx,candidates)
    ctx,candidates,value=explained_retrieval()
    claim=value.adaptation_reason[0]
    claim.source_decision_ids=['rejected'];claim.evidence_ids=['rejected-frame'];claim.grounding='recorded'
    with pytest.raises(ValueError,match='adopted sources'):
        validate_retrieval(value,ctx,candidates)


def test_legacy_decisions_keep_empty_explanation_defaults():
    from arma.contracts import RetrievalDecision
    ctx,candidates,value=explained_retrieval()
    payload=value.model_dump()
    for field in ('memory_summary','current_comparison','adaptation_reason'):payload.pop(field)
    legacy=RetrievalDecision.model_validate(payload)
    assert legacy.memory_summary==legacy.current_comparison==legacy.adaptation_reason==[]


def test_explanation_fallback_never_repairs_core_execution_or_model_authored_bypass():
    import pytest
    from arma.contracts import degrade_retrieval_explanation
    ctx,candidates,value=explained_retrieval()
    value.observation_id='stale'
    with pytest.raises(ValueError,match='Stale'):
        degrade_retrieval_explanation(value,ctx,candidates,['presentation issue'])
    ctx,candidates,value=explained_retrieval()
    value.evidence_ids=['invented']
    with pytest.raises(ValueError,match='historical'):
        degrade_retrieval_explanation(value,ctx,candidates,['presentation issue'])
    ctx,candidates,value=explained_retrieval()
    value.explanation_degraded=True
    with pytest.raises(ValueError,match='Model-authored'):
        degrade_retrieval_explanation(value,ctx,candidates,['presentation issue'])


def test_keep_preserves_active_instruction_without_relaxing_envelope_or_citations():
    import pytest
    from arma.contracts import GOAL,RetrievalDecision,validate_retrieval_execution
    ctx={'attempt_id':'a','decision_index':2,'based_on_step':10,'observation_id':'current',
        'original_goal':GOAL,'current_instruction':GOAL+'. Lift the secured bowl before moving to the plate.'}
    value=RetrievalDecision(**{k:ctx[k] for k in ('attempt_id','decision_index','based_on_step','observation_id')},
        decision='keep',executed_instruction=ctx['current_instruction'],reason='Retain committed instruction')
    assert validate_retrieval_execution(value,ctx,[]) is value
    value.executed_instruction=GOAL
    with pytest.raises(ValueError,match='current_instruction'):validate_retrieval_execution(value,ctx,[])
    value.executed_instruction=ctx['current_instruction'];value.evidence_ids=['invented']
    with pytest.raises(ValueError,match='historical'):validate_retrieval_execution(value,ctx,[])
    value.evidence_ids=[];value.observation_id='stale'
    with pytest.raises(ValueError,match='Stale'):validate_retrieval_execution(value,ctx,[])


def test_registered_exact_successful_historical_instruction_can_be_adopted_and_retained():
    from arma.contracts import GOAL,RetrievalDecision,validate_retrieval_execution
    text='put the black bowl in the middle of the table on the plate'
    ctx={'attempt_id':'a','decision_index':1,'based_on_step':0,'observation_id':'obs','original_goal':GOAL,'current_instruction':GOAL}
    value=RetrievalDecision(**{k:ctx[k] for k in ('attempt_id','decision_index','based_on_step','observation_id')},
        decision='adapt',executed_instruction=text,source_decision_ids=['success'],evidence_ids=['frame'],
        candidates=[{'source_decision_id':'success','adopted':True,'reason':'Exact recorded full-task language'}],reason='Actual success source')
    candidate={'source_decision_id':'success','evidence_ids':['frame'],'instruction':text,'attempt_outcome':'success'}
    assert validate_retrieval_execution(value,ctx,[candidate]) is value
    value.decision='keep';value.source_decision_ids=[];value.evidence_ids=[];value.candidates=[]
    ctx['current_instruction']=text
    assert validate_retrieval_execution(value,ctx,[]) is value


def test_registered_paraphrase_requires_exact_successful_source_not_just_approval():
    import pytest
    from arma.contracts import validate_retrieval_execution
    ctx,candidates,value=explained_retrieval()
    text='put the black bowl in the middle of the table on the plate';value.executed_instruction=text
    candidates[0].update(instruction=text,attempt_outcome='failure')
    with pytest.raises(ValueError,match='adopted successful'):validate_retrieval_execution(value,ctx,candidates)
    candidates[0].update(attempt_outcome='success',instruction='different instruction')
    with pytest.raises(ValueError,match='adopted successful'):validate_retrieval_execution(value,ctx,candidates)
    candidates[0]['instruction']=text;value.executed_instruction='put the red cup on the stove'
    with pytest.raises(ValueError,match='unregistered'):validate_retrieval_execution(value,ctx,candidates)


def transition_candidate(tmp_path,name,attempt_id):
    candidate=historical_candidate(tmp_path,name)
    before=historical_candidate(tmp_path,name+'-before')
    candidate.update(source_attempt_id=attempt_id,before_evidence_id=before['after_evidence_id'],
        observation_before_id=name+'-before-observation')
    candidate['evidence_ids']+=before['evidence_ids'];candidate['evidence']+=before['evidence']
    return candidate


def test_retrieval_attaches_two_distinct_source_transitions_without_reranking(tmp_path):
    first=transition_candidate(tmp_path,'failure-first','failed-attempt')
    duplicate=transition_candidate(tmp_path,'failure-later','failed-attempt')
    success=transition_candidate(tmp_path,'success','successful-attempt')
    result=retrieval_fixture(tmp_path,[first,duplicate,success]);ctx=result['context']
    assert len(result['images'])==5
    assert [c['source_decision_id'] for c in ctx['candidates']]==['failure-first','failure-later','success']
    assert [m['source_attempt_id'] for m in ctx['image_order'][1:]]==['failed-attempt']*2+['successful-attempt']*2
    assert [m['source_decision_id'] for m in ctx['image_order'][1:]]==['failure-first']*2+['success']*2
    assert [m['role'] for m in ctx['image_order']]==['current_observation','historical_before','historical_after','historical_before','historical_after']
    assert set(ctx['visible_historical_evidence_ids'])==set(first['evidence_ids']+success['evidence_ids'])
    assert all(e['attached'] for c in (ctx['candidates'][0],ctx['candidates'][2]) for e in c['evidence'])
    assert not any(e['attached'] for e in ctx['candidates'][1]['evidence'])


def test_missing_second_source_frame_is_not_marked_visible(tmp_path):
    first=transition_candidate(tmp_path,'failure','failed-attempt')
    second=transition_candidate(tmp_path,'success','successful-attempt')
    second['evidence'][0]['hash']='mismatch'
    result=retrieval_fixture(tmp_path,[first,second]);ctx=result['context']
    assert len(result['images'])==4
    assert second['after_evidence_id'] not in ctx['visible_historical_evidence_ids']
    assert ctx['image_order'][-1]['role']=='historical_before'
    assert ctx['image_order'][-1]['source_attempt_id']=='successful-attempt'
    assert ctx['candidates'][1]['evidence'][0]['attached'] is False


def test_gemini_call_keeps_five_image_hashes_and_rejects_unbudgeted_sixth(tmp_path):
    import pytest
    image=tmp_path/'image.png';Image.new('RGB',(8,8),'white').save(image)
    agent=GeminiAgents.__new__(GeminiAgents);agent.types=types;agent.root=tmp_path
    agent.model='gemini-3-flash-preview';agent.calls=[];agent.budget=Budget(tmp_path/'budget.sqlite')
    seen=[]
    def generate_content(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(text=json.dumps(evaluation()),usage_metadata=SimpleNamespace(prompt_token_count=100,candidates_token_count=100,thoughts_token_count=0))
    agent.client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    agent.call('evaluator',EvaluationRecord,{},[str(image)]*5)
    assert len(agent.calls[0]['image_hashes'])==5 and len(seen[0]['contents'])==6
    with pytest.raises(ValueError,match='five-image cap'):
        agent.call('evaluator',EvaluationRecord,{},[str(image)]*6)
    assert len(seen)==1


def test_model_specific_reservations_settlement_and_generation_config(tmp_path):
    import pytest
    reservations={};records={};configs={}
    for model in ('gemini-3-flash-preview','gemini-3.5-flash'):
        class RecordingBudget(Budget):
            def reserve(self,amount,*args,**kwargs):
                reservations.setdefault(model,[]).append(amount)
                return super().reserve(amount,*args,**kwargs)
        agent=GeminiAgents.__new__(GeminiAgents);agent.types=types;agent.root=tmp_path
        agent.model=model;agent.calls=[];agent.budget=RecordingBudget(tmp_path/(model+'.sqlite'))
        def generate_content(**kwargs):
            configs[model]=kwargs['config'].model_dump(exclude_none=True)
            return SimpleNamespace(text=json.dumps(evaluation()),usage_metadata=SimpleNamespace(
                prompt_token_count=1000,candidates_token_count=200,thoughts_token_count=50))
        agent.client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
        agent.call('evaluator',EvaluationRecord,{},[])
        records[model]=agent.calls[0]
        assert agent.budget.totals()['api']==pytest.approx(agent.calls[0]['cost_usd'])
    assert reservations['gemini-3.5-flash'][0]==pytest.approx(3*reservations['gemini-3-flash-preview'][0])
    assert records['gemini-3.5-flash']['cost_usd']==pytest.approx((1000*1.5+250*9)/1_000_000)
    assert records['gemini-3-flash-preview']['cost_usd']==pytest.approx((1000*.5+250*3)/1_000_000)
    assert records['gemini-3.5-flash']['output_tokens']==250
    assert configs['gemini-3-flash-preview']['temperature']==0
    assert 'temperature' not in configs['gemini-3.5-flash']
    assert 'top_p' not in configs['gemini-3.5-flash'] and 'top_k' not in configs['gemini-3.5-flash']
    assert configs['gemini-3.5-flash']['thinking_config']['thinking_level']=='MINIMAL'
    assert configs['gemini-3.5-flash']['response_json_schema']==configs['gemini-3-flash-preview']['response_json_schema']


def test_unknown_model_refuses_dispatch_and_reservation(tmp_path):
    import pytest
    agent=GeminiAgents.__new__(GeminiAgents);agent.model='unpriced-model';agent.budget=Budget(tmp_path/'budget.sqlite')
    called=[];agent.client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw:called.append(kw)))
    with pytest.raises(ValueError,match='paid dispatch refused'):
        agent.call('evaluator',EvaluationRecord,{},[])
    assert not called and agent.budget.totals()['api']==0
    with pytest.raises(ValueError,match='paid dispatch refused'):
        GeminiAgents(agent.budget,model='unpriced-model')
