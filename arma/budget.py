"""Durable, pessimistic reservation ledger; ambiguous calls retain their reserve."""
import json
import math
import sqlite3
import time
import uuid
from pathlib import Path

class BudgetExceeded(RuntimeError):
    pass

class Budget:
    def __init__(self, path=".runtime/budget.sqlite", api_limit=4.0, compute_limit=5.0):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.limits = {"api": api_limit, "compute": compute_limit}
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS charges (id TEXT PRIMARY KEY, category TEXT, amount REAL, settled INTEGER, metadata TEXT, created REAL)")

    def _db(self):
        return sqlite3.connect(self.path, timeout=30)

    def reserve(self, amount, category="api", metadata=None):
        if not math.isfinite(amount) or amount < 0 or category not in self.limits:
            raise ValueError("Invalid budget reservation")
        charge_id = uuid.uuid4().hex
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute("SELECT COALESCE(SUM(amount),0) FROM charges WHERE category=?", (category,)).fetchone()[0]
            if used + amount > self.limits[category] + 1e-10:
                raise BudgetExceeded(f"{category} allocation exhausted")
            db.execute("INSERT INTO charges VALUES (?,?,?,?,?,?)", (charge_id,category,amount,0,json.dumps(metadata or {}),time.time()))
        return charge_id

    def settle(self, charge_id, actual, metadata=None):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT amount,settled FROM charges WHERE id=?",(charge_id,)).fetchone()
            if row is None or not math.isfinite(actual) or actual < 0:
                raise ValueError("Invalid settlement")
            if row[1]:
                if abs(row[0]-actual)>1e-9:
                    raise ValueError("Conflicting settlement")
                return
            db.execute("UPDATE charges SET amount=?,settled=1,metadata=? WHERE id=?",(actual,json.dumps(metadata or {}),charge_id))

    def retain_unsettled_upper_bound(self, charge_id, amount, proof_metadata):
        """Release unused reservation after cloud verifies termination, not billing.

        The retained amount remains unsettled and explicitly estimated. This is
        not settle(); a later actual provider bill replaces it via settle().
        """
        if not math.isfinite(amount) or amount <= 0 or not proof_metadata.get("deletion_proof_signature"):
            raise ValueError("Positive upper bound and verified deletion proof required")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT category,amount,settled,metadata FROM charges WHERE id=?",(charge_id,)).fetchone()
            if not row or row[0]!="compute" or row[2] or amount>row[1]:
                raise ValueError("Only an unsettled compute reservation may be reduced")
            metadata=json.loads(row[3])
            if metadata.get("pod_id")!=proof_metadata.get("pod_id"):
                raise ValueError("Termination proof belongs to another pod")
            previous=metadata.get("reservation_history",[])
            if row[1] != amount:
                previous=previous+[{"previous_amount":row[1],"retained_amount":amount,"at":time.time()}]
            metadata.update(proof_metadata)
            metadata.update({"state":"estimated_upper_bound_unsettled","billing_confirmed":False,
                             "reservation_history":previous})
            db.execute("UPDATE charges SET amount=?,metadata=? WHERE id=?",(amount,json.dumps(metadata),charge_id))
        return amount

    def totals(self):
        with self._db() as db:
            rows = db.execute("SELECT category,SUM(amount) FROM charges GROUP BY category").fetchall()
        return {k: dict(rows).get(k,0.0) for k in self.limits}

    def remaining(self, category="api"):
        return max(0.0,self.limits[category]-self.totals()[category])

    @staticmethod
    def api_cost(input_tokens, output_tokens):
        return (input_tokens*0.5 + output_tokens*3.0)/1_000_000
