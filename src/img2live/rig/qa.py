"""Numeric rig QA: evaluate the puppet at extreme / combined poses and look for flipped or crazy triangles.

A triangle is *flipped* when its signed area changes sign relative to the rest pose (the mesh folded over).
Meshes that flip are damped automatically: the keyform fields of the offending parameter are scaled down until
the pose is clean (eye-closing fields are exempt: they collapse by design but never invert).
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Optional

import numpy as np

from .runtime_py import evaluate

FLIP_LIMIT = 0.02  # share of a mesh's visible (opaque) area allowed to flip in any tested pose


def _signed_area(pos: np.ndarray, tri: np.ndarray) -> np.ndarray:
    p = pos[tri]
    return 0.5 * ((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))


def _poses(puppet: dict) -> List[Dict[str, float]]:
    P = {p["id"]: p for p in puppet["params"]}
    driven = {k for k, p in P.items() if p.get("driven")}
    poses: List[Dict[str, float]] = []
    for pid, p in P.items():
        if pid.endswith("Open"):
            poses.append({pid: p["min"]})
        elif p["min"] < 0:
            poses += [{pid: p["min"]}, {pid: p["max"]}]
        else:
            poses.append({pid: p["max"]})

    def have(*ids):
        return all(i in P for i in ids)

    def ext(i):
        return [P[i]["min"], P[i]["max"]] if P[i]["min"] < 0 else [P[i]["max"]]

    combos = [("ParamAngleX", "ParamAngleY"), ("ParamAngleX", "ParamAngleZ"), ("ParamAngleY", "ParamAngleZ"),
              ("ParamAngleX", "ParamBodyAngleX"), ("ParamAngleX", "ParamEyeBallX"), ("ParamAngleX", "ParamHairBack"),
              ("ParamBodyAngleX", "ParamBodyAngleZ"), ("ParamAngleX", "ParamAngleY", "ParamAngleZ")]
    for ids in combos:
        if have(*ids):
            for vals in itertools.product(*[ext(i) for i in ids]):
                poses.append(dict(zip(ids, vals)))
    if have("ParamAngleX", "ParamEyeLOpen"):
        poses.append({"ParamAngleX": 30.0, "ParamEyeLOpen": 0.0, "ParamEyeROpen": 0.0})
    return poses


def _scale_param_fields(mesh: dict, param: str, k: float):
    for d in mesh["deform"]:
        if d["param"] == param and "fields" in d:
            d["fields"] = [None if f is None else [round(v * k, 2) for v in f] for f in d["fields"]]


def run_qa(puppet: dict, fix: bool = True, max_rounds: int = 6, weights: Optional[Dict[str, np.ndarray]] = None) -> dict:
    meshes = puppet["meshes"]
    tris = {m["id"]: np.asarray(m["indices"], dtype=np.int64).reshape(-1, 3) for m in meshes}
    mesh_by_id = {m["id"]: m for m in meshes}
    poses = _poses(puppet)
    rest = evaluate(puppet, {})
    rest_area = {i: _signed_area(rest[i], tris[i]) for i in tris}
    damped: Dict[str, float] = {}

    def scan():
        worst = (0.0, None, None)
        flagged = []
        max_stretch = 0.0
        for pose in poses:
            pos = evaluate(puppet, pose)
            for i, t in tris.items():
                a = _signed_area(pos[i], t)
                a0 = rest_area[i]
                ok = np.abs(a0) > 1e-6
                if not ok.any():
                    continue
                wgt = (weights[i].astype(np.float64) if weights is not None and i in weights else np.ones(len(a0)))[ok]
                tot = float(wgt.sum())
                # flipped = orientation reversed AND not merely collapsed (|area| < 5% of rest is a deliberate
                # collapse such as a closed eye, whose sign is numerical noise)
                flipped = ((a[ok] * a0[ok]) < 0) & (np.abs(a[ok] / a0[ok]) > 0.05)
                frac = float((wgt * flipped).sum() / tot) if tot > 0 else 0.0  # flipped share of VISIBLE area
                if i != "mouth_overlay":  # its opening is a deliberate 50x area change
                    st = np.abs(a[ok] / a0[ok])
                    max_stretch = max(max_stretch, float(np.percentile(st, 99)))
                if frac > FLIP_LIMIT:
                    flagged.append((i, pose, frac))
                if frac > worst[0]:
                    worst = (frac, i, pose)
        return worst, flagged, max_stretch

    worst, flagged, max_stretch = scan()
    rounds = 0
    while fix and flagged and rounds < max_rounds:
        rounds += 1
        for mid, pose, _frac in flagged:
            for param, v in pose.items():
                if param.endswith("Open") or v == 0:
                    continue
                if not any(d["param"] == param and "fields" in d for d in mesh_by_id[mid]["deform"]):
                    continue  # rotations and unrelated params cannot be damped
                key = f"{mid}:{param}"
                _scale_param_fields(mesh_by_id[mid], param, 0.85)
                damped[key] = round(damped.get(key, 1.0) * 0.85, 3)
        worst, flagged, max_stretch = scan()

    return {
        "poses_tested": len(poses),
        "max_flipped_fraction": round(worst[0], 4),
        "worst_mesh": worst[1],
        "worst_pose": worst[2],
        "max_stretch_p99": round(max_stretch, 2),
        "auto_damped": damped,
        "passed": worst[0] <= FLIP_LIMIT,
        "flipped_meshes_remaining": sorted({f[0] for f in flagged}),
    }
