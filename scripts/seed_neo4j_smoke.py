"""Insert a clearly synthetic fixture through the real ARMA memory adapter.

No LLM, simulator, snapshot, deletion, or credential output is involved.
Run from the repository root with .venv/bin/python scripts/seed_neo4j_smoke.py.
Add --apply to write to the configured Neo4j instance and verify physical edges.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from arma.memory import InMemoryRepository, Neo4jRepository

FIELDS = {
    "attempt_id", "step_index", "task_goal", "success_criteria",
    "initial_context", "executed_instruction", "status", "outcome",
    "termination_reason", "latest_observation_ref", "evidence_refs",
    "judgment_source", "observed_facts", "cause_hypothesis", "previous_attempt_id",
}


def validate_fixture(fixture: dict) -> None:
    assert fixture["provenance"] == "synthetic"
    for entry in fixture["entries"]:
        attempt = entry["attempt"]
        assert FIELDS <= attempt.keys()
        assert attempt["provenance"] == "synthetic"
        assert attempt["dataset_split"] == "smoke_test"
        assert attempt["run_id"] == fixture["run_id"]
        for evidence in entry["decision"]["evidence"]:
            path = ROOT / evidence["uri"]
            assert path.is_relative_to(ROOT)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]


def seed_and_read(repo, fixture: dict) -> list[dict]:
    for entry in fixture["entries"]:
        repo.start_attempt(entry["attempt"])
        repo.commit_decision(entry["attempt"]["attempt_id"], 0,
                             entry["decision"], entry["attempt_update"])
    records = []
    for entry in fixture["entries"]:
        actual = repo.get_attempt(entry["attempt"]["attempt_id"])
        expected = {**entry["attempt"], **entry["attempt_update"]}
        assert actual == expected, "Neo4j logical payload did not round-trip"
        assert FIELDS <= actual.keys()
        records.append(actual)
    return records


def physical_graph(repo, run_id: str) -> dict:
    # Read actual nodes/relationships; export_graph alone reconstructs them.
    with repo.driver.session(database=repo.database) as session:
        paths = session.run(
            "MATCH p=(r:Run {run_id:$run_id})-[:HAS_ATTEMPT]->"
            "(:Attempt)-[*0..2]->() RETURN p", run_id=run_id
        )
        nodes, relationships = {}, {}
        for record in paths:
            for node in record["p"].nodes:
                nodes[node.element_id] = {
                    "labels": sorted(node.labels),
                    "key": node.get("attempt_id", node.get("decision_id", node.get("run_id", node.get("task_id", node.get("id"))))),
                }
            for rel in record["p"].relationships:
                relationships[rel.element_id] = {
                    "type": rel.type, "source": rel.start_node.element_id,
                    "target": rel.end_node.element_id,
                }
        label_counts, relationship_counts = {}, {}
        for node in nodes.values():
            for label in node["labels"]:
                label_counts[label] = label_counts.get(label, 0) + 1
        for rel in relationships.values():
            relationship_counts[rel["type"]] = relationship_counts.get(rel["type"], 0) + 1
        assert label_counts.get("Attempt") == 2
        assert label_counts.get("DecisionStep") == 2
        assert label_counts.get("StepEvent") == 2
        assert relationship_counts.get("RETRY_OF") == 1
        assert relationship_counts.get("RETRIEVED") == 1
        assert relationship_counts.get("HAS_EVIDENCE") == 2
        return {"node_count": len(nodes), "relationship_count": len(relationships),
                "labels": label_counts, "relationships": relationship_counts,
                "nodes": nodes, "edges": relationships}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    fixture = json.loads((ROOT / "fixtures/neo4j-smoke/memory.json").read_text())
    validate_fixture(fixture)
    if args.apply:
        load_dotenv(ROOT / ".env")
        repo = Neo4jRepository(os.environ["NEO4J_URI"], os.environ["NEO4J_USERNAME"],
                               os.environ["NEO4J_PASSWORD"], os.environ.get("NEO4J_DATABASE", "neo4j"))
    else:
        repo = InMemoryRepository()
    try:
        if args.apply:
            repo.driver.verify_connectivity()
            repo.migrate()
        records = seed_and_read(repo, fixture)
        before = physical_graph(repo, fixture["run_id"]) if args.apply else repo.export_graph()
        # Re-run the exact fixture to prove ID-safe insertion without duplicates.
        assert seed_and_read(repo, fixture) == records
        after = physical_graph(repo, fixture["run_id"]) if args.apply else repo.export_graph()
        assert before == after, "Repeated seed changed the graph"
        report = {"mode": "neo4j" if args.apply else "dry_run", "run_id": fixture["run_id"],
                  "provenance": "synthetic", "round_trip": True, "idempotent": True,
                  "outcomes": {a["attempt_id"]: a["outcome"] for a in records}, "graph": after}
        output = ROOT / "artifacts/neo4j-smoke"
        output.mkdir(parents=True, exist_ok=True)
        (output / ("verification.json" if args.apply else "dry-run.json")).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        summary = {k: v for k, v in report.items() if k != "graph"}
        if args.apply:
            summary.update({k: after[k] for k in ("node_count", "relationship_count", "labels", "relationships")})
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        if args.apply:
            repo.close()


if __name__ == "__main__":
    main()
