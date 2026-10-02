"""Writing a job's artifacts: layer PNGs + index, composite, PSD, zips."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from ..engine.types import DecomposeResult
from ..rig.compile import DRAW_ORDER

ALPHA_T = 16


def _bbox(rgba: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    m = (rgba[..., 3] >= ALPHA_T).astype(np.uint8)
    if m.sum() == 0:
        return None
    x, y, w, h = cv2.boundingRect(cv2.findNonZero(m))
    return x, y, x + w, y + h


def composite(layers: Dict[str, np.ndarray], size: int) -> np.ndarray:
    """Alpha-composite canvas layers in draw order (straight alpha in/out)."""
    acc = np.zeros((size, size, 4), np.float32)
    for tag in sorted((t for t in layers if t in DRAW_ORDER), key=lambda t: DRAW_ORDER[t]):
        l = layers[tag].astype(np.float32) / 255.0
        a = l[..., 3:4]
        out_a = a + acc[..., 3:4] * (1 - a)
        acc[..., :3] = np.where(out_a > 1e-6, (l[..., :3] * a + acc[..., :3] * acc[..., 3:4] * (1 - a)) / np.maximum(out_a, 1e-6), 0)
        acc[..., 3:4] = out_a
    return (np.clip(acc, 0, 1) * 255).astype(np.uint8)


def write_layers(res: DecomposeResult, out: Path) -> dict:
    """layers/<tag>.png cropped + layers_hires/<tag>.png cropped, plus index.json describing the placement."""
    (out / "layers").mkdir(parents=True, exist_ok=True)
    (out / "layers_hires").mkdir(parents=True, exist_ok=True)
    index = {"canvas": res.canvas, "head_square": list(res.head_square) if res.head_square else None, "layers": [], "hires": []}
    for tag, rgba in res.layers.items():
        if tag == "head":
            continue
        bb = _bbox(rgba)
        if bb is None:
            index["layers"].append({"tag": tag, "empty": True})
            continue
        x0, y0, x1, y1 = bb
        name = tag.replace(" ", "_")
        Image.fromarray(rgba[y0:y1, x0:x1], "RGBA").save(out / "layers" / f"{name}.png", optimize=True)
        index["layers"].append({"tag": tag, "file": f"layers/{name}.png", "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                                "opaque_px": int((rgba[..., 3] >= ALPHA_T).sum())})
    if res.head_hires and res.head_square:
        sq = res.head_square
        for tag, rgba in res.head_hires.items():
            bb = _bbox(rgba)
            if bb is None:
                continue
            x0, y0, x1, y1 = bb
            Image.fromarray(rgba[y0:y1, x0:x1], "RGBA").save(out / "layers_hires" / f"{tag}.png", optimize=True)
            s = sq[2] / rgba.shape[0]
            index["hires"].append({"tag": tag, "file": f"layers_hires/{tag}.png", "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                                   "canvas_x": sq[0] + x0 * s, "canvas_y": sq[1] + y0 * s, "scale": s})
    (out / "layers" / "index.json").write_text(json.dumps(index, indent=1))
    return index


def write_psd(layers: Dict[str, np.ndarray], size: int, path: Path) -> None:
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer

    psd = PSDImage.new("RGBA", (size, size))
    for tag in sorted((t for t in layers if t in DRAW_ORDER), key=lambda t: DRAW_ORDER[t]):
        bb = _bbox(layers[tag])
        if bb is None:
            continue
        x0, y0, x1, y1 = bb
        psd.append(PixelLayer.frompil(Image.fromarray(layers[tag][y0:y1, x0:x1], "RGBA"), psd, name=tag, top=y0, left=x0))
    psd.save(str(path))


def zip_dir(src: Path, dest: Path, include: List[str]) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in include:
            p = src / rel
            if p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file():
                        z.write(f, f.relative_to(src).as_posix())
            elif p.is_file():
                z.write(p, rel)


def write_fullcanvas_zip(layers: Dict[str, np.ndarray], psd_path: Optional[Path], dest: Path) -> None:
    import io

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for tag, rgba in layers.items():
            if tag == "head" or _bbox(rgba) is None:
                continue
            buf = io.BytesIO()
            Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
            z.writestr(f"{tag.replace(' ', '_')}.png", buf.getvalue())
        if psd_path and psd_path.exists():
            z.write(psd_path, "layers.psd")


def list_files(job_dir: Path) -> List[dict]:
    out = []
    for p in sorted(job_dir.rglob("*")):
        if p.is_file():
            out.append({"path": p.relative_to(job_dir).as_posix(), "size": p.stat().st_size})
    return out
