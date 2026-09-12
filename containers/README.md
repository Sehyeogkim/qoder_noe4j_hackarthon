# CPU preparation, then A40 runtime

The image prepares pinned OpenVLA/LIBERO software on an **amd64 CPU Docker host**.
It does not download the 7B checkpoint, require a GPU, or run robot inference.
Local Docker is not installed in the current workspace; this image has not been
built here. Do not describe the Docker recipe as a verified image build.

```bash
docker build --platform linux/amd64 -f containers/Dockerfile -t arma-worker:astras .
```

The base is the verified public RunPod CUDA 12.1 / PyTorch 2.2.0 image, pinned by
digest. Worker Python 3.10.13 and backend Python 3.11 use separate environments.
`TORCH_CUDA_ARCH_LIST=8.6` targets the currently authorized A40 for extension
builds. The same recipe can target L40S only when explicitly selected, using
`--build-arg ARMA_CUDA_ARCH=8.9 --build-arg "ARMA_EXPECTED_GPU=NVIDIA L40S"`. FlashAttention 2.5.5 itself explicitly builds sm80/sm90 kernels in its
upstream setup script; this environment variable does not rewrite those flags.
Installation uses the verified upstream prebuilt CUDA 12.x / Torch 2.2 / Python
3.10 wheel first; it does not compile CUDA or import a model by default. Source
compilation requires the explicit `ARMA_ALLOW_FLASH_SOURCE_BUILD=1` setting and
imports PyTorch for ABI/version metadata without executing CUDA operations. CUDA toolkit headers and nvcc are present on the CPU
build host inside the devel image. `MAX_JOBS=2` bounds compiler concurrency.

The dependency resolver can be checked without Docker or a GPU:

```bash
bash containers/check_dependencies.sh
```

This checks Linux/Python 3.10 dependency resolution, not native linking or EGL.
The full resolved worker and backend package versions must be captured after
installation. Runtime behavior remains gated by the subsequent smoke test.

On the later, explicitly authorized single **NVIDIA A40 48 GB** pod:

```bash
# Must pass before checkpoint download. nvidia-smi alone is not sufficient.
python worker/gpu_preflight.py --expected-gpu "NVIDIA A40"
/opt/venvs/worker/bin/python -m worker.smoke
/opt/venvs/worker/bin/python -m worker.serve --port 18001
```

The server preloads the frozen checkpoint before accepting HTTP requests and
writes its exact revision into the attempt manifest. Port 18001 avoids the
RunPod base image nginx service commonly occupying port 8001. Nothing in the Docker build creates, starts, stops, or bills a pod.
Use the ARMA ownership manifest/watchdog and the $5 compute reservation before
provisioning. Keep artifacts under `/workspace/arma/artifacts`, and keep API keys
in runtime environment variables. The Docker context excludes `.env`, logs,
recordings, private keys, and existing local runtime data.

Runtime verification on the existing L40S pod found and fixed compatibility
issues that dependency resolution alone did not reveal: the LIBERO namespace
needs an explicit source-root `.pth` under modern editable installs; robosuite
1.4.1 uses MuJoCo 2.3.7; TensorFlow 2.15/tfds 4.9.3 use tensorflow-metadata
1.14.0, protobuf 3.20.3 and wandb 0.16.6. These versions are now pinned.

The checkpoint's `auto_map` points to Python code in a separate Hugging Face
repository. Offline loading uses the audited classes from the pinned OpenVLA
checkout with remote code disabled, preserving the model weights and official
preprocessing. Adapter version and source hash are recorded in the manifest.
A newer CUDA 12.8 host is supported with the prebuilt CUDA 12.x wheels; the
12.1 devel-toolkit check applies only to an explicitly requested source build.
