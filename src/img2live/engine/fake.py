"""Synthetic stand-in for the decomposition engine (no GPU, no model, no copyrighted art).

Draws a simple cartoon character, already split into the LayerDiff3D tag vocabulary, with the same data layout as
``DecomposeResult`` (including a high-resolution head pass).  It exists for tests, CI and local development of the
rig compiler / service; it is selected with ``IMG2LIVE_ENGINE=fake``.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, Optional

import numpy as np
from PIL import Image, ImageDraw

from .types import DecomposeResult

SS = 4  # supersampling factor for antialiasing


def _canvas(side: int) -> Image.Image:
    return Image.new("RGBA", (side * SS, side * SS), (0, 0, 0, 0))


def _done(img: Image.Image, side: int) -> np.ndarray:
    return np.asarray(img.resize((side, side), Image.LANCZOS), dtype=np.uint8).copy()


def _scale(pts, k):
    return [(x * k * SS, y * k * SS) for x, y in pts]


def _ellipse(d, cx, cy, rx, ry, k, **kw):
    d.ellipse([(cx - rx) * k * SS, (cy - ry) * k * SS, (cx + rx) * k * SS, (cy + ry) * k * SS], **kw)


def _draw_head(side: int, k: float, ox: float, oy: float) -> Dict[str, np.ndarray]:
    """Head parts. Coordinates are canvas px (1280 grid); ``k`` canvas->pixel scale, (ox, oy) origin of the surface."""
    def P(pts):
        return _scale([(x - ox, y - oy) for x, y in pts], k)

    def E(d, cx, cy, rx, ry, **kw):
        _ellipse(d, cx - ox, cy - oy, rx, ry, k, **kw)

    out: Dict[str, np.ndarray] = {}
    skin, hair, hair2 = (250, 214, 190, 255), (70, 48, 92, 255), (96, 66, 122, 255)

    im = _canvas(side); d = ImageDraw.Draw(im)
    E(d, 640, 210, 74, 86, fill=skin, outline=(40, 25, 40, 255), width=max(1, int(2 * k * SS)))
    E(d, 585, 232, 18, 9, fill=(255, 150, 150, 120))
    E(d, 695, 232, 18, 9, fill=(255, 150, 150, 120))
    out["face"] = _done(im, side)

    for name, cx in (("l", 606), ("r", 674)):
        pass
    im = _canvas(side); d = ImageDraw.Draw(im)
    for cx in (606, 674):
        E(d, cx, 212, 19, 12, fill=(255, 255, 255, 255))
    out["eyewhite"] = _done(im, side)

    im = _canvas(side); d = ImageDraw.Draw(im)
    for cx in (606, 674):
        E(d, cx, 213, 9.5, 11, fill=(70, 130, 200, 255))
        E(d, cx, 213, 4.5, 5.5, fill=(15, 25, 50, 255))
        E(d, cx - 3, 209, 2.4, 2.4, fill=(255, 255, 255, 255))
    out["irides"] = _done(im, side)

    im = _canvas(side); d = ImageDraw.Draw(im)
    for cx, sgn in ((606, -1), (674, 1)):
        d.arc([(cx - 21 - ox) * k * SS, (200 - oy) * k * SS, (cx + 21 - ox) * k * SS, (226 - oy) * k * SS], 190, 350,
              fill=(30, 20, 40, 255), width=max(2, int(3.4 * k * SS)))
        d.line(P([(cx + sgn * 20, 208), (cx + sgn * 26, 204)]), fill=(30, 20, 40, 255), width=max(2, int(2.6 * k * SS)))
    out["eyelash"] = _done(im, side)

    im = _canvas(side); d = ImageDraw.Draw(im)
    for cx in (606, 674):
        d.line(P([(cx - 17, 184), (cx, 179), (cx + 17, 183)]), fill=(60, 40, 70, 255), width=max(2, int(2.8 * k * SS)))
    out["eyebrow"] = _done(im, side)

    im = _canvas(side); d = ImageDraw.Draw(im)
    E(d, 640, 241, 2.2, 1.6, fill=(205, 150, 140, 255))
    out["nose"] = _done(im, side)

    im = _canvas(side); d = ImageDraw.Draw(im)
    d.arc([(626 - ox) * k * SS, (246 - oy) * k * SS, (654 - ox) * k * SS, (262 - oy) * k * SS], 20, 160,
          fill=(170, 70, 80, 255), width=max(2, int(2.6 * k * SS)))
    out["mouth"] = _done(im, side)

    im = _canvas(side); d = ImageDraw.Draw(im)
    E(d, 566, 218, 9, 14, fill=skin, outline=(40, 25, 40, 255), width=max(1, int(1.6 * k * SS)))
    E(d, 714, 218, 9, 14, fill=skin, outline=(40, 25, 40, 255), width=max(1, int(1.6 * k * SS)))
    out["ears"] = _done(im, side)

    for tag in ("headwear", "eyewear", "earwear"):
        out[tag] = np.zeros((side, side, 4), np.uint8)
    return out


def synthetic_layers(canvas: int = 1280) -> Dict[str, np.ndarray]:
    """Body layers + canvas-scale head layers."""
    L: Dict[str, np.ndarray] = {}
    skin, cloth, skirt = (250, 214, 190, 255), (230, 90, 120, 255), (60, 70, 150, 255)
    hair, hair2 = (70, 48, 92, 255), (96, 66, 122, 255)

    def new():
        im = _canvas(canvas)
        return im, ImageDraw.Draw(im)

    # back hair (long, behind everything)
    im, d = new()
    d.polygon(_scale([(552, 150), (640, 108), (728, 150), (760, 330), (748, 520), (700, 540), (640, 380), (580, 540), (532, 520), (520, 330)], 1), fill=hair)
    L["back hair"] = _done(im, canvas)
    # front hair (bangs + side locks)
    im, d = new()
    d.polygon(_scale([(560, 190), (570, 140), (640, 120), (710, 140), (722, 190), (690, 170), (650, 200), (620, 168), (590, 196)], 1), fill=hair2)
    d.polygon(_scale([(556, 190), (548, 330), (566, 360), (572, 230)], 1), fill=hair2)
    d.polygon(_scale([(724, 190), (732, 330), (714, 360), (708, 230)], 1), fill=hair2)
    L["front hair"] = _done(im, canvas)
    # neck
    im, d = new()
    d.rectangle(_scale([(622, 280), (658, 318)], 1)[0] + _scale([(622, 280), (658, 318)], 1)[1], fill=skin)
    L["neck"] = _done(im, canvas)
    # topwear
    im, d = new()
    d.polygon(_scale([(580, 312), (700, 312), (730, 360), (716, 560), (564, 560), (550, 360)], 1), fill=cloth)
    L["topwear"] = _done(im, canvas)
    # arms
    im, d = new()
    d.polygon(_scale([(552, 340), (580, 336), (586, 600), (560, 606), (540, 450)], 1), fill=skin)
    d.polygon(_scale([(728, 340), (700, 336), (694, 600), (720, 606), (740, 450)], 1), fill=skin)
    L["handwear"] = _done(im, canvas)
    # skirt
    im, d = new()
    d.polygon(_scale([(570, 550), (710, 550), (760, 700), (520, 700)], 1), fill=skirt)
    L["bottomwear"] = _done(im, canvas)
    # legs
    im, d = new()
    d.rectangle(_scale([(596, 700), (628, 1180)], 1)[0] + _scale([(596, 700), (628, 1180)], 1)[1], fill=skin)
    d.rectangle(_scale([(652, 700), (684, 1180)], 1)[0] + _scale([(652, 700), (684, 1180)], 1)[1], fill=skin)
    L["legwear"] = _done(im, canvas)
    # shoes
    im, d = new()
    _ellipse(d, 604, 1196, 34, 16, 1, fill=(40, 40, 50, 255))
    _ellipse(d, 676, 1196, 34, 16, 1, fill=(40, 40, 50, 255))
    L["footwear"] = _done(im, canvas)
    for tag in ("neckwear", "tail", "wings", "objects"):
        L[tag] = np.zeros((canvas, canvas, 4), np.uint8)
    L["head"] = np.zeros((canvas, canvas, 4), np.uint8)
    for tag, arr in _draw_head(canvas, 1.0, 0.0, 0.0).items():
        L[tag] = arr
    return L


def _flatten(layers: Dict[str, np.ndarray], size: int) -> np.ndarray:
    """Opaque composite of the synthetic layers on white (stands in for the padded source image)."""
    order = ["back hair", "footwear", "legwear", "bottomwear", "topwear", "handwear", "neck", "ears", "face", "eyewhite",
             "irides", "eyelash", "eyebrow", "nose", "mouth", "eyewear", "front hair"]
    acc = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    for t in order:
        if t in layers:
            acc.alpha_composite(Image.fromarray(layers[t], "RGBA"))
    return np.asarray(acc, dtype=np.uint8).copy()


class FakeDecomposer:
    """Drop-in for :class:`Decomposer` that ignores the input image.

    ``leak_attempts``: the first N runs simulate the real failure mode (the plain background dumped into the
    ``legwear`` layer) so the clean-up / retry path can be tested.
    """

    def __init__(self, *a, leak_attempts: int = 0, **k):
        self.loaded = False
        self.leak_attempts = leak_attempts
        self.runs = 0

    def load(self) -> None:
        self.loaded = True

    def run(self, rgba: np.ndarray, resolution: int = 1280, steps: int = 30, seed: int = 42,
            progress: Optional[Callable[[str, float, str], None]] = None) -> DecomposeResult:
        progress = progress or (lambda *a: None)
        t0 = time.time()
        for i in range(10):
            progress("body", 0.55 * (i + 1) / 10, f"synthetic body pass {i + 1}/10")
            time.sleep(0.05)
        layers = synthetic_layers(resolution)
        fullpage = _flatten(layers, resolution)
        if self.runs < self.leak_attempts:
            leak = np.zeros_like(layers["legwear"])
            leak[...] = (170, 170, 170, 255)
            keep = layers["legwear"][..., 3] > 0
            leak[keep] = layers["legwear"][keep]
            layers["legwear"] = leak
        self.runs += 1
        sq = (520.0 * resolution / 1280, 60.0 * resolution / 1280, 240.0 * resolution / 1280)
        k = resolution / sq[2]  # hi-res px per canvas px
        hires = _draw_head(resolution, k, sq[0], sq[1])
        for i in range(10):
            progress("head", 0.55 + 0.45 * (i + 1) / 10, f"synthetic head pass {i + 1}/10")
            time.sleep(0.05)
        h, w = rgba.shape[:2]
        return DecomposeResult(canvas=resolution, source_size=(w, h), layers=layers, head_hires=hires, head_square=sq,
                               fullpage=fullpage, source_box=(0, 0, resolution, resolution), seed=seed, steps=steps,
                               timings={"body_s": 0.5, "head_s": 0.5, "total_s": time.time() - t0})
