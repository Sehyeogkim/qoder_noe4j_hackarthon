"""Transactional, evidence-backed ARMA experience storage.

No model or robot call belongs inside this module. The in-memory implementation
shares validation/retrieval rules with Neo4j and is only for tests/local dry runs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

RETRIEVAL_RANKING_VERSION = "compatible-diverse-nearest-action-v2"

class MemoryConflict(RuntimeError):
    """An immutable ID was reused or progress is stale."""


class MemoryValidationError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _meta(value: dict, key: str, default: Any = None) -> Any:
    return value.get(key, value.get("metadata", {}).get(key, default))


def _identity(value: dict, key: str) -> Any:
    if key == "task":
        return _meta(value, "task", _meta(value, "task_id", value.get("task_goal")))
    if key == "policy_revision":
        return _meta(value, key, _meta(value, "policy_id", _meta(value, "policy")))
    if key == "robot":
        return _meta(value, key, _meta(value, "robot_id"))
    return _meta(value, key)


def _validate_attempt(attempt: dict) -> None:
    if not attempt.get("attempt_id"):
        raise MemoryValidationError("attempt_id is required")
    status = attempt.get("status", "running")
    outcome = attempt.get("outcome")
    if status not in ("running", "completed"):
        raise MemoryValidationError("invalid attempt status")
    if (status == "running" and outcome is not None) or (
        status == "completed" and outcome not in ("success", "failure", "unknown")
    ):
        raise MemoryValidationError("status and outcome are inconsistent")
    if not isinstance(attempt.get("step_index", 0), int) or attempt.get("step_index", 0) < 0:
        raise MemoryValidationError("step_index must be a nonnegative integer")


def _updated(attempt: dict, update: dict) -> dict:
    immutable = ("attempt_id", "task_goal", "success_criteria", "initial_context", "previous_attempt_id", "metadata")
    for key in immutable:
        if key in update and key in attempt and update[key] != attempt[key]:
            raise MemoryConflict(f"immutable attempt field: {key}")
    for key in ("task", "task_id", "robot", "robot_id", "policy", "policy_id", "policy_revision", "perception_mode", "dataset_split", "provenance", "run_id"):
        if key in update and key in attempt and update[key] != attempt[key]:
            raise MemoryConflict(f"immutable attempt metadata: {key}")
    result = {**attempt, **copy.deepcopy(update)}
    if result.get("step_index", 0) < attempt.get("step_index", 0):
        raise MemoryConflict("attempt progress cannot move backwards")
    if attempt.get("status") == "completed" and result != attempt:
        raise MemoryConflict("completed attempts are immutable")
    _validate_attempt(result)
    return result


def _validate_decision(attempt: dict, expected: int, decision: dict, update: dict) -> dict:
    if not decision.get("decision_id"):
        raise MemoryValidationError("decision_id is required")
    if attempt.get("status", "running") != "running":
        raise MemoryConflict("cannot append a decision to a completed attempt")
    if attempt.get("step_index", 0) != expected or decision.get("start_step_index") != expected:
        raise MemoryConflict("stale decision progress")
    end = decision.get("end_step_index")
    if not isinstance(end, int) or not expected <= end <= expected + 10:
        raise MemoryValidationError("a decision must span zero through ten policy actions")
    if update.get("step_index") != end:
        raise MemoryValidationError("attempt update must match decision end_step_index")
    if "attempt_id" in decision and decision["attempt_id"] != attempt["attempt_id"]:
        raise MemoryConflict("decision belongs to another attempt")
    actions = decision.get("execution", {}).get("actions")
    if actions is not None and len(actions) != end - expected:
        raise MemoryValidationError("action log does not match progress")
    return _updated(attempt, update)


def _eligible(attempt: dict, query: dict, members: set[str]) -> bool:
    return (
        attempt["attempt_id"] in members
        and attempt.get("status") == "completed"
        and attempt.get("outcome") in ("success", "failure")
        and _meta(attempt, "provenance") == "real_execution"
        and _meta(attempt, "dataset_split") == "memory_build"
        and all(_identity(query, key) is not None and _identity(attempt, key) == _identity(query, key)
                for key in ("task", "robot", "policy_revision", "perception_mode"))
    )


def _context_map(contexts: Any) -> dict:
    if isinstance(contexts, dict):
        contexts = [{"kind": k, "value": v} for k, v in contexts.items()]
    result = {}
    for context in contexts or []:
        key = context.get("kind", context.get("name", context.get("key")))
        value = context.get("value", "unknown")
        if value in (True, "true"):
            value = "true"
        elif value in (False, "false"):
            value = "false"
        else:
            value = "unknown"
        if key:
            result[key] = value
    return result


def _search(attempts: dict, decisions: dict, snapshot: dict, query: dict, graph_paths: dict | None = None) -> list[dict]:
    based_on_step = query.get("based_on_step")
    if based_on_step is not None and (type(based_on_step) is not int or based_on_step < 0):
        raise MemoryValidationError("based_on_step must be a nonnegative integer")

    def progress_distance(candidate):
        start = candidate.get("start_step_index")
        if based_on_step is None or type(start) is not int or start < 0:
            return float("inf")
        return abs(start - based_on_step)

    members = set(snapshot.get("attempt_ids", []))
    eligible = {k: v for k, v in attempts.items() if _eligible(v, query, members)}
    current = _context_map(query.get("contexts", []))
    stage = query.get("stage", query.get("subtask"))
    candidates = []
    for decision in decisions.values():
        attempt = eligible.get(decision["attempt_id"])
        if attempt is None:
            continue
        contexts = _context_map(decision.get("contexts", []))
        if any(v != "unknown" and contexts.get(k, "unknown") != "unknown" and contexts[k] != v for k, v in current.items()):
            continue
        matches = sum(v != "unknown" and contexts.get(k) == v for k, v in current.items())
        historical_stage = decision.get("planner", {}).get("stage", decision.get("stage"))
        stage_match = stage is not None and stage == historical_stage
        evidence = decision.get("evidence", [])
        # A retry path is evidence of sequence, never a causal conclusion. Every
        # intermediate Attempt must belong to the same eligible frozen corpus.
        path = []
        cursor = attempt
        for _ in range(3):
            previous = cursor.get("previous_attempt_id")
            if not previous or previous not in eligible or previous in path:
                break
            path.append(previous)
            cursor = eligible[previous]
        if graph_paths is not None:
            actual_paths = graph_paths.get(attempt["attempt_id"], [])
            path = max(actual_paths, key=len, default=[])
        failed_ancestors = [a for a in path if eligible[a]["outcome"] == "failure"]
        reasons = ["same robot, policy, task and perception mode", f"{matches} matching known conditions"]
        if stage_match:
            reasons.append("same subtask stage")
        if failed_ancestors:
            reasons.append("eligible retry of a recorded failure; sequence is not causation")
        instruction = decision.get("execution", {}).get("actual_instruction") or decision.get("retrieval", {}).get("instruction") or decision.get("retrieval", {}).get("executed_instruction") or ""
        evaluation = decision.get("evaluation", {})
        execution = decision.get("execution", {})
        before = execution.get("observation_before") or {}
        after = execution.get("observation_after") or {}
        candidates.append({
            "source_decision_id": decision["decision_id"], "source_attempt_id": attempt["attempt_id"],
            "instruction": instruction,
            # Compatibility: `outcome` always describes the WHOLE Attempt.
            # An early successful subtask can belong to an ultimately failed episode.
            "outcome": attempt["outcome"], "attempt_outcome": attempt["outcome"],
            "step_task_outcome": evaluation.get("task_outcome"),
            "subtask_outcome": evaluation.get("subtask_outcome", "unknown"),
            "decision_index": decision.get("decision_index"),
            "start_step_index": decision.get("start_step_index"),
            "end_step_index": decision.get("end_step_index"),
            "observation_before_id": before.get("observation_id", execution.get("observation_before_id")),
            "observation_after_id": after.get("observation_id", execution.get("observation_after_id")),
            "before_evidence_id": before.get("evidence_id"),
            "after_evidence_id": after.get("evidence_id"),
            "stage": historical_stage,
            "contexts": copy.deepcopy(decision.get("contexts", [])), "evidence": copy.deepcopy(evidence),
            "evidence_ids": [e.get("evidence_id", e.get("id")) for e in evidence if e.get("evidence_id", e.get("id"))],
            "observed_facts": copy.deepcopy(decision.get("evaluation", {}).get("observed_facts", [])),
            "cause_hypothesis": decision.get("evaluation", {}).get("cause_hypothesis"),
            "retry_path": list(reversed(path)) + [attempt["attempt_id"]] if path else [],
            "reasons": reasons, "score": 10 * int(stage_match) + 2 * matches + min(len(evidence), 3),
        })
    # Collapse repeated windows of the same instruction under the same explicit
    # conditions/judgments. Preserve distinct outcomes and condition transitions.
    # Action distance is only a soft tie-break, never a visual condition match.
    # Callers without a progress hint retain the legacy latest-window fallback.
    representatives = {}
    for candidate in candidates:
        signature = _json([
            candidate["source_attempt_id"], candidate["instruction"], candidate["stage"],
            _context_map(candidate["contexts"]), candidate["step_task_outcome"],
            candidate["subtask_outcome"],
        ])
        previous = representatives.get(signature)
        representative_priority = lambda c: (progress_distance(c), -(c["end_step_index"] or 0),
                                              -len(set(c["evidence_ids"])), c["source_decision_id"])
        if previous is None or representative_priority(candidate) < representative_priority(previous):
            representatives[signature] = candidate
    pool = list(representatives.values())
    selected, seen_attempts, seen_instructions = [], set(), set()
    while pool and len(selected) < 3:
        def priority(candidate):
            historical = _context_map(candidate["contexts"])
            known_matches = sum(v != "unknown" and historical.get(k) == v for k, v in current.items())
            return (
                -int(stage is not None and candidate["stage"] == stage),
                -known_matches,
                -int(candidate["source_attempt_id"] not in seen_attempts),
                -int(candidate["instruction"] not in seen_instructions),
                -min(len(set(candidate["evidence_ids"])), 3),
                progress_distance(candidate),
                -(candidate["end_step_index"] or 0),
                candidate["source_decision_id"],
            )
        chosen = min(pool, key=priority)
        if based_on_step is None:
            chosen["reasons"].append("latest representative of matching instruction, conditions, and step judgments; no progress hint supplied")
        else:
            chosen["reasons"].append("nearest action-start representative of matching instruction, conditions, and step judgments; soft progress tie-break, not visual evidence")
        if chosen["source_attempt_id"] not in seen_attempts:
            chosen["reasons"].append("distinct source attempt among equally compatible candidates")
        selected.append(chosen)
        seen_attempts.add(chosen["source_attempt_id"])
        seen_instructions.add(chosen["instruction"])
        pool.remove(chosen)
    return selected


def _graph(attempts: dict, decisions: dict) -> dict:
    nodes, edges = {}, []
    def node(label, identifier, properties):
        key = f"{label}:{identifier}"
        nodes[key] = {"id": key, "label": label, "properties": copy.deepcopy(properties)}
        return key
    def edge(source, target, kind, properties=None):
        edges.append({"source": source, "target": target, "type": kind, "properties": properties or {}})
    for a in attempts.values():
        aid = node("Attempt", a["attempt_id"], a)
        task_id = str(_identity(a, "task") or "unknown")
        edge(aid, node("Task", task_id, {"task_id": task_id}), "FOR_TASK")
        run_id = _meta(a, "run_id", "unassigned")
        edge(node("Run", run_id, {"run_id": run_id}), aid, "HAS_ATTEMPT")
        if a.get("previous_attempt_id") in attempts:
            edge(aid, f"Attempt:{a['previous_attempt_id']}", "RETRY_OF")
    for d in decisions.values():
        if d["attempt_id"] not in attempts:
            continue
        did = node("DecisionStep", d["decision_id"], d)
        edge(f"Attempt:{d['attempt_id']}", did, "HAS_DECISION")
        instruction = d.get("execution", {}).get("actual_instruction", d.get("retrieval", {}).get("instruction", ""))
        edge(did, node("Instruction", _hash(instruction), {"text": instruction}), "USED_INSTRUCTION")
        planner = d.get("planner", {})
        skill = planner.get("skill", planner.get("skill_id", "pick_place_v1"))
        if isinstance(skill, dict):
            skill = skill.get("skill_id", skill.get("id", "pick_place_v1"))
        version = planner.get("skill_version", "1")
        edge(did, node("Skill", f"{skill}:{version}", {"skill_id": skill, "version": version, "provenance": "authored_procedure"}), "USED_SKILL")
        for i, action in enumerate(d.get("execution", {}).get("actions", [])):
            edge(did, node("StepEvent", f"{d['decision_id']}:{i}", action), "HAS_ACTION")
        for i, context in enumerate(d.get("contexts", [])):
            edge(did, node("ContextObservation", f"{d['decision_id']}:{i}", context), "HAS_CONTEXT")
        for e in d.get("evidence", []):
            eid = e.get("evidence_id", e.get("id", _hash(e)))
            edge(did, node("Evidence", eid, e), "HAS_EVIDENCE")
        retrieval = d.get("retrieval", {})
        refs = list(retrieval.get("source_step_ids", retrieval.get("source_decision_ids", [])))
        selections = retrieval.get("candidates", [])
        refs = list(dict.fromkeys(refs + [c["source_decision_id"] for c in selections if c.get("source_decision_id")]))
        for source_id in refs:
            selection = next((c for c in selections if c.get("source_decision_id") == source_id), {})
            edge(did, f"DecisionStep:{source_id}", "RETRIEVED", {"adopted": selection.get("adopted", source_id in retrieval.get("source_decision_ids", retrieval.get("source_step_ids", []))), "reason": selection.get("reason", "cited by retrieval decision")})
    return {"nodes": list(nodes.values()), "edges": edges}


def _export_graph(attempts: dict, decisions: dict) -> dict:
    """Export exactly the supplied attempts and edges with both endpoints present.

    Include collection AND evaluation attempt IDs to show their retrieval links.
    The raw graph builder remains usable for transactional cross-attempt edges.
    """
    graph = _graph(attempts, decisions)
    node_ids = {node["id"] for node in graph["nodes"]}
    graph["edges"] = [edge for edge in graph["edges"]
                      if edge["source"] in node_ids and edge["target"] in node_ids]
    return graph


class InMemoryRepository:
    def __init__(self):
        self._attempts, self._decisions, self._snapshots = {}, {}, {}
        self._start_hashes, self._commit_hashes = {}, {}
        self._lock = threading.RLock()

    def migrate(self):
        return None

    def start_attempt(self, attempt: dict) -> dict:
        attempt = {"step_index": 0, "status": "running", "outcome": None, **copy.deepcopy(attempt)}
        _validate_attempt(attempt)
        aid, digest = attempt["attempt_id"], _hash(attempt)
        with self._lock:
            if aid in self._attempts:
                if self._start_hashes[aid] != digest:
                    raise MemoryConflict("attempt ID reused with a different payload")
                return copy.deepcopy(self._attempts[aid])
            previous = attempt.get("previous_attempt_id")
            if previous and previous not in self._attempts:
                raise MemoryValidationError("retry predecessor does not exist")
            self._attempts[aid], self._start_hashes[aid] = attempt, digest
            return copy.deepcopy(attempt)

    def get_attempt(self, attempt_id: str) -> dict:
        with self._lock:
            if attempt_id not in self._attempts:
                raise KeyError(attempt_id)
            return copy.deepcopy(self._attempts[attempt_id])

    def commit_decision(self, attempt_id: str, expected_step_index: int, decision: dict, attempt_update: dict) -> dict:
        digest = _hash([attempt_id, expected_step_index, decision, attempt_update])
        did = decision.get("decision_id")
        with self._lock:
            if did in self._commit_hashes:
                if self._commit_hashes[did] != digest:
                    raise MemoryConflict("decision ID reused with a different payload")
                return self.get_attempt(attempt_id)
            attempt = self.get_attempt(attempt_id)
            result = _validate_decision(attempt, expected_step_index, decision, attempt_update)
            known_evidence = {e.get("evidence_id", e.get("id", _hash(e))): _hash(e) for d in self._decisions.values() for e in d.get("evidence", [])}
            for e in decision.get("evidence", []):
                eid = e.get("evidence_id", e.get("id", _hash(e)))
                if eid in known_evidence and known_evidence[eid] != _hash(e):
                    raise MemoryConflict("evidence ID reused with a different payload")
                known_evidence[eid] = _hash(e)
            self._decisions[did] = {**copy.deepcopy(decision), "attempt_id": attempt_id}
            self._attempts[attempt_id], self._commit_hashes[did] = result, digest
            return copy.deepcopy(result)

    def finalize_attempt(self, attempt_id: str, update: dict) -> dict:
        with self._lock:
            result = _updated(self.get_attempt(attempt_id), update)
            if result.get("status") != "completed":
                raise MemoryValidationError("finalize_attempt requires completed status")
            self._attempts[attempt_id] = result
            return copy.deepcopy(result)

    def freeze_snapshot(self, snapshot_id: str, attempt_ids: list[str]) -> dict:
        snapshot = {"snapshot_id": snapshot_id, "attempt_ids": sorted(set(attempt_ids))}
        with self._lock:
            if snapshot_id in self._snapshots:
                if self._snapshots[snapshot_id] != snapshot:
                    raise MemoryConflict("snapshot membership is immutable")
                return copy.deepcopy(snapshot)
            for aid in snapshot["attempt_ids"]:
                a = self.get_attempt(aid)
                if a.get("status") != "completed" or a.get("outcome") not in ("success", "failure") or _meta(a, "provenance") != "real_execution" or _meta(a, "dataset_split") != "memory_build":
                    raise MemoryValidationError("snapshots accept completed real memory-building attempts only")
            self._snapshots[snapshot_id] = snapshot
            return copy.deepcopy(snapshot)

    def search_experiences(self, query: dict) -> list[dict]:
        with self._lock:
            snapshot = self._snapshots.get(query.get("snapshot_id"), {})
            return _search(self._attempts, self._decisions, snapshot, query)

    def export_graph(self, attempt_ids: list[str] | None = None) -> dict:
        with self._lock:
            attempts = {k: v for k, v in self._attempts.items() if attempt_ids is None or k in attempt_ids}
            return _export_graph(attempts, self._decisions)


class Neo4jRepository:
    """Neo4j driver is optional until this production adapter is instantiated."""
    def __init__(self, uri: str, username: str, password: str, database: str = "neo4j", *, driver=None):
        from neo4j import GraphDatabase
        self.driver = driver or GraphDatabase.driver(uri, auth=(username, password))
        self.database = database
        self._bookmarks = GraphDatabase.bookmark_manager()

    def _session(self):
        return self.driver.session(database=self.database, bookmark_manager=self._bookmarks)

    def close(self):
        self.driver.close()

    def migrate(self):
        source = (Path(__file__).parent / "migrations" / "001_memory.cypher").read_text()
        with self._session() as session:
            for statement in source.split(";"):
                if statement.strip():
                    session.run(statement).consume()

    @staticmethod
    def _read_attempt(tx, aid, lock=False):
        locking = "SET a.lock_version = coalesce(a.lock_version, 0) + 1" if lock else ""
        row = tx.run(f"MATCH (a:Attempt {{attempt_id: $aid}}) {locking} RETURN a.payload AS payload", aid=aid).single()
        if row is None:
            raise KeyError(aid)
        return json.loads(row["payload"])

    @staticmethod
    def _write_attempt(tx, attempt):
        aid = attempt["attempt_id"]
        props = {key: _identity(attempt, key) for key in ("task", "robot", "policy_revision", "perception_mode")}
        props.update({key: _meta(attempt, key) for key in ("provenance", "dataset_split")})
        props.update({"status": attempt.get("status"), "outcome": attempt.get("outcome"), "step_index": attempt.get("step_index", 0)})
        tx.run("MATCH (a:Attempt {attempt_id:$aid}) SET a += $props, a.payload=$payload", aid=aid, props=props, payload=_json(attempt)).consume()

    def start_attempt(self, attempt: dict) -> dict:
        attempt = {"step_index": 0, "status": "running", "outcome": None, **copy.deepcopy(attempt)}
        _validate_attempt(attempt)
        digest, aid = _hash(attempt), attempt["attempt_id"]
        def write(tx):
            row = tx.run("MERGE (a:Attempt {attempt_id:$aid}) ON CREATE SET a.start_hash=$digest, a.payload=$payload SET a.lock_version=coalesce(a.lock_version,0)+1 RETURN a.start_hash AS digest, a.payload AS payload", aid=aid, digest=digest, payload=_json(attempt)).single()
            if row["digest"] != digest:
                raise MemoryConflict("attempt ID reused with a different payload")
            existing = json.loads(row["payload"])
            previous = attempt.get("previous_attempt_id")
            if previous:
                self._read_attempt(tx, previous)
                tx.run("MATCH (a:Attempt {attempt_id:$aid}), (p:Attempt {attempt_id:$previous}) MERGE (a)-[:RETRY_OF]->(p)", aid=aid, previous=previous).consume()
            self._write_attempt(tx, existing)
            tx.run("MATCH (a:Attempt {attempt_id:$aid}) MERGE (r:Run {run_id:$run}) MERGE (t:Task {task_id:$task}) MERGE (r)-[:HAS_ATTEMPT]->(a) MERGE (a)-[:FOR_TASK]->(t)", aid=aid, run=str(_meta(attempt, "run_id", "unassigned")), task=str(_identity(attempt,"task") or "unknown")).consume()
            return existing
        with self._session() as session:
            return session.execute_write(write)

    def get_attempt(self, attempt_id: str) -> dict:
        with self._session() as session:
            return session.execute_read(lambda tx: self._read_attempt(tx, attempt_id))

    def commit_decision(self, attempt_id: str, expected_step_index: int, decision: dict, attempt_update: dict) -> dict:
        digest = _hash([attempt_id, expected_step_index, decision, attempt_update])
        did = decision.get("decision_id")
        if not did:
            raise MemoryValidationError("decision_id is required")
        def write(tx):
            attempt = self._read_attempt(tx, attempt_id, lock=True)
            existing = tx.run("MATCH (d:DecisionStep {decision_id:$did}) RETURN d.commit_hash AS digest", did=did).single()
            if existing:
                if existing["digest"] != digest:
                    raise MemoryConflict("decision ID reused with a different payload")
                return attempt
            result = _validate_decision(attempt, expected_step_index, decision, attempt_update)
            stored = {**decision, "attempt_id": attempt_id}
            tx.run("MATCH (a:Attempt {attempt_id:$aid}) CREATE (d:DecisionStep {decision_id:$did, commit_hash:$digest, payload:$payload, stage:$stage}) MERGE (a)-[:HAS_DECISION]->(d)", aid=attempt_id, did=did, digest=digest, payload=_json(stored), stage=decision.get("planner", {}).get("stage")).consume()
            graph = _graph({attempt_id: result}, {did: stored})
            for node in graph["nodes"]:
                label, props = node["label"], node["properties"]
                if label in ("Attempt", "Task", "Run", "DecisionStep"):
                    continue
                identity = node["id"].split(":", 1)[1]
                # Labels and identity property names come from this fixed graph builder.
                record = tx.run(f"MERGE (n:{label} {{id:$id}}) ON CREATE SET n.payload=$payload RETURN n.payload AS payload", id=identity, payload=_json(props)).single()
                if record["payload"] != _json(props):
                    raise MemoryConflict(f"immutable {label} ID reused with a different payload")
            keys = {"Attempt":"attempt_id", "DecisionStep":"decision_id", "Task":"task_id", "Run":"run_id"}
            for edge in graph["edges"]:
                sl, sid = edge["source"].split(":", 1)
                tl, tid = edge["target"].split(":", 1)
                tx.run(f"MATCH (s:{sl} {{{keys.get(sl,'id')}:$sid}}), (t:{tl} {{{keys.get(tl,'id')}:$tid}}) MERGE (s)-[r:{edge['type']}]->(t) SET r += $props", sid=sid, tid=tid, props=edge["properties"]).consume()
            self._write_attempt(tx, result)
            return result
        with self._session() as session:
            return session.execute_write(write)

    def finalize_attempt(self, attempt_id: str, update: dict) -> dict:
        def write(tx):
            result = _updated(self._read_attempt(tx, attempt_id, lock=True), update)
            if result.get("status") != "completed":
                raise MemoryValidationError("finalize_attempt requires completed status")
            self._write_attempt(tx, result)
            return result
        with self._session() as session:
            return session.execute_write(write)

    def freeze_snapshot(self, snapshot_id: str, attempt_ids: list[str]) -> dict:
        snapshot = {"snapshot_id": snapshot_id, "attempt_ids": sorted(set(attempt_ids))}
        digest = _hash(snapshot)
        def write(tx):
            row = tx.run("MERGE (s:MemorySnapshot {snapshot_id:$sid}) ON CREATE SET s.digest=$digest, s.payload=$payload SET s.lock_version=coalesce(s.lock_version,0)+1 RETURN s.digest AS digest", sid=snapshot_id,digest=digest,payload=_json(snapshot)).single()
            if row["digest"] != digest:
                raise MemoryConflict("snapshot membership is immutable")
            for aid in snapshot["attempt_ids"]:
                a = self._read_attempt(tx, aid, lock=True)
                if a.get("status") != "completed" or a.get("outcome") not in ("success","failure") or _meta(a,"provenance") != "real_execution" or _meta(a,"dataset_split") != "memory_build":
                    raise MemoryValidationError("snapshots accept completed real memory-building attempts only")
                tx.run("MATCH (s:MemorySnapshot {snapshot_id:$sid}), (a:Attempt {attempt_id:$aid}) MERGE (s)-[:INCLUDES]->(a)", sid=snapshot_id, aid=aid).consume()
            return snapshot
        with self._session() as session:
            return session.execute_write(write)

    def search_experiences(self, query: dict) -> list[dict]:
        if any(_identity(query,k) is None for k in ("task","robot","policy_revision","perception_mode")):
            return []
        params = {key:_identity(query,key) for key in ("task","robot","policy_revision","perception_mode")}
        params["sid"] = query.get("snapshot_id")
        def read(tx):
            # Corpus is bounded by its frozen membership. Retry expansions are
            # constrained at EVERY node; no evaluation records enter this query.
            rows = tx.run("""
                MATCH (s:MemorySnapshot {snapshot_id:$sid})-[:INCLUDES]->(a:Attempt)
                WHERE a.status='completed' AND a.outcome IN ['success','failure']
                  AND a.provenance='real_execution' AND a.dataset_split='memory_build'
                  AND a.task=$task AND a.robot=$robot AND a.policy_revision=$policy_revision
                  AND a.perception_mode=$perception_mode
                OPTIONAL MATCH (a)-[:HAS_DECISION]->(d:DecisionStep)
                RETURN a.payload AS attempt, d.payload AS decision
                """, **params)
            attempts, decisions = {}, {}
            for row in rows:
                a = json.loads(row["attempt"])
                attempts[a["attempt_id"]] = a
                if row["decision"]:
                    d = json.loads(row["decision"])
                    decisions[d["decision_id"]] = d
            paths = {}
            for row in tx.run("""
                MATCH (s:MemorySnapshot {snapshot_id:$sid})-[:INCLUDES]->(failed:Attempt)
                MATCH path=(failed)<-[:RETRY_OF*1..3]-(retry:Attempt)
                WHERE failed.outcome='failure' AND all(n IN nodes(path) WHERE
                    EXISTS { MATCH (s)-[:INCLUDES]->(n) }
                    AND n.status='completed' AND n.outcome IN ['success','failure']
                    AND n.provenance='real_execution' AND n.dataset_split='memory_build'
                    AND n.task=$task AND n.robot=$robot
                    AND n.policy_revision=$policy_revision AND n.perception_mode=$perception_mode)
                RETURN retry.attempt_id AS retry, [n IN nodes(path) | n.attempt_id] AS path
                """, **params):
                paths.setdefault(row["retry"], []).append(list(reversed(row["path"][:-1])))
            return _search(attempts, decisions, {"attempt_ids":list(attempts)}, query, paths)
        with self._session() as session:
            return session.execute_read(read)

    def export_graph(self, attempt_ids: list[str] | None = None) -> dict:
        def read(tx):
            attempts, decisions = {}, {}
            for row in tx.run("MATCH (a:Attempt) WHERE $ids IS NULL OR a.attempt_id IN $ids OPTIONAL MATCH (a)-[:HAS_DECISION]->(d:DecisionStep) RETURN a.payload AS attempt, d.payload AS decision", ids=attempt_ids):
                a = json.loads(row["attempt"])
                attempts[a["attempt_id"]] = a
                if row["decision"]:
                    d = json.loads(row["decision"])
                    decisions[d["decision_id"]] = d
            return _export_graph(attempts, decisions)
        with self._session() as session:
            return session.execute_read(read)
