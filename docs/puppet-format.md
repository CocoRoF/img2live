# img2live puppet format (`img2live-puppet/1`)

Produced by `src/img2live/rig/compile.py`, consumed by the browser runtime (`src/img2live/web/static/js/`).
The Python reference evaluator is `src/img2live/rig/runtime_py.py` — the JS runtime must give the same vertex
positions (this is tested).

All coordinates are **canvas pixels, y down**. Textures live next to `puppet.json` (`tex/<id>.png`, straight
alpha, colour bled into transparent pixels).

```jsonc
{
  "schema": "img2live-puppet/1",
  "canvas":  {"w": 1280, "h": 1280},
  "bounds":      [x0, y0, x1, y1],        // whole character
  "headBounds":  [x0, y0, x1, y1],        // head close-up framing
  "params": [{"id": "ParamAngleX", "name": "Head yaw", "min": -30, "max": 30, "default": 0, "driven": false}],
  "meshes": [{                             // sorted by "order" (draw order, low = behind)
    "id": "eyewhite_l", "tag": "eyewhite", "texture": "tex/eyewhite_l.png", "texSize": [w, h],
    "order": 120,
    "positions": [x0, y0, x1, y1, ...],    // rest pose, canvas px
    "uvs":       [u0, v0, ...],            // 0..1, v down (v = texture row / height)
    "indices":   [a, b, c, ...],
    "clip": "eyewhite_l",                  // optional: draw only where the mesh with this id has alpha > 0.5
    "opacityBind": {"param": "ParamMouthOpenY", "keys": [0, 0.05, 1], "values": [0, 1, 1]},   // optional
    "deform": [                            // ORDERED list, applied top to bottom
      {"param": "ParamAngleX", "keys": [-30, 0, 30], "fields": [[dx0, dy0, ...], null, [dx0, dy0, ...]]},
      {"param": "ParamAngleZ", "kind": "rotate", "pivot": [x, y], "degPerUnit": 0.45},
      {"param": "ParamBreath", "kind": "shift", "perUnit": [dx, dy]}   // optional: uniform translation (not emitted by the compiler yet)
    ]
  }],
  "physics": [{"out": "ParamHairBack", "in": [["ParamAngleX", 0.03]], "freq": 0.95, "damping": 0.26,
               "gain": 3.4, "limit": 1.0, "wind": 0.0}],
  "motions": {
    "idle":  {"tracks": [{"param": "ParamAngleX", "amp": 3.2, "period": 6.4, "phase": 0.0, "offset": 0.0}], "saccade": true},
    "blink": {"enabled": true, "intervalMin": 2.4, "intervalMax": 6.0, "duration": 0.2, "doubleBlinkProb": 0.15,
              "params": ["ParamEyeLOpen", "ParamEyeROpen"]}
  },
  "groups": {"EyeBlink": ["ParamEyeLOpen", "ParamEyeROpen"], "LipSync": ["ParamMouthOpenY"]},
  "meta": {"capability": {"blink": "degraded: ..."}, "rigSpec": {...}, "side_convention": "l/r = screen left/right"}
}
```

## Evaluation (per frame, per mesh)

```
pos = positions                                  # Nx2
for d in deform:
    v = paramValue[d.param]
    if d.fields:                                  # piecewise-linear over d.keys, clamped at both ends
        pos += interp(d.keys, d.fields, v)        # a null field = zeros
    elif d.kind == "rotate":                      # clockwise on screen (y down): x' = c*x - s*y, y' = s*x + c*y
        angle = d.degPerUnit * v  (degrees) about d.pivot
    elif d.kind == "shift":                       # uniform translation
        pos += d.perUnit * v
```
Opacity: `opacityBind` → `np.interp(param, keys, values)`; otherwise the optional static `opacity` (default 1).

## Drawing
* meshes in ascending `order`; texture premultiplied-alpha blending (or straight alpha with `ONE, ONE_MINUS_SRC_ALPHA` after premultiplying in the shader);
* `clip`: render the clip mesh into the stencil buffer (discard texels with alpha < 0.5), then draw this mesh with stencil test EQUAL;
* `opacity` multiplies the fragment alpha.

## Physics (runtime)
For each entry: `u = Σ w_i * param_i` (dimensionless, about ±1). The output param follows a damped second-order
response driven by the *acceleration* of `u` (hair lags and overshoots a head movement, then settles):
`o'' = -(2πf)² o - 2ζ(2πf) o' - gain * u''` , clamp to `±limit`, plus an optional slow wind term
`wind * sin(t * 0.9 + phase)`. Physics outputs are `driven` params: the UI shows them read-only.
(The browser runtime estimates `u''` by finite differences of `u` after a 40 ms low-pass and integrates with fixed
1/120 s sub-steps, so the result does not depend on the frame rate.)

## Idle / blink
Idle tracks: `param = offset + amp * sin(2π t / period + phase)` added to the user's value while idle is on and
the user is not dragging that parameter. Blink: at random intervals ramp `EyeBlink` params 1 → 0 → 1 over
`duration` (ease in/out), double-blink with probability `doubleBlinkProb`. `saccade`: tiny random gaze jumps.

## Parameters
Ids follow the Cubism standard names so a future `.moc3` exporter is mechanical. `l`/`r` in layer names are the
viewer's (screen) left/right; whether Cubism's "L" means the same is **not verified**.
