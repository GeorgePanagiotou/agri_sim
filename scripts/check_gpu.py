"""Check whether the configured PyTorch wheel can actually execute on the RTX 5070 Ti."""
from sys import exit
try:
    import torch
except ImportError:
    raise SystemExit('Install CUDA extra first: uv sync --extra gpu')
print('Torch:',torch.__version__,'CUDA build:',torch.version.cuda)
print('CUDA available:',torch.cuda.is_available())
if not torch.cuda.is_available():
    print('CUDA not visible. Verify NVIDIA driver, active environment and GPU index.')
    exit(2)
props=torch.cuda.get_device_properties(0)
print('GPU:',props.name,'Memory GiB:',round(props.total_memory/1024**3,2))
print('Compute capability:',torch.cuda.get_device_capability(0))
a=torch.randn((512,512),device='cuda')
c=(a@a).mean()
torch.cuda.synchronize()
print('Matrix operation on CUDA:',float(c))
print('Blackwell architecture detected:',torch.cuda.get_device_capability(0)[0]>=12)
