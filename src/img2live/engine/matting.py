"""Plain-background removal before decomposition.

LayerDiff3D was trained on characters cut out of layered files, i.e. on a transparent background.  Illustrations
uploaded to the service usually sit on a flat colour (or black/white); on dark-on-dark art the model then loses
parts of the character (a hole in the face, missing garment areas).  When the border of the image is one flat
colour we turn that background transparent first: pixels close to the background colour *and connected to the
border* become transparent (soft ramp at the edge), pockets enclosed by the character are kept.
"""
from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np


def cutout_plain_background(rgba: np.ndarray) -> Tuple[np.ndarray, dict]:
    """Return (rgba, info).  ``rgba`` is returned unchanged when the image already has transparency or no flat
    border background can be found; ``info['applied']`` says which."""
    h, w = rgba.shape[:2]
    if (rgba[..., 3] < 250).mean() > 0.02:
        return rgba, {"applied": False, "reason": "source has transparency"}
    rgb = rgba[..., :3].astype(np.float32)
    b = max(3, int(0.02 * min(h, w)))
    border = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3), rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    spread = float(np.median(np.linalg.norm(border - bg, axis=1)))
    if spread > 14.0:
        return rgba, {"applied": False, "reason": "background is not flat", "spread": round(spread, 1)}
    dist = np.linalg.norm(rgb - bg, axis=2)
    hi = max(28.0, 4.0 * spread + 14.0)
    lo = 0.5 * hi
    near = (dist < hi).astype(np.uint8)
    n, lab = cv2.connectedComponents(near, connectivity=4)
    touching = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    touching = touching[touching != 0]
    bgmask = np.isin(lab, touching) & (near > 0)
    alpha = np.full((h, w), 255, np.float32)
    ramp = np.clip((dist - lo) / (hi - lo), 0.0, 1.0) * 255.0
    alpha[bgmask] = ramp[bgmask]
    removed = float((alpha < 128).mean())
    if not 0.05 < removed < 0.95:
        return rgba, {"applied": False, "reason": "implausible background share", "removed": round(removed, 3)}
    out = rgba.copy()
    out[..., 3] = np.minimum(out[..., 3], alpha.astype(np.uint8))
    return out, {"applied": True, "removed": round(removed, 3), "bg": [int(v) for v in bg], "spread": round(spread, 1)}
