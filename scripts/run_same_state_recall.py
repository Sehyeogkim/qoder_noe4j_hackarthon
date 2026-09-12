"""Explicit calibrated recall experiment. Imports real probes, then runs real agents."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from arma.agents import GeminiAgents
from arma.budget import Budget
from arma.contracts import TASK_NAME
from arma.memory import Neo4jRepository
from arma.robot import RobotClient
from arma.runtime import Runner
from scripts.import_instruction_probe import normalize_probe, apply_import


class MatchedRobotClient(RobotClient):
    def __init__(self, baseline, audit_path):
        super().__init__('http://127.0.0.1:18001')
        self.baseline,self.audit_path=baseline,Path(audit_path)

    def reset(self, request):
        result=super().reset(request)
        b=self.baseline;m=result['manifest']
        checks={
            'initial_rgb_hash':result['observation']['sha256']==b['initial_context']['sha256'],
            'policy_id':m.get('policy_id')==b['policy_id'],
            'init_state_id':m.get('init_state_id')==b['init_state_id'],
            'seed':m.get('seed')==b['seed'],
            'task_name':m.get('task_name')==TASK_NAME,
            'frozen':m.get('model_training') is False and m.get('trainable_parameter_count')==0,
        }
        self.audit_path.write_text(json.dumps({'checks':checks,'observation':result['observation'],'manifest':m},indent=2))
        if not all(checks.values()):
            self.close(result['session_id'])
            raise ValueError('Recall reset does not match baseline; no policy actions or agent calls dispatched')
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='artifacts/same-state-recall-v1')
    parser.add_argument('--protocol', default='configs/same_state_recall_v1.json')
    parser.add_argument('--env-file',default='.env.first-demo')
    parser.add_argument('--source-root',default='artifacts/instruction-calibration-v2')
    parser.add_argument('--baseline',default='artifacts/first-demo/83cdfc31a1354b80adf58289fbe5b617/attempt.json')
    parser.add_argument('--reuse-snapshot',help='Reuse these already imported exact source records without writing them again')
    args=parser.parse_args()
    root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=True)
    protocol_bytes=Path(args.protocol).read_bytes()
    protocol=json.loads(protocol_bytes)
    progress_path=root/'agent-progress.json'
    if progress_path.exists():
        raise RuntimeError('An experiment already started here. Inspect its execution status; never blindly replay it.')
    baseline=json.loads(Path(args.baseline).read_text())
    sources=[]
    for name in ('grasp_middle','put_middle'):
        path=Path(args.source_root)/name/'attempt.json';data=path.read_bytes();raw=json.loads(data)
        for field in ('task_goal','init_state_id','seed','policy_id'):
            if raw[field]!=baseline[field]:raise ValueError('Unmatched source/baseline '+field)
        if raw['initial_context']['sha256']!=baseline['initial_context']['sha256']:
            raise ValueError('Unmatched initialization image')
        sources.append(normalize_probe(raw,hashlib.sha256(data).hexdigest(),
            protocol=protocol,protocol_sha256=hashlib.sha256(protocol_bytes).hexdigest()))
    ids=[p['start_attempt']['attempt_id'] for p in sources]
    if ids!=protocol['corpus']['attempt_ids']:raise ValueError('Source IDs differ from predeclared protocol')
    if sources[0]['commits'][-1]['attempt_update']['outcome']!='failure' or sources[1]['commits'][-1]['attempt_update']['outcome']!='success':
        raise ValueError('Expected actual failed trial followed by successful trial')
    load_dotenv(args.env_file)
    memory=Neo4jRepository(os.environ['NEO4J_URI'],os.environ['NEO4J_USERNAME'],os.environ['NEO4J_PASSWORD'],os.environ.get('NEO4J_DATABASE','neo4j'))
    budget=Budget(root/'api-budget.sqlite',api_limit=protocol['paid_api_limit_usd'])
    progress={'experiment_id':protocol['experiment_id'],'protocol':protocol,'collection':[],'evaluation':[]}
    (root/'protocol.json').write_text(json.dumps(protocol,indent=2))
    def save():
        progress['api_budget_totals']=budget.totals()
        progress_path.write_text(json.dumps(progress,indent=2))
    save()
    for payload in sources:
        if args.reuse_snapshot:
            result=memory.get_attempt(payload['start_attempt']['attempt_id'])
            if result.get('import_provenance')!=payload['start_attempt']['import_provenance'] or result.get('previous_attempt_id')!=payload['start_attempt'].get('previous_attempt_id'):
                raise ValueError('Existing source provenance differs from the exact reviewed import')
        else:
            result=apply_import(memory,payload)
        progress['collection'].append({k:result.get(k) for k in ('attempt_id','condition','init_state_id','outcome','step_index')})
        (root/(result['attempt_id']+'-import.json')).write_text(json.dumps(payload,indent=2))
        save()
    snapshot=memory.freeze_snapshot(args.reuse_snapshot or protocol['experiment_id']+'-snapshot',ids)
    progress['snapshot']=snapshot;save()
    query={'snapshot_id':snapshot['snapshot_id'],'task_id':TASK_NAME,'robot_id':baseline['robot_id'],
           'policy_id':baseline['policy_id'],'perception_mode':baseline['perception_mode'],
           'stage':'approach','contexts':[],'based_on_step':0}
    candidates=memory.search_experiences(query)
    (root/'initial-retrieval-candidates.json').write_text(json.dumps(candidates,indent=2))
    print(json.dumps({'snapshot':snapshot,'candidate_attempts':[c['source_attempt_id'] for c in candidates]}),flush=True)
    agents=GeminiAgents(budget,root.parent)
    robot=MatchedRobotClient(baseline,root/'recall-reset-audit.json')
    runner=Runner(robot,memory,agents,root,max_actions=220,interval_actions=10)
    try:
        result=runner.run(protocol['init_state_id'],'agents_memory','evaluation',snapshot['snapshot_id'])
        row={k:result.get(k) for k in ('attempt_id','init_state_id','condition','outcome','step_index','termination_reason','cost_usd')}
        progress['evaluation'].append(row);save();print(json.dumps(row),flush=True)
        (root/'experiment-graph.json').write_text(json.dumps(memory.export_graph(ids+[result['attempt_id']]),indent=2))
    finally:
        save();robot.client.close()

if __name__=='__main__':main()
