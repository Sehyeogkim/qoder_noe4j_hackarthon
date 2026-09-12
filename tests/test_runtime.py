"""CPU-only integration of real Runner + memory repository + worker HTTP API.

Synthetic workers and agents stay explicitly synthetic in every persisted record.
"""
import pytest
from fastapi.testclient import TestClient
from arma.agents import FakeAgents
from arma.contracts import Condition, GOAL
from arma.memory import InMemoryRepository, MemoryValidationError
from arma.robot import RobotClient
from arma.runtime import Runner
from worker.app import create_app
from worker.engine import Engine
from worker.robots import FakeRobot


def integrated(tmp_path,agents=None,success_at=3,max_actions=220,memory=None,interval_actions=10):
    fixture=FakeRobot(success_at=success_at)
    engine=Engine(fixture,tmp_path/'worker')
    client=RobotClient()
    client.client.close()
    client.client=TestClient(create_app(engine))
    repository=memory or InMemoryRepository()
    runner=Runner(client,repository,agents or FakeAgents(),tmp_path/'runs',max_actions=max_actions,interval_actions=interval_actions)
    return fixture,engine,runner,repository


def test_runner_worker_memory_complete_episode(tmp_path):
    fixture,engine,runner,memory=integrated(tmp_path)
    result=runner.run(attempt_id='integrated',synthetic=True)
    assert result['outcome']=='success'
    assert result['step_index']==3 and result['decision_index']==1
    assert result['provenance']=='synthetic'
    assert result['decisions'][0]['execution']['actual_instruction']==GOAL
    assert fixture.prediction_frames==[0,1,2]
    assert engine.session is None
    graph=memory.export_graph()
    assert any(e['type']=='HAS_ACTION' for e in graph['edges'])
    assert any(n['label']=='Evidence' for n in graph['nodes'])
    with pytest.raises(MemoryValidationError):
        memory.freeze_snapshot('no-synthetic-memory',['integrated'])


class UnavailableEvaluator(FakeAgents):
    def evaluate(self,*args):
        raise RuntimeError('injected evaluator outage')


def test_authoritative_success_survives_evaluator_outage(tmp_path):
    fixture,engine,runner,memory=integrated(tmp_path,agents=UnavailableEvaluator())
    result=runner.run(synthetic=True)
    assert result['outcome']=='success'
    evaluation=result['decisions'][0]['evaluation']
    assert evaluation['task_outcome']=='success'
    assert evaluation['evaluation_degraded'] is True
    assert evaluation['subtask_outcome']=='unknown'


class SubtaskSuccess(FakeAgents):
    def __init__(self):
        self.seen_contexts=[]
    def evaluate(self,ctx,planner,retrieval,result,outcome):
        self.seen_contexts.append(ctx)
        value=super().evaluate(ctx,planner,retrieval,result,outcome)
        value.subtask_outcome='success'
        value.subtask_evidence_refs=[result['observation_after']['evidence_id']]
        value.contexts=[Condition(kind='target_lifted',value='unknown',evidence_ids=[result['observation_after']['evidence_id']])]
        return value


def test_subtask_success_never_completes_whole_task_unknown_preserved(tmp_path):
    agents=SubtaskSuccess()
    fixture,engine,runner,memory=integrated(tmp_path,agents=agents,success_at=None,max_actions=6,interval_actions=3)
    result=runner.run(synthetic=True)
    assert fixture.step_count==6
    assert result['outcome']=='failure'
    decisions=result['decisions']
    assert len(decisions)==2
    assert decisions[0]['evaluation']['task_outcome'] is None
    assert decisions[0]['evaluation']['subtask_outcome']=='success'
    assert result['contexts'][0]['value']=='unknown'
    assert agents.seen_contexts[0]['original_goal']==GOAL
    assert agents.seen_contexts[0]['success_criteria']['id']=='libero_task_predicate'


class AmbiguousCommit(InMemoryRepository):
    """Commit succeeds, but first response is lost. Retry must be idempotent."""
    def __init__(self):
        super().__init__()
        self.commit_calls=0
    def commit_decision(self,*args):
        self.commit_calls+=1
        result=super().commit_decision(*args)
        if self.commit_calls==1:
            raise ConnectionError('injected lost commit response')
        return result


def test_persistence_retry_does_not_replay_robot(tmp_path,monkeypatch):
    monkeypatch.setattr('arma.runtime.time.sleep',lambda _:None)
    memory=AmbiguousCommit()
    fixture,engine,runner,_=integrated(tmp_path,memory=memory)
    result=runner.run(synthetic=True)
    assert result['outcome']=='success'
    assert memory.commit_calls==2
    assert fixture.step_count==3
    assert len(result['decisions'])==1


class StalePlanner(FakeAgents):
    def plan(self,*args):
        value=super().plan(*args)
        value.observation_id='stale-observation'
        return value


def test_stale_agent_decision_cannot_execute(tmp_path):
    fixture,engine,runner,memory=integrated(tmp_path,agents=StalePlanner())
    result=runner.run(synthetic=True)
    assert result['outcome']=='unknown'
    assert fixture.step_count==0
    assert engine.session is None


def test_fake_worker_cannot_be_recorded_as_real_baseline(tmp_path):
    fixture,engine,runner,memory=integrated(tmp_path)
    with pytest.raises(ValueError,match='Synthetic|synthetic|provenance'):
        runner.run(condition='baseline',synthetic=False)
    assert fixture.step_count==0


@pytest.mark.parametrize('violation',['empty_known','unseen_frame','duplicate_kind'])
def test_evaluator_unseen_or_ungrounded_conditions_are_degraded(tmp_path,violation):
    class Ungrounded(FakeAgents):
        def evaluate(self,ctx,planner,retrieval,result,outcome):
            value=super().evaluate(ctx,planner,retrieval,result,outcome)
            refs=[] if violation=='empty_known' else [result['actions'][0]['evidence_id']]
            if violation=='duplicate_kind':refs=[result['observation_after']['evidence_id']]
            value.contexts=[Condition(kind='target_lifted',value='true',evidence_ids=refs)]
            if violation=='duplicate_kind':value.contexts*=2
            return value
    fixture,engine,runner,memory=integrated(tmp_path,agents=Ungrounded())
    result=runner.run(synthetic=True)
    assert result['outcome']=='success'
    assert result['decisions'][0]['evaluation']['evaluation_degraded'] is True
    assert result['contexts']==[]


def test_rejected_candidate_evidence_cannot_support_adaptation(tmp_path):
    from arma.contracts import CandidateChoice
    class CandidateMemory(InMemoryRepository):
        def search_experiences(self,query):
            return [{'source_decision_id':'adopted','evidence_ids':['adopted-frame']},
                    {'source_decision_id':'rejected','evidence_ids':['rejected-frame']}]
    class CrossCiting(FakeAgents):
        def retrieve(self,*args):
            value=super().retrieve(*args);value.decision='adapt'
            value.source_decision_ids=['adopted'];value.evidence_ids=['rejected-frame']
            value.candidates=[CandidateChoice(source_decision_id='adopted',adopted=True,reason='test'),
                CandidateChoice(source_decision_id='rejected',adopted=False,reason='test')]
            return value
    fixture,engine,runner,memory=integrated(tmp_path,agents=CrossCiting(),memory=CandidateMemory())
    result=runner.run(condition='agents_memory',synthetic=True,snapshot_id='fixture')
    assert result['outcome']=='unknown'
    assert fixture.step_count==0
