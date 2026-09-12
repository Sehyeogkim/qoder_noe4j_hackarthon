// Run these individually in Neo4j Aura Query, connected to ARMA-Memory.
// Graph: 17 nodes and 20 relationships for this synthetic fixture.
MATCH p=(r:Run {run_id: 'arma_schema_smoke_v1'})-[:HAS_ATTEMPT]->(:Attempt)-[*0..2]->()
RETURN p;

// Table: inspect all 15 logical Attempt fields inside the JSON payload.
MATCH (:Run {run_id: 'arma_schema_smoke_v1'})-[:HAS_ATTEMPT]->(a:Attempt)
RETURN a.attempt_id, a.status, a.outcome, a.provenance, a.payload
ORDER BY a.attempt_id;

// Retry relation: new successful fixture -> earlier failed fixture.
MATCH p=(a:Attempt {attempt_id: 'arma_schema_smoke_v1:success'})-[:RETRY_OF]->(b:Attempt)
RETURN p;

// Remembered-decision relation (hand-authored example, not a live agent call).
MATCH p=(d:DecisionStep {decision_id: 'arma_schema_smoke_v1:success:decision:0'})-[:RETRIEVED]->(previous:DecisionStep)
RETURN p;
