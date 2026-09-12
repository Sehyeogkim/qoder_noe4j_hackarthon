"""Run one real frozen-policy episode with local records and no external agents/DB."""
import argparse
import json
from pathlib import Path

from arma.agents import BaselineAgents
from arma.cli import export_artifacts
from arma.memory import InMemoryRepository
from arma.robot import RobotClient
from arma.runtime import Runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-url', default='http://127.0.0.1:18001')
    parser.add_argument('--artifacts', default='artifacts/gpu-baseline')
    parser.add_argument('--init-state', type=int, default=4)
    args = parser.parse_args()
    root = Path(args.artifacts).resolve()
    root.mkdir(parents=True, exist_ok=True)
    memory = InMemoryRepository()
    runner = Runner(RobotClient(args.worker_url), memory, BaselineAgents(), root,
                    max_actions=220, interval_actions=10)
    result = runner.run(args.init_state, 'baseline', 'smoke')
    replay = export_artifacts(root, root / 'replay', memory)
    summary = {key: result[key] for key in (
        'attempt_id', 'status', 'outcome', 'step_index', 'termination_reason')}
    summary.update(replay=str(replay), external_database_used=False, agent_api_calls=0)
    (root / 'baseline-summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
    return 2 if result['outcome'] == 'unknown' else 0


if __name__ == '__main__':
    raise SystemExit(main())
