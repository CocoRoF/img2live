"""Reference evaluator for the puppet format (the browser runtime must match this).

Vertex position of a mesh = base positions + sum of keyform fields, then ordered rotations:

    positions = base
    for d in mesh["deform"]:
        if d has "fields":   positions += interp(d.keys, d.fields, params[d.param])   # piecewise linear, clamped
        elif d.kind == "rotate": rotate positions about d.pivot by d.degPerUnit * params[d.param] degrees (clockwise on screen)
        elif d.kind == "shift":  positions += d.perUnit * params[d.param]
"""
from __future__ import annotations

import math
from typing import Dict

import numpy as np


def interp_field(keys, fields, value: float, n: int) -> np.ndarray:
    """fields[i] is None (zeros) or a flat [x0,y0,x1,y1,...] list/array aligned with keys[i]."""
    if value <= keys[0]:
        f = fields[0]
        return np.zeros((n, 2)) if f is None else np.asarray(f, dtype=np.float64).reshape(-1, 2)
    if value >= keys[-1]:
        f = fields[-1]
        return np.zeros((n, 2)) if f is None else np.asarray(f, dtype=np.float64).reshape(-1, 2)
    for i in range(len(keys) - 1):
        if keys[i] <= value <= keys[i + 1]:
            t = (value - keys[i]) / (keys[i + 1] - keys[i])
            a = np.zeros((n, 2)) if fields[i] is None else np.asarray(fields[i], dtype=np.float64).reshape(-1, 2)
            b = np.zeros((n, 2)) if fields[i + 1] is None else np.asarray(fields[i + 1], dtype=np.float64).reshape(-1, 2)
            return a * (1 - t) + b * t
    return np.zeros((n, 2))


def evaluate_mesh(mesh: dict, params: Dict[str, float]) -> np.ndarray:
    pos = np.asarray(mesh["positions"], dtype=np.float64).reshape(-1, 2).copy()
    n = len(pos)
    for d in mesh.get("deform", []):
        v = params.get(d["param"], 0.0)
        if "fields" in d:
            pos += interp_field(d["keys"], d["fields"], v, n)
        elif d.get("kind") == "rotate":
            a = math.radians(d["degPerUnit"] * v)
            c, s = math.cos(a), math.sin(a)
            px, py = d["pivot"]
            x, y = pos[:, 0] - px, pos[:, 1] - py
            pos[:, 0] = px + c * x - s * y
            pos[:, 1] = py + s * x + c * y
        elif d.get("kind") == "shift":
            pos += np.asarray(d["perUnit"], dtype=np.float64) * v
    return pos


def evaluate(puppet: dict, params: Dict[str, float]) -> Dict[str, np.ndarray]:
    full = {p["id"]: p["default"] for p in puppet["params"]}
    full.update(params)
    return {m["id"]: evaluate_mesh(m, full) for m in puppet["meshes"]}


def opacity_of(mesh: dict, params: Dict[str, float]) -> float:
    b = mesh.get("opacityBind")
    if not b:
        return float(mesh.get("opacity", 1.0))
    v = params.get(b["param"], 0.0)
    return float(np.interp(v, b["keys"], b["values"]))
