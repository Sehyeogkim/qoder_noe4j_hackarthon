"""Lazy real adapter and explicitly synthetic test adapter."""
import hashlib
import importlib.metadata
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from .protocol import CHECKPOINT, TASK_NAME

OPENVLA_SHA = 'c8f03f48af692657d3060c19588038c7220e9af9'
LIBERO_SHA = '8f1084e3132a39270c3a13ebe37270a43ece2a01'
ADAPTER_VERSION = 'arma-openvla-libero-v2-local-pinned-hf'

def stable_policy_id(manifest):
    identity = {key:manifest[key] for key in ('checkpoint','hf_revision','unnorm_key','openvla_commit','libero_commit')}
    identity['adapter_version'] = ADAPTER_VERSION
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()

class FakeRobot:
    """Offline contract fixture. Never usable as a real_execution record."""
    def __init__(self, success_at=3, fail_at=None):
        self.success_at, self.fail_at = success_at, fail_at
        self.step_count = 0
        self.prediction_frames = []
        self.frames = []
    def reset(self, req):
        self.step_count = 0
        self.prediction_frames = []
        self.frames = []
        return {'provenance':'synthetic_fixture','task_name':req.task_name,'init_state_id':req.init_state_id,'seed':req.seed,'settling_actions':10,'policy':'fake','policy_id':'synthetic-fixture-v1','perception_mode':'fixture'}
    def predict(self, instruction):
        self.prediction_frames.append(self.step_count)
        return [0.0]*7, [0.0]*7
    def step(self, action):
        self.step_count += 1
        if self.step_count == self.fail_at:
            raise RuntimeError('injected execution failure')
    def check_success(self):
        return self.success_at is not None and self.step_count >= self.success_at
    def save_rgb(self, path):
        from PIL import Image, ImageDraw
        image = Image.new('RGB',(256,256),(235,241,243))
        draw = ImageDraw.Draw(image)
        draw.text((20,30),'SYNTHETIC FIXTURE',fill=(200,60,30))
        draw.text((20,60),f'Action {self.step_count}',fill=(10,40,60))
        image.save(path)
        self.frames.append(image.copy())
    def export_video(self, path):
        # Tests need no video encoder. Real worker exports MP4 below.
        return None
    def close(self):
        pass
    def health(self):
        return {'mode':'fake','provenance':'synthetic_fixture','model_loaded':True,'gpu':False,'renderer':'PIL'}

class LiberoRobot:
    def __init__(self):
        os.environ.setdefault('MUJOCO_GL','egl')
        os.environ.setdefault('PYOPENGL_PLATFORM','egl')
        os.environ.setdefault('CUDA_VISIBLE_DEVICES','0')
        os.environ.setdefault('MUJOCO_EGL_DEVICE_ID','0')
        self.model = None
        self.env = None
        self.frames = []
        self.manifest = {}

    def _load(self):
        if self.model is not None:
            return
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError('Real OpenVLA worker requires CUDA')
        # Avoid TensorFlow preallocating the GPU needed by PyTorch.
        import tensorflow as tf
        tf.config.set_visible_devices([], 'GPU')
        from huggingface_hub import HfApi, snapshot_download
        from transformers import AutoConfig, AutoImageProcessor, AutoModelForVision2Seq, AutoProcessor
        from prismatic.extern.hf.configuration_prismatic import OpenVLAConfig
        from prismatic.extern.hf.modeling_prismatic import OpenVLAForActionPrediction
        from prismatic.extern.hf.processing_prismatic import PrismaticImageProcessor, PrismaticProcessor
        revision = os.environ.get('ARMA_HF_REVISION') or HfApi().model_info(CHECKPOINT).sha
        checkpoint = snapshot_download(CHECKPOINT, revision=revision)
        self.cfg = SimpleNamespace(pretrained_checkpoint=checkpoint, load_in_8bit=False, load_in_4bit=False)
        # The checkpoint auto_map names Python code in a DIFFERENT HF repo.
        # Register the audited local implementations and refuse remote code so
        # offline loading uses the pinned source revision, not an untracked cache.
        AutoConfig.register('openvla', OpenVLAConfig)
        AutoImageProcessor.register(OpenVLAConfig, PrismaticImageProcessor)
        AutoProcessor.register(OpenVLAConfig, PrismaticProcessor)
        AutoModelForVision2Seq.register(OpenVLAConfig, OpenVLAForActionPrediction)
        self.model = AutoModelForVision2Seq.from_pretrained(checkpoint,
            attn_implementation='flash_attention_2', torch_dtype=torch.bfloat16,
            load_in_8bit=False, load_in_4bit=False, low_cpu_mem_usage=True,
            trust_remote_code=False, local_files_only=True).to('cuda:0')
        statistics=Path(checkpoint)/'dataset_statistics.json'
        if statistics.is_file():
            self.model.norm_stats=json.loads(statistics.read_text())
        self.model.eval()
        self.model.requires_grad_(False)
        if 'libero_spatial' not in self.model.norm_stats:
            raise RuntimeError('Checkpoint lacks required libero_spatial normalization')
        self.processor = AutoProcessor.from_pretrained(checkpoint,trust_remote_code=False,local_files_only=True)
        self.manifest.update({'checkpoint':CHECKPOINT,'hf_revision':revision,'policy':'openvla','unnorm_key':'libero_spatial',
            'dtype':'bfloat16','attention':'flash_attention_2','training':False,
            'implementation_source':'pinned_openvla_checkout','implementation_commit':OPENVLA_SHA,
            'adapter_version':ADAPTER_VERSION,'adapter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'model_training':self.model.training,
            'trainable_parameter_count':sum(p.numel() for p in self.model.parameters() if p.requires_grad),
            'gpu_name':torch.cuda.get_device_name(0),'cuda':torch.version.cuda})

    @staticmethod
    def _source_sha(root, expected):
        actual = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
        if actual != expected:
            raise RuntimeError(f'Unapproved source revision: {root} at {actual}')
        return actual

    def reset(self, req):
        from libero.libero import benchmark
        from experiments.robot.libero.libero_utils import get_libero_env, get_libero_dummy_action
        from experiments.robot.robot_utils import set_seed_everywhere
        set_seed_everywhere(req.seed)
        # Rendering is exercised before model allocation.
        suite = benchmark.get_benchmark_dict()['libero_spatial'](task_order_index=0)
        task_ids = [i for i in range(suite.n_tasks) if suite.get_task(i).name == TASK_NAME]
        if len(task_ids) != 1:
            raise RuntimeError('Expected task is not uniquely available')
        task_id = task_ids[0]
        task = suite.get_task(task_id)
        states = suite.get_task_init_states(task_id)
        if len(states) <= max(12,req.init_state_id):
            raise RuntimeError('Required memory/calibration/evaluation init states unavailable')
        self.env, self.task_language = get_libero_env(task,'openvla',resolution=256)
        self.env.reset()
        self.obs = self.env.set_init_state(states[req.init_state_id])
        for _ in range(10):
            self.obs, _, _, _ = self.env.step(get_libero_dummy_action('openvla'))
        image = self.obs['agentview_image']
        if image.shape != (256,256,3):
            raise RuntimeError('Unexpected renderer image dimensions')
        self.frames = []
        base = Path(os.environ.get('ARMA_VENDOR_ROOT','/workspace/arma/vendor'))
        source = {'openvla_commit':self._source_sha(base/'openvla',OPENVLA_SHA),
                  'libero_commit':self._source_sha(base/'LIBERO',LIBERO_SHA)}
        self._load()
        self.manifest.update({**source,
            'provenance':'real_execution','robot':'franka_panda','suite':'libero_spatial','task_name':TASK_NAME,
            'task_language':self.task_language,'task_id_resolved':task_id,'init_state_id':req.init_state_id,
            'seed':req.seed,'environment_seed':0,'settling_actions':10,'max_policy_actions':220,
            'perception_mode':'rgb_only_agents_simulator_task_predicate','camera':'agentview',
            'render_resolution':[256,256],'policy_resolution':[224,224],'center_crop_area':0.9,
            'video_fps':20,'video_timing':'simulator time; agent wall-time pauses excluded',
            'dependencies':{d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata['Name']}})
        self.manifest['policy_id'] = stable_policy_id(self.manifest)
        return dict(self.manifest)

    def predict(self, instruction):
        import torch
        from experiments.robot.libero.libero_utils import get_libero_image
        from experiments.robot.openvla_utils import get_vla_action
        from experiments.robot.robot_utils import normalize_gripper_action, invert_gripper_action
        image = get_libero_image(self.obs,224)
        with torch.inference_mode():
            raw = get_vla_action(self.model,self.processor,CHECKPOINT,{'full_image':image},instruction,'libero_spatial',center_crop=True)
        raw = raw.copy()
        action = invert_gripper_action(normalize_gripper_action(raw.copy(),binarize=True))
        return raw.tolist(),action.tolist()

    def step(self, action):
        self.obs, _, _, _ = self.env.step(action)

    def check_success(self):
        return bool(self.env.check_success())

    def save_rgb(self, path):
        from PIL import Image
        frame = self.obs['agentview_image'][::-1,::-1].copy()
        Image.fromarray(frame).save(path)
        self.frames.append(frame)

    def export_video(self, path):
        import imageio.v2 as imageio
        if not self.frames:
            return None
        with imageio.get_writer(str(path),fps=20) as out:
            for frame in self.frames:
                out.append_data(frame)
        return path

    def close(self):
        if self.env is not None:
            self.env.close()
            self.env = None
        self.frames = []

    def health(self):
        return {'mode':'real','provenance':'real_execution','model_loaded':self.model is not None,
                'model_training':self.manifest.get('model_training'),
                'trainable_parameter_count':self.manifest.get('trainable_parameter_count'),
                'adapter_version':self.manifest.get('adapter_version'),
                'gpu':self.manifest.get('gpu_name'),'renderer':'egl' if self.env is not None else 'not_initialized'}
