import time
import httpx

class ExecutionUnknown(RuntimeError):
    pass

class RobotClient:
    def __init__(self, url="http://127.0.0.1:8001"):
        self.client=httpx.Client(base_url=url,timeout=120)
    def health(self):
        r=self.client.get('/health'); r.raise_for_status(); return r.json()
    def reset(self,request):
        r=self.client.post('/sessions/reset',json=request);r.raise_for_status();return r.json()
    def execute(self,session_id,request):
        try:
            r=self.client.post(f'/sessions/{session_id}/execute',json=request)
            r.raise_for_status();return r.json()
        except (httpx.TimeoutException,httpx.NetworkError):
            # Reconcile only; never re-post uncertain actions.
            for _ in range(30):
                try:
                    r=self.client.get(f'/sessions/{session_id}/executions/{request["execution_id"]}')
                    r.raise_for_status();status=r.json()
                    if status['status']=='completed':return status['result']
                    if status['status']=='unknown':break
                except (httpx.HTTPError,KeyError):
                    pass
                time.sleep(2)
            raise ExecutionUnknown("Robot execution status cannot be recovered")
    def close(self,session_id):
        r=self.client.post(f'/sessions/{session_id}/close');r.raise_for_status();return r.json()
