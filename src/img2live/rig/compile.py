"""Rig compiler: layers -> puppet.json (+ textures).

The puppet format is a flat, Cubism-shaped set of keyform data (see ``runtime_py.py`` for exact semantics):
every mesh owns an ordered list of deformation entries; an entry is either a piecewise-linear *field* over a
parameter (per-vertex displacement at a few key values) or an exact *rotation* about a pivot.  Everything the
compiler produces is an analytic model sampled into those fields, so the runtime stays tiny and a learned or
generated-keyframe compiler can later emit the same data.

Models (all deterministic, no learning):
  * head yaw / pitch   cylinder dome over the face plane: facial features move a lot, the outline little,
                       hair/ears/neck follow with parallax weights
  * head roll          rotation about the neck pivot
  * eyes               no closed-eye art is generated: the lash line travels to a closing curve, the eye white
                       and iris collapse onto it (iris is clipped by the eye white at render time)
  * gaze / brows       translations (iris clipped to the eye white)
  * mouth              a template open-mouth overlay (the decomposition gives no open-mouth art) -> "degraded"
  * body               sway (shear above the hips), roll about the hips, breathing
  * hair / tail        bend fields driven by a small physics model in the runtime
"""
from __future__ import annotations

import json
import math
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from .layers import Layer, by_tag
from .mesh import build_mesh
from .qa import run_qa
from .spec import RigSpec

DRAW_ORDER = {
    "wings": 8, "back hair": 10, "tail": 14, "objects": 18, "footwear": 30, "legwear": 40, "bottomwear": 50,
    "neck": 52, "topwear": 60, "handwear": 66, "neckwear": 68, "ears": 100, "face": 110, "eyewhite": 120,
    "irides": 124, "eyelash": 128, "eyebrow": 132, "nose": 136, "mouth": 140, "mouth_overlay": 142,
    "eyewear": 150, "earwear": 152, "front hair": 160, "headwear": 170,
}
FACE_PLANE = {"face", "eyewhite", "irides", "eyelash", "eyebrow", "nose", "mouth", "mouth_overlay", "eyewear"}
HEAD_GROUP = FACE_PLANE | {"ears", "earwear", "headwear", "front hair", "back hair"}
UPPER_BODY = {"topwear", "neckwear", "handwear", "neck"}

PARAMS = {  # id -> (name, min, max, default)
    "ParamAngleX": ("Head yaw", -30, 30, 0), "ParamAngleY": ("Head pitch", -30, 30, 0),
    "ParamAngleZ": ("Head roll", -30, 30, 0), "ParamBodyAngleX": ("Body sway", -10, 10, 0),
    "ParamBodyAngleZ": ("Body roll", -10, 10, 0), "ParamBreath": ("Breath", 0, 1, 0),
    "ParamEyeLOpen": ("Eye L open", 0, 1, 1), "ParamEyeROpen": ("Eye R open", 0, 1, 1),
    "ParamEyeBallX": ("Gaze X", -1, 1, 0), "ParamEyeBallY": ("Gaze Y", -1, 1, 0),
    "ParamBrowLY": ("Brow L", -1, 1, 0), "ParamBrowRY": ("Brow R", -1, 1, 0),
    "ParamMouthOpenY": ("Mouth open", 0, 1, 0),
    "ParamHairFront": ("Hair front sway", -1, 1, 0), "ParamHairBack": ("Hair back sway", -1, 1, 0),
    "ParamTailSway": ("Tail sway", -1, 1, 0),
}
# Note on sides: "l"/"r" are the viewer's (screen) left/right.  ParamEyeLOpen drives the screen-left eye.
# Whether Cubism's "L" means the same is NOT verified; it only matters for a future .moc3 exporter.


def _smooth(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


class Rig:
    """Collects meshes while the compiler walks the layer set."""

    def __init__(self, layers: List[Layer], spec: RigSpec):
        self.layers = layers
        self.spec = spec
        self.tags = by_tag(layers)
        self.meshes: List[dict] = []
        self.used_params: set = set()
        self.cap: Dict[str, str] = {}
        self.notes: List[str] = []
        self._mesh_cache: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self.tri_weights: Dict[str, np.ndarray] = {}   # mesh id -> visible (opaque) pixel count per triangle
        self._anchors()

    # ---------------------------------------------------------------- anchors
    def one(self, tag: str, side: Optional[str] = None) -> Optional[Layer]:
        for l in self.tags.get(tag, []):
            if side is None or l.side == side:
                return l
        return None

    def _anchors(self):
        face = self.one("face")
        allb = np.array([l.canvas_bbox() for l in self.layers])
        self.bounds = (float(allb[:, 0].min()), float(allb[:, 1].min()), float(allb[:, 2].max()), float(allb[:, 3].max()))
        if face is None:  # fall back to the hair/ears envelope
            head = [l for l in self.layers if l.tag in ("front hair", "ears", "eyewhite", "headwear")]
            if not head:
                raise ValueError("no face found: cannot build a head rig")
            hb = np.array([l.canvas_bbox() for l in head])
            fb = (hb[:, 0].min(), hb[:, 1].min(), hb[:, 2].max(), hb[:, 3].max())
            self.notes.append("no face layer: head box estimated from other parts")
        else:
            fb = face.canvas_bbox()
        self.face_bbox = fb
        self.fcx, self.fcy = (fb[0] + fb[2]) / 2, (fb[1] + fb[3]) / 2
        self.fw, self.fh = fb[2] - fb[0], fb[3] - fb[1]
        self.Rx, self.Ry = 0.56 * self.fw, 0.58 * self.fh
        neck = self.one("neck")
        self.neck_pivot = ((neck.canvas_bbox()[0] + neck.canvas_bbox()[2]) / 2, neck.canvas_bbox()[1] + 0.25 * (neck.canvas_bbox()[3] - neck.canvas_bbox()[1])) if neck else (self.fcx, fb[3])
        bw = self.one("bottomwear")
        tw = self.one("topwear")
        if bw:
            b = bw.canvas_bbox()
            self.hip = ((b[0] + b[2]) / 2, b[1] + 0.15 * (b[3] - b[1]))
        elif tw:
            b = tw.canvas_bbox()
            self.hip = ((b[0] + b[2]) / 2, b[3])
        else:
            self.hip = (self.fcx, fb[3] + 2.5 * self.fh)
        self.body_h = max(self.bounds[3] - self.neck_pivot[1], 3 * self.fh)
        self.has_body = bool(tw or bw or self.tags.get("legwear"))

    # ---------------------------------------------------------------- mesh plumbing
    def mesh_for(self, l: Layer, density: float = 1.0):
        key = l.name
        if key not in self._mesh_cache:
            self._mesh_cache[key] = build_mesh(l, density=density)
        pos_px, tri, counts = self._mesh_cache[key]
        self.tri_weights[l.name] = counts
        return pos_px, tri, l.to_canvas(pos_px)

    def add_mesh(self, mid: str, tag: str, l: Layer, P: np.ndarray, pos_px: np.ndarray, tri: np.ndarray,
                 deform: List[dict], clip: Optional[str] = None, texture: Optional[str] = None) -> dict:
        h, w = l.rgba.shape[:2]
        m = {
            "id": mid, "tag": tag, "texture": texture or f"tex/{mid}.png", "texSize": [int(w), int(h)],
            "order": DRAW_ORDER.get(tag, 100),
            "positions": [round(float(v), 2) for v in P.reshape(-1)],
            "uvs": [round(float(v), 4) for v in np.stack([pos_px[:, 0] / w, pos_px[:, 1] / h], 1).reshape(-1)],
            "indices": [int(v) for v in tri.reshape(-1)],
            "deform": [d for d in deform if d],
        }
        if clip:
            m["clip"] = clip
        for d in m["deform"]:
            self.used_params.add(d["param"])
        self.meshes.append(m)
        return m

    # ---------------------------------------------------------------- deformation primitives
    @staticmethod
    def field(param: str, keys: List[float], fields: List[Optional[np.ndarray]]) -> Optional[dict]:
        out = []
        any_nz = False
        for f in fields:
            if f is None or not np.any(np.abs(f) > 0.004):
                out.append(None)
            else:
                any_nz = True
                out.append([round(float(v), 2) for v in f.reshape(-1)])
        if not any_nz:
            return None
        return {"param": param, "keys": keys, "fields": out}

    @staticmethod
    def rotate(param: str, pivot, deg_per_unit: float) -> dict:
        return {"param": param, "kind": "rotate", "pivot": [round(float(pivot[0]), 2), round(float(pivot[1]), 2)],
                "degPerUnit": round(float(deg_per_unit), 4)}

    def head_yaw_pitch(self, tag: str, P: np.ndarray, w_int: Optional[np.ndarray] = None) -> List[dict]:
        """Cylinder-dome yaw/pitch for one mesh; returns two field entries.

        Facial features follow the cylinder fully.  The skin layer is damped by ``1 - |u|^3`` so its outline stays
        put while the interior (blush, shading) slides with the features; the falloff keeps the displacement
        gradient below 1, i.e. no triangle folds.
        """
        hr = self.spec.head_range
        thx_max, thy_max = math.radians(24.0 * hr), math.radians(16.0 * hr)
        out = []
        for param, kmax, th_max in (("ParamAngleX", 30.0, thx_max), ("ParamAngleY", 30.0, thy_max)):
            fields = []
            for sign in (-1.0, 1.0):
                th = sign * th_max
                D = np.zeros_like(P)
                if param == "ParamAngleX":
                    if tag in FACE_PLANE:
                        u = np.clip((P[:, 0] - self.fcx) / self.Rx, -0.97, 0.97)
                        ang = np.clip(np.arcsin(u) + th, -math.radians(86), math.radians(86))
                        dx = self.Rx * (np.sin(ang) - u)
                        D[:, 0] = dx * ((1.0 - np.abs(u) ** 3) if tag == "face" else 1.0)
                    elif tag in ("front hair", "headwear", "earwear"):
                        D[:, 0] = 0.85 * self.Rx * math.sin(th) * self._hair_taper(P)
                    elif tag == "back hair":
                        D[:, 0] = 0.25 * self.Rx * math.sin(th)
                    elif tag == "ears":
                        D[:, 0] = 0.55 * self.Rx * math.sin(th)
                    elif tag == "neck":
                        D[:, 0] = 0.10 * self.Rx * math.sin(th)
                else:
                    if tag in FACE_PLANE:
                        v = np.clip((P[:, 1] - self.fcy) / self.Ry, -0.97, 0.97)
                        ang = np.clip(np.arcsin(v) - th, -math.radians(86), math.radians(86))
                        dy = self.Ry * (np.sin(ang) - v)
                        D[:, 1] = dy * ((1.0 - np.abs(v) ** 3) if tag == "face" else 1.0)
                    elif tag in ("front hair", "headwear", "earwear"):
                        D[:, 1] = -0.8 * self.Ry * math.sin(th) * self._hair_taper(P)
                    elif tag == "back hair":
                        D[:, 1] = -0.2 * self.Ry * math.sin(th)
                    elif tag == "ears":
                        D[:, 1] = -0.9 * self.Ry * math.sin(th)
                fields.append(D)
            f = self.field(param, [-kmax, 0.0, kmax], [fields[0], None, fields[1]])
            if f:
                out.append(f)
        return out

    def _hair_taper(self, P: np.ndarray) -> np.ndarray:
        """1.0 at the eye line and below, falling to 0.3 at the top of the head (the skull outline barely moves)."""
        top = self.face_bbox[1] - 0.15 * self.fh
        t = np.clip((P[:, 1] - top) / max(self.fcy - top, 1.0), 0.0, 1.0)
        return 0.3 + 0.7 * (t * t * (3 - 2 * t))

    def body_entries(self, tag: str, P: np.ndarray) -> List[dict]:
        """Body sway / roll / breath entries shared by head group and upper body."""
        out: List[dict] = []
        if not self.has_body:
            return out
        ny = self.neck_pivot[1]
        hy = self.hip[1]
        span = max(hy - ny, 1.0)
        if tag in HEAD_GROUP or tag in UPPER_BODY:
            if tag in HEAD_GROUP:
                w = np.ones(len(P))
            else:
                w = _smooth((hy - P[:, 1]) / span)
            sway = 0.035 * self.body_h
            Dx = np.zeros_like(P)
            Dx[:, 0] = sway * w
            f = self.field("ParamBodyAngleX", [-10.0, 0.0, 10.0], [-Dx, None, Dx])
            if f:
                out.append(f)
            out.append(self.rotate("ParamBodyAngleZ", self.hip, 0.35))
            Db = np.zeros_like(P)
            Db[:, 1] = -(0.0025 if tag in HEAD_GROUP else 0.006) * self.body_h * (np.ones(len(P)) if tag in HEAD_GROUP else w)
            f = self.field("ParamBreath", [0.0, 1.0], [None, Db])
            if f:
                out.append(f)
        elif tag == "bottomwear":
            w = _smooth((hy + 0.25 * span - P[:, 1]) / (0.25 * span))
            Dx = np.zeros_like(P)
            Dx[:, 0] = 0.035 * self.body_h * 0.3 * w
            f = self.field("ParamBodyAngleX", [-10.0, 0.0, 10.0], [-Dx, None, Dx])
            if f:
                out.append(f)
            out.append(self.rotate("ParamBodyAngleZ", self.hip, 0.18))
        return out

    # ---------------------------------------------------------------- eyes
    def eye_geometry(self, side: str):
        ew = self.one("eyewhite", side)
        if ew is None:
            return None
        x0, y0, x1, y1 = ew.canvas_bbox()
        return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "w": x1 - x0, "h": y1 - y0}

    @staticmethod
    def _y_close(geo, x):
        t = np.clip((x - geo["x0"]) / max(geo["w"], 1e-6), 0.0, 1.0)
        base = geo["y1"] - 0.10 * geo["h"]
        return base + 0.08 * geo["h"] * (1.0 - (2 * t - 1) ** 2)

    @staticmethod
    def _top_profile(l: Layer):
        """Upper edge y(x) of a layer in canvas coords, smoothed so thin tails do not make it jump."""
        a = l.alpha_mask()
        cols = np.where(a.any(axis=0))[0]
        if len(cols) == 0:
            return lambda x: np.full_like(x, l.origin[1])
        first = np.argmax(a, axis=0).astype(np.float64)
        xs = (np.arange(a.shape[1]) + 0.5) * l.scale + l.origin[0]
        ys = first * l.scale + l.origin[1]
        xv, yv = xs[cols], ys[cols]
        k = max(3, int(0.14 * len(yv))) | 1  # odd window, ~14% of the width
        pad = np.pad(yv, (k // 2, k // 2), mode="edge")
        yv = np.convolve(pad, np.ones(k) / k, mode="valid")
        return lambda x: np.interp(x, xv, yv)

    # ---------------------------------------------------------------- build everything
    def build(self):
        spec = self.spec
        # eyes ----------------------------------------------------------------------
        eye_geo = {s: self.eye_geometry(s) for s in ("l", "r")}
        unsplit_eye = self.one("eyewhite") is not None and not any(eye_geo.values())
        for l in self.layers:
            tag = l.tag
            pos_px, tri, P = self.mesh_for(l, density=1.3 if tag in ("eyewhite", "irides", "eyelash", "eyebrow", "mouth", "nose") else 1.0)
            deform: List[dict] = []
            clip = None
            if tag in HEAD_GROUP:
                deform += self.head_yaw_pitch(tag, P)

            side = l.side if l.side in ("l", "r") else None
            geo = eye_geo.get(side) if side else None
            open_param = {"l": "ParamEyeLOpen", "r": "ParamEyeROpen"}.get(side or "", "ParamEyeLOpen")
            if tag in ("eyewhite", "irides") and (geo or unsplit_eye):
                g = geo or {"x0": P[:, 0].min(), "y0": P[:, 1].min(), "x1": P[:, 0].max(), "y1": P[:, 1].max(),
                            "w": np.ptp(P[:, 0]), "h": np.ptp(P[:, 1])}
                D = np.zeros_like(P)
                # collapse slightly BELOW the lash line so the remaining sliver hides under the lash body
                D[:, 1] = 0.99 * (self._y_close(g, P[:, 0]) + 0.06 * g["h"] - P[:, 1])
                deform.append(self.field(open_param, [0.0, 1.0], [D, None]))
                if tag == "irides":
                    G = np.zeros_like(P)
                    G[:, 0] = 0.22 * g["w"]
                    GY = np.zeros_like(P)
                    GY[:, 1] = 0.16 * g["h"]
                    deform.append(self.field("ParamEyeBallX", [-1.0, 0.0, 1.0], [-G, None, G]))
                    deform.append(self.field("ParamEyeBallY", [-1.0, 0.0, 1.0], [GY, None, -GY]))  # +1 = look up (y down on screen)
                    ew = self.one("eyewhite", side)
                    if ew is not None:
                        clip = f"eyewhite_{side}" if side else "eyewhite"
            elif tag == "eyelash" and (geo or unsplit_eye):
                g = geo or {"x0": P[:, 0].min(), "y0": P[:, 1].min(), "x1": P[:, 0].max(), "y1": P[:, 1].max(),
                            "w": np.ptp(P[:, 0]), "h": np.ptp(P[:, 1])}
                ytop = self._top_profile(l)(P[:, 0])
                D = np.zeros_like(P)
                D[:, 1] = (self._y_close(g, P[:, 0]) - ytop) - 0.25 * (P[:, 1] - ytop)
                deform.append(self.field(open_param, [0.0, 1.0], [D, None]))
            elif tag == "eyebrow":
                g = geo
                hgt = g["h"] if g else 0.06 * self.fh
                bp = {"l": "ParamBrowLY", "r": "ParamBrowRY"}.get(side or "", "ParamBrowLY")
                up = np.zeros_like(P)
                up[:, 1] = -0.45 * hgt
                dn = np.zeros_like(P)
                dn[:, 1] = 0.30 * hgt
                deform.append(self.field(bp, [-1.0, 0.0, 1.0], [dn, None, up]))
            elif tag == "back hair" or tag == "front hair":
                x0, y0, x1, y1 = l.canvas_bbox()
                root = y0 if tag == "front hair" else min(y0 + 0.15 * (y1 - y0), self.face_bbox[1] + 0.3 * self.fh)
                length = max(y1 - root, 1.0)
                t = np.clip((P[:, 1] - root) / length, 0.0, 1.0)
                amp = (0.12 if tag == "front hair" else 0.10) * length
                D = np.zeros_like(P)
                D[:, 0] = amp * t ** 1.6
                pname = "ParamHairFront" if tag == "front hair" else "ParamHairBack"
                deform.append(self.field(pname, [-1.0, 0.0, 1.0], [-D, None, D]))
            elif tag == "tail":
                body_c = np.array([self.fcx, (self.neck_pivot[1] + self.hip[1]) / 2])
                x0, y0, x1, y1 = l.canvas_bbox()
                pts = P
                root = pts[np.argmin(np.linalg.norm(pts - body_c, axis=1))]
                tip = pts[np.argmax(np.linalg.norm(pts - root, axis=1))]
                axis = tip - root
                L = max(np.linalg.norm(axis), 1.0)
                axis /= L
                perp = np.array([-axis[1], axis[0]])
                t = np.clip(((pts - root) @ axis) / L, 0.0, 1.0)
                D = (0.28 * L * (t ** 1.5))[:, None] * perp[None, :]
                deform.append(self.field("ParamTailSway", [-1.0, 0.0, 1.0], [-D, None, D]))

            if tag in HEAD_GROUP:
                deform.append(self.rotate("ParamAngleZ", self.neck_pivot, 0.45 * spec.head_range * (0.55 if tag == "back hair" else 1.0)))
            deform += self.body_entries(tag, P)
            self.add_mesh(l.name, tag, l, P, pos_px, tri, deform, clip=clip)

        self._mouth_overlay()
        self._capabilities(eye_geo, unsplit_eye)

    # ---------------------------------------------------------------- mouth overlay (template, degraded)
    def _mouth_overlay(self):
        mouth = self.one("mouth")
        if mouth is None:
            return
        x0, y0, x1, y1 = mouth.canvas_bbox()
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w = max(x1 - x0, 0.26 * self.fw)
        w = min(w, 0.42 * self.fw)
        hmax = min(0.62 * w, 0.20 * self.fh)
        # texture: dark mouth interior with a tongue, antialiased by supersampling
        ss, tw, th = 4, 64, 48
        img = np.zeros((th * ss, tw * ss, 4), np.uint8)
        dark = np.array(self._lip_dark(mouth)) * 0.35 + np.array([60, 14, 22]) * 0.65
        cv2.ellipse(img, (tw * ss // 2, int(th * ss * 0.40)), (int(tw * ss * 0.46), int(th * ss * 0.38)), 0, 0, 360, (*[int(c) for c in dark], 255), -1, cv2.LINE_AA)
        cv2.ellipse(img, (tw * ss // 2, int(th * ss * 0.60)), (int(tw * ss * 0.30), int(th * ss * 0.20)), 0, 0, 360, (210, 96, 110, 255), -1, cv2.LINE_AA)
        # keep the tongue inside the mouth
        inner = np.zeros(img.shape[:2], np.uint8)
        cv2.ellipse(inner, (tw * ss // 2, int(th * ss * 0.40)), (int(tw * ss * 0.46), int(th * ss * 0.38)), 0, 0, 360, 255, -1, cv2.LINE_AA)
        img[..., 3] = np.minimum(img[..., 3], inner)
        tex = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
        tex_layer = Layer(name="mouth_overlay", tag="mouth_overlay", rgba=tex, origin=(cx - w / 2, cy - hmax * 0.12), scale=1.0)
        self._overlay_tex = tex
        # grid mesh: 5 columns x 4 rows over the overlay box (box height = hmax)
        cols, rows = 5, 4
        gx = np.linspace(cx - w / 2, cx + w / 2, cols)
        gy = np.linspace(cy - hmax * 0.12, cy - hmax * 0.12 + hmax, rows)
        P = np.array([[x, y] for y in gy for x in gx])
        uv = np.array([[(i / (cols - 1)) * tw, (j / (rows - 1)) * th] for j in range(rows) for i in range(cols)])
        tri = []
        for j in range(rows - 1):
            for i in range(cols - 1):
                a = j * cols + i
                tri += [[a, a + 1, a + cols], [a + 1, a + cols + 1, a + cols]]
        tri = np.array(tri, dtype=np.int32)
        # at rest the box collapses to a line at the mouth centre; OpenY opens it downward/outward
        base = P.copy()
        base[:, 1] = cy + (P[:, 1] - cy) * 0.02
        D = P - base  # field that opens the mouth (key 1)
        deform = list(self.head_yaw_pitch("mouth_overlay", base, None))
        deform.append(self.field("ParamMouthOpenY", [0.0, 1.0], [None, D]))
        deform.append(self.rotate("ParamAngleZ", self.neck_pivot, 0.45 * self.spec.head_range))
        deform += self.body_entries("mouth_overlay", base)
        self.tri_weights["mouth_overlay"] = np.ones(len(tri), dtype=np.int64)
        m = self.add_mesh("mouth_overlay", "mouth_overlay", tex_layer, base, uv, tri, deform)
        m["opacityBind"] = {"param": "ParamMouthOpenY", "keys": [0.0, 0.05, 1.0], "values": [0.0, 1.0, 1.0]}
        self._extra_textures = {"mouth_overlay": tex}

    @staticmethod
    def _lip_dark(mouth: Layer):
        a = mouth.rgba
        m = a[..., 3] >= 100
        if m.sum() == 0:
            return (120, 40, 50)
        px = a[..., :3][m].astype(np.float64)
        lum = px.sum(axis=1)
        return tuple(int(v) for v in px[np.argsort(lum)[: max(1, len(lum) // 4)]].mean(axis=0))

    # ---------------------------------------------------------------- capability report
    def _capabilities(self, eye_geo, unsplit_eye):
        c = self.cap
        c["layers"] = f"{len(self.layers)} layers"
        c["head_yaw_pitch"] = "ok" if self.one("face") else "degraded: no face layer, head box estimated"
        c["head_roll"] = "ok"
        have_eyes = any(eye_geo.values())
        if have_eyes and self.one("eyelash", "l") and self.one("eyelash", "r"):
            c["blink"] = "degraded: no closed-eye art; lashes close onto a curve, eye white/iris collapse"
        elif have_eyes or unsplit_eye:
            c["blink"] = "degraded: eye white collapses, no lash line" if not unsplit_eye else "degraded: eyes not separable, both blink together"
        else:
            c["blink"] = "unavailable: no eye layers found"
        c["gaze"] = "ok" if self.one("irides") and self.one("eyewhite") else "unavailable: no iris/eye-white pair"
        c["brows"] = "ok" if self.one("eyebrow") else "unavailable: no eyebrow layer"
        c["mouth_open"] = "degraded: template mouth overlay (no generated open-mouth art)" if self.one("mouth") else "unavailable: no mouth layer"
        c["lipsync"] = "degraded: open/close only (no vowel shapes)" if self.one("mouth") else "unavailable"
        c["hair_physics"] = "ok" if (self.one("front hair") or self.one("back hair")) and self.spec.hair_strength > 0 else ("off by prompt" if self.spec.hair_strength == 0 else "unavailable: no hair layer")
        c["body"] = "ok" if self.has_body else "unavailable: no body layers"
        c["tail"] = "ok" if self.one("tail") else "absent"
        c["mouth_shapes_aiueo"] = "unavailable: no generated vowel shapes yet"
        c["closed_eye_art"] = "unavailable: not generated yet"


def _physics(rig: Rig) -> List[dict]:
    s = rig.spec.hair_strength
    out = []
    if s <= 0:
        return out
    if rig.one("front hair"):
        out.append({"out": "ParamHairFront", "in": [["ParamAngleX", 1 / 30 * 0.9], ["ParamAngleZ", 1 / 30 * 0.5], ["ParamBodyAngleX", 1 / 10 * 0.6]],
                    "freq": 1.25, "damping": 0.30, "gain": 3.0 * s, "limit": 1.0})
    if rig.one("back hair"):
        out.append({"out": "ParamHairBack", "in": [["ParamAngleX", 1 / 30 * 0.9], ["ParamAngleZ", 1 / 30 * 0.6], ["ParamBodyAngleX", 1 / 10 * 0.8]],
                    "freq": 0.95, "damping": 0.26, "gain": 3.4 * s, "limit": 1.0})
    if rig.one("tail"):
        out.append({"out": "ParamTailSway", "in": [["ParamBodyAngleX", 1 / 10 * 1.0], ["ParamAngleX", 1 / 30 * 0.3]],
                    "freq": 0.8, "damping": 0.22, "gain": 3.6 * s, "limit": 1.0, "wind": 0.18 * s})
    return out


def _motions(rig: Rig) -> dict:
    k = rig.spec.motion_intensity
    tracks = []
    if rig.spec.idle:
        tracks = [
            {"param": "ParamAngleX", "amp": 3.2 * k, "period": 6.4, "phase": 0.0},
            {"param": "ParamAngleY", "amp": 1.8 * k, "period": 5.1, "phase": 1.3},
            {"param": "ParamAngleZ", "amp": 1.6 * k, "period": 7.7, "phase": 2.1},
            {"param": "ParamBodyAngleX", "amp": 1.2 * k, "period": 6.4, "phase": 0.6},
            {"param": "ParamBodyAngleZ", "amp": 0.9 * k, "period": 8.3, "phase": 1.7},
            {"param": "ParamBreath", "amp": 0.5, "period": 3.6, "phase": 0.0, "offset": 0.5},
        ]
    return {
        "idle": {"tracks": tracks, "saccade": rig.spec.idle},
        "blink": {"enabled": bool(rig.spec.blink), "intervalMin": 2.4, "intervalMax": 6.0, "duration": 0.20,
                  "doubleBlinkProb": 0.15, "params": ["ParamEyeLOpen", "ParamEyeROpen"]},
    }


def compile_puppet(layers: List[Layer], spec: Optional[RigSpec] = None, out_dir: Optional[str] = None,
                   source_name: str = "") -> Tuple[dict, dict]:
    """Compile layers into (puppet, report).  With ``out_dir`` also writes puppet.json and textures."""
    spec = spec or RigSpec()
    rig = Rig(layers, spec)
    rig.build()

    params = []
    for pid, (name, lo, hi, df) in PARAMS.items():
        if pid in rig.used_params:
            params.append({"id": pid, "name": name, "min": lo, "max": hi, "default": df})
    # physics-driven params are real params too (shown as read-only in the UI)
    physics = _physics(rig)
    drivers = {p["out"] for p in physics}
    for p in params:
        p["driven"] = p["id"] in drivers

    hb = rig.face_bbox
    pad = 0.55 * max(rig.fw, rig.fh)
    puppet = {
        "schema": "img2live-puppet/1",
        "canvas": {"w": int(max(l.canvas_bbox()[2] for l in layers)) + 1, "h": int(max(l.canvas_bbox()[3] for l in layers)) + 1},
        "bounds": [round(v, 1) for v in rig.bounds],
        "headBounds": [round(hb[0] - pad, 1), round(hb[1] - pad * 0.9, 1), round(hb[2] + pad, 1), round(hb[3] + pad * 0.9, 1)],
        "params": params,
        "meshes": sorted(rig.meshes, key=lambda m: m["order"]),
        "physics": physics,
        "motions": _motions(rig),
        "groups": {"EyeBlink": [p for p in ("ParamEyeLOpen", "ParamEyeROpen") if p in rig.used_params],
                   "LipSync": ["ParamMouthOpenY"] if "ParamMouthOpenY" in rig.used_params else []},
        "meta": {"generator": "img2live", "ai_generated": True, "side_convention": "l/r = screen left/right",
                 "capability": rig.cap, "rigSpec": spec.to_dict()},
    }

    report = {"capability": rig.cap, "notes": rig.notes, "rigSpec": spec.to_dict(),
              "stats": {"meshes": len(rig.meshes), "vertices": int(sum(len(m["positions"]) // 2 for m in rig.meshes)),
                        "triangles": int(sum(len(m["indices"]) // 3 for m in rig.meshes)),
                        "params": [p["id"] for p in params]}}
    report["qa"] = run_qa(puppet, weights=rig.tri_weights)

    if out_dir:
        os.makedirs(os.path.join(out_dir, "tex"), exist_ok=True)
        by_name = {l.name: l for l in layers}
        for m in puppet["meshes"]:
            if m["id"] == "mouth_overlay":
                Image.fromarray(rig._extra_textures["mouth_overlay"], "RGBA").save(os.path.join(out_dir, m["texture"]))
            else:
                Image.fromarray(by_name[m["id"]].rgba, "RGBA").save(os.path.join(out_dir, m["texture"]), compress_level=6)
        with open(os.path.join(out_dir, "puppet.json"), "w", encoding="utf8") as f:
            json.dump(puppet, f, separators=(",", ":"))
        with open(os.path.join(out_dir, "report.json"), "w", encoding="utf8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return puppet, report
