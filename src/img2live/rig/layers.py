"""Layer model for the rig compiler.

A :class:`Layer` is a cropped RGBA texture plus the affine placement that maps texture pixels to canvas
coordinates (``canvas = origin + scale * pixel``).  Body layers have ``scale == 1``; head layers taken from the
high-resolution head pass have ``scale < 1`` (the texture is finer than the canvas grid).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from ..engine.imgutils import pad_rgb

ALPHA_T = 16  # alpha threshold (0..255) used for masks / bounding boxes

# tags that come in screen-left / screen-right pairs and are split by connected components
PAIRED = ("eyewhite", "irides", "eyelash", "eyebrow", "ears", "handwear", "earwear")


@dataclass
class Layer:
    name: str                    # unique id, e.g. "eyewhite_l"
    tag: str                     # semantic tag, e.g. "eyewhite"
    rgba: np.ndarray             # cropped texture, HxWx4 uint8 (straight alpha, colour-bled)
    origin: Tuple[float, float]  # canvas position of texture pixel (0, 0)
    scale: float = 1.0           # canvas px per texture px
    side: Optional[str] = None   # "l" | "r" = SCREEN left / right (viewer's perspective), None if unpaired
    hires: bool = False

    @property
    def size(self) -> Tuple[int, int]:  # (w, h) of the texture
        return self.rgba.shape[1], self.rgba.shape[0]

    def alpha_mask(self) -> np.ndarray:
        return self.rgba[..., 3] >= ALPHA_T

    def canvas_bbox(self) -> Tuple[float, float, float, float]:
        h, w = self.rgba.shape[:2]
        x0, y0 = self.origin
        return (x0, y0, x0 + w * self.scale, y0 + h * self.scale)

    def to_canvas(self, pts_px: np.ndarray) -> np.ndarray:
        return pts_px * self.scale + np.asarray(self.origin, dtype=np.float64)

    def mask_centroid(self) -> Tuple[float, float]:
        ys, xs = np.nonzero(self.alpha_mask())
        if len(xs) == 0:
            return (self.origin[0], self.origin[1])
        c = np.array([xs.mean() + 0.5, ys.mean() + 0.5])
        return tuple(self.to_canvas(c))

    def mask_area_canvas(self) -> float:
        return float(self.alpha_mask().sum()) * self.scale ** 2


def _crop(rgba: np.ndarray, pad: int = 2) -> Optional[Tuple[np.ndarray, Tuple[int, int]]]:
    m = (rgba[..., 3] >= ALPHA_T).astype(np.uint8)
    if m.sum() == 0:
        return None
    x, y, w, h = cv2.boundingRect(cv2.findNonZero(m))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(rgba.shape[1], x + w + pad), min(rgba.shape[0], y + h + pad)
    return rgba[y0:y1, x0:x1].copy(), (x0, y0)


def _bleed(rgba: np.ndarray) -> np.ndarray:
    """Spread foreground colour into transparent pixels so bilinear sampling has no dark halo."""
    out = rgba.copy()
    rgb = pad_rgb(rgba, to_uint8=True)  # HxWx3
    out[..., :3] = rgb
    return out


def _split_pair(rgba: np.ndarray) -> Optional[List[np.ndarray]]:
    """Split a layer into its two largest connected components, ordered screen-left -> screen-right."""
    a = (rgba[..., 3] >= ALPHA_T).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(a, connectivity=8)
    if n < 3:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    order = np.argsort(areas)[::-1][:2] + 1
    if areas[order[1] - 1] < 0.12 * areas[order[0] - 1]:  # the second blob is just a speck
        return None
    order = sorted(order, key=lambda i: stats[i][cv2.CC_STAT_LEFT] + stats[i][cv2.CC_STAT_WIDTH] / 2)
    parts = []
    for i in order:
        p = rgba.copy()
        p[..., 3] = np.where(lab == i, rgba[..., 3], 0)
        parts.append(p)
    return parts


def build_layers(canvas_layers: Dict[str, np.ndarray], head_hires: Optional[Dict[str, np.ndarray]] = None,
                 head_square: Optional[Tuple[float, float, float]] = None) -> List[Layer]:
    """Create rig layers from decomposition output.

    ``canvas_layers``: tag -> canvas-sized RGBA.  ``head_hires`` / ``head_square``: the native-resolution head
    pass and its placement; when given, facial tags use those textures instead of the canvas-scale ones.
    """
    layers: List[Layer] = []
    for tag, full in canvas_layers.items():
        if tag == "head":  # combined silhouette, only used for locating the head
            continue
        hires = False
        rgba, origin, scale = full, (0.0, 0.0), 1.0
        if head_hires and head_square and tag in head_hires:
            rgba = head_hires[tag]
            side = head_square[2] / rgba.shape[0]
            origin, scale, hires = (head_square[0], head_square[1]), side, True
        c = _crop(rgba)
        if c is None:
            continue
        tex, (cx, cy) = c
        org = (origin[0] + cx * scale, origin[1] + cy * scale)
        parts = _split_pair(tex) if tag in PAIRED else None
        if parts is None:
            layers.append(Layer(name=tag.replace(" ", "_"), tag=tag, rgba=tex, origin=org, scale=scale, hires=hires))
            continue
        for side_name, part in zip(("l", "r"), parts):
            c2 = _crop(part)
            if c2 is None:
                continue
            t2, (cx2, cy2) = c2
            layers.append(Layer(name=f"{tag}_{side_name}", tag=tag, rgba=t2, side=side_name,
                                origin=(org[0] + cx2 * scale, org[1] + cy2 * scale), scale=scale, hires=hires))
    for l in layers:
        l.rgba = _bleed(l.rgba)
    return layers


def by_tag(layers: List[Layer]) -> Dict[str, List[Layer]]:
    d: Dict[str, List[Layer]] = {}
    for l in layers:
        d.setdefault(l.tag, []).append(l)
    return d
