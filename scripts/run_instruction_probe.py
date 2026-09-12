"""Explicit diagnostic text intervention: frozen worker only, no Gemini/Neo4j calls.

A successful probe is not an agents_memory result. Validate a useful diagnostic
instruction through the actual agent system in a separately recorded experiment.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from arma.contracts import GOAL,TASK_NAME
from arma.robot import RobotClient

# Shared fixed same-task registry; diagnostic use still needs explicit approval.
from arma.task_instructions import APPROVED_TASK_PARAPHRASES


def validate_approval(config):
    if config is None:return None
    if not isinstance(config,dict) or config.get('task_id')!=TASK_NAME or config.get('task_goal')!=GOAL:
        raise ValueError('Diagnostic approval must name the unchanged supported task and immutable goal')
    if not isinstance(config.get('version'),str) or not config['version'].strip():
        raise ValueError('Diagnostic approval requires an explicit version')
    instructions=config.get('instructions')
    if not isinstance(instructions,list) or not instructions or any(x not in APPROVED_TASK_PARAPHRASES for x in instructions):
        raise ValueError('Only explicitly registered full-task diagnostic paraphrases may be approved')
    if len(instructions)!=len(set(instructions)):raise ValueError('Duplicate approved instruction')
    return config


def validate_schedule(schedule,max_actions,approval=None):
    approval=validate_approval(approval)
    approved=approval['instructions'] if approval else []
    if type(max_actions) is not int or not 1<=max_actions<=220:
        raise ValueError('Policy action budget must be 1..220')
    if not isinstance(schedule,list) or not schedule:
        raise ValueError('Provide a nonempty explicit manual instruction schedule')
    previous=-1
    for item in schedule:
        start=item.get('start_step');instruction=item.get('instruction')
        if type(start) is not int or not 0<=start<max_actions or start<=previous:
            raise ValueError('start_step must be a strictly ascending nonnegative policy-action index')
        if not isinstance(instruction,str) or len(instruction)>500 or (not instruction.startswith(GOAL) and instruction not in approved):
            raise ValueError('Instruction must retain the original-goal prefix or be an explicitly approved diagnostic full-task paraphrase, within500 characters')
        previous=start
    if schedule[0]['start_step']!=0:raise ValueError('Schedule must begin at policy action0')
    return schedule


def save(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)


def run_probe(robot,output,schedule,version,init_state=19,max_actions=220,allow_synthetic=False,approval=None):
    validate_schedule(schedule,max_actions,approval)
    if type(init_state) is not int or init_state<0:raise ValueError('init_state must be nonnegative')
    if not isinstance(version,str) or not version.strip():raise ValueError('An explicit manual instruction version is required')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    aid='probe-'+uuid.uuid4().hex
    result={'attempt_id':aid,'condition':'diagnostic_instruction_probe',
        'provenance':'synthetic_fixture' if allow_synthetic else 'real_execution',
        'origin':'authored_skill_procedure','execution_provenance':None,'dataset_split':'memory_build',
        'task_goal':GOAL,'task_id':TASK_NAME,'success_criteria':{'id':'libero_task_predicate','version':'1'},
        'init_state_id':init_state,'seed':7,'status':'running','outcome':None,'step_index':0,
        'agent_api_calls':0,'external_database_used':False,'memory_snapshot_written':False,
        'manual_instruction_version':version,'schedule':schedule,'action_budget':max_actions,
        'diagnostic_instruction_approval':approval,
        'selection_note':'Predeclared authored-procedure calibration corpus. Eligible only for a separately frozen same-state recall demonstration, never the original evaluation snapshot. Not an agents_memory comparison result.',
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'decisions':[]}
    save(output/'manifest.json',result)
    session=None;started=time.monotonic()
    try:
        health=robot.health();result['worker_health_before']=health
        if not health.get('ready') or health.get('session_active'):
            raise RuntimeError('Worker must be ready with no active session')
        if not allow_synthetic and (health.get('model_training') is not False or health.get('trainable_parameter_count')!=0):
            raise RuntimeError('Frozen policy health must report training=false and zero trainable parameters')
        reset=robot.reset({'attempt_id':aid,'init_state_id':init_state,'seed':7,'task_name':TASK_NAME})
        session=reset['session_id'];manifest=reset['manifest'];obs=reset['observation']
        result['execution_provenance']=manifest.get('provenance');result['manifest']=manifest
        result['policy_id']=manifest.get('policy_id');result['robot_id']='libero_franka_panda'
        result['perception_mode']='simulator_assisted_task_rgb_planning'
        if not allow_synthetic and manifest.get('provenance')!='real_execution':
            raise ValueError('Diagnostic execution requires the real frozen worker')
        result['initial_context']=obs;save(output/'reset.json',reset);save(output/'manifest.json',result)
        cursor=0
        while result['step_index']<max_actions and not obs.get('task_success'):
            step=result['step_index']
            while cursor+1<len(schedule) and schedule[cursor+1]['start_step']<=step:cursor+=1
            next_change=schedule[cursor+1]['start_step'] if cursor+1<len(schedule) else max_actions
            if os.environ.get('ARMA_COMPUTE_MANIFEST'):
                from arma.cloud import assert_dispatch_window
                assert_dispatch_window(os.environ['ARMA_COMPUTE_MANIFEST'])
            index=len(result['decisions'])+1
            request={'attempt_id':aid,'execution_id':f'{aid}:{index}','expected_step_index':step,
                'observation_id':obs['observation_id'],'executed_instruction':schedule[cursor]['instruction'],
                'max_actions':min(10,max_actions-step,next_change-step)}
            # Persist intent first. On transport ambiguity RobotClient queries
            # execution status; this script never blindly repeats the action POST.
            save(output/f'execution-{index:04d}-request.json',request)
            execution=robot.execute(session,request)
            save(output/f'execution-{index:04d}.json',execution)
            if execution['actual_instruction']!=request['executed_instruction'] or execution['start_step_index']!=step:
                raise ValueError('Worker execution disagrees with the recorded request')
            if not step<execution['end_step_index']<=step+request['max_actions']:
                raise ValueError('Worker returned invalid action progress')
            result['decisions'].append({'decision_index':index,'manual_schedule_index':cursor,'execution':execution})
            result['step_index']=execution['end_step_index'];obs=execution['observation_after']
            save(output/'progress.json',result)
        result['outcome']='success' if obs.get('task_success') else 'failure'
        result['termination_reason']='goal_satisfied' if result['outcome']=='success' else 'step_budget_exhausted'
    except Exception as exc:
        result['outcome']='unknown';result['termination_reason']=type(exc).__name__;result['error']=str(exc)
    finally:
        if session:
            try:
                closed=robot.close(session);result['video_ref']=closed.get('video_ref');result['video_error']=closed.get('video_error')
            except Exception as exc:result['close_error']=f'{type(exc).__name__}: {exc}'
        result['status']='completed';result['elapsed_ms']=(time.monotonic()-started)*1000
        save(output/'attempt.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schedule',required=True,type=Path,help='JSON list of {start_step,instruction}; retained until the next scheduled change')
    parser.add_argument('--version',required=True,help='Explicit manual cue/version label')
    parser.add_argument('--output',required=True,type=Path,help='New empty output directory, never reuse a prior probe')
    parser.add_argument('--init-state',type=int,default=19)
    parser.add_argument('--max-actions',type=int,default=220)
    parser.add_argument('--worker-url',default='http://127.0.0.1:18001')
    parser.add_argument('--approved-instructions',type=Path,help='Explicit versioned task-preserving paraphrase approval JSON; diagnostic only')
    args=parser.parse_args();robot=RobotClient(args.worker_url)
    approval=json.loads(args.approved_instructions.read_text()) if args.approved_instructions else None
    try:result=run_probe(robot,args.output,json.loads(args.schedule.read_text()),args.version,args.init_state,args.max_actions,approval=approval)
    finally:robot.client.close()
    print(json.dumps({k:result.get(k) for k in ['attempt_id','condition','init_state_id','outcome','step_index','termination_reason','video_ref']}))
    return 2 if result['outcome']=='unknown' else 0

if __name__=='__main__':raise SystemExit(main())
