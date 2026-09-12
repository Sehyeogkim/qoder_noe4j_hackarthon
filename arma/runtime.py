"""Sequential routing and validation; deliberately not a fourth agent."""
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .contracts import GOAL,TASK_NAME,SKILL,STAGES,EvaluationRecord,validate_envelope,validate_evaluation,validate_planner,validate_retrieval,expected_outcome
from .agents import FakeAgents,BaselineAgents
from .memory import RETRIEVAL_RANKING_VERSION
from .contracts import INSTRUCTION_CONTROLLER_VERSION

def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()

class Runner:
    def __init__(self,robot,memory,agents,artifact_root="artifacts",max_actions=220,interval_actions=10):
        if not 1<=interval_actions<=10 or not 1<=max_actions<=220:raise ValueError("Invalid execution budget")
        self.robot,self.memory,self.agents=robot,memory,agents
        self.root=Path(artifact_root);self.root.mkdir(parents=True,exist_ok=True)
        self.max_actions,self.interval_actions=max_actions,interval_actions

    def run(self, init_state_id=4, condition="agents_no_memory", dataset_split="smoke", snapshot_id=None,
            previous_attempt_id=None, attempt_id=None, synthetic=False):
        if condition not in ("baseline","agents_no_memory","agents_memory"):raise ValueError("Unsupported condition")
        if condition=="agents_memory" and not snapshot_id:raise ValueError("Memory requires a frozen snapshot")
        attempt_id=attempt_id or uuid.uuid4().hex
        reset=self.robot.reset({"attempt_id":attempt_id,"init_state_id":init_state_id,"seed":7,"task_name":TASK_NAME})
        sid=reset["session_id"];obs=reset["observation"];manifest=reset["manifest"]
        worker_synthetic=manifest.get("provenance") != "real_execution"
        if worker_synthetic and not synthetic:
            self.robot.close(sid);raise ValueError("Synthetic worker cannot create a real execution")
        if isinstance(self.agents,FakeAgents) and condition!="baseline" and not synthetic:
            self.robot.close(sid);raise ValueError("Synthetic agents cannot create a real agent run")
        policy_id=manifest.get("policy_id")
        if not policy_id:
            self.robot.close(sid);raise ValueError('Worker must provide a stable policy_id')
        prompt_root=Path(__file__).resolve().parent.parent/'prompts'
        manifest={**manifest,'agent_model':None if condition=='baseline' else getattr(self.agents,'model','synthetic_fixture'),
            'agent_calls_enabled':condition!='baseline',
            'retrieval_input_version':getattr(self.agents,'retrieval_input_version',None),
            'retrieval_ranking_version':RETRIEVAL_RANKING_VERSION,
            'instruction_controller_version':INSTRUCTION_CONTROLLER_VERSION,
            'backend_source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).resolve().parent.glob('*.py'))},
            'prompt_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(prompt_root.glob('*.md'))},
            'skill_hash':digest(SKILL),'memory_snapshot_id':snapshot_id,
            'interval_actions':self.interval_actions,'action_budget':self.max_actions}
        attempt={"attempt_id":attempt_id,"run_id":attempt_id,"task_id":TASK_NAME,"task_goal":GOAL,
            "success_criteria":{"id":"libero_task_predicate","version":"1"},"initial_context":obs,
            "executed_instruction":GOAL,"status":"running","outcome":None,"termination_reason":None,
            "step_index":0,"decision_index":0,"latest_observation_ref":obs["rgb_ref"],"observation":obs,
            "evidence_refs":[],"judgment_source":"simulator_task_predicate","observed_facts":[],"cause_hypothesis":None,
            "previous_attempt_id":previous_attempt_id,"robot_id":"libero_franka_panda","policy_id":policy_id,
            "perception_mode":"simulator_assisted_task_rgb_planning","dataset_split":dataset_split,
            "memory_snapshot_id":snapshot_id,"provenance":"synthetic" if synthetic else "real_execution",
            "condition":condition,"init_state_id":init_state_id,"seed":7,"started_at":now(),
            "manifest":manifest,"skill":SKILL,"schema_version":"1","contexts":[],"decisions":[]}
        directory=self.root/attempt_id;directory.mkdir(parents=True,exist_ok=True)
        (directory/'manifest.json').write_text(json.dumps(attempt,indent=2))
        try:
            self.memory.start_attempt(attempt)
        except Exception:
            self.robot.close(sid)
            raise
        started=time.monotonic();replans=0;last_evaluation=None;last_result=None;pending_update=None
        call_start=len(getattr(self.agents,'calls',[]))
        try:
            if obs.get('task_success'):
                attempt=self.memory.finalize_attempt(attempt_id,{"status":"completed","outcome":"success","termination_reason":"goal_satisfied","ended_at":now()})
            while attempt['status']=='running':
                # This state comes from the committed repository record.
                obs=attempt['observation']
                ctx={"attempt_id":attempt_id,"decision_index":attempt['decision_index']+1,
                    "based_on_step":attempt['step_index'],"observation_id":obs['observation_id'],
                    "original_goal":GOAL,"success_criteria":attempt['success_criteria'],
                    "current_instruction":attempt.get('executed_instruction') or GOAL,
                    "allowed_current_evidence_ids":[obs['evidence_id']],
                    "last_evaluation":last_evaluation,"remaining_actions":self.max_actions-attempt['step_index']}
                active=BaselineAgents() if condition=='baseline' else self.agents
                planner=active.plan(ctx,obs);validate_planner(planner,ctx)
                candidates=[]
                if condition=='agents_memory':
                    candidates=self.memory.search_experiences({"snapshot_id":snapshot_id,"task_id":TASK_NAME,
                        "robot_id":attempt['robot_id'],"policy_id":policy_id,"perception_mode":attempt['perception_mode'],
                        "stage":planner.stage,"contexts":attempt.get('contexts',[]),"based_on_step":attempt['step_index']})
                retrieval=active.retrieve(ctx,planner,candidates,obs);validate_retrieval(retrieval,ctx,candidates)
                if retrieval.decision=='request_replan':
                    replans+=1
                    if replans>2:raise RuntimeError('replan_budget_exhausted')
                    ctx['replan_reason']=retrieval.reason
                    last_evaluation={"replan_reason":retrieval.reason}
                    continue
                replans=0
                execution_id=f"{attempt_id}:{ctx['decision_index']}"
                import os
                if os.environ.get('ARMA_COMPUTE_MANIFEST'):
                    from .cloud import assert_dispatch_window
                    assert_dispatch_window(os.environ['ARMA_COMPUTE_MANIFEST'])
                result=self.robot.execute(sid,{"attempt_id":attempt_id,"execution_id":execution_id,
                    "expected_step_index":attempt['step_index'],"observation_id":obs['observation_id'],
                    "executed_instruction":retrieval.executed_instruction,
                    "max_actions":min(self.interval_actions,self.max_actions-attempt['step_index'])})
                last_result=result
                if result['start_step_index']!=attempt['step_index'] or result['end_step_index']<=attempt['step_index']:
                    raise ValueError('Invalid execution interval')
                if result['actual_instruction']!=retrieval.executed_instruction:raise ValueError('Executed instruction mismatch')
                outcome,termination=expected_outcome(result,self.max_actions)
                env={k:ctx[k] for k in ('attempt_id','decision_index','based_on_step','observation_id')}
                # The evaluator receives only these two images. Intermediate
                # action records remain inspectable logs, not seen visual proof.
                evidence_ids={result['observation_before']['evidence_id'],result['observation_after']['evidence_id']}
                evaluation=None;evaluation_error=None
                try:
                    evaluation=active.evaluate(ctx,planner,retrieval,result,outcome)
                    validate_evaluation(evaluation,ctx,outcome,evidence_ids)
                except Exception as exc:
                    evaluation_error={'type':type(exc).__name__,'message':str(exc),
                        'rejected_record':evaluation.model_dump() if evaluation is not None else None}
                    # Always retain the robot result, especially authoritative success.
                    evaluation=EvaluationRecord(**env,task_outcome=outcome,subtask_outcome='unknown',
                        task_evidence_refs=[result['observation_after']['evidence_id']],subtask_evidence_refs=[],
                        observed_facts=[],contexts=[],evaluation_degraded=True,subtask_judgment_source='unavailable')
                    if outcome is None:outcome,termination='unknown','evaluator_unavailable'
                    evaluation.task_outcome=outcome
                contexts=[c.model_dump() for c in evaluation.contexts]
                evidence=[]
                for item in [result['observation_before'],*result['actions'],result['observation_after']]:
                    ref=item['rgb_ref'];p=Path(ref)
                    evidence.append({"evidence_id":item['evidence_id'],"uri":ref,"type":"image/png",
                        "hash":hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None})
                decision={"decision_id":execution_id,"decision_index":ctx['decision_index'],
                    "start_step_index":result['start_step_index'],"end_step_index":result['end_step_index'],
                    "planner":planner.model_dump(),"retrieval":retrieval.model_dump(),"evaluation":evaluation.model_dump(),
                    "evaluation_error":evaluation_error,
                    "execution":result,"contexts":attempt.get('contexts',[]),"evidence":evidence}
                update={"step_index":result['end_step_index'],"decision_index":ctx['decision_index'],
                    "observation":result['observation_after'],"latest_observation_ref":result['observation_after']['rgb_ref'],
                    "executed_instruction":retrieval.executed_instruction,"outcome":outcome,"termination_reason":termination,
                    "status":"completed" if outcome else 'running',"contexts":contexts,
                    "observed_facts":evaluation.observed_facts,"cause_hypothesis":evaluation.cause_hypothesis,
                    "evidence_refs":evaluation.task_evidence_refs,"ended_at":now() if outcome else None}
                pending_update=update
                # Local outbox exists before the atomic DB write; no actions in retries.
                outbox=directory/f"decision-{ctx['decision_index']:04d}.json"
                outbox.write_text(json.dumps({"decision":decision,"attempt_update":update},indent=2))
                for n in range(3):
                    try:
                        self.memory.commit_decision(attempt_id,attempt['step_index'],decision,update);break
                    except Exception:
                        if n==2:raise RuntimeError('persistence_blocked')
                        time.sleep(0.2*(n+1))
                attempt=self.memory.get_attempt(attempt_id)
                pending_update=None
                last_evaluation=evaluation.model_dump()
        except Exception as exc:
            # Do not expose API tokens or arbitrary SDK error payloads in artifacts.
            failure={"status":"completed","outcome":"unknown","termination_reason":type(exc).__name__,"ended_at":now()}
            if pending_update is not None:
                failure.update(pending_update)
                failure.update({'status':'completed','outcome':pending_update['outcome'] or 'unknown',
                    'termination_reason':pending_update['termination_reason'] or 'persistence_blocked',
                    'persistence_status':'pending_outbox','ended_at':now()})
            elif last_result and last_result.get('task_success'):
                failure.update({'outcome':'success','termination_reason':'goal_satisfied',
                    'step_index':last_result['end_step_index'],'persistence_status':'pending_outbox'})
            (directory/'interruption.json').write_text(json.dumps(failure))
            try:
                if pending_update is not None:raise RuntimeError('Replay outbox before finalization')
                attempt=self.memory.finalize_attempt(attempt_id,failure)
            except Exception:attempt.update(failure)
        finally:
            try:
                closed=self.robot.close(sid)
                if closed.get('video_ref'):attempt['video_ref']=closed['video_ref']
                if closed.get('video_error'):attempt['video_error']=closed['video_error']
            except Exception:pass
        attempt['elapsed_ms']=(time.monotonic()-started)*1000
        attempt['api_calls']=getattr(self.agents,'calls',[])[call_start:]
        attempt['cost_usd']=sum(x.get('cost_usd',0) for x in attempt['api_calls'])
        # Repository is source of decision records; local metadata adds replay assets.
        if not attempt.get('decisions'):
            attempt['decisions']=[json.loads(p.read_text())['decision'] for p in sorted(directory.glob('decision-*.json'))]
        (directory/'attempt.json').write_text(json.dumps(attempt,indent=2))
        return attempt
