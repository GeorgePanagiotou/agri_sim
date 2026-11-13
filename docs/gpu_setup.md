# NVIDIA RTX 5070 / 5070 Ti CUDA setup

The **optional `gpu` dependency group** pins PyTorch **2.14.1**, TorchVision **0.29.1**, CUDA **13.0** wheels, from the dedicated official PyTorch index. RTX 5070 Ti is a Blackwell GPU (compute capability 12.0). This is a tested published wheel combination, **not a claim we ran it on your Windows PC**.

```powershell
uv sync --extra gpu --extra app --extra notebooks
uv run --extra gpu python scripts/check_gpu.py
```

The PyTorch runtime bundles CUDA components; a separately installed CUDA toolkit is not required for normal wheel inference. A **compatible NVIDIA driver** must be installed. If the device is not visible, update the NVIDIA driver, confirm `nvidia-smi`, and rerun the script. Windows + Python 3.11 supported. On macOS don't select the GPU extra.

Official installation references:
- https://pytorch.org/get-started/previous-versions/
- https://docs.astral.sh/uv/guides/integration/pytorch/
