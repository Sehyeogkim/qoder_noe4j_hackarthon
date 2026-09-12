"""One physical execution at a time, with write-ahead idempotency intent.

A process restart cannot restore MuJoCo reliably. Outstanding intents become
unknown; completed results remain readable but no session is silently resumed.
"""
import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from .protocol import ActionEvent, ExecutionRequest, ExecutionResult, Observation, ResetRequest

class WorkerError(Exception):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code

class Engine:
    def __init__(self, robot, artifact_dir, action_budget=220):
        self.robot = robot
        self.root = Path(artifact_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.action_budget = action_budget
        self.lock = threading.Lock()
        self.db_lock = threading.RLock()
        self.db = sqlite3.connect(self.root / 'executions.sqlite3', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS executions (execution_id TEXT PRIMARY KEY, session_id TEXT, payload TEXT, status TEXT, result TEXT, error TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS resets (attempt_id TEXT PRIMARY KEY, payload TEXT, status TEXT, result TEXT)')
        self.db.execute("UPDATE executions SET status='unknown', error='worker restarted before durable completion' WHERE status='running'")
        self.db.execute("UPDATE resets SET status='unknown' WHERE status='running'")
        self.db.commit()
        self.session = None

    def _digest(self, req):
        return hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True).encode()).hexdigest()

    def _observe(self, step):
        session_id = self.session['session_id']
        path = self.root / session_id / f'frame-{step:04d}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.robot.save_rgb(path)
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        return Observation(observation_id=f'{session_id}:obs:{step}', step_index=step,
                           rgb_ref=str(path), evidence_id=f'{session_id}:rgb:{step}',
                           sha256=content_hash, task_success=bool(self.robot.check_success()))

    def reset(self, req: ResetRequest):
        if not self.lock.acquire(blocking=False):
            raise WorkerError('worker busy')
        try:
            payload = self._digest(req)
            with self.db_lock:
                old = self.db.execute('SELECT payload,status,result FROM resets WHERE attempt_id=?', (req.attempt_id,)).fetchone()
            if old:
                if old[0] != payload:
                    raise WorkerError('reset payload conflicts with existing attempt')
                if old[1] == 'completed' and self.session and self.session['attempt_id'] == req.attempt_id:
                    return json.loads(old[2])
                raise WorkerError('attempt already reset; create a new attempt after restart or close')
            if self.session:
                raise WorkerError('close current session before reset')
            with self.db_lock:
                self.db.execute('INSERT INTO resets VALUES (?,?,?,NULL)', (req.attempt_id,payload,'running'))
                self.db.commit()
            self.session = {'session_id': str(uuid.uuid4()), 'attempt_id': req.attempt_id, 'step': 0, 'unknown': False}
            try:
                manifest = self.robot.reset(req)
                observation = self._observe(0)
                self.session['observation'] = observation
                result = {'session_id':self.session['session_id'], 'observation':observation.model_dump(), 'manifest':manifest}
                (self.root / self.session['session_id'] / 'manifest.json').write_text(json.dumps(manifest, indent=2))
                with self.db_lock:
                    self.db.execute('UPDATE resets SET status=?,result=? WHERE attempt_id=?', ('completed',json.dumps(result),req.attempt_id))
                    self.db.commit()
                return result
            except Exception:
                self.session['unknown'] = True
                try:
                    self.robot.close()
                finally:
                    self.session = None
                with self.db_lock:
                    self.db.execute("UPDATE resets SET status='unknown' WHERE attempt_id=?", (req.attempt_id,))
                    self.db.commit()
                raise
        finally:
            self.lock.release()

    def status(self, session_id, execution_id):
        with self.db_lock:
            row = self.db.execute('SELECT session_id,status,result,error FROM executions WHERE execution_id=?', (execution_id,)).fetchone()
        if not row or row[0] != session_id:
            raise WorkerError('execution not found',404)
        return {'execution_id':execution_id,'status':row[1], 'result':json.loads(row[2]) if row[2] else None,'error':row[3]}

    def execute(self, session_id, req: ExecutionRequest):
        if not self.lock.acquire(blocking=False):
            raise WorkerError('worker busy; query execution status')
        try:
            payload = self._digest(req)
            with self.db_lock:
                old = self.db.execute('SELECT session_id,payload,status,result FROM executions WHERE execution_id=?',(req.execution_id,)).fetchone()
            if old:
                if old[0] != session_id or old[1] != payload:
                    raise WorkerError('execution ID payload conflict')
                if old[2] == 'completed':
                    return ExecutionResult.model_validate_json(old[3])
                raise WorkerError('execution is unresolved; do not replay')
            s = self.session
            if not s or s['session_id'] != session_id:
                raise WorkerError('session not available',404)
            if s['unknown']:
                raise WorkerError('session execution is unknown; close and create new attempt')
            if req.attempt_id != s['attempt_id']:
                raise WorkerError('attempt mismatch')
            before = s['observation']
            if req.expected_step_index != s['step'] or req.observation_id != before.observation_id:
                raise WorkerError('stale step or observation')
            if before.task_success or s['step'] >= self.action_budget:
                raise WorkerError('attempt is already terminal')
            if req.max_actions > self.action_budget - s['step']:
                raise WorkerError('requested interval exceeds remaining action budget')
            with self.db_lock:
                self.db.execute('INSERT INTO executions VALUES (?,?,?,?,NULL,NULL)', (req.execution_id,session_id,payload,'running'))
                self.db.commit()
            started = time.monotonic()
            events = []
            try:
                for _ in range(req.max_actions):
                    # predict uses the current live robot observation, updated by step().
                    raw, action = self.robot.predict(req.executed_instruction)
                    raw, action = [float(v) for v in raw], [float(v) for v in action]
                    if len(raw) != 7 or len(action) != 7 or not all(math.isfinite(v) for v in raw + action):
                        raise ValueError('policy must return finite 7D raw and environment actions')
                    self.robot.step(action)
                    s['step'] += 1
                    after = self._observe(s['step'])
                    s['observation'] = after
                    event = ActionEvent(step_index=s['step'],raw_policy_action=raw,env_action=action,
                                        resulting_observation_id=after.observation_id,evidence_id=after.evidence_id,rgb_ref=after.rgb_ref)
                    events.append(event)
                    with (self.root / session_id / 'actions.jsonl').open('a') as f:
                        f.write(json.dumps({'execution_id':req.execution_id,**event.model_dump()})+'\n')
                        f.flush()
                        import os
                        os.fsync(f.fileno())
                    if after.task_success:
                        break
                after = s['observation']
                reason = 'task_success' if after.task_success else ('action_budget_exhausted' if s['step'] >= self.action_budget else 'interval_complete')
                result = ExecutionResult(execution_id=req.execution_id,start_step_index=before.step_index,end_step_index=after.step_index,
                    observation_before_id=before.observation_id,observation_after_id=after.observation_id,
                    observation_before=before,observation_after=after,actual_instruction=req.executed_instruction,
                    actions=events,task_success=after.task_success,termination_reason=reason,
                    artifact_refs=[before.rgb_ref]+[e.rgb_ref for e in events],elapsed_ms=(time.monotonic()-started)*1000)
                with self.db_lock:
                    self.db.execute('UPDATE executions SET status=?,result=? WHERE execution_id=?',('completed',result.model_dump_json(),req.execution_id))
                    self.db.commit()
                return result
            except Exception as exc:
                s['unknown'] = True
                with self.db_lock:
                    self.db.execute('UPDATE executions SET status=?,error=? WHERE execution_id=?',('unknown',type(exc).__name__+': '+str(exc),req.execution_id))
                    self.db.commit()
                raise WorkerError('execution uncertain; inspect status and terminate attempt') from exc
        finally:
            self.lock.release()

    def close(self, session_id):
        if not self.lock.acquire(blocking=False):
            raise WorkerError('cannot close while executing')
        try:
            if not self.session or self.session['session_id'] != session_id:
                raise WorkerError('session not available',404)
            video = None
            video_error = None
            try:
                video = self.robot.export_video(self.root / session_id / 'rollout.mp4')
            except Exception as exc:
                video_error = type(exc).__name__
            finally:
                try:
                    self.robot.close()
                finally:
                    self.session = None
            return {'session_id':session_id,'closed':True,'video_ref':str(video) if video else None,'video_error':video_error}
        finally:
            self.lock.release()

    def health(self):
        details = self.robot.health()
        return {'ready': bool(details.get('model_loaded')),
                'session_ready': self.session is not None and not self.session.get('unknown', False),
                'session_active': self.session is not None, **details}
