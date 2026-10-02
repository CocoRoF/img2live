"""Rest-pose fidelity: keep a generated pixel only if it brings the picture closer to the source.

The high-resolution head pass enlarges a ~200 px head five- to six-fold and *redraws* it.  The redraw is usually
right, but it adds things the source does not have: a contour around the eyelid shading, a tinted nose patch, a thin
outline on the lips.  At rest pose the puppet should look like the source, so for every face-part layer we ask, per
pixel: does the picture agree better with the source *with* this layer or *without* it (everything else unchanged)?
Where removing the layer helps, the layer's alpha is faded out.  Line art that matches the source (lashes, brows, the
iris) is kept because without it the picture would be further from the source.

The comparison is made on tone at about one source pixel (both pictures are blurred alike), so single-pixel
misregistration of lines is not punished and pixel art is not mistaken for noise.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np

from .cleanup import _drop_specks

# Head-part layers whose redrawn detail is known to contradict the source: the nose layer is often a tinted patch with a
# rim, the eyelash layer carries the lid's skin ring with a contour.  The eye white, iris, brow and mouth are left alone:
# they are redrawn too, but they are what the face is made of, and small misregistration there must not eat them.
HEAD_PARTS = ("nose", "eyelash", "face")
# line art inside those layers (dark strokes: lashes) is kept whatever the tone comparison says
KEEP_DARK = {"eyelash": 110.0}
# the face layer is the reference surface (skin), so only its hair-coloured spill (bluish pixels) is up for judgement
ONLY_BLUISH = {"face"}


def _over(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    """Premultiplied 'over' (float32, HxWx4)."""
    return top + bottom * (1.0 - top[..., 3:4])


def _premult(rgba_u8: np.ndarray) -> np.ndarray:
    f = rgba_u8.astype(np.float32) / 255.0
    f[..., :3] *= f[..., 3:4]
    return f


def _flat(pm: np.ndarray) -> np.ndarray:
    """Premultiplied RGBA -> RGB over white, 0..255."""
    return (pm[..., :3] + (1.0 - pm[..., 3:4])) * 255.0


def _warp(img: np.ndarray, x0: float, y0: float, k: float, roi: Tuple[int, int, int, int], interp=cv2.INTER_LINEAR) -> np.ndarray:
    """Resample a canvas-grid image into the hi-res head grid inside ``roi`` = (u0, v0, u1, v1) (hi-res px)."""
    u0, v0, u1, v1 = roi
    # hi-res (u, v) -> canvas (x0 + u*k, y0 + v*k);  with WARP_INVERSE_MAP M maps destination px -> source px
    M = np.array([[k, 0, x0 + u0 * k], [0, k, y0 + v0 * k]], np.float32)
    return cv2.warpAffine(img, M, (u1 - u0, v1 - v0), flags=interp | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def _decide(stack: List[Tuple[str, np.ndarray]], order: Dict[str, int], elig: List[str], src_flat: np.ndarray,
            valid: np.ndarray, sigma: float, gsigma: float, tolerance: float, thin: int = 0) -> Dict[str, np.ndarray]:
    """Keep/remove weights (0..1, same grid as the stack) for the eligible layers; ``stack`` is updated in place.

    Greedy from the top-most layer down, so each decision sees the ones already taken.  ``thin`` > 0 additionally
    judges strokes narrower than ``thin`` px on their own (a one-pixel contour would otherwise be outvoted by the
    good pixels next to it).
    """
    tags = [t for t, _ in stack]
    src_b = cv2.GaussianBlur(src_flat, (0, 0), sigma)

    def compose(skip: Optional[int] = None) -> np.ndarray:
        acc = np.zeros(stack[0][1].shape, np.float32)
        for i, (_, a) in enumerate(stack):
            if i != skip:
                acc = _over(a, acc)
        return acc

    def err(pm: np.ndarray) -> np.ndarray:
        return np.abs(cv2.GaussianBlur(_flat(pm), (0, 0), sigma) - src_b).mean(-1)

    weights: Dict[str, np.ndarray] = {}
    for tag in sorted(elig, key=lambda t: -order.get(t, 100)):
        i = tags.index(tag)
        layer = stack[i][1]
        support = layer[..., 3] > 0.05
        if not support.any():
            continue
        raw_gain = err(compose(skip=i)) - err(compose())  # >0: the layer helps; <0: closer to the source without it
        gain = raw_gain
        # decide on regions, not single pixels: average the gain over the layer's support at ~one source pixel
        sup = (support & valid).astype(np.float32)
        gain = cv2.GaussianBlur(gain * sup, (0, 0), gsigma) / np.maximum(cv2.GaussianBlur(sup, (0, 0), gsigma), 1e-3)
        w = np.clip((gain + tolerance) / tolerance, 0.0, 1.0)
        w = np.where(valid & support, w, 1.0).astype(np.float32)
        w = cv2.GaussianBlur(w, (0, 0), 1.5)
        w = np.clip((w - 0.35) / 0.4, 0.0, 1.0)  # a clean edge: no faint ghost of a removed contour
        if thin:
            solid = (layer[..., 3] > 0.5).astype(np.uint8)
            opened = cv2.morphologyEx(solid, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thin, thin)))
            stroke = (solid > 0) & (opened == 0) & valid
            w_stroke = np.clip((raw_gain + tolerance * 0.5) / (tolerance * 0.5), 0.0, 1.0)
            w_stroke = cv2.GaussianBlur(np.where(stroke, w_stroke, 1.0).astype(np.float32), (0, 0), 0.7)
            w = np.where(stroke, np.minimum(w, np.clip((w_stroke - 0.35) / 0.4, 0.0, 1.0)), w)
        if tag in ONLY_BLUISH:
            rgb = layer[..., :3] / np.maximum(layer[..., 3:4], 1e-3)
            w = np.where(rgb[..., 2] - rgb[..., 0] > 6.0 / 255.0, w, 1.0)
        if tag in KEEP_DARK:
            lum = (layer[..., :3] * np.array([0.299, 0.587, 0.114], np.float32)).sum(-1) / np.maximum(layer[..., 3], 1e-3) * 255.0
            w = np.where(lum < KEEP_DARK[tag], 1.0, w)
        stack[i] = (tag, layer * w[..., None])
        weights[tag] = w
    return weights


def _roi(masks: List[np.ndarray], margin: int, n_h: int, n_w: int) -> Tuple[int, int, int, int]:
    m = np.zeros((n_h, n_w), bool)
    for x in masks:
        m |= x
    ys, xs = np.where(m)
    return (max(0, int(xs.min()) - margin), max(0, int(ys.min()) - margin), min(n_w, int(xs.max()) + margin), min(n_h, int(ys.max()) + margin))


def _apply(a8: np.ndarray, w_roi: np.ndarray, roi: Tuple[int, int, int, int], island_frac: float, island_min: int) -> Tuple[np.ndarray, float]:
    """Multiply alpha by the weights inside ``roi`` (only ever reducing it); colours stay. Returns (layer, removed share).

    What survives a heavy cut is a few shards, which look worse than nothing: when more than half of a layer was
    judged wrong the layer goes entirely, otherwise shards smaller than ``island_frac`` of the layer are dropped.
    """
    u0, v0, u1, v1 = roi
    w = np.ones(a8.shape[:2], np.float32)
    w[v0:v1, u0:u1] = w_roi
    orig = int((a8[..., 3] >= 16).sum())
    out = a8.copy()
    out[..., 3] = np.clip(out[..., 3].astype(np.float32) * w, 0, 255).astype(np.uint8)
    left = int((out[..., 3] >= 16).sum())
    if orig and left < 0.5 * orig:
        return np.zeros_like(a8), 1.0
    if orig and left < 0.97 * orig:  # something was cut: tidy up what is left
        n, lab, stats, _ = cv2.connectedComponentsWithStats((out[..., 3] >= 40).astype(np.uint8), connectivity=8)
        keep = np.zeros(n, bool)
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= max(island_min, int(island_frac * orig))
        near = cv2.dilate(keep[lab].astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        out[..., 3] = np.where(near, out[..., 3], 0)
    out, _ = _drop_specks(out, max(24, int(0.0015 * (out[..., 3] >= 16).sum())))
    return out, 1.0 - float((out[..., 3] >= 16).sum()) / max(orig, 1)


def refine_head(res, order: Optional[Dict[str, int]] = None, eligible: Iterable[str] = HEAD_PARTS, tolerance: float = 8.0,
                margin: int = 48) -> Dict[str, float]:
    """Fade out head-part pixels that make the rest pose less faithful to the source (in place on ``res.head_hires``).

    Returns tag -> share of the layer's opaque pixels that were removed.
    """
    if not res.head_hires or not res.head_square or res.fullpage is None:
        return {}
    if order is None:
        from ..rig.compile import DRAW_ORDER as order  # lazy: the rig is a sibling package
    x0, y0, side = res.head_square
    n = next(iter(res.head_hires.values())).shape[0]
    k = side / n  # canvas px per hi-res px
    elig = [t for t in eligible if t in res.head_hires and (res.head_hires[t][..., 3] >= 16).any()]
    if not elig:
        return {}
    roi = _roi([res.head_hires[t][..., 3] >= 16 for t in elig], margin, n, n)
    u0, v0, u1, v1 = roi

    # the source in the same grid (premultiplied so transparent borders do not bleed dark)
    src_pm = _warp(_premult(res.fullpage), x0, y0, k, roi, cv2.INTER_CUBIC)
    # all layers on the head grid, bottom to top
    stack: List[Tuple[str, np.ndarray]] = []
    hires_tags = set(res.head_hires)
    for tag, a in res.layers.items():
        if tag == "head" or tag in hires_tags or not (a[..., 3] > 0).any():
            continue  # 'head' is only a silhouette; head parts come from the hi-res pass
        stack.append((tag, _warp(_premult(a), x0, y0, k, roi)))
    for tag, a in res.head_hires.items():
        if (a[..., 3] > 0).any():
            stack.append((tag, _premult(a[v0:v1, u0:u1])))
    stack.sort(key=lambda it: order.get(it[0], 100))

    src_px = float(np.clip(res.canvas / max(res.source_size), 0.3, 4.0))  # canvas px per source px
    weights = _decide(stack, order, elig, _flat(src_pm), src_pm[..., 3] > 0.97, max(1.5, 0.45 * src_px / k),
                      max(2.5, 0.9 * src_px / k), tolerance)
    removed: Dict[str, float] = {}
    for tag, w in weights.items():
        res.head_hires[tag], removed[tag] = _apply(res.head_hires[tag], w, roi, 0.04, 150)
    return removed


# canvas-scale layers that carry a generated contour the source does not have
CANVAS_PARTS = ("neck", "topwear")


def refine_canvas(res, order: Optional[Dict[str, int]] = None, eligible: Iterable[str] = CANVAS_PARTS, tolerance: float = 8.0,
                  margin: int = 24) -> Dict[str, float]:
    """The same test for canvas-scale layers (e.g. the dark line along the bottom of a separately drawn neck)."""
    if res.fullpage is None:
        return {}
    if order is None:
        from ..rig.compile import DRAW_ORDER as order
    elig = [t for t in eligible if t in res.layers and (res.layers[t][..., 3] >= 16).any()]
    if not elig:
        return {}
    n = res.canvas
    roi = _roi([res.layers[t][..., 3] >= 16 for t in elig], margin, n, n)
    u0, v0, u1, v1 = roi
    src_pm = _premult(res.fullpage)[v0:v1, u0:u1]
    stack = [(t, _premult(a[v0:v1, u0:u1])) for t, a in res.layers.items() if t != "head" and (a[v0:v1, u0:u1, 3] > 0).any()]
    stack.sort(key=lambda it: order.get(it[0], 100))
    src_px = float(np.clip(res.canvas / max(res.source_size), 0.3, 4.0))
    weights = _decide(stack, order, elig, _flat(src_pm), src_pm[..., 3] > 0.97, max(1.0, 0.45 * src_px),
                      max(1.5, 0.9 * src_px), tolerance, thin=5)
    removed: Dict[str, float] = {}
    for tag, w in weights.items():
        res.layers[tag], removed[tag] = _apply(res.layers[tag], w, roi, 0.002, 60)
    return removed
