"""Collect actual agent experience and evaluate a frozen, isolated demo snapshot."""
import argparse
import json
import os
import uuid
from pathlib import Path
from dotenv import load_dotenv
from arma.agents import GeminiAgents
from arma.budget import Budget
from arma.memory import Neo4jRepository
from arma.robot import RobotClient
from arma.runtime import Runner


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['collect','evaluate'])
    p.add_argument('--root',default='artifacts/first-demo')
    p.add_argument('--env-file',default='.env.first-demo')
    p.add_argument('--state',type=int,default=10)
    p.add_argument('--worker-url',default='http://127.0.0.1:18001')
    p.add_argument('--api-limit',type=float,default=2.0)
    args=p.parse_args()
    load_dotenv(args.env_file)
    root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=True)
    progress_path=root/'agent-progress.json'
    progress=json.loads(progress_path.read_text()) if progress_path.exists() else {'experiment_id':'first-demo-'+uuid.uuid4().hex,'collection':[],'evaluation':[]}
    budget=Budget(root/'api-budget.sqlite',api_limit=args.api_limit)
    memory=Neo4jRepository(os.environ['NEO4J_URI'],os.environ['NEO4J_USERNAME'],os.environ['NEO4J_PASSWORD'],os.environ.get('NEO4J_DATABASE','neo4j'))
    # Worker media live under the common artifact directory; never relax to '/'.
    agents=GeminiAgents(budget,root.parent)
    runner=Runner(RobotClient(args.worker_url),memory,agents,root,max_actions=220,interval_actions=10)
    def save():
        progress['api_budget_totals']=budget.totals()
        progress_path.write_text(json.dumps(progress,indent=2))
    def record(result,kind):
        row={k:result[k] for k in ('attempt_id','init_state_id','condition','outcome','step_index','termination_reason','cost_usd')}
        progress[kind].append(row);save();print(json.dumps(row),flush=True)
        if result['outcome']=='unknown':raise RuntimeError('Execution or evaluation unknown; inspect retained evidence before continuing')
    save()
    if args.mode=='collect':
        done={r['init_state_id'] for r in progress['collection'] if r['outcome'] in ('success','failure')}
        for state in [0,1]:
            if state not in done:
                record(runner.run(state,'agents_no_memory','memory_build'),'collection')
        ids=[r['attempt_id'] for r in progress['collection'] if r['outcome'] in ('success','failure')]
        if not ids:raise RuntimeError('No real completed memory')
        snapshot=memory.freeze_snapshot(progress['experiment_id']+'-snapshot',ids)
        progress['snapshot']=snapshot;save()
        print(json.dumps({'snapshot':snapshot,'api_budget_totals':budget.totals()}),flush=True)
    else:
        if not progress.get('snapshot'):raise RuntimeError('Collect and freeze memory first')
        record(runner.run(args.state,'agents_memory','evaluation',progress['snapshot']['snapshot_id']),'evaluation')
    ids=progress.get('snapshot',{}).get('attempt_ids',[])+[r['attempt_id'] for r in progress['evaluation']]
    (root/'experiment-graph.json').write_text(json.dumps(memory.export_graph(ids),indent=2))
    save()


if __name__=='__main__':main()
