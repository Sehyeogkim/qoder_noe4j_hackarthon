// Real execution memory already stored in Aura; read-only, no import required.
// Overview: frozen memory source attempts plus evaluation turns that retrieved them.
MATCH (s:MemorySnapshot {snapshot_id:'first-demo-cbd3b645234646a69604db0e86722c16-snapshot'})
      -[i:INCLUDES]->(source:Attempt)
OPTIONAL MATCH (source)-[h:HAS_DECISION]->(past:DecisionStep)
OPTIONAL MATCH (current:DecisionStep)-[r:RETRIEVED]->(past)
OPTIONAL MATCH (trial:Attempt)-[d:HAS_DECISION]->(current)
RETURN s,i,source,h,past,current,r,trial,d;

// Results of the six attempts included in the verified local export.
MATCH (a:Attempt)
WHERE a.attempt_id IN ['10295101277547b6aa6f8ecc6bab12d5','6d63c92665534414871cf18d4a19815e',
  '640b56e80fd64f0e9767cdad49161e77','a2cd74eca3284c0aaa7e043ae4f0fc79',
  'e715cf2ba698468f83148645cb3ae8dd','3acae640f7ce4e3e8f87521ef3b9e9a6']
RETURN a.attempt_id,a.outcome,a.step_index,a.dataset_split,a.provenance;

// One evaluation turn: actual prompt, observations, actions and evidence.
MATCH (a:Attempt {attempt_id:'3acae640f7ce4e3e8f87521ef3b9e9a6'})-[:HAS_DECISION]->(t:DecisionStep)
WITH a,t ORDER BY t.decision_id LIMIT 1
MATCH p=(t)-[*1..1]->(detail)
RETURN a,p;
