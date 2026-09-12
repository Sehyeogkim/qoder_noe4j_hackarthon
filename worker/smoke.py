"""GPU/EGL smoke only; does not download or load the policy."""
import os
os.environ.setdefault('MUJOCO_GL','egl')
os.environ.setdefault('PYOPENGL_PLATFORM','egl')

def main():
    import torch
    import numpy as np
    from libero.libero import benchmark
    from experiments.robot.libero.libero_utils import get_libero_env
    from .protocol import TASK_NAME
    assert torch.cuda.is_available(), 'CUDA unavailable'
    value=(torch.ones((2,2),device='cuda') @ torch.ones((2,2),device='cuda')).cpu()
    assert value.sum().item()==8
    suite=benchmark.get_benchmark_dict()['libero_spatial'](task_order_index=0)
    task_id=next(i for i in range(suite.n_tasks) if suite.get_task(i).name==TASK_NAME)
    env,_=get_libero_env(suite.get_task(task_id),'openvla',resolution=256)
    try:
        env.reset()
        states=suite.get_task_init_states(task_id)
        assert len(states)>12
        obs=env.set_init_state(states[4])
        rgb=obs['agentview_image']
        assert rgb.shape==(256,256,3) and np.isfinite(rgb).all() and rgb.std()>0
        from pathlib import Path
        from PIL import Image
        import hashlib,json
        output=Path(os.environ.get('ARMA_SMOKE_RGB','artifacts/renderer-smoke.png')).resolve()
        output.parent.mkdir(parents=True,exist_ok=True)
        Image.fromarray(rgb[::-1,::-1].copy()).save(output)
        evidence={'rgb_ref':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                  'task_name':TASK_NAME,'init_state_id':4,'policy_loaded':False,'policy_actions':0,
                  'kind':'real_simulator_smoke','renderer':os.environ['MUJOCO_GL']}
        output.with_suffix('.json').write_text(json.dumps(evidence,indent=2))
        print('CUDA matmul and EGL RGB smoke passed; policy not loaded.')
        print(json.dumps(evidence))
    finally:
        env.close()

if __name__=='__main__':
    main()
