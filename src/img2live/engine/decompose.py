# Derived from See-through (https://github.com/shitagaki-lab/see-through), Apache-2.0
# (original: inference/scripts/inference_psd_quantized.py `run_layerdiff` and
# common/utils/inference_utils.py `apply_layerdiff`, tag version "v3").
# Modified for img2live: re-implemented as a library API with progress callbacks, the head pass keeps its
# native high-resolution output (the original shrinks it back to source scale and discards the detail),
# bounds are guarded, and the optional depth stage is not part of this module.
# See the NOTICE file at the repository root for attribution and licence details.
"""Layer decomposition: one illustration -> ~23 semantic RGBA layers (two LayerDiff3D passes).

Pass 1 (*body*) runs on the whole character and yields hair (front/back), a combined ``head``
silhouette, neck, clothes, arms, legs, shoes, tail, wings, objects.  Pass 2 (*head*) crops the head out of the
**source** image, enlarges it to the model resolution and yields the facial parts: face, irides, eyebrow,
eyewhite, eyelash, eyewear, ears, earwear, nose, mouth, headwear.

The head pass is generated at the full model resolution (e.g. 1280 px) for a head that may be only ~150 px wide
in the source.  We keep that output (``head_hires``) together with its placement in canvas coordinates so the rig
can use sharp face textures.
"""
from __future__ import annotations

import gc
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

import cv2
import numpy as np

from .imgutils import center_square_pad_resize, smart_resize
from .types import BODY_TAGS, DEFAULT_REPOS, HEAD_TAGS, DecomposeResult, ProgressFn  # noqa: F401  (re-exported)

log = logging.getLogger(__name__)

class _StepProgress:
    """Stand-in for diffusers' tqdm progress bar that forwards step counts to a callback."""

    def __init__(self, total: int, cb: Callable[[int, int], None]):
        self.total, self.n, self.cb = total, 0, cb

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, n: int = 1):
        self.n += n
        self.cb(self.n, self.total)


class Decomposer:
    """Loads LayerDiff3D once and decomposes images.  Not thread-safe (single GPU, one job at a time)."""

    def __init__(self, repo: Optional[str] = None, quant: str = "nf4", group_offload: bool = True,
                 device: str = "cuda"):
        if quant not in DEFAULT_REPOS:
            raise ValueError(f"quant must be one of {list(DEFAULT_REPOS)}")
        self.repo = repo or DEFAULT_REPOS[quant]
        self.quant = quant
        self.group_offload = group_offload
        self.device = device
        self.pipeline = None

    # ------------------------------------------------------------------ loading
    def load(self) -> None:
        if self.pipeline is not None:
            return
        import torch

        from .layerdiffuse.diffusers_kdiffusion_sdxl import KDiffusionStableDiffusionXLPipeline
        from .layerdiffuse.layerdiff3d import UNetFrameConditionModel
        from .layerdiffuse.vae import TransparentVAE

        t0 = time.time()
        log.info("loading LayerDiff3D (%s, quant=%s, group_offload=%s)", self.repo, self.quant, self.group_offload)
        trans_vae = TransparentVAE.from_pretrained(self.repo, subfolder="trans_vae")
        unet = UNetFrameConditionModel.from_pretrained(self.repo, subfolder="unet")
        pipe = KDiffusionStableDiffusionXLPipeline.from_pretrained(self.repo, trans_vae=trans_vae, unet=unet,
                                                                   scheduler=None)
        pipe.vae.to(dtype=torch.bfloat16, device=self.device)
        pipe.trans_vae.to(dtype=torch.bfloat16, device=self.device)
        if self.quant == "bf16":
            # full-precision weights are moved explicitly; NF4 components are placed by bitsandbytes
            pipe.unet.to(dtype=torch.bfloat16, device=self.device)
            pipe.text_encoder.to(dtype=torch.bfloat16, device=self.device)
            pipe.text_encoder_2.to(dtype=torch.bfloat16, device=self.device)
        if self.group_offload:
            pipe.enable_group_offload(self.device, num_blocks_per_group=1)
        pipe.cache_tag_embeds()  # embed the fixed tag vocabulary once, then drop the text encoders
        self.pipeline = pipe
        log.info("LayerDiff3D ready in %.1fs", time.time() - t0)

    def unload(self) -> None:
        import torch

        self.pipeline = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ------------------------------------------------------------------ inference
    def _run_pass(self, tags, image_rgba, group_index, seed, steps, step_cb):
        import torch

        pipe = self.pipeline
        rng = torch.Generator(device=pipe.unet.device).manual_seed(seed)
        pipe.progress_bar = lambda total=None, **kw: _StepProgress(total or steps, step_cb)
        out = pipe(strength=1.0, num_inference_steps=steps, batch_size=1, generator=rng, guidance_scale=1.0,
                   prompt=list(tags), negative_prompt="", fullpage=image_rgba, group_index=group_index,
                   show_progress=False)
        return out.images  # list of HxWx4 uint8, order == tags

    def run(self, rgba: np.ndarray, resolution: int = 1280, steps: int = 30, seed: int = 42,
            progress: Optional[ProgressFn] = None) -> DecomposeResult:
        """Decompose ``rgba`` (HxWx4 uint8) into layers.

        ``progress(stage, fraction, message)`` is called with ``stage`` in {"body", "head"} and a fraction of
        the whole decomposition (body pass = 0..0.55, head pass = 0.55..1).
        """
        from .tensor_utils import seed_everything

        if self.pipeline is None:
            self.load()
        assert rgba.ndim == 3 and rgba.shape[2] == 4 and rgba.dtype == np.uint8
        progress = progress or (lambda *a: None)
        seed_everything(seed)
        t_start = time.time()

        src_h, src_w = rgba.shape[:2]
        fullpage, pad_size, pad_pos = center_square_pad_resize(rgba, resolution, return_pad_info=True)
        scale = pad_size[0] / resolution  # source px per canvas px

        # ---- pass 1: body
        t0 = time.time()
        body_imgs = self._run_pass(
            BODY_TAGS, fullpage, 0, seed, steps,
            lambda i, n: progress("body", 0.55 * i / n, f"body pass step {i}/{n}"))
        layers: Dict[str, np.ndarray] = {tag: img for tag, img in zip(BODY_TAGS, body_imgs)}
        t_body = time.time() - t0

        # ---- head crop from the *source* image (not from the generated silhouette)
        head_sil = layers["head"]
        mask = (head_sil[..., 3] > 15).astype(np.uint8)
        result = DecomposeResult(canvas=resolution, source_size=(src_w, src_h), layers={}, fullpage=fullpage,
                                 seed=seed, steps=steps)
        if mask.sum() == 0:
            log.warning("no head found in the body pass; skipping the head pass")
            result.layers = layers
            result.timings = {"body_s": t_body, "head_s": 0.0, "total_s": time.time() - t_start}
            return result

        hx0, hy0, hw, hh = cv2.boundingRect(cv2.findNonZero(mask))
        hx, hy, hw, hh = (int(hx0 * scale) - pad_pos[0], int(hy0 * scale) - pad_pos[1], int(hw * scale), int(hh * scale))
        input_head, (cx1, cy1, cx2, cy2) = _crop_head(rgba, (hx, hy, hw, hh))
        head_sq, head_pad_size, head_pad_pos = center_square_pad_resize(input_head, resolution, return_pad_info=True)

        # ---- pass 2: head
        t0 = time.time()
        head_imgs = self._run_pass(
            HEAD_TAGS, head_sq, 1, seed, steps,
            lambda i, n: progress("head", 0.55 + 0.45 * i / n, f"head pass step {i}/{n}"))
        t_head = time.time() - t0

        # placement of the head square in canvas coordinates
        # canvas_x = (source_x + pad_pos_x) / scale ; the square's top-left in source px is (cx1 - head_pad_pos_x, ...)
        side_c = head_pad_size[0] / scale
        x0_c = (cx1 - head_pad_pos[0] + pad_pos[0]) / scale
        y0_c = (cy1 - head_pad_pos[1] + pad_pos[1]) / scale
        result.head_square = (float(x0_c), float(y0_c), float(side_c))
        result.head_hires = {tag: img for tag, img in zip(HEAD_TAGS, head_imgs)}

        # canvas-scale head layers (what the original See-through produces): shrink the head-square output to
        # canvas scale and paste it; kept so every consumer that wants plain canvas layers still works
        out_side = max(1, int(round(side_c)))
        px0, py0 = int(round(x0_c)), int(round(y0_c))
        for tag, img in zip(HEAD_TAGS, head_imgs):
            small = smart_resize(img, (out_side, out_side))
            canvas = np.zeros((resolution, resolution, 4), dtype=np.uint8)
            sx0, sy0 = max(0, -px0), max(0, -py0)
            dx0, dy0 = max(0, px0), max(0, py0)
            w = min(out_side - sx0, resolution - dx0)
            h = min(out_side - sy0, resolution - dy0)
            if w > 0 and h > 0:
                canvas[dy0:dy0 + h, dx0:dx0 + w] = small[sy0:sy0 + h, sx0:sx0 + w]
            layers[tag] = canvas

        result.layers = layers
        result.timings = {"body_s": t_body, "head_s": t_head, "total_s": time.time() - t_start}
        progress("done", 1.0, "decomposition finished")
        return result


def _crop_head(img: np.ndarray, xywh) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """Crop the head box (source px) with a margin of w/5 (clamped), as See-through does."""
    x, y, w, h = xywh
    ih, iw = img.shape[:2]
    x1, y1, x2, y2 = x, y, x + w, y + h
    if w < iw // 2:
        px = min(iw - x - w, x, w // 5)
        x1 = min(max(x - px, 0), iw)
        x2 = min(max(x + w + px, 0), iw)
    if h < ih // 2:
        py = min(ih - y - h, y, h // 5)
        y2 = min(max(y + h + py, 0), ih)
        y1 = min(max(y - py, 0), ih)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(iw, max(x2, x1 + 1)), min(ih, max(y2, y1 + 1))
    return img[y1:y2, x1:x2], (x1, y1, x2, y2)
