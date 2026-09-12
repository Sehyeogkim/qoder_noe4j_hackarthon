"""Run with the pod's existing Python BEFORE large installs or checkpoint download.

This intentionally executes a tiny real CUDA tensor operation. nvidia-smi alone
is not sufficient evidence that CUDA is usable by the container.
"""
import argparse
import ctypes
import json
import os
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-gpu',default=os.environ.get('ARMA_EXPECTED_GPU','NVIDIA A40'))
    args=parser.parse_args()
    result={'expected_gpu':args.expected_gpu,'model_loaded':False}
    try:
        result['cuInit_code']=ctypes.CDLL('libcuda.so.1').cuInit(0)
        if result['cuInit_code']!=0:
            raise RuntimeError('CUDA driver initialization failed')
        import torch
        result['torch_version']=torch.__version__
        result['cuda_available']=torch.cuda.is_available()
        if not result['cuda_available']:
            raise RuntimeError('PyTorch CUDA unavailable')
        result['gpu_name']=torch.cuda.get_device_name(0)
        if result['gpu_name']!=args.expected_gpu:
            raise RuntimeError('GPU differs from explicitly selected hardware')
        x=torch.ones((16,16),device='cuda',dtype=torch.bfloat16)
        result['bf16_matmul_sum']=(x@x).float().sum().item()
        if result['bf16_matmul_sum']!=4096:
            raise RuntimeError('CUDA BF16 matrix operation failed')
        torch.cuda.synchronize()
        result['ready']=True
    except Exception as exc:
        result['ready']=False
        result['error_type']=type(exc).__name__
        result['error']=str(exc)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['ready'] else 1

if __name__=='__main__':sys.exit(main())
