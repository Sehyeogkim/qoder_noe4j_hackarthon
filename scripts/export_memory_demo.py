"""Read-only Aura export plus strictly bounded SSH evidence copy for local inspection."""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

from arma.memory import Neo4jRepository
from arma.replay import export_bundle

REMOTE_ROOT = Path('/workspace/arma/artifacts')
ASSET_FIELDS = {'rgb_ref', 'video_ref', 'image_ref', 'artifact_ref', 'uri', 'latest_observation_ref'}


def references(value, key=''):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from references(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from references(v, 'artifact_ref' if key == 'artifact_refs' else '')
    elif key in ASSET_FIELDS and isinstance(value, str) and value:
        p = Path(value)
        if '..' in p.parts or not p.is_absolute() or not p.is_relative_to(REMOTE_ROOT):
            raise ValueError('Only evidence beneath the declared remote artifact root is allowed')
        yield p.relative_to(REMOTE_ROOT).as_posix()


def relocate(value, local_root: Path, key=''):
    if isinstance(value, dict):
        return {k: relocate(v, local_root, k) for k, v in value.items()}
    if isinstance(value, list):
        return [relocate(v, local_root, 'artifact_ref' if key == 'artifact_refs' else '') for v in value]
    if key in ASSET_FIELDS and isinstance(value, str) and value:
        return str(local_root / Path(value).relative_to(REMOTE_ROOT))
    return value


def validate_evidence(graph, root):
    checked = 0
    for node in graph['nodes']:
        if node['label'] != 'Evidence':
            continue
        p = node['properties']
        ref = p.get('uri') or p.get('rgb_ref')
        digest = p.get('sha256') or p.get('hash')
        if ref and digest:
            path = Path(ref)
            if not path.is_absolute():
                path = root / path
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Evidence hash mismatch: ' + node['id'])
            checked += 1
    if not checked:
        raise ValueError('No independently recorded evidence hashes were verified')
    return checked


def portable_latest_refs(value, root, assets):
    """The general replay exporter does not yet recognize this Attempt field."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == 'latest_observation_ref' and isinstance(item, str) and item:
                source = Path(item).resolve(strict=True)
                if not source.is_relative_to(root.resolve()):
                    raise ValueError('Latest observation escapes the evidence root')
                name = hashlib.sha256(source.read_bytes()).hexdigest() + source.suffix.lower()
                if not (assets / name).is_file():
                    raise ValueError('Latest observation was not exported as evidence')
                result[key] = 'assets/' + name
            else:
                result[key] = portable_latest_refs(item, root, assets)
        return result
    if isinstance(value, list):
        return [portable_latest_refs(item, root, assets) for item in value]
    return value


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', required=True)
    p.add_argument('--evaluation-attempt', action='append', default=[])
    p.add_argument('--output', type=Path, default=Path('artifacts/memory-demo'))
    p.add_argument('--ssh-host', required=True)
    p.add_argument('--ssh-port', required=True, type=int)
    p.add_argument('--ssh-key', type=Path, required=True)
    args = p.parse_args()
    from dotenv import dotenv_values
    v = {**dotenv_values('.env'), **os.environ}
    repo = Neo4jRepository(v['NEO4J_URI'], v['NEO4J_USERNAME'], v['NEO4J_PASSWORD'], v.get('NEO4J_DATABASE', 'neo4j'))
    try:
        from neo4j import READ_ACCESS
        with repo.driver.session(database=repo.database, default_access_mode=READ_ACCESS) as session:
            rows = session.execute_read(lambda tx: [dict(r) for r in tx.run(
                'MATCH (s:MemorySnapshot {snapshot_id:$sid})-[:INCLUDES]->(a:Attempt) RETURN s.payload AS snapshot,a.attempt_id AS id', sid=args.snapshot)])
        if not rows:
            raise ValueError('Snapshot not found or empty')
        snapshot = json.loads(rows[0]['snapshot'])
        members = sorted(r['id'] for r in rows)
        if members != sorted(snapshot['attempt_ids']):
            raise ValueError('Snapshot physical membership differs from payload')
        ids = list(dict.fromkeys(members + args.evaluation_attempt))
        attempts = [repo.get_attempt(aid) for aid in ids]
        for a in attempts:
            if a['status'] != 'completed' or a['provenance'] != 'real_execution':
                raise ValueError('Only completed actual executions may be exported')
            if a['attempt_id'] in members and (a['dataset_split'] != 'memory_build' or a['outcome'] not in ('success', 'failure')):
                raise ValueError('Ineligible snapshot source')
        graph = repo.export_graph(ids)
    finally:
        repo.driver.close()
    graph['nodes'].append({'id': 'MemorySnapshot:' + args.snapshot, 'label': 'MemorySnapshot', 'properties': snapshot})
    graph['edges'].extend({'source': 'MemorySnapshot:' + args.snapshot, 'target': 'Attempt:' + aid, 'type': 'INCLUDES', 'properties': {}} for aid in members)
    refs = sorted(set(references(graph)))
    # Remote code receives data as JSON, never as interpolated shell paths.
    remote_code = '''import sys,json,pathlib,tarfile
root=pathlib.Path('/workspace/arma/artifacts').resolve()
names=json.loads(DATA)
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as tar:
 for name in names:
  file=(root/name).resolve(strict=True)
  if not file.is_relative_to(root) or not file.is_file(): raise ValueError('Invalid evidence path')
  tar.add(file,arcname=name,recursive=False)
'''.replace('DATA', repr(json.dumps(refs)))
    result = subprocess.run(['ssh', '-p', str(args.ssh_port), '-i', str(args.ssh_key.expanduser()), '-o', 'BatchMode=yes', args.ssh_host, 'python3 -'], input=remote_code.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='arma-memory-export-') as temp:
        local_root = Path(temp) / 'evidence'
        local_root.mkdir()
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
            # Explicitly prohibit links and anything beyond requested artifact files.
            for item in tar.getmembers():
                if item.name not in refs or not item.isfile():
                    raise ValueError('Unexpected archive member')
                target = local_root / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(item) as source, target.open('wb') as dest:
                    shutil.copyfileobj(source, dest)
        local_graph = relocate(graph, local_root)
        before_count = validate_evidence(local_graph, local_root)
        staging = Path(temp) / 'portable'
        export_bundle({'schema_version': '1', 'attempts': [], 'graph': local_graph}, staging, local_root)
        portable = portable_latest_refs(json.loads((staging / 'bundle.json').read_text())['graph'], local_root, staging / 'assets')
        shutil.copytree(staging / 'assets', output / 'assets', dirs_exist_ok=True)
        verified_count = validate_evidence(portable, output)
        if before_count != verified_count:
            raise ValueError('Evidence verification coverage changed')
    snapshot_meta = {**snapshot, 'evaluation_attempt_ids': args.evaluation_attempt, 'provenance': 'real_execution'}
    metadata = {
        'schema_version': '1', 'exported_at': datetime.now(timezone.utc).isoformat(),
        'origin': 'Read-only export of the ARMA Aura database and actual LIBERO execution artifacts',
        'no_training': True, 'data_kind': 'Recorded execution experience; not model training data',
        'snapshot_id': args.snapshot, 'eligible_source_attempt_ids': members,
        'evaluation_attempt_ids': args.evaluation_attempt, 'local_neo4j_import_executed': False,
        'counts': {'nodes': len(portable['nodes']), 'edges': len(portable['edges']),
                   'node_labels': dict(collections.Counter(n['label'] for n in portable['nodes'])),
                   'edge_types': dict(collections.Counter(e['type'] for e in portable['edges'])),
                   'assets': len(list((output / 'assets').iterdir())), 'hash_verified_evidence': verified_count},
        'attempts': [{**{k: a.get(k) for k in ('attempt_id','condition','init_state_id','status','outcome','step_index','decision_index','dataset_split','provenance','origin','record_kind','agent_api_calls')},
                      'eligible_memory_source': a['attempt_id'] in members} for a in attempts],
        'limitations': ['Environment is LIBERO simulation, not a physical robot.', 'Agent explanations are recorded interpretations.', 'Evaluation records are not snapshot retrieval sources.', 'No local Neo4j server was installed or imported during export.'],
    }
    for name, value in [('graph', portable), ('metadata', metadata), ('snapshot', snapshot_meta)]:
        (output / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    data = json.dumps({'graph': portable, 'metadata': metadata, 'snapshot': snapshot_meta}, ensure_ascii=False)
    for char, replacement in [('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')]:
        data = data.replace(char, replacement)
    (output / 'data.js').write_text('window.ARMA_MEMORY_DATA = ' + data + ';\n')
    assets_manifest = [{'path': f'assets/{p.name}', 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
                       for p in sorted((output / 'assets').iterdir()) if p.is_file()]
    (output / 'assets-manifest.json').write_text(json.dumps(assets_manifest, indent=2) + '\n')
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'arma/migrations/001_memory.cypher', output / 'schema.cypher')
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
