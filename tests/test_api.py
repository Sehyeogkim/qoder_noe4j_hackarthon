import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arma.api import create_app


@pytest.fixture
def root(tmp_path, monkeypatch):
    for key in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "frame.png").write_bytes(b"png-test-bytes")
    (tmp_path / "a" / "attempt.json").write_text(json.dumps({
        "attempt_id":"a", "provenance":"synthetic", "dataset_split":"evaluation", "init_state_id":10,
        "task_goal":"put bowl on plate", "outcome":"success", "observation":{"rgb_ref":"a/frame.png"},
        "api_key":"do-not-render", "nested":{"password":"do-not-render", "input_tokens":10},
    }))
    return tmp_path


def test_read_routes_and_existing_ui_load_dynamic_bundle(root):
    client=TestClient(create_app(root))
    assert client.get('/health').json()['mode']=='recorded_read_only'
    assert client.get('/').status_code==200
    assert 'bundle.js' in client.get('/').text
    assert client.get('/app.js').status_code==200
    assert client.get('/styles.css').status_code==200
    assert client.get('/runs').json()['runs'][0]['attempt_id']=='a'
    assert client.get('/runs/a').json()['provenance']=='synthetic'
    assert client.get('/runs/missing').status_code==404
    assert client.post('/runs').status_code==405
    bundle=client.get('/api/bundle').json()
    assert bundle['graph_source']=='unavailable'
    image=bundle['attempts'][0]['observation']['rgb_ref']
    assert image.startswith('assets/')
    assert client.get('/'+image).content==b'png-test-bytes'
    assert client.get('/bundle.js').text.startswith('window.ARMA_BUNDLE = ')


def test_secret_values_and_keys_are_not_rendered(root,monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','private-value-123')
    path=root/'a'/'attempt.json';record=json.loads(path.read_text())
    record['message']='failure private-value-123';record['endpoint']='neo4j+s://name:password@db.test'
    path.write_text(json.dumps(record))
    client=TestClient(create_app(root))
    for route in ('/runs','/runs/a','/api/bundle','/bundle.js'):
        response=client.get(route)
        assert 'do-not-render' not in response.text and 'private-value-123' not in response.text
        assert 'name:password@' not in response.text
    assert client.get('/runs/a').json()['nested']['input_tokens']==10


def test_graph_repository_preferred_and_failure_fallback_explicit(root):
    class Memory:
        def export_graph(self):return {'nodes':[{'id':'actual'}],'edges':[]}
    (root/'graph.json').write_text(json.dumps({'nodes':[{'id':'saved'}],'edges':[]}))
    client=TestClient(create_app(root,memory=Memory()))
    assert client.get('/graph').json()=={'nodes':[{'id':'actual'}],'edges':[],'source':'repository'}
    class Broken:
        def export_graph(self):raise RuntimeError('secret database error')
    response=TestClient(create_app(root,memory=Broken())).get('/graph')
    assert response.json()['source']=='saved_graph'
    assert response.json()['nodes'][0]['id']=='saved'
    assert 'secret database error' not in response.text


def test_traversal_symlinks_and_nonmedia_artifacts_are_denied(root,tmp_path_factory):
    outside=tmp_path_factory.mktemp('outside');(outside/'secret.png').write_bytes(b'not permitted')
    (root/'a'/'linked.png').symlink_to(outside/'secret.png')
    (root/'a'/'secret.json').write_text('{"password":"not permitted"}')
    client=TestClient(create_app(root))
    for path in ('a/linked.png','a/secret.json','%2E%2E/secret.png','a/%2E%2E/%2E%2E/secret.png',str(outside/'secret.png')):
        assert client.get('/artifacts/'+path).status_code==404
    assert client.get('/artifacts/a/frame.png').content==b'png-test-bytes'
    assert client.get('/assets/unknown.png').status_code==404
    assert client.get('/artifacts/a/attempt.json').status_code==404


def test_invalid_and_symlink_run_records_do_not_escape(root,tmp_path_factory):
    outside=tmp_path_factory.mktemp('records');(outside/'attempt.json').write_text('{"attempt_id":"escape"}')
    (root/'escape').symlink_to(outside,target_is_directory=True)
    (root/'bad').mkdir();(root/'bad'/'attempt.json').write_text('invalid')
    client=TestClient(create_app(root))
    assert [r['attempt_id'] for r in client.get('/runs').json()['runs']]==['a']


def test_script_escapes_untrusted_text_and_external_refs(root):
    path=root/'a'/'attempt.json';data=json.loads(path.read_text())
    data['task_goal']='</script><script>alert(1)</script>\u2028'
    data['video_ref']='https://external.test/a.mp4';path.write_text(json.dumps(data))
    client=TestClient(create_app(root))
    script=client.get('/bundle.js').text
    assert '</script>' not in script and '\\u003c' in script and '\\u2028' in script
    assert client.get('/api/bundle').json()['attempts'][0]['video_ref'] is None
    assert client.get('/health',headers={'host':'evil.test'}).status_code==403
