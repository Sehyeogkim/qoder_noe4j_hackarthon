"""Normalize a real authored probe for reviewed graph import; CLI never writes a DB.

The original raw ledger remains immutable. No planner/retrieval output or visual
subtask judgment is synthesized, and no memory snapshot is created here.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arma.contracts import GOAL,TASK_NAME
from arma.memory import InMemoryRepository
from worker.protocol import ExecutionResult
from scripts.run_instruction_probe import validate_schedule

IMPORT_VERSION='authored-probe-environment-import-v1'


def normalize_probe(raw,source_sha256,protocol=None,protocol_sha256=None):
    expected={'status':'completed','provenance':'real_execution','execution_provenance':'real_execution',
        'origin':'authored_skill_procedure','condition':'diagnostic_instruction_probe','dataset_split':'memory_build',
        'task_goal':GOAL,'task_id':TASK_NAME}
    for key,value in expected.items():
        if raw.get(key)!=value:raise ValueError(f'Probe {key} must retain its predeclared {value!r} metadata')
    if raw.get('outcome') not in ('success','failure'):raise ValueError('Unknown probes cannot become eligible historical memory')
    if raw.get('agent_api_calls')!=0 or raw.get('external_database_used') is not False or raw.get('memory_snapshot_written') is not False:
        raise ValueError('Authored probe must record zero agent calls and no prior DB/snapshot writes')
    manifest=raw.get('manifest',{})
    if not raw.get('policy_id') or raw['policy_id']!=manifest.get('policy_id'):
        raise ValueError('Probe must retain the worker policy identity')
    initial=raw.get('initial_context',{})
    if initial.get('step_index')!=0 or not initial.get('observation_id'):raise ValueError('Missing initial observation')
    aid=raw['attempt_id'];schedule=validate_schedule(raw['schedule'],raw['action_budget'],raw.get('diagnostic_instruction_approval'))
    previous_attempt_id=None
    if protocol is not None:
        if not protocol_sha256 or protocol.get('task_name')!=TASK_NAME or protocol.get('init_state_id')!=raw['init_state_id'] or protocol.get('seed')!=raw['seed']:
            raise ValueError('Declared recall protocol must match task, state and seed and have a source hash')
        sequence=protocol.get('corpus',{}).get('retry_sequence',[])
        if aid not in sequence or len(sequence)!=len(set(sequence)):raise ValueError('Probe absent or repeated in declared retry sequence')
        position=sequence.index(aid)
        if position:previous_attempt_id=sequence[position-1]
    import_info={'version':IMPORT_VERSION,'raw_record_sha256':source_sha256,
        'origin':'authored_skill_procedure','no_reasoning_agents_invoked':True,
        'observation_boundary':'RGB and environment whole-task predicate; no inferred object poses or visual subtask success',
        'snapshot_policy':'New explicitly selected calibration snapshot only; never mutate an earlier snapshot'}
    if protocol is not None:import_info.update(protocol_sha256=protocol_sha256,retry_sequence=protocol['corpus']['retry_sequence'])
    start={key:copy.deepcopy(raw[key]) for key in ('attempt_id','condition','provenance','origin','dataset_split',
        'task_goal','task_id','success_criteria','init_state_id','seed','policy_id','robot_id','perception_mode',
        'manual_instruction_version','schedule','diagnostic_instruction_approval') if key in raw}
    start.update(run_id=aid,status='running',outcome=None,termination_reason=None,step_index=0,decision_index=0,
        initial_context=copy.deepcopy(initial),observation=copy.deepcopy(initial),latest_observation_ref=initial.get('rgb_ref'),
        executed_instruction='',evidence_refs=[],observed_facts=[],cause_hypothesis=None,contexts=[],
        previous_attempt_id=previous_attempt_id,manifest=copy.deepcopy(manifest),import_provenance=import_info,
        agent_api_calls=0,external_database_used=False,memory_snapshot_written=False)
    commits=[];previous=initial;step=0;seen_success=bool(initial.get('task_success'));cursor=0
    for i,window in enumerate(raw.get('decisions',[]),1):
        ex=ExecutionResult.model_validate(window['execution']).model_dump()
        if seen_success:raise ValueError('Probe contains execution after task success')
        if window.get('decision_index')!=i or ex['execution_id']!=f'{aid}:{i}':raise ValueError('Probe interval identity mismatch')
        if ex['start_step_index']!=step or not step<ex['end_step_index']<=min(step+10,raw['action_budget']):
            raise ValueError('Noncontiguous or unbounded probe interval')
        if ex['observation_before']!=previous:raise ValueError('Probe before-observation does not match committed prior result')
        if ex['observation_before_id']!=previous['observation_id'] or ex['observation_after_id']!=ex['observation_after']['observation_id']:
            raise ValueError('Probe observation references disagree')
        if ex['observation_after']['step_index']!=ex['end_step_index'] or ex['task_success']!=ex['observation_after']['task_success']:
            raise ValueError('Probe environment outcome/progress disagrees with after observation')
        if len(ex['actions'])!=ex['end_step_index']-step or [a['step_index'] for a in ex['actions']]!=list(range(step+1,ex['end_step_index']+1)):
            raise ValueError('Probe action count or indexing disagrees with interval')
        while cursor+1<len(schedule) and schedule[cursor+1]['start_step']<=step:cursor+=1
        if ex['actual_instruction']!=schedule[cursor]['instruction']:raise ValueError('Actual instruction does not match predeclared authored schedule')
        if cursor+1<len(schedule) and ex['end_step_index']>schedule[cursor+1]['start_step']:
            raise ValueError('Execution crosses an authored schedule boundary')
        after=ex['observation_after'];terminal=i==len(raw['decisions'])
        outcome='success' if ex['task_success'] else ('failure' if terminal else None)
        facts=[f"Environment task_success={ex['task_success']} after policy action {ex['end_step_index']}."]
        evaluation={'task_outcome':outcome,'subtask_outcome':'unknown','task_judgment_source':'simulator_task_predicate',
            'subtask_judgment_source':'unavailable','task_evidence_refs':[after['evidence_id']],
            'subtask_evidence_refs':[],'observed_facts':facts,'cause_hypothesis':None,'contexts':[],
            'evaluation_origin':'deterministic_environment_record','agent_invoked':False}
        evidence=[]
        for obs in (ex['observation_before'],after):
            evidence.append({'evidence_id':obs['evidence_id'],'uri':obs['rgb_ref'],'type':'image/png','hash':obs['sha256']})
        decision={'decision_id':ex['execution_id'],'attempt_id':aid,'decision_index':i,
            'start_step_index':step,'end_step_index':ex['end_step_index'],'execution':ex,'evaluation':evaluation,
            'contexts':[],'evidence':evidence,'origin':'authored_skill_procedure','record_kind':'authored_instruction_probe',
            'instruction_source':'manual_configuration','manual_instruction_version':raw['manual_instruction_version'],
            'manual_schedule_index':cursor,'import_provenance':import_info}
        update={'step_index':ex['end_step_index'],'decision_index':i,'observation':after,
            'latest_observation_ref':after['rgb_ref'],'executed_instruction':ex['actual_instruction'],
            'status':'completed' if terminal else 'running','outcome':outcome,
            'termination_reason':raw.get('termination_reason') if terminal else None,
            'evidence_refs':[after['evidence_id']],'judgment_source':'simulator_task_predicate',
            'observed_facts':facts,'cause_hypothesis':None,'contexts':[]}
        if terminal:update.update(video_ref=raw.get('video_ref'),elapsed_ms=raw.get('elapsed_ms'))
        commits.append({'expected_step_index':step,'decision':decision,'attempt_update':update})
        step=ex['end_step_index'];previous=after;seen_success=ex['task_success']
    if not commits:raise ValueError('An authored instruction memory requires at least one actual execution interval')
    expected_outcome='success' if seen_success else 'failure'
    if raw['outcome']!=expected_outcome or raw['step_index']!=step:
        raise ValueError('Final probe result conflicts with actual environment records')
    if not seen_success and step!=raw['action_budget']:raise ValueError('Failure requires exhausted predeclared action budget')
    return {'schema_version':IMPORT_VERSION,'source_record_sha256':source_sha256,'start_attempt':start,'commits':commits,
        'creates_snapshot':False,'contains_model_generated_decisions':False}


def apply_import(repository,payload):
    """Explicit caller-controlled write interface; not called with Neo4j by CLI."""
    aid=payload['start_attempt']['attempt_id'];repository.start_attempt(payload['start_attempt'])
    for c in payload['commits']:
        repository.commit_decision(aid,c['expected_step_index'],c['decision'],c['attempt_update'])
    return repository.get_attempt(aid)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path,help='Reviewed import payload JSON, not a database destination')
    parser.add_argument('--graph-preview',type=Path,help='Optional local graph preview from the actual source record')
    parser.add_argument('--protocol',type=Path,help='Explicit immutable same-state recall protocol with actual retry sequence')
    args=parser.parse_args();data=args.probe.read_bytes()
    protocol_data=args.protocol.read_bytes() if args.protocol else None
    payload=normalize_probe(json.loads(data),hashlib.sha256(data).hexdigest(),
        json.loads(protocol_data) if protocol_data else None,hashlib.sha256(protocol_data).hexdigest() if protocol_data else None)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(payload,indent=2)+'\n')
    if args.graph_preview:
        repo=InMemoryRepository();apply_import(repo,payload)
        args.graph_preview.parent.mkdir(parents=True,exist_ok=True)
        args.graph_preview.write_text(json.dumps(repo.export_graph(),indent=2)+'\n')
    print(json.dumps({'attempt_id':payload['start_attempt']['attempt_id'],'intervals':len(payload['commits']),
        'database_written':False,'snapshot_created':False,'output':str(args.output)}))

if __name__=='__main__':main()
