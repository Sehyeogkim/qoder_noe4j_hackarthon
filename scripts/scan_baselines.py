"""Record an explicitly exploratory baseline scan; never force a failure."""
import argparse
import json
from pathlib import Path
from arma.agents import BaselineAgents
from arma.memory import InMemoryRepository
from arma.robot import RobotClient
from arma.runtime import Runner


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--states',type=int,nargs='+',default=[0,1,10,11,12])
    p.add_argument('--root',default='artifacts/first-demo')
    p.add_argument('--worker-url',default='http://127.0.0.1:18001')
    args=p.parse_args()
    root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=True)
    log={'selection_rule':'Ascending supplied state order; stop at first actual failure. Exploratory selection, not an aggregate or held-out claim.','requested_states':args.states,'attempts':[]}
    (root/'scan.json').write_text(json.dumps(log,indent=2))
    runner=Runner(RobotClient(args.worker_url),InMemoryRepository(),BaselineAgents(),root,max_actions=220,interval_actions=10)
    for state in args.states:
        result=runner.run(state,'baseline','smoke')
        summary={k:result[k] for k in ('attempt_id','init_state_id','outcome','step_index','termination_reason')}
        log['attempts'].append(summary)
        (root/'scan.json').write_text(json.dumps(log,indent=2))
        print(json.dumps(summary),flush=True)
        if result['outcome'] in ('failure','unknown'):
            break


if __name__=='__main__':main()
