"""Software preview renderer + pose contact sheet (QA artifact, independent of the browser runtime).

Triangles are drawn with per-triangle affine texture warps (cv2).  Good enough to eyeball deformations and
to ship a "rig sanity sheet" with every job; the WebGL viewer is the real renderer.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .runtime_py import evaluate, opacity_of


def _load_textures(puppet: dict, tex_dir: str) -> Dict[str, np.ndarray]:
    out = {}
    for m in puppet["meshes"]:
        a = np.asarray(Image.open(os.path.join(tex_dir, m["texture"])).convert("RGBA"), dtype=np.float32) / 255.0
        a[..., :3] *= a[..., 3:4]  # premultiply
        out[m["id"]] = a
    return out


def _draw_mesh(dst: np.ndarray, tex: np.ndarray, pos: np.ndarray, uv: np.ndarray, tri: np.ndarray, M: np.ndarray) -> None:
    """Accumulate one mesh into ``dst`` (premultiplied RGBA float, 'over' with itself via max-alpha per triangle)."""
    th, tw = tex.shape[:2]
    P = pos * M[0] + M[1]
    U = uv * np.array([tw, th], dtype=np.float32)
    H, W = dst.shape[:2]
    for a, b, c in tri:
        d = P[[a, b, c]].astype(np.float32)
        x0, y0 = np.floor(d.min(axis=0)).astype(int) - 1
        x1, y1 = np.ceil(d.max(axis=0)).astype(int) + 1
        if x1 <= 0 or y1 <= 0 or x0 >= W or y0 >= H or x1 - x0 < 1 or y1 - y0 < 1:
            continue
        x0c, y0c, x1c, y1c = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
        s = U[[a, b, c]].astype(np.float32)
        A = cv2.getAffineTransform(s, d - np.array([x0c, y0c], dtype=np.float32))
        w, h = x1c - x0c, y1c - y0c
        patch = cv2.warpAffine(tex, A, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        mask = np.zeros((h, w), np.uint8)
        cv2.fillConvexPoly(mask, np.round((d - np.array([x0c, y0c], dtype=np.float32)) * 16).astype(np.int32), 255, lineType=cv2.LINE_8, shift=4)
        roi = dst[y0c:y1c, x0c:x1c]
        sel = mask > 0
        roi[sel] = patch[sel]  # overwrite (not 'over'): triangles of one mesh must not double-blend at shared edges


def render(puppet: dict, textures: Dict[str, np.ndarray], params: Dict[str, float], view: Tuple[float, float, float, float],
           out_w: int = 480, bg=(255, 255, 255)) -> np.ndarray:
    x0, y0, x1, y1 = view
    scale = out_w / (x1 - x0)
    out_h = int(round((y1 - y0) * scale))
    M = (np.array([scale, scale], dtype=np.float32), np.array([-x0 * scale, -y0 * scale], dtype=np.float32))
    pos = evaluate(puppet, params)
    full = {p["id"]: p["default"] for p in puppet["params"]}
    full.update(params)
    layers: Dict[str, np.ndarray] = {}
    acc = np.zeros((out_h, out_w, 4), np.float32)
    meshes = puppet["meshes"]
    by_id = {m["id"]: m for m in meshes}
    cache: Dict[str, np.ndarray] = {}

    def mesh_layer(m: dict) -> np.ndarray:
        if m["id"] not in cache:
            L = np.zeros((out_h, out_w, 4), np.float32)
            uv = np.asarray(m["uvs"], dtype=np.float32).reshape(-1, 2)
            tri = np.asarray(m["indices"], dtype=np.int64).reshape(-1, 3)
            _draw_mesh(L, textures[m["id"]], pos[m["id"]].astype(np.float32), uv, tri, M)
            cache[m["id"]] = L
        return cache[m["id"]]

    for m in meshes:
        op = opacity_of(m, full)
        if op <= 0.001:
            continue
        L = mesh_layer(m)
        if m.get("clip") and m["clip"] in by_id:
            L = L * np.clip(mesh_layer(by_id[m["clip"]])[..., 3:4] * 1.0, 0, 1)
        L = L * op
        acc = L + acc * (1 - L[..., 3:4])
    bgc = np.array(bg, np.float32) / 255.0
    rgb = acc[..., :3] + bgc * (1 - acc[..., 3:4])
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)


POSES: List[Tuple[str, Dict[str, float], str]] = [
    ("rest", {}, "body"),
    ("rest (head)", {}, "head"),
    ("yaw +30", {"ParamAngleX": 30}, "head"),
    ("yaw -30", {"ParamAngleX": -30}, "head"),
    ("pitch +30", {"ParamAngleY": 30}, "head"),
    ("pitch -30", {"ParamAngleY": -30}, "head"),
    ("roll +25", {"ParamAngleZ": 25}, "head"),
    ("eyes closed", {"ParamEyeLOpen": 0, "ParamEyeROpen": 0}, "head"),
    ("wink L", {"ParamEyeLOpen": 0}, "head"),
    ("gaze right+up", {"ParamEyeBallX": 1, "ParamEyeBallY": 0.8}, "head"),
    ("mouth open", {"ParamMouthOpenY": 1}, "head"),
    ("brows up", {"ParamBrowLY": 1, "ParamBrowRY": 1}, "head"),
    ("hair sway", {"ParamHairFront": 1, "ParamHairBack": 1}, "body"),
    ("body sway + roll", {"ParamBodyAngleX": 10, "ParamBodyAngleZ": 10}, "body"),
    ("breath", {"ParamBreath": 1}, "body"),
    ("yaw30+roll+eyes", {"ParamAngleX": 30, "ParamAngleZ": 15, "ParamEyeLOpen": 0, "ParamEyeROpen": 0, "ParamMouthOpenY": 1}, "head"),
]


def pose_sheet(puppet: dict, tex_dir: str, out_path: str, cell: int = 300, cols: int = 4,
               poses: Optional[Sequence[Tuple[str, Dict[str, float], str]]] = None) -> str:
    textures = _load_textures(puppet, tex_dir)
    avail = {p["id"] for p in puppet["params"]}
    poses = [p for p in (poses or POSES) if all(k in avail for k in p[1])]
    cells = []
    hb, bb = puppet["headBounds"], puppet["bounds"]
    for name, params, view in poses:
        v = hb if view == "head" else (bb[0] - 20, bb[1] - 20, bb[2] + 20, bb[3] + 20)
        # square-ish framing with the cell aspect
        vw, vh = v[2] - v[0], v[3] - v[1]
        cx, cy = (v[0] + v[2]) / 2, (v[1] + v[3]) / 2
        side = max(vw, vh)
        v = (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
        img = render(puppet, textures, params, v, out_w=cell)
        cells.append((name, img))
    rows = (len(cells) + cols - 1) // cols
    pad = 22
    sheet = Image.new("RGB", (cols * cell, rows * (cell + pad)), (245, 245, 245))
    d = ImageDraw.Draw(sheet)
    for i, (name, img) in enumerate(cells):
        x, y = (i % cols) * cell, (i // cols) * (cell + pad)
        d.text((x + 6, y + 5), name, fill=(40, 40, 40))
        sheet.paste(Image.fromarray(img), (x, y + pad))
    sheet.save(out_path, compress_level=6)
    return out_path
