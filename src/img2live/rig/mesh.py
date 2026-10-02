"""Alpha-mask triangulation.

A layer's mesh is built from its alpha only: dilate the mask by a pixel, resample the outer/hole contours at an
arc-length spacing, add a staggered interior lattice away from the border, Delaunay-triangulate everything and
drop the triangles that leave the mask (so concavities stay concave).  Spacing follows the layer size, so tiny
parts such as eyes get dense meshes and big parts such as the legs stay light.
"""
from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np
from scipy.spatial import Delaunay

from .layers import ALPHA_T, Layer


def _resample(contour: np.ndarray, spacing: float) -> np.ndarray:
    pts = contour.reshape(-1, 2).astype(np.float64) + 0.5
    if len(pts) < 3:
        return pts
    closed = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    total = seg.sum()
    if total < 1e-6:
        return pts[:1]
    n = int(np.clip(round(total / spacing), 8, 600))
    t = np.linspace(0, total, n, endpoint=False)
    cum = np.concatenate([[0], np.cumsum(seg)])
    idx = np.searchsorted(cum, t, side="right") - 1
    idx = np.clip(idx, 0, len(seg) - 1)
    f = (t - cum[idx]) / np.maximum(seg[idx], 1e-9)
    return closed[idx] + (closed[idx + 1] - closed[idx]) * f[:, None]


def build_mesh(layer: Layer, density: float = 1.0, max_verts: int = 1400) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (positions in TEXTURE pixels (N,2), triangles (M,3) int32, opaque-pixel count per triangle (M,))."""
    h, w = layer.rgba.shape[:2]
    mask = (layer.rgba[..., 3] >= ALPHA_T).astype(np.uint8)
    mask_d = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    area = float(mask.sum())
    spacing = float(np.clip(np.sqrt(max(area, 1.0)) / (9.0 * density), 2.0, 22.0))

    for _ in range(6):  # raise the spacing until the vertex budget is met
        contours, _h = cv2.findContours(mask_d, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        pts = [_resample(c, spacing) for c in contours if len(c) >= 3]
        pts = [p for p in pts if len(p)]
        if not pts:
            break
        # interior lattice (staggered rows) kept away from the border
        dist = cv2.distanceTransform(mask_d, cv2.DIST_L2, 3)
        ys = np.arange(spacing * 0.5, h, spacing * 0.866)
        inner = []
        for r, y in enumerate(ys):
            xs = np.arange(spacing * 0.5 + (spacing * 0.5 if r % 2 else 0.0), w, spacing)
            for x in xs:
                xi, yi = int(x), int(y)
                if 0 <= xi < w and 0 <= yi < h and dist[yi, xi] >= 0.7 * spacing:
                    inner.append((x, y))
        allp = np.vstack(pts + ([np.array(inner)] if inner else []))
        if len(allp) <= max_verts:
            break
        spacing *= 1.35
    else:
        allp = allp[:max_verts]

    if not pts or len(allp) < 3:
        return _quad(w, h)

    allp = np.unique(np.round(allp, 3), axis=0)
    try:
        tri = Delaunay(allp)
    except Exception:  # degenerate geometry
        return _quad(w, h)
    simplices, counts = _keep_covering(allp, tri.simplices, mask, mask_d)
    if len(simplices) == 0:
        return _quad(w, h)

    # consistent orientation: signed area > 0 (image coordinates, y down); drop degenerates
    p = allp[simplices]
    area2 = (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1])
    flip = area2 < 0
    simplices[flip] = simplices[flip][:, [0, 2, 1]]
    ok = np.abs(area2) > 1e-3
    simplices, counts = simplices[ok], counts[ok]
    used = np.unique(simplices)
    remap = -np.ones(len(allp), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return allp[used], remap[simplices].astype(np.int32), counts


def _keep_covering(pts: np.ndarray, simplices: np.ndarray, mask: np.ndarray, mask_d: np.ndarray):
    """Keep every triangle that covers at least one opaque pixel; drop only triangles lying entirely outside.

    The texture's own alpha defines the visible shape, so extra triangles over transparent texels are harmless,
    while dropping a triangle that touches a thin strand would cut the strand.  The test is exact (rasterised).
    """
    h, w = mask.shape
    keep = np.zeros(len(simplices), dtype=bool)
    counts = np.zeros(len(simplices), dtype=np.int64)
    for i, (a, b, c) in enumerate(simplices):
        tri = pts[[a, b, c]]
        x0, y0 = np.floor(tri.min(axis=0)).astype(int)
        x1, y1 = np.ceil(tri.max(axis=0)).astype(int) + 1
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if x1 <= x0 or y1 <= y0:
            continue
        roi = mask_d[y0:y1, x0:x1]
        if not roi.any():
            continue
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillConvexPoly(m, np.round((tri - [x0, y0]) * 16).astype(np.int32), 1, lineType=cv2.LINE_8, shift=4)
        keep[i] = bool((m & roi).any())
        if keep[i]:
            counts[i] = int((m & mask[y0:y1, x0:x1]).sum())
    return simplices[keep], counts[keep]


def _inside(mask: np.ndarray, pts: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    xi = np.clip(pts[:, 0].astype(int), 0, w - 1)
    yi = np.clip(pts[:, 1].astype(int), 0, h - 1)
    return mask[yi, xi] > 0


def _quad(w: int, h: int):
    pos = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float64)
    return pos, np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32), np.array([w * h // 2, w * h // 2], dtype=np.int64)
