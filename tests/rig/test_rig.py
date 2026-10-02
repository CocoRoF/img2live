"""Rig compiler tests on the synthetic character (license-clean fixture)."""
import numpy as np

from img2live.engine.fake import FakeDecomposer
from img2live.rig.compile import compile_puppet
from img2live.rig.layers import build_layers
from img2live.rig.runtime_py import evaluate
from img2live.rig.spec import parse_prompt


def _compile(prompt=""):
    r = FakeDecomposer().run(np.zeros((10, 10, 4), np.uint8))
    layers = build_layers(r.layers, r.head_hires, r.head_square)
    return layers, *compile_puppet(layers, parse_prompt(prompt))


def test_pairs_are_split_by_screen_side():
    layers, puppet, report = _compile()
    sides = {l.name: l for l in layers}
    for tag in ("eyewhite", "irides", "eyelash", "eyebrow", "ears"):
        l, r = sides[f"{tag}_l"], sides[f"{tag}_r"]
        assert l.canvas_bbox()[0] < r.canvas_bbox()[0], tag  # l = screen-left
    assert sides["eyewhite_l"].hires and sides["eyewhite_l"].scale < 0.5  # head layers use the high-res pass


def test_qa_passes_and_params_exist():
    _, puppet, report = _compile()
    assert report["qa"]["passed"]
    ids = {p["id"] for p in puppet["params"]}
    assert {"ParamAngleX", "ParamAngleY", "ParamAngleZ", "ParamEyeLOpen", "ParamEyeROpen", "ParamMouthOpenY", "ParamBreath"} <= ids


def test_yaw_moves_features_more_than_outline():
    _, puppet, _ = _compile()
    rest = evaluate(puppet, {})
    turned = evaluate(puppet, {"ParamAngleX": 30})
    d = lambda mid: np.abs(turned[mid] - rest[mid])[:, 0].mean()
    assert d("irides_l") > 3 * d("face") > 0 or d("irides_l") > d("face")
    assert d("irides_l") > d("back_hair")
    # positive yaw turns toward the viewer's right
    assert (turned["irides_l"] - rest["irides_l"])[:, 0].mean() > 0


def test_eye_close_collapses_and_gaze_is_clipped_by_eye_white():
    layers, puppet, _ = _compile()
    rest = evaluate(puppet, {})
    closed = evaluate(puppet, {"ParamEyeLOpen": 0})
    h = lambda p: np.ptp(p[:, 1])
    assert h(closed["eyewhite_l"]) < 0.1 * h(rest["eyewhite_l"])
    assert h(closed["eyewhite_r"]) > 0.9 * h(rest["eyewhite_r"])  # the other eye is untouched (wink works)
    m = {x["id"]: x for x in puppet["meshes"]}
    assert m["irides_l"]["clip"] == "eyewhite_l" and m["irides_r"]["clip"] == "eyewhite_r"


def test_prompt_controls_rig():
    _, puppet, _ = _compile("no hair motion, no blink, static")
    assert puppet["physics"] == [] and puppet["motions"]["blink"]["enabled"] is False and puppet["motions"]["idle"]["tracks"] == []
    _, puppet2, _ = _compile("energetic, windy hair")
    assert puppet2["motions"]["idle"]["tracks"][0]["amp"] > 3.2 and puppet2["physics"][0]["gain"] > 3.0


def test_mouth_overlay_is_hidden_when_closed():
    _, puppet, _ = _compile()
    m = {x["id"]: x for x in puppet["meshes"]}["mouth_overlay"]
    assert m["opacityBind"]["values"][0] == 0.0
