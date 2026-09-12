"""Preload the frozen model once before opening the local HTTP listener."""
import argparse
import os
import socket


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1',choices=['127.0.0.1'])
    parser.add_argument('--port',default=18001,type=int)
    args=parser.parse_args()
    os.environ.setdefault('HF_HOME','/workspace/arma/hf-cache')
    os.environ.setdefault('MUJOCO_GL','egl')
    os.environ.setdefault('PYOPENGL_PLATFORM','egl')
    os.environ.setdefault('CUDA_VISIBLE_DEVICES','0')
    os.environ.setdefault('MUJOCO_EGL_DEVICE_ID','0')
    from .app import create_app
    import uvicorn
    # Reserve the address before loading 7B weights. Binding without listening
    # detects occupied ports cheaply and does not expose HTTP before readiness.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind((args.host,args.port))
        app=create_app()
        robot=app.state.engine.robot
        if hasattr(robot,'_load'):
            robot._load()
        # The exact loaded instance serves subsequent resets. No second copy.
        config=uvicorn.Config(app,host=args.host,port=args.port,workers=1)
        uvicorn.Server(config).run(sockets=[listener])

if __name__=='__main__':main()
