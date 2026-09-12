import argparse
import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from .budget import Budget,BudgetExceeded
from .contracts import GOAL,TASK_NAME
from .runtime import Runner,now
from .robot import RobotClient
from .agents import GeminiAgents,FakeAgents
from .memory import Neo4jRepository,InMemoryRepository

def repository():
    required=['NEO4J_URI','NEO4J_USERNAME','NEO4J_PASSWORD']
    missing=[x for x in required if not os.environ.get(x)]
    if missing:raise RuntimeError('Missing environment settings: '+', '.join(missing))
    return Neo4jRepository(os.environ['NEO4J_URI'],os.environ['NEO4J_USERNAME'],os.environ['NEO4J_PASSWORD'],os.environ.get('NEO4J_DATABASE','neo4j'))

def export_artifacts(root,output,memory=None):
    from .replay import export_bundle
    attempts=[json.loads(p.read_text()) for p in sorted(root.glob('*/attempt.json'))]
    graph=memory.export_graph() if memory else {'nodes':[],'edges':[]}
    # A saved graph export permits future replay after the database is unavailable.
    if not memory and (root/'graph.json').exists():graph=json.loads((root/'graph.json').read_text())
    if memory:(root/'graph.json').write_text(json.dumps(graph,indent=2))
    bundle={'schema_version':'1','generated_at':now(),'attempts':attempts,'graph':graph,
            'selection_note':'All collected attempts are listed. Default pair is the lowest evaluated initialization index; synthetic fixtures are not experiments.'}
    return export_bundle(bundle,Path(output),root)

def make_fake(root,success_at=3):
    from worker.engine import Engine
    from worker.robots import FakeRobot
    from worker.protocol import ResetRequest,ExecutionRequest
    engine=Engine(FakeRobot(success_at=success_at),str(root/'worker'))
    class LocalRobot:
        def reset(self,p):return engine.reset(ResetRequest(**p))
        def execute(self,s,p):
            result=engine.execute(s,ExecutionRequest(**p))
            return result.model_dump() if hasattr(result,'model_dump') else result
        def close(self,s):return engine.close(s)
        def health(self):return engine.health()
    return LocalRobot()

def main(argv=None):
    load_dotenv()
    p=argparse.ArgumentParser(description='ARMA real executions and explicitly synthetic contract checks')
    p.add_argument('--artifacts',default=os.environ.get('ARMA_ARTIFACT_ROOT','artifacts'))
    p.add_argument('--config',default='configs/demo.yaml')
    subs=p.add_subparsers(dest='command',required=True)
    subs.add_parser('doctor');subs.add_parser('migrate-memory');subs.add_parser('smoke-gemini')
    fake=subs.add_parser('smoke');fake.add_argument('--output',default='replay-output')
    run=subs.add_parser('run');run.add_argument('--condition',choices=['baseline','agents_no_memory','agents_memory'],default='baseline')
    run.add_argument('--init-state',type=int,default=4);run.add_argument('--split',choices=['smoke','memory_build','evaluation'],default='smoke');run.add_argument('--snapshot')
    subs.add_parser('collect');subs.add_parser('compare')
    recover=subs.add_parser('recover-memory');recover.add_argument('attempt_id')
    export=subs.add_parser('export');export.add_argument('--output',default='replay-output');export.add_argument('--offline',action='store_true')
    args=p.parse_args(argv);root=Path(args.artifacts).resolve();root.mkdir(parents=True,exist_ok=True)
    import yaml
    config=yaml.safe_load(Path(args.config).read_text())
    if args.command=='doctor':
        settings={k:bool(os.environ.get(k)) for k in ['GEMINI_API_KEY','RUNPOD_API_KEY','NEO4J_URI','NEO4J_USERNAME','NEO4J_PASSWORD']}
        try:health=RobotClient(os.environ.get('ARMA_WORKER_URL','http://127.0.0.1:8001')).health()
        except Exception:health={'ready':False,'reason':'worker_unreachable'}
        print(json.dumps({'settings_present':settings,'worker':health,'budget':Budget().totals()},indent=2));return
    if args.command=='smoke':
        memory=InMemoryRepository();runner=Runner(make_fake(root),memory,FakeAgents(),root)
        result=runner.run(synthetic=True)
        print(json.dumps({'provenance':result['provenance'],'outcome':result['outcome'],'steps':result['step_index'],'replay':str(export_artifacts(root,args.output,memory))}))
        if result['outcome']=='unknown':raise SystemExit(2)
        return
    budget=Budget()
    if args.command=='smoke-gemini':
        from PIL import Image
        image=root/'gemini-smoke.png';Image.new('RGB',(256,256),'white').save(image)
        ctx={'attempt_id':'gemini_smoke','decision_index':1,'based_on_step':0,'observation_id':'smoke_frame','original_goal':GOAL,'success_criteria':{'id':'libero_task_predicate'},'last_evaluation':None}
        agents=GeminiAgents(budget,root)
        result=agents.plan(ctx,{'rgb_ref':str(image)})
        record={'status':'passed','input_provenance':'synthetic_smoke_image','decision':result.model_dump(),'usage':agents.calls}
        (root/'gemini-smoke.json').write_text(json.dumps(record,indent=2));print(json.dumps({'status':'passed','cost':budget.totals()}));return
    if args.command=='export':
        memory=None if args.offline else repository()
        print(export_artifacts(root,args.output,memory));return
    if args.command=='run' and args.condition=='baseline' and not os.environ.get('NEO4J_URI'):
        memory=InMemoryRepository()
    else:
        memory=repository()
    if args.command=='migrate-memory':memory.migrate();print('Neo4j migrations applied');return
    if args.command=='recover-memory':
        directory=(root/args.attempt_id).resolve()
        if not directory.is_relative_to(root):raise ValueError('Invalid attempt path')
        initial=json.loads((directory/'manifest.json').read_text())
        if initial['attempt_id']!=args.attempt_id:raise ValueError('Attempt identity mismatch')
        memory.start_attempt(initial)
        for file in sorted(directory.glob('decision-*.json')):
            record=json.loads(file.read_text());decision=record['decision']
            memory.commit_decision(args.attempt_id,decision['start_step_index'],decision,record['attempt_update'])
        committed=memory.get_attempt(args.attempt_id)
        local=json.loads((directory/'attempt.json').read_text()) if (directory/'attempt.json').exists() else {}
        if committed['status']=='running' and (directory/'interruption.json').exists():
            interruption=json.loads((directory/'interruption.json').read_text())
            # Keep committed counters; recovery never calls the worker.
            committed=memory.finalize_attempt(args.attempt_id,{"status":"completed","outcome":interruption['outcome'],
                "termination_reason":interruption['termination_reason'],"ended_at":interruption['ended_at']})
        recovered={**local,**committed,'persistence_status':'committed'}
        (directory/'attempt.json').write_text(json.dumps(recovered,indent=2))
        print(json.dumps({'attempt_id':args.attempt_id,'status':'recovered','outcome':recovered['outcome']}));return
    robot=RobotClient(os.environ.get('ARMA_WORKER_URL','http://127.0.0.1:8001'))
    agents=FakeAgents() if args.command=='run' and args.condition=='baseline' else GeminiAgents(budget,root)
    runner=Runner(robot,memory,agents,root,max_actions=config['max_actions'],interval_actions=config['interval_actions'])
    if args.command=='run':
        result=runner.run(args.init_state,args.condition,args.split,args.snapshot)
        print(json.dumps({k:result[k] for k in ['attempt_id','status','outcome','step_index','termination_reason']}))
        if result['outcome']=='unknown':raise SystemExit(2)
        return
    if args.command=='collect':
        results=[]
        for state in config['memory_build_states']:
            if budget.remaining()<0.25:break
            result=runner.run(state,'agents_no_memory','memory_build');results.append(result)
            if result['outcome']=='unknown':break
        for prior in sorted([r for r in results if r['outcome']=='failure'],key=lambda a:a['init_state_id'])[:config['max_retries']]:
            if budget.remaining()<0.25:break
            ids=[r['attempt_id'] for r in results if r['outcome'] in ('success','failure')]
            snap=f"build-{len(results)}-{int(time.time())}";memory.freeze_snapshot(snap,ids)
            results.append(runner.run(prior['init_state_id'],'agents_memory','memory_build',snap,prior['attempt_id']))
        ids=[r['attempt_id'] for r in results if r['outcome'] in ('success','failure')]
        if not ids:raise RuntimeError('No eligible real memory was collected')
        snapshot=memory.freeze_snapshot('evaluation-v1',ids)
        (root/'snapshot.json').write_text(json.dumps(snapshot,indent=2))
        print(json.dumps({'attempts':len(results),'snapshot':snapshot}));return
    if args.command=='compare':
        snapshot=json.loads((root/'snapshot.json').read_text())
        snapshot_id=snapshot.get('snapshot_id','evaluation-v1')
        completed=[]
        # Real measured cost and latency from collection inform a conservative group reserve.
        records=[json.loads(f.read_text()) for f in root.glob('*/attempt.json')]
        per_episode=max([r.get('cost_usd',0)*max(1,220/max(r.get('step_index',1),1)) for r in records]+[0.35])
        conditions=config.get('comparison_conditions',['agents_no_memory','agents_memory'])
        for state in config['evaluation_states']:
            if budget.remaining()<per_episode*2.5:break
            for condition in conditions:
                result=runner.run(state,condition,'evaluation',snapshot_id if condition=='agents_memory' else None)
                completed.append({k:result[k] for k in ['attempt_id','condition','init_state_id','outcome','step_index','cost_usd']})
                if result['outcome']=='unknown':break
            if completed[-1]['outcome']=='unknown':break
        target=len(config['evaluation_states'])*len(conditions)
        report={'runs':completed,'target_episodes':target,'complete':len(completed)==target and all(r['outcome']!='unknown' for r in completed),'budget':budget.totals(),
                'claim_boundary':'Small demonstration only; no general success-rate claim.'}
        (root/'comparison.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
        if not report['complete']:raise SystemExit(2)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Configuration names are useful; API response strings may contain secrets.
        print(f'ARMA stopped: {type(exc).__name__}',file=sys.stderr)
        if isinstance(exc,RuntimeError) and str(exc).startswith('Missing environment'):print(str(exc),file=sys.stderr)
        sys.exit(1)
