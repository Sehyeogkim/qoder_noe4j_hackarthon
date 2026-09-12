import importlib.util
import hashlib
from pathlib import Path

import pytest


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'scripts' / f'{name}.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_export_rejects_non_artifact_paths_and_traversal():
    export = module('export_memory_demo')
    for uri in ('/workspace/arma/.env', '/workspace/arma/artifacts/../.env', 'https://example.com/file.png'):
        with pytest.raises(ValueError):
            list(export.references({'uri': uri}))
    assert list(export.references({'uri': '/workspace/arma/artifacts/a.png'})) == ['a.png']


def test_import_refuses_remote_and_embedded_credentials():
    importer = module('import_memory_demo')
    for uri in ('neo4j+s://example.databases.neo4j.io', 'bolt://remote:7687', 'bolt://user:secret@localhost:7687'):
        with pytest.raises(ValueError):
            importer.validate_local_uri(uri)
    assert importer.validate_local_uri('bolt://127.0.0.1:7687')


def test_import_refuses_existing_database_before_any_creation():
    importer = module('import_memory_demo')
    class Result:
        def single(self):
            return {'count': 1}
    class Tx:
        def __init__(self):
            self.calls = []
        def run(self, query, **kwargs):
            self.calls.append(query)
            return Result()
    tx = Tx()
    with pytest.raises(ValueError, match='not empty'):
        importer.import_transaction(tx, {'nodes': [], 'edges': []})
    assert tx.calls == ['MATCH (n) RETURN count(n) AS count']


def test_import_label_and_endpoint_validation():
    importer = module('import_memory_demo')
    with pytest.raises(ValueError):
        importer.validate_graph({'nodes': [{'id': 'Injected:x', 'label': 'Injected', 'properties': {}}], 'edges': []})
    with pytest.raises(ValueError):
        importer.validate_graph({'nodes': [], 'edges': [{'source': 'a', 'target': 'b', 'type': 'RETRIEVED'}]})


def test_portable_latest_reference_and_recorded_hash_validation(tmp_path):
    export = module('export_memory_demo')
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    source = evidence / 'frame.png'
    source.write_bytes(b'actual-test-image-bytes')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assets = tmp_path / 'assets'
    assets.mkdir()
    (assets / (digest + '.png')).write_bytes(source.read_bytes())
    result = export.portable_latest_refs({'latest_observation_ref': str(source)}, evidence, assets)
    assert result['latest_observation_ref'] == 'assets/' + digest + '.png'
    graph = {'nodes': [{'label': 'Evidence', 'id': 'Evidence:x', 'properties': {'uri': result['latest_observation_ref'], 'hash': digest}}]}
    assert export.validate_evidence(graph, tmp_path) == 1
    (assets / (digest + '.png')).write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='hash mismatch'):
        export.validate_evidence(graph, tmp_path)
