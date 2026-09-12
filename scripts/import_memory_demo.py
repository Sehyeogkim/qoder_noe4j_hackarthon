"""Import the portable experience graph into an EMPTY local Neo4j database.

Never reads .env. Remote hosts and nonempty databases are rejected. Use --dry-run
to validate without Neo4j; this script never deletes existing data.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

LABEL_KEYS = {'Attempt': 'attempt_id', 'DecisionStep': 'decision_id', 'Run': 'run_id',
              'Task': 'task_id', 'MemorySnapshot': 'snapshot_id', 'StepEvent': 'id',
              'ContextObservation': 'id', 'Instruction': 'id', 'Evidence': 'id', 'Skill': 'id'}
RELATIONS = {'FOR_TASK', 'HAS_ATTEMPT', 'RETRY_OF', 'HAS_DECISION', 'USED_INSTRUCTION',
             'USED_SKILL', 'HAS_ACTION', 'HAS_CONTEXT', 'HAS_EVIDENCE', 'RETRIEVED', 'INCLUDES'}


def validate_local_uri(uri):
    parsed = urlsplit(uri)
    if parsed.scheme not in ('bolt', 'neo4j') or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Importer accepts only local bolt:// or neo4j:// loopback addresses')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Pass credentials separately; URI must be a plain local address')
    return uri


def validate_graph(graph):
    ids = set()
    for n in graph['nodes']:
        if n['label'] not in LABEL_KEYS or n['id'] in ids or not n['id'].startswith(n['label'] + ':'):
            raise ValueError('Invalid graph node type or duplicate ID')
        ids.add(n['id'])
        if n['label'] == 'Attempt' and (n['properties'].get('provenance') != 'real_execution' or n['properties'].get('status') != 'completed'):
            raise ValueError('Demo accepts completed actual executions only')
    for e in graph['edges']:
        if e['type'] not in RELATIONS or e['source'] not in ids or e['target'] not in ids:
            raise ValueError('Invalid relationship or missing endpoint')
    return graph


def native_properties(node):
    label, p = node['label'], dict(node['properties'])
    identity = node['id'][len(label) + 1:]
    # Preserve the original full record in the same JSON payload layout used by
    # Neo4jRepository, and retain scalar/searchable properties for Cypher.
    props = {k: (json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v)
             for k, v in p.items() if v is not None}
    props.update({LABEL_KEYS[label]: identity, 'arma_export_id': node['id'],
                  'payload': json.dumps(p, ensure_ascii=False, sort_keys=True)})
    if label == 'Attempt':
        props.update({'task': p.get('task', p.get('task_id')), 'robot': p.get('robot', p.get('robot_id')),
                      'policy_revision': p.get('policy_revision', p.get('policy_id')), 'lock_version': 0})
    if label == 'DecisionStep':
        props['stage'] = p.get('planner', {}).get('stage')
    if label == 'Instruction':
        props['hash'] = identity
    if label == 'MemorySnapshot':
        props['digest'] = hashlib.sha256(json.dumps(p, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return props


def import_transaction(tx, graph):
    count = tx.run('MATCH (n) RETURN count(n) AS count').single()['count']
    if count:
        raise ValueError('Database is not empty; choose a fresh dedicated local database. Nothing was deleted.')
    for label in LABEL_KEYS:
        rows = [native_properties(n) for n in graph['nodes'] if n['label'] == label]
        if rows:
            # Label is from a fixed allowlist; every ID/property is a parameter.
            tx.run(f'UNWIND $rows AS row CREATE (n:{label}) SET n = row', rows=rows).consume()
    for kind in RELATIONS:
        rows = [e for e in graph['edges'] if e['type'] == kind]
        if rows:
            tx.run(f'UNWIND $rows AS row MATCH (a {{arma_export_id:row.source}}), (b {{arma_export_id:row.target}}) CREATE (a)-[r:{kind}]->(b) SET r = row.properties', rows=rows).consume()
    return {'nodes': len(graph['nodes']), 'edges': len(graph['edges'])}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, default=Path(__file__).resolve().parent)
    p.add_argument('--uri', default='bolt://127.0.0.1:7687')
    p.add_argument('--database', default='neo4j')
    p.add_argument('--username', default='neo4j')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    validate_local_uri(args.uri)
    graph = validate_graph(json.loads((args.bundle / 'graph.json').read_text()))
    if args.dry_run:
        print(json.dumps({'validated': True, 'nodes': len(graph['nodes']), 'edges': len(graph['edges']), 'database_modified': False}))
        return
    from neo4j import GraphDatabase
    password = os.environ.get('LOCAL_NEO4J_PASSWORD') or getpass.getpass('Password for the fresh LOCAL Neo4j database: ')
    with GraphDatabase.driver(args.uri, auth=(args.username, password)) as driver:
        with driver.session(database=args.database) as session:
            # Check before creating even constraints in an existing database.
            if session.execute_read(lambda tx: tx.run('MATCH (n) RETURN count(n) AS count').single()['count']):
                raise ValueError('Database is not empty; import refused')
            for statement in (args.bundle / 'schema.cypher').read_text().split(';'):
                if statement.strip():
                    session.run(statement).consume()
            session.run('CREATE CONSTRAINT arma_export_id IF NOT EXISTS FOR (n:Attempt) REQUIRE n.arma_export_id IS UNIQUE').consume()
            result = session.execute_write(import_transaction, graph)
            counts = session.execute_read(lambda tx: dict(tx.run('MATCH (n) WITH count(n) AS nodes OPTIONAL MATCH ()-[r]->() RETURN nodes,count(r) AS edges').single()))
            if counts != result:
                raise RuntimeError('Imported counts differ from exported graph')
    print(json.dumps({'imported': result, 'uri': args.uri, 'database': args.database}))


if __name__ == '__main__':
    main()
