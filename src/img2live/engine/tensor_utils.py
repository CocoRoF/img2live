# Derived from See-through (https://github.com/shitagaki-lab/see-through), Apache-2.0
# (original path: common/utils/torch_utils.py). Modified for img2live: only the helpers the engine
# needs were kept and simplified (numpy -> tensor path only).
# See the NOTICE file at the repository root for attribution and licence details.
"""Small tensor helpers used by the LayerDiff3D pipeline."""
import random

import numpy as np
import torch


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def zero_module(module):
    """Zero out the parameters of a module and return it."""
    for p in module.parameters():
        p.detach().zero_()
    return module


def img2tensor(img: np.ndarray, normalize: bool = False, mean=0.0, std=255.0, dim_order: str = "bchw",
               dtype=torch.float32, device="cpu") -> torch.Tensor:
    """numpy HxW[xC] -> tensor in ``dim_order`` ('bchw' | 'chw' | 'hwc'); optional (x-mean)/std."""
    if img.ndim == 2:
        img = img[..., None]
    assert img.ndim == 3, "expected HxW or HxWxC"
    t = torch.from_numpy(np.ascontiguousarray(img))  # h w c
    if dim_order == "bchw":
        t = t.permute(2, 0, 1)[None]
    elif dim_order == "chw":
        t = t.permute(2, 0, 1)
    elif dim_order != "hwc":
        raise ValueError(f"bad dim_order {dim_order!r}")
    t = t.to(device=device, dtype=dtype)
    if normalize:
        c = t.shape[1] if dim_order == "bchw" else (t.shape[0] if dim_order == "chw" else t.shape[2])
        m = torch.tensor([mean] * c if np.isscalar(mean) else list(mean)[:c], dtype=dtype, device=device)
        s = torch.tensor([std] * c if np.isscalar(std) else list(std)[:c], dtype=dtype, device=device)
        shape = (1, c, 1, 1) if dim_order == "bchw" else ((c, 1, 1) if dim_order == "chw" else (1, 1, c))
        t = (t - m.view(shape)) / s.view(shape)
    return t
