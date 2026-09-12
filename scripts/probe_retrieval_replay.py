"""Post-hoc planner/retrieval demonstration from stored RGB. Never executes a robot."""
import hashlib
import json
import os
from pathlib import Path
import uuid
from dotenv import load_dotenv
from arma.agents import GeminiAgents
from arma.budget import Budget
from arma.contracts import GOAL,TASK_NAME
from arma.memory import Neo4jRepository


def main():
    root=Path('artifacts/posthoc-retrieval-35-v1');root.mkdir(exist_ok=False)
    load_dotenv('.runtime/first-demo.env')
    outer=Budget();rid=outer.reserve(.35,metadata={'purpose':'post-hoc stored observation planner/retrieval; no robot','model':'gemini-3.5-flash'})
    (root/'reservation.json').write_text(json.dumps({'reservation_id':rid,'maximum_usd':.35}))
    budget=Budget(root/'api-budget.sqlite',api_limit=.35)
    agents=GeminiAgents(budget,'artifacts',model='gemini-3.5-flash')
    record={'mode':'posthoc_stored_observation_retrieval','robot_executed':False,'writes_to_memory':False,
        'model':agents.model,'retrieval_input_version':agents.retrieval_input_version,
        'limitation':'Generated after the successful direct instruction video. This output did not cause that recorded execution.'}
    def save():
        record['calls']=agents.calls;record['budget']=budget.totals()
        (root/'record.json').write_text(json.dumps(record,indent=2,ensure_ascii=False))
    def localize(value):
        if isinstance(value,str) and value.startswith('/workspace/arma/artifacts/'):
            return str(Path(value.replace('/workspace/arma/',str(Path.cwd())+'/',1)))
        if isinstance(value,list):return [localize(x) for x in value]
        if isinstance(value,dict):return {k:localize(v) for k,v in value.items()}
        return value
    try:
        audit=json.loads(Path('artifacts/same-state-recall-v1/recall-reset-audit.json').read_text())
        obs=localize(audit['observation'])
        assert hashlib.sha256(Path(obs['rgb_ref']).read_bytes()).hexdigest()==obs['sha256']
        ctx={'attempt_id':'posthoc-'+uuid.uuid4().hex,'decision_index':1,'based_on_step':0,
            'observation_id':obs['observation_id'],'original_goal':GOAL,
            'success_criteria':{'id':'libero_task_predicate','version':'1'},'current_instruction':GOAL,
            'allowed_current_evidence_ids':[obs['evidence_id']],'last_evaluation':None,'remaining_actions':220}
        record.update(context=ctx,observation=obs,source_observation_file='artifacts/same-state-recall-v1/recall-reset-audit.json')
        record['prompts']={p.name:{'text':p.read_text(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in Path('prompts').glob('*.md')}
        save()
        planner=agents.plan(ctx,obs);record['planner']=planner.model_dump();save()
        memory=Neo4jRepository(os.environ['NEO4J_URI'],os.environ['NEO4J_USERNAME'],os.environ['NEO4J_PASSWORD'],os.environ.get('NEO4J_DATABASE','neo4j'))
        query={'snapshot_id':'same-state-recall-v1-snapshot','task_id':TASK_NAME,
            'robot_id':'libero_franka_panda','policy_id':audit['manifest']['policy_id'],
            'perception_mode':'simulator_assisted_task_rgb_planning','stage':planner.stage,'contexts':[],'based_on_step':0}
        candidates=localize(memory.search_experiences(query));record.update(query=query,candidates=candidates);save()
        retrieval=agents.retrieve(ctx,planner,candidates,obs);record['retrieval']=retrieval.model_dump();record['status']='completed';save()
        print(json.dumps({'status':'completed','decision':retrieval.decision,'instruction':retrieval.executed_instruction,'reason':retrieval.reason,'cost':budget.totals()},ensure_ascii=False))
    except Exception as exc:
        record.update(status='error',error_type=type(exc).__name__);save();raise
    finally:
        save();outer.settle(rid,budget.totals()['api'],{'purpose':record['mode'],'child_ledger':str(root/'api-budget.sqlite')})

if __name__=='__main__':main()
