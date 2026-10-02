"""Plain data types of the decomposition engine (no torch import, safe in CPU-only processes)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

import numpy as np

BODY_TAGS = ["front hair", "back hair", "head", "neck", "neckwear", "topwear", "handwear", "bottomwear",
             "legwear", "footwear", "tail", "wings", "objects"]
HEAD_TAGS = ["headwear", "face", "irides", "eyebrow", "eyewhite", "eyelash", "eyewear", "ears", "earwear",
             "nose", "mouth"]

DEFAULT_REPOS = {
    "nf4": "24yearsold/seethroughv0.0.2_layerdiff3d_nf4",
    "bf16": "layerdifforg/seethroughv0.0.2_layerdiff3d",
}

ProgressFn = Callable[[str, float, str], None]  # (stage, fraction 0..1 within the whole decomposition, message)


@dataclass
class DecomposeResult:
    canvas: int                                   # side of the square canvas the layers live on
    source_size: Tuple[int, int]                  # (w, h) of the input image
    layers: Dict[str, np.ndarray]                 # tag -> canvas x canvas x 4 uint8 (head layers shrunk to canvas scale)
    head_hires: Dict[str, np.ndarray] = field(default_factory=dict)  # tag -> res x res x 4 uint8, native head-pass output
    head_square: Optional[Tuple[float, float, float]] = None        # (x0, y0, side) of that square in canvas px
    fullpage: Optional[np.ndarray] = None         # the padded input at canvas size (RGBA)
    source_box: Optional[Tuple[int, int, int, int]] = None  # (x0, y0, x1, y1) of the real source inside the padded canvas
    seed: int = 0
    steps: int = 30
    timings: Dict[str, float] = field(default_factory=dict)
    fidelity: Dict[str, float] = field(default_factory=dict)  # head-part tag -> share removed because the source disagrees


