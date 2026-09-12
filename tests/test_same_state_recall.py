"""No-network checks for the calibrated recall reset boundary."""
import copy
import json

import pytest

from arma.contracts import TASK_NAME
from arma.memory import InMemoryRepository
from arma.robot import RobotClient
from arma.runtime import Runner
from scripts.run_same_state_recall import MatchedRobotClient


def baseline():
    return {'initial_context': {'sha256': 'baseline-frame-hash'},
            'policy_id': 'frozen-policy', 'init_state_id': 19, 'seed': 7}


def reset_result():
    return {'session_id': 'mock-session',
            'observation': {'sha256': 'baseline-frame-hash'},
            'manifest': {'policy_id': 'frozen-policy', 'init_state_id': 19, 'seed': 7,
                         'task_name': TASK_NAME, 'model_training': False,
                         'trainable_parameter_count': 0}}


def install_robot(monkeypatch, response):
    calls = []
    monkeypatch.setattr(RobotClient, '__init__', lambda self, url: None)
    monkeypatch.setattr(RobotClient, 'reset', lambda self, request: copy.deepcopy(response))
    monkeypatch.setattr(RobotClient, 'close', lambda self, sid: calls.append(('close', sid)))
    monkeypatch.setattr(RobotClient, 'execute', lambda self, *args: calls.append(('execute', args)))
    return calls


def test_matching_reset_returns_record_and_writes_audit_without_actions(monkeypatch, tmp_path):
    response = reset_result()
    calls = install_robot(monkeypatch, response)
    path = tmp_path / 'reset-audit.json'
    robot = MatchedRobotClient(baseline(), path)
    assert robot.reset({'init_state_id': 19}) == response
    audit = json.loads(path.read_text())
    assert all(audit['checks'].values())
    assert audit['observation'] == response['observation']
    assert calls == []


@pytest.mark.parametrize('section,key,value,failed_check', [
    ('observation', 'sha256', 'different-frame', 'initial_rgb_hash'),
    ('manifest', 'policy_id', 'another-policy', 'policy_id'),
    ('manifest', 'init_state_id', 20, 'init_state_id'),
    ('manifest', 'seed', 8, 'seed'),
    ('manifest', 'task_name', 'another_task', 'task_name'),
    ('manifest', 'model_training', True, 'frozen'),
    ('manifest', 'trainable_parameter_count', 1, 'frozen'),
])
def test_mismatch_closes_session_before_any_agent_or_policy_dispatch(monkeypatch, tmp_path, section, key, value, failed_check):
    response = reset_result()
    response[section][key] = value
    calls = install_robot(monkeypatch, response)
    path = tmp_path / 'reset-audit.json'
    robot = MatchedRobotClient(baseline(), path)
    class NoPaidAgents:
        def plan(self, *args):
            pytest.fail('An agent call must not run after an unmatched reset')
    memory = InMemoryRepository()
    runner = Runner(robot, memory, NoPaidAgents(), tmp_path / 'artifacts')
    with pytest.raises(ValueError, match='Recall reset does not match baseline'):
        runner.run(19, 'agents_memory', 'evaluation', 'test-snapshot')
    assert calls == [('close', 'mock-session')]
    assert json.loads(path.read_text())['checks'][failed_check] is False
    assert memory.export_graph()['nodes'] == []
