"""Pixel operations of the studio (numpy, straight-alpha uint8 RGBA arrays in an N x N edit grid)."""
from __future__ import annotations

import base64
import io
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image


# ------------------------------------------------------------------ masks
def decode_mask(b64: str, n: int, feather: float = 0.0) -> np.ndarray:
    """Base64 PNG -> float32 mask in 0..1 (selected = grey > 127), optionally softened at its edge."""
    im = Image.open(io.BytesIO(base64.b64decode(b64))).convert("L")
    if im.size != (n, n):
        im = im.resize((n, n), Image.NEAREST)
    m = (np.asarray(im) > 127).astype(np.float32)
    if feather and feather > 0:
        m = np.clip(cv2.GaussianBlur(m, (0, 0), float(feather)) * 1.0, 0.0, 1.0)
        m = np.where(m > 0.02, m, 0.0).astype(np.float32)
    return m


# ------------------------------------------------------------------ grids
def convert_grid(rgba: np.ndarray, src: str, dst: str, head_square: Optional[Tuple[float, float, float]]) -> np.ndarray:
    """Move a layer between the canvas grid and the head grid (the head square enlarged to the grid size)."""
    if src == dst or not head_square:
        return rgba
    n = rgba.shape[0]
    x0, y0, side = head_square
    k = side / n  # canvas px per head-grid px
    f = rgba.astype(np.float32) / 255.0
    f[..., :3] *= f[..., 3:4]
    if src == "canvas":   # head(u,v) = canvas(x0 + u k, y0 + v k)
        M = np.array([[k, 0, x0], [0, k, y0]], np.float32)
    else:                 # canvas(x,y) = head((x - x0)/k, (y - y0)/k); smooth first, it is a reduction
        f = cv2.GaussianBlur(f, (0, 0), max(0.5, 0.5 / k)) if k < 1 else f
        M = np.array([[1 / k, 0, -x0 / k], [0, 1 / k, -y0 / k]], np.float32)
    out = cv2.warpAffine(f, M, (n, n), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = out[..., 3:4]
    rgb = np.where(a > 1e-4, out[..., :3] / np.maximum(a, 1e-4), 0)
    return (np.clip(np.concatenate([rgb, a], -1), 0, 1) * 255 + 0.5).astype(np.uint8)


def convert_mask(m: np.ndarray, src: str, dst: str, head_square) -> np.ndarray:
    if src == dst or not head_square:
        return m
    rgba = np.zeros(m.shape + (4,), np.uint8)
    rgba[..., 3] = (m * 255).astype(np.uint8)
    return convert_grid(rgba, src, dst, head_square)[..., 3].astype(np.float32) / 255.0


# ------------------------------------------------------------------ edits
def _over(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    """Straight-alpha 'over' of two uint8 RGBA arrays."""
    t, b = top.astype(np.float32) / 255.0, bottom.astype(np.float32) / 255.0
    ta, ba = t[..., 3:4], b[..., 3:4]
    oa = ta + ba * (1 - ta)
    rgb = np.where(oa > 1e-6, (t[..., :3] * ta + b[..., :3] * ba * (1 - ta)) / np.maximum(oa, 1e-6), 0)
    return (np.clip(np.concatenate([rgb, oa], -1), 0, 1) * 255 + 0.5).astype(np.uint8)


def erase(cur: np.ndarray, m: np.ndarray) -> np.ndarray:
    out = cur.copy()
    out[..., 3] = np.clip(cur[..., 3].astype(np.float32) * (1.0 - m) + 0.5, 0, 255).astype(np.uint8)
    return out


def restore(cur: np.ndarray, m: np.ndarray, src: np.ndarray, fg: np.ndarray) -> np.ndarray:
    """Paint the SOURCE pixels into the selection - only where the source is foreground, so no background is pasted."""
    w = m * fg.astype(np.float32) * (src[..., 3].astype(np.float32) / 255.0)
    s = src.copy()
    s[..., 3] = np.clip(w * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return _over(s, cur)


def take(cur: np.ndarray, m: np.ndarray) -> np.ndarray:
    """The part of ``cur`` inside the selection (colours kept, alpha scaled by the mask)."""
    out = cur.copy()
    out[..., 3] = np.clip(cur[..., 3].astype(np.float32) * m + 0.5, 0, 255).astype(np.uint8)
    return out


def fill_holes(cur: np.ndarray, src: np.ndarray, fg: np.ndarray, m: Optional[np.ndarray] = None) -> Tuple[np.ndarray, int]:
    """Fill the layer's enclosed transparent holes with source pixels where the source is foreground."""
    solid = (cur[..., 3] >= 16).astype(np.uint8)
    inv = (1 - solid).astype(np.uint8)
    h, w = inv.shape
    ff = inv.copy()
    msk = np.zeros((h + 2, w + 2), np.uint8)
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if ff[y, x] == 1:
            cv2.floodFill(ff, msk, (x, y), 2)
    holes = (ff == 1)                      # transparent and not reachable from the border
    holes &= fg
    if m is not None:
        holes &= m > 0.5
    n = int(holes.sum())
    if n == 0:
        return cur, 0
    paint = src.copy()
    paint[..., 3] = np.where(holes, src[..., 3], 0)
    return _over(paint, cur), n


def alpha_bbox(rgba: np.ndarray, thr: int = 16) -> Optional[Tuple[int, int, int, int]]:
    ys, xs = np.where(rgba[..., 3] >= thr)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
