import os
from fastapi import FastAPI, HTTPException
from .engine import Engine, WorkerError
from .protocol import ExecutionRequest, ResetRequest
from .robots import FakeRobot, LiberoRobot

def create_app(engine=None):
    app = FastAPI(title='ARMA Robot Worker',version='1.0')
    if engine is None:
        mode = os.environ.get('ARMA_WORKER_MODE','real')
        if mode not in {'real','fake'}:
            raise ValueError('ARMA_WORKER_MODE must be real or fake')
        engine = Engine(FakeRobot() if mode == 'fake' else LiberoRobot(),os.environ.get('ARMA_ARTIFACT_DIR','artifacts/worker'))
    app.state.engine = engine

    def call(fn,*args):
        try:
            return fn(*args)
        except WorkerError as exc:
            raise HTTPException(exc.status_code,str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503,f'Robot unavailable ({type(exc).__name__}); inspect worker logs') from exc

    @app.get('/health')
    def health():
        return engine.health()
    @app.post('/sessions/reset')
    def reset(request:ResetRequest):
        return call(engine.reset,request)
    @app.post('/sessions/{session_id}/execute')
    def execute(session_id:str,request:ExecutionRequest):
        return call(engine.execute,session_id,request)
    @app.get('/sessions/{session_id}/executions/{execution_id}')
    def status(session_id:str,execution_id:str):
        return call(engine.status,session_id,execution_id)
    @app.post('/sessions/{session_id}/close')
    def close(session_id:str):
        return call(engine.close,session_id)
    return app
