# Derived from See-through (https://github.com/shitagaki-lab/see-through), Apache-2.0
# (original path: common/utils/cv.py). Modified for img2live: only the helpers the engine needs were
# kept; typing imports fixed. `pad_rgb` / `build_alpha_pyramid` were written by lvmin (LayerDiffuse).
# See the NOTICE file at the repository root for attribution and licence details.
"""Image helpers used by the LayerDiff3D pipeline."""
import math
from typing import List, Tuple, Union

import cv2
import numpy as np


def smart_resize(src: np.ndarray, target_size, upscale_interpolation=cv2.INTER_LINEAR,
                 downscale_interpolation=cv2.INTER_AREA) -> np.ndarray:
    h, w = src.shape[:2]
    th, tw = target_size
    if th == h and tw == w:
        return src.copy()
    interpolation = downscale_interpolation if th * tw < h * w else upscale_interpolation
    return cv2.resize(src, (tw, th), interpolation=interpolation)


def validate_resolution(resolution: Union[str, Tuple, List, int], div: int = -1) -> List[int]:
    """Make sure resolution is a valid [h, w] list whose entries are divisible by ``div``."""
    if isinstance(resolution, str):
        resolution = [int(r.strip()) for r in resolution.split(",")]
    elif isinstance(resolution, int):
        resolution = [resolution, resolution]
    else:
        resolution = list(resolution)[:2]
    out = []
    for res in resolution:
        if div > 0 and res % div != 0:
            res = math.ceil(res / div) * div
        out.append(res)
    return out


def center_square_pad_resize(img: np.ndarray, target_size: int, pad_value=0,
                             upscale_interpolation=cv2.INTER_LINEAR, downscale_interpolation=cv2.INTER_AREA,
                             return_pad_info: bool = False):
    """Pad ``img`` to a centred square, then resize to ``target_size``.

    With ``return_pad_info`` also returns ``pad_size`` = (w, h) of the padded square in *source* pixels
    and ``pad_pos`` = (x, y) offset of the source inside that square.
    """
    h, w = img.shape[:2]
    pad_size = (w, h)
    pad_pos = (0, 0)
    if h != w:
        sz = max(h, w)
        px1 = (sz - w) // 2
        py1 = (sz - h) // 2
        shape = (sz, sz) if img.ndim == 2 else (sz, sz, img.shape[-1])
        padded = np.full(shape, pad_value, dtype=img.dtype)
        padded[py1: py1 + h, px1: px1 + w] = img
        h, w = padded.shape[:2]
        img = padded
        pad_size = (w, h)
        pad_pos = (px1, py1)
    if h != target_size or w != target_size:
        img = smart_resize(img, (target_size, target_size), upscale_interpolation=upscale_interpolation,
                           downscale_interpolation=downscale_interpolation)
    if return_pad_info:
        return img, pad_size, pad_pos
    return img


def build_alpha_pyramid(color, alpha, dk=1.2):
    # Written by lvmin at Stanford
    pyramid = []
    current_premultiplied_color = color * alpha
    current_alpha = alpha
    while True:
        pyramid.append((current_premultiplied_color, current_alpha))
        H, W, _ = current_alpha.shape
        if min(H, W) == 1:
            break
        current_premultiplied_color = cv2.resize(current_premultiplied_color, (int(W / dk), int(H / dk)),
                                                 interpolation=cv2.INTER_AREA)
        current_alpha = cv2.resize(current_alpha, (int(W / dk), int(H / dk)),
                                   interpolation=cv2.INTER_AREA)[:, :, None]
    return pyramid[::-1]


def pad_rgb(np_rgba_hwc_uint8, return_format="rgb", to_uint8=False, keep_ori_pixel=True):
    """Bleed foreground colour into fully transparent pixels (avoids dark fringes). Written by lvmin."""
    np_rgba_hwc = np_rgba_hwc_uint8.astype(np.float32) / 255.0
    if keep_ori_pixel:
        ori_rgb = np_rgba_hwc[..., :3].copy()
        ori_alpha = np_rgba_hwc[..., [-1]].copy()
    pyramid = build_alpha_pyramid(color=np_rgba_hwc[..., :3], alpha=np_rgba_hwc[..., 3:])
    top_c, top_a = pyramid[0]
    fg = np.sum(top_c, axis=(0, 1), keepdims=True) / np.sum(top_a, axis=(0, 1), keepdims=True).clip(1e-8, 1e32)
    for layer_c, layer_a in pyramid:
        layer_h, layer_w, _ = layer_c.shape
        fg = cv2.resize(fg, (layer_w, layer_h), interpolation=cv2.INTER_LINEAR)
        fg = layer_c + fg * (1.0 - layer_a)
    if keep_ori_pixel:
        fg = np.clip(ori_alpha * ori_rgb + (1 - ori_alpha) * fg, 0, 1)
    if return_format == "argb":
        fg = np.concatenate([np_rgba_hwc[..., 3:], fg], axis=2)
    if to_uint8:
        fg = (fg * 255).astype(np.uint8)
    return fg


def checkerboard(shape):
    return np.indices(shape).sum(axis=0) % 2
