"""Sanity checks and clean-up of decomposition output.

LayerDiff3D is a diffusion model: depending on the seed it sometimes dumps a large area (typically the plain
background) into one layer, and the high-resolution head pass carries faint alpha specks.  Because every hidden
part lies *behind* a visible part, a correct layer never leaves the character's silhouette.  So:

1. estimate the foreground silhouette from the source image (its alpha, else the colour distance to the border),
2. clip every layer to the silhouette (dilated by a margin),
3. drop alpha specks and tiny islands,
4. report layers that were mostly outside the silhouette; the pipeline retries with another seed if too much
   of the character's area was lost to leaks,
5. give visible silhouette pixels that *no* layer covers (the model sometimes returns an empty layer, e.g. no
   shoes) to the neighbouring layer, using the source colours - the visible part of a character is known exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

ALPHA_T = 16


@dataclass
class CleanupReport:
    silhouette_ok: bool = False
    silhouette_frac: float = 0.0
    leaks: Dict[str, float] = field(default_factory=dict)       # tag -> share of the layer's area outside the silhouette
    severe: List[str] = field(default_factory=list)             # tags with a severe leak
    removed_specks: Dict[str, int] = field(default_factory=dict)
    uncovered_frac: float = 0.0                                  # share of the silhouette no layer covered
    filled: Dict[str, int] = field(default_factory=dict)         # tag -> pixels taken from the source image
    note: str = ""

    def to_dict(self) -> dict:
        return {"silhouette_ok": self.silhouette_ok, "silhouette_frac": round(self.silhouette_frac, 4),
                "leaks": {k: round(v, 3) for k, v in self.leaks.items()}, "severe": self.severe,
                "removed_specks": self.removed_specks, "uncovered_frac": round(self.uncovered_frac, 4),
                "filled": self.filled, "note": self.note}


def _estimate(fullpage_rgba: np.ndarray, source_box: Optional[Tuple[int, int, int, int]] = None
              ) -> Tuple[np.ndarray, np.ndarray, bool]:
    """(silhouette, solid, trusted) on the canvas grid.

    ``silhouette`` is the foreground with enclosed pockets filled in (it only has to *contain* every layer);
    ``solid`` is the foreground without that hole filling - pixels that really differ from the background - and is
    what may be handed to a layer.  ``source_box`` is where the real source image sits inside the (transparently
    padded) square canvas; only that region is analysed so the padding is not mistaken for transparency.
    """
    H, W = fullpage_rgba.shape[:2]
    x0, y0, x1, y1 = source_box if source_box else (0, 0, W, H)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    crop = fullpage_rgba[y0:y1, x0:x1]
    a = crop[..., 3]
    if (a < 250).mean() > 0.05:  # the source itself carries transparency (e.g. a cut-out): use its alpha
        m_crop = a > 20
        solid_crop = m_crop
        trusted = bool(0.01 < m_crop.mean() < 0.8)
    else:
        rgb = crop[..., :3].astype(np.float32)
        h, w = rgb.shape[:2]
        b = max(3, int(0.02 * min(h, w)))
        border = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3), rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
        bg = np.median(border, axis=0)
        spread = float(np.median(np.linalg.norm(border - bg, axis=1)))
        dist = np.linalg.norm(rgb - bg, axis=2)
        thr = max(28.0, 4.0 * spread + 14.0)
        solid_crop = dist > thr
        m = cv2.morphologyEx(solid_crop.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        # fill holes: everything not reachable from the border
        ff = (1 - m).astype(np.uint8)
        fm = np.zeros((h + 2, w + 2), np.uint8)
        for sx, sy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if ff[sy, sx] == 1:
                cv2.floodFill(ff, fm, (sx, sy), 2)
        m_crop = (m > 0) | (ff == 1)
        trusted = bool(spread < 18.0 and 0.01 < m_crop.mean() < 0.75)
    out = np.zeros((H, W), bool)
    out[y0:y1, x0:x1] = m_crop
    solid = np.zeros((H, W), bool)
    solid[y0:y1, x0:x1] = solid_crop
    return out, solid, trusted


def silhouette(fullpage_rgba: np.ndarray, source_box: Optional[Tuple[int, int, int, int]] = None) -> Tuple[np.ndarray, bool]:
    """Foreground mask on the canvas grid (bool HxW) and whether the estimate is trustworthy."""
    sil, _, trusted = _estimate(fullpage_rgba, source_box)
    return sil, trusted


def _drop_specks(rgba: np.ndarray, min_area: int, hard: int = 40) -> Tuple[np.ndarray, int]:
    """Zero out alpha specks: low alpha everywhere, and connected components smaller than ``min_area``."""
    a = rgba[..., 3]
    core = (a >= hard).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(core, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    kept_core = keep[lab]
    near = cv2.dilate(kept_core.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0  # soft edge of a kept island survives
    out = rgba.copy()
    removed = int(((a > 0) & ~near).sum())
    out[..., 3] = np.where(near, a, 0)
    return out, removed


def _clean_one(rgba: np.ndarray, sil: Optional[np.ndarray], rep: CleanupReport, tag: str, min_island_frac: float,
               track_leak: bool = True) -> np.ndarray:
    cur = rgba
    opaque = int((cur[..., 3] >= ALPHA_T).sum())
    if sil is not None and opaque > 0:
        outside = int(((cur[..., 3] >= ALPHA_T) & ~sil).sum())
        if outside > 0 and track_leak:
            share = outside / opaque
            rep.leaks[tag] = max(rep.leaks.get(tag, 0.0), share)
            if share > 0.35 and outside > 0.01 * cur.shape[0] * cur.shape[1]:
                if tag not in rep.severe:
                    rep.severe.append(tag)
        cur = cur.copy()
        cur[~sil] = 0
    if (cur[..., 3] >= ALPHA_T).any():
        area = int((cur[..., 3] >= ALPHA_T).sum())
        cur, removed = _drop_specks(cur, max(24, int(min_island_frac * area)))
        if removed:
            rep.removed_specks[tag] = rep.removed_specks.get(tag, 0) + removed
    # a layer that is nothing but a few pixels is empty
    if int((cur[..., 3] >= ALPHA_T).sum()) < 40:
        cur = np.zeros_like(cur)
    return cur


def decontaminate(rgba: np.ndarray, solid: float = 0.9, reach: int = 6) -> np.ndarray:
    """Give semi-transparent edge pixels the colour of the nearest (nearly) opaque pixel, alpha unchanged.

    The decoder's colour under low alpha drifts towards black (the transparent area is dark), so a plain alpha blend
    shows a dark fringe, e.g. a grey ring around a skin-coloured eyelid layer.  ``reach`` limits how far a colour may
    be taken (px): thin strokes that never become opaque keep their own colour.
    """
    from scipy import ndimage as ndi

    a = rgba[..., 3]
    core = a >= int(255 * solid)
    semi = (a > 0) & ~core
    if not core.any() or not semi.any():
        return rgba
    dist, (iy, ix) = ndi.distance_transform_edt(~core, return_indices=True)
    take = semi & (dist <= reach)
    out = rgba.copy()
    out[take, :3] = rgba[iy[take], ix[take], :3]
    return out


UNCOVERED_SEVERE = 0.08   # more than this share of the silhouette without any layer: the decomposition failed


def _fill_uncovered(res, sil: np.ndarray, solid: np.ndarray, rep: CleanupReport, min_area_frac: float = 0.0007) -> None:
    """Assign foreground pixels that no layer covers to a layer, with colours from the source image.

    Only ``solid`` pixels qualify: background pockets enclosed by the character (between the legs, inside a hair loop)
    are inside the silhouette but are not part of any layer."""
    H, W = sil.shape
    tags = [t for t in res.layers if t != "head"]
    covered = np.zeros((H, W), bool)
    for t in tags:
        covered |= res.layers[t][..., 3] >= 100
    unc = (sil & solid & ~covered).astype(np.uint8)
    unc = cv2.morphologyEx(unc, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))  # edge halos are not missing parts
    rep.uncovered_frac = float(unc.sum()) / max(1, int((sil & solid).sum()))
    if rep.uncovered_frac == 0 or res.fullpage is None:
        return
    n, lab, stats, cent = cv2.connectedComponentsWithStats(unc, connectivity=8)
    min_area = max(60, int(min_area_frac * H * W))
    opaque = {t: res.layers[t][..., 3] >= 100 for t in tags}
    leg = opaque.get("legwear")
    leg_rows = np.where(leg.any(axis=1))[0] if leg is not None and leg.any() else None
    footwear_missing = "footwear" in res.layers and not opaque["footwear"].any()  # judged before anything is filled
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < min_area:
            continue
        comp = lab == i
        ring = (cv2.dilate(comp.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0) & ~comp
        votes = {t: int(m[ring].sum()) for t, m in opaque.items() if m[ring].any()}
        target = max(votes, key=votes.get) if votes else "objects"
        if (target in ("legwear", "footwear") and footwear_missing
                and leg_rows is not None and cent[i][1] >= leg_rows[0] + 0.6 * (leg_rows[-1] - leg_rows[0])):
            target = "footwear"  # what hangs below the legs and was left out is the footwear
        grow = (cv2.dilate(comp.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & sil & solid & ~covered
        layer = res.layers[target].copy()
        layer[grow, :3] = res.fullpage[grow, :3]
        layer[grow, 3] = 255
        res.layers[target] = layer
        opaque[target] = layer[..., 3] >= 100
        rep.filled[target] = rep.filled.get(target, 0) + int(grow.sum())
    if rep.uncovered_frac > UNCOVERED_SEVERE and "uncovered" not in rep.severe:
        rep.severe.append("uncovered")


def clean_result(res, margin: int = 3, min_island_frac: float = 0.0015) -> CleanupReport:
    """Clean a DecomposeResult in place (canvas layers and the hi-res head layers) and return the verdict."""
    rep = CleanupReport()
    sil = None
    if res.fullpage is not None and res.fullpage[..., 3].any():
        sil, solid, rep.silhouette_ok = _estimate(res.fullpage, res.source_box)
        rep.silhouette_frac = float(sil.mean())
        sil_raw = sil
        if rep.silhouette_ok:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin + 1, 2 * margin + 1))
            sil = cv2.dilate(sil.astype(np.uint8), k) > 0
        else:
            sil = None
    for tag in list(res.layers):
        if tag == "head":
            continue
        res.layers[tag] = _clean_one(res.layers[tag], sil, rep, tag, min_island_frac)
    if sil is not None:
        _fill_uncovered(res, sil_raw, solid, rep)
    if res.head_hires and res.head_square:
        x0, y0, side = res.head_square
        n = next(iter(res.head_hires.values())).shape[0]
        s = side / n  # canvas px per hi-res px
        sil_hi = None
        if sil is not None:
            M = np.array([[1 / s, 0, -x0 / s], [0, 1 / s, -y0 / s]], dtype=np.float32)
            sil_hi = cv2.warpAffine(sil.astype(np.uint8), M, (n, n), flags=cv2.INTER_NEAREST, borderValue=0) > 0
        for tag in list(res.head_hires):
            res.head_hires[tag] = _clean_one(res.head_hires[tag], sil_hi, rep, "hires:" + tag, min_island_frac, track_leak=False)
    # the hi-res head layers are drawn 5-6x larger than the source, where a dark colour fringe on soft edges shows as a ring
    for tag in list(res.head_hires):
        res.head_hires[tag] = decontaminate(res.head_hires[tag], reach=12)
    return rep
