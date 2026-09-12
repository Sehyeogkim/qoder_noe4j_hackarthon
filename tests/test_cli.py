"""CLI contract tests run without cloud credentials, paid APIs, or a robot."""
import json
from pathlib import Path

import pytest

from arma import cli
from arma.budget import Budget
from arma.memory import InMemoryRepository


@pytest.fixture(autouse=True)
def no_credentials_or_paid_services(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, 'load_dotenv', lambda: None)
    for key in ('GEMINI_API_KEY','GOOGLE_API_KEY','NEO4J_URI','NEO4J_USERNAME','NEO4J_PASSWORD','RUNPOD_API_KEY','ARMA_COMPUTE_MANIFEST'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cli,'Budget',lambda:Budget(tmp_path/'budget.sqlite'))


def test_smoke_creates_honestly_labeled_offline_replay(tmp_path, capsys, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Smoke must not invoke paid services or Neo4j')
    monkeypatch.setattr(cli,'repository',forbidden)
    monkeypatch.setattr(cli,'GeminiAgents',forbidden)
    root=tmp_path/'artifacts'; output=tmp_path/'replay'
    cli.main(['--artifacts',str(root),'smoke','--output',str(output)])
    report=json.loads(capsys.readouterr().out)
    assert report['provenance']=='synthetic'
    assert report['outcome']=='success' and report['steps']==3
    bundle=json.loads((output/'bundle.json').read_text())
    assert len(bundle['attempts'])==1
    assert bundle['attempts'][0]['provenance']=='synthetic'
    assert bundle['attempts'][0]['step_index']==3
    assert (output/'index.html').is_file() and (output/'bundle.js').is_file()
    assert bundle['graph']['nodes']
    assert 'real_execution' not in {a['provenance'] for a in bundle['attempts']}


def test_offline_export_uses_saved_graph_without_repository(tmp_path,capsys,monkeypatch):
    root=tmp_path/'artifacts'; (root/'test-run').mkdir(parents=True)
    (root/'test-run'/'attempt.json').write_text(json.dumps({'attempt_id':'test-run','provenance':'synthetic','decisions':[]}))
    graph={'nodes':[{'id':'Attempt:test-run','label':'Attempt','properties':{'attempt_id':'test-run'}}], 'edges':[]}
    (root/'graph.json').write_text(json.dumps(graph))
    monkeypatch.setattr(cli,'repository',lambda:pytest.fail('Offline export opened Neo4j'))
    output=tmp_path/'offline'
    cli.main(['--artifacts',str(root),'export','--offline','--output',str(output)])
    assert Path(capsys.readouterr().out.strip())==output/'index.html'
    data=json.loads((output/'bundle.json').read_text())
    assert data['graph']==graph and data['attempts'][0]['attempt_id']=='test-run'


def test_baseline_does_not_require_gemini_or_neo4j(tmp_path,capsys,monkeypatch):
    monkeypatch.setattr(cli,'repository',lambda:pytest.fail('Standalone baseline required Neo4j'))
    monkeypatch.setattr(cli,'GeminiAgents',lambda *a,**k:pytest.fail('Baseline instantiated paid Gemini client'))
    monkeypatch.setattr(cli,'RobotClient',lambda *a,**k:object())
    calls=[]
    class Runner:
        def __init__(self,*args,**kwargs):pass
        def run(self,*args):
            calls.append(args)
            return {'attempt_id':'baseline','status':'completed','outcome':'failure','step_index':220,'termination_reason':'step_budget_exhausted'}
    monkeypatch.setattr(cli,'Runner',Runner)
    cli.main(['--artifacts',str(tmp_path/'artifacts'),'run','--condition','baseline','--init-state','4'])
    report=json.loads(capsys.readouterr().out)
    assert report['outcome']=='failure'  # Valid measured failure is not infrastructure failure.
    assert calls==[(4,'baseline','smoke',None)]


def test_unknown_run_reports_nonzero_exit_for_automation(tmp_path,capsys,monkeypatch):
    monkeypatch.setattr(cli,'repository',lambda:InMemoryRepository())
    monkeypatch.setattr(cli,'GeminiAgents',lambda *a,**k:object())
    monkeypatch.setattr(cli,'RobotClient',lambda *a,**k:object())
    class Runner:
        def __init__(self,*args,**kwargs):pass
        def run(self,*args):
            return {'attempt_id':'unknown','status':'completed','outcome':'unknown','step_index':0,'termination_reason':'worker_unreachable'}
    monkeypatch.setattr(cli,'Runner',Runner)
    with pytest.raises(SystemExit) as failure:
        cli.main(['--artifacts',str(tmp_path/'artifacts'),'run','--condition','agents_no_memory'])
    assert failure.value.code==2
    assert json.loads(capsys.readouterr().out)['outcome']=='unknown'


def test_doctor_prints_presence_only_without_credential_values(tmp_path,capsys,monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test-secret-never-render')
    class Robot:
        def health(self):raise RuntimeError('private transport details')
    monkeypatch.setattr(cli,'RobotClient',lambda *a,**k:Robot())
    cli.main(['--artifacts',str(tmp_path/'artifacts'),'doctor'])
    output=capsys.readouterr().out
    report=json.loads(output)
    assert report['settings_present']['GEMINI_API_KEY'] is True
    assert report['worker']['ready'] is False
    assert 'test-secret-never-render' not in output and 'private transport details' not in output


def test_recover_memory_replays_outbox_idempotently_without_robot(tmp_path,capsys,monkeypatch):
    root=tmp_path/'artifacts';directory=root/'recoverable';directory.mkdir(parents=True)
    initial={'attempt_id':'recoverable','task_goal':'put bowl on plate','status':'running','outcome':None,'step_index':0,'provenance':'synthetic','dataset_split':'smoke'}
    (directory/'manifest.json').write_text(json.dumps(initial))
    for index in (1,2):
        decision={'decision_id':f'recoverable:{index}','decision_index':index,'start_step_index':index-1,'end_step_index':index,
                  'planner':{},'retrieval':{},'evaluation':{},'execution':{'actions':[{'step_index':index}]},'contexts':[],'evidence':[]}
        update={'step_index':index,'status':'running' if index==1 else 'completed','outcome':None if index==1 else 'success'}
        (directory/f'decision-{index:04d}.json').write_text(json.dumps({'decision':decision,'attempt_update':update}))
    (directory/'attempt.json').write_text(json.dumps({**initial,'outcome':'success','status':'completed','persistence_status':'pending_outbox'}))
    memory=InMemoryRepository()
    monkeypatch.setattr(cli,'repository',lambda:memory)
    monkeypatch.setattr(cli,'RobotClient',lambda *a,**k:pytest.fail('Recovery touched robot'))
    monkeypatch.setattr(cli,'GeminiAgents',lambda *a,**k:pytest.fail('Recovery touched Gemini'))
    for _ in range(2):
        cli.main(['--artifacts',str(root),'recover-memory','recoverable'])
        assert json.loads(capsys.readouterr().out)['outcome']=='success'
    saved=json.loads((directory/'attempt.json').read_text())
    assert saved['step_index']==2 and saved['persistence_status']=='committed'
    graph=memory.export_graph()
    assert len([n for n in graph['nodes'] if n['label']=='DecisionStep'])==2
    assert len([n for n in graph['nodes'] if n['label']=='StepEvent'])==2
