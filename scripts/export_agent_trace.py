"""Export recorded ARMA agent decisions without a model call or database access."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

OPENVLA_COMMIT = 'c8f03f48af692657d3060c19588038c7220e9af9'
CHECKPOINT = 'openvla/openvla-7b-finetuned-libero-spatial'
ROLE_FIELDS = {'subtask':'planner','retrieval':'retrieval','evaluator':'evaluation'}


def read_json(path):
    return json.loads(Path(path).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def prompt_catalog(roots):
    catalog={}
    for root in roots:
        for folder in sorted(Path(root).glob('prompt-snapshot*')):
            if not folder.is_dir():continue
            for path in sorted(folder.rglob('*.md')):
                data=path.read_bytes();sha=hashlib.sha256(data).hexdigest()
                catalog.setdefault(sha,{'status':'verified_snapshot','hash':sha,'text':data.decode(),
                    'source':str(path.resolve())})
    return catalog


def historical_index(source_root,graph_path=None):
    """Return source records, not purported exact retrieval request payloads."""
    entries={}
    if graph_path:
        graph=read_json(graph_path)
        attempt_nodes={n['id']:n.get('properties',{}) for n in graph.get('nodes',[]) if n.get('label')=='Attempt'}
        source_attempts={e['target']:attempt_nodes.get(e['source'],{}) for e in graph.get('edges',[]) if e.get('type')=='HAS_DECISION'}
        for node in graph.get('nodes',[]):
            if node.get('label')=='DecisionStep':
                value=node.get('properties',{});did=value.get('decision_id') or node['id'].removeprefix('DecisionStep:')
                parent=source_attempts.get(node['id'],{})
                entries[did]={'record':value,'source':str(Path(graph_path).resolve()),'origin':'exported_graph',
                    'attempt_id':parent.get('attempt_id'),'attempt_outcome':parent.get('outcome')}
    for path in sorted(Path(source_root).glob('*/attempt.json')):
        attempt=read_json(path)
        for decision in attempt.get('decisions',[]):
            did=decision['decision_id']
            entries.setdefault(did,{'record':decision,'source':str(path.resolve()),'origin':'source_attempt',
                'attempt_id':attempt.get('attempt_id'),'attempt_outcome':attempt.get('outcome')})
    return entries


def policy_prompt(instruction,manifest):
    supported=(manifest.get('openvla_commit')==OPENVLA_COMMIT and manifest.get('checkpoint')==CHECKPOINT)
    return {'status':'exact_reconstruction_from_pinned_implementation' if supported else 'unavailable_unverified_policy_adapter',
        'text':f'In: What action should the robot take to {instruction.lower()}?\nOut:' if supported else None,
        'recorded_directly':False,'source_commit':manifest.get('openvla_commit'),
        'source_file':'experiments/robot/openvla_utils.py:163',
        'scope':'Formatted text only. Processor tensors, tokens and the full inference request were not logged.'}


def source_refs(retrieval,index):
    ids=list(dict.fromkeys([*retrieval.get('source_decision_ids',[]),
        *(c['source_decision_id'] for c in retrieval.get('candidates',[]) if 'source_decision_id' in c),
        *(sid for field in ('memory_summary','current_comparison','adaptation_reason')
          for claim in retrieval.get(field,[]) for sid in claim.get('source_decision_ids',[]))]))
    output=[]
    for did in ids:
        found=index.get(did)
        item={'source_decision_id':did,'adopted':did in retrieval.get('source_decision_ids',[]),
            'status':'resolved_historical_record' if found else 'unavailable',
            'is_exact_supplied_candidate_payload':False}
        if found:
            d=found['record'];ex=d.get('execution',{})
            item.update(origin=found['origin'],source_file=found['source'],
                source_attempt_id=d.get('attempt_id',found.get('attempt_id')),
                historical_record={
                    'decision_index':d.get('decision_index'),'start_step_index':d.get('start_step_index'),
                    'end_step_index':d.get('end_step_index'),'planner':d.get('planner'),
                    'actual_instruction':ex.get('actual_instruction'),
                    'contexts':d.get('contexts',[]),'evaluation':d.get('evaluation'),
                    'attempt_outcome':found.get('attempt_outcome'),
                    'observation_before':ex.get('observation_before'),
                    'observation_after':ex.get('observation_after'),'evidence':d.get('evidence',[])})
        output.append(item)
    return output


def export_trace(attempt_path,source_root=None,prompt_roots=None,graph_path=None):
    attempt_path=Path(attempt_path);a=read_json(attempt_path)
    if a.get('status')!='completed':raise ValueError('Trace requires a completed saved Attempt; do not export a partial episode as final')
    source_root=Path(source_root or attempt_path.parent.parent)
    catalog=prompt_catalog(prompt_roots or [source_root]);manifest=a.get('manifest',{})
    prompts={}
    for role in ROLE_FIELDS:
        sha=manifest.get('prompt_hashes',{}).get(f'{role}_v1.md')
        prompts[role]=catalog.get(sha,{'status':'unavailable_no_matching_snapshot','hash':sha,'text':None,'source':None})
    index=historical_index(source_root,graph_path)
    decisions=[];by_index={}
    for d in a.get('decisions',[]):
        ex=d['execution'];retrieval=d.get('retrieval',{})
        item={'decision_id':d['decision_id'],'decision_index':d['decision_index'],
            'planner':d.get('planner'),'retrieval':retrieval,'evaluator':d.get('evaluation'),
            'evaluation_error':d.get('evaluation_error'),
            'execution':{'actual_instruction':ex['actual_instruction'],'start_step_index':ex['start_step_index'],
                'end_step_index':ex['end_step_index'],'task_success':ex.get('task_success'),
                'observation_before':ex.get('observation_before'),'observation_after':ex.get('observation_after'),
                'actions':ex.get('actions',[]),'vla_prompt_reconstruction':policy_prompt(ex['actual_instruction'],manifest)},
            'referenced_sources':source_refs(retrieval,index),'api_calls':[],
            'supplied_candidates':{'status':'not_recorded','exact_payload':None,
                'note':'Referenced source records and model-reported choices are available; the exact candidate input payload was not logged.'},
            'context_reconstruction':{'status':'reconstructed_from_committed_records_not_full_request',
                'original_goal':a.get('task_goal'),'success_criteria':a.get('success_criteria'),
                'current_observation':ex.get('observation_before'),'current_start_conditions':d.get('contexts',[])}}
        decisions.append(item);by_index[d['decision_index']]=item
    unmapped=[]
    for i,call in enumerate(a.get('api_calls',[])):
        entry={'call_index':i,'record':call,'image_audit':{
            'image_hashes':call.get('image_hashes',[]),'image_order':call.get('image_order'),
            'order_status':'recorded' if 'image_order' in call else 'not_recorded'},
            'system_prompt':catalog.get(call.get('prompt_hash'),{'status':'unavailable_no_matching_snapshot',
                'hash':call.get('prompt_hash'),'text':None,'source':None}),
            'full_request_payload':{'status':'not_logged','exact_payload':None}}
        try:response=json.loads(call.get('response_text') or '')
        except (ValueError,TypeError):response=None
        entry['parsed_response']=response
        reason=None
        if call.get('validation_errors'):reason='rejected_or_invalid_response_retained_without_assignment'
        elif not isinstance(response,dict):reason='missing_or_unparseable_response_envelope'
        elif response.get('attempt_id')!=a['attempt_id']:reason='mismatched_attempt_envelope'
        elif type(response.get('decision_index')) is not int or response['decision_index'] not in by_index:
            reason='no_committed_decision_for_response_envelope'
        elif call.get('role') not in ROLE_FIELDS:reason='unknown_role'
        if reason:
            entry['mapping_status']=reason;unmapped.append(entry);continue
        target=by_index[response['decision_index']]
        saved=target[{'subtask':'planner','retrieval':'retrieval','evaluator':'evaluator'}[call['role']]] or {}
        matches=all(k in saved and saved[k]==v for k,v in response.items())
        entry['mapping_status']='response_matches_committed_role_output' if matches else 'envelope_match_only_output_differs'
        target['api_calls'].append(entry)
    return {'schema_version':'arma-agent-trace-v1','attempt':{k:a.get(k) for k in
        ('attempt_id','condition','init_state_id','outcome','termination_reason','step_index','decision_index','task_goal','cost_usd','video_ref')},
        'manifest':manifest,'source_attempt_file':str(attempt_path.resolve()),'system_prompts':prompts,
        'provenance':{'full_gemini_requests_logged':False,'agent_outputs':'committed records and retained API response_text',
            'source_records':'resolved stored experience; not an exact reconstruction of supplied candidate payloads',
            'visual_judgments':'VLM interpretations; only environment whole-task predicate is authoritative'},
        'decisions':decisions,'unmapped_api_calls':unmapped,
        'evidence_assets':{n['properties'].get('evidence_id',n['id'].removeprefix('Evidence:')):n['properties']
            for n in (read_json(graph_path).get('nodes',[]) if graph_path else []) if n.get('label')=='Evidence'}}


def write_trace(trace,output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(trace,ensure_ascii=False,indent=2)
    output.write_text(payload+'\n')
    output.with_name('trace-data.js').write_text('window.ARMA_AGENT_TRACE = '+payload.replace('</','<\\/')+';\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt',required=True,type=Path)
    parser.add_argument('--source-root',type=Path)
    parser.add_argument('--prompt-root',type=Path,action='append')
    parser.add_argument('--graph',type=Path)
    parser.add_argument('--output',type=Path,default=Path('artifacts/agent-trace/trace.json'))
    args=parser.parse_args()
    trace=export_trace(args.attempt,args.source_root,args.prompt_root,args.graph)
    write_trace(trace,args.output)
    print(json.dumps({'output':str(args.output),'decisions':len(trace['decisions']),
        'mapped_calls':sum(len(d['api_calls']) for d in trace['decisions']),
        'unmapped_calls':len(trace['unmapped_api_calls'])}))

if __name__=='__main__':main()
