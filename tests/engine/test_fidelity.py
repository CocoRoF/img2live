import numpy as np

from img2live.engine.cleanup import clean_result, decontaminate
from img2live.engine.fake import FakeDecomposer
from img2live.engine.fidelity import refine_canvas, refine_head


def _result():
    res = FakeDecomposer().run(np.zeros((10, 10, 4), np.uint8))
    clean_result(res)
    return res


def test_a_faithful_decomposition_is_left_alone():
    res = _result()
    before = {t: int((a[..., 3] > 16).sum()) for t, a in res.head_hires.items()}
    removed = refine_head(res)
    assert set(removed) == {"nose", "eyelash", "face"}
    assert all(v < 0.05 for v in removed.values()), removed               # the lashes match the source: they stay
    for t, n in before.items():
        assert int((res.head_hires[t][..., 3] > 16).sum()) >= 0.95 * n, t


def test_a_tinted_patch_the_source_does_not_have_is_removed():
    """The real failure: the model's nose layer was a tan patch with a rim on a face whose source has no such thing."""
    res = _result()
    patch = np.zeros_like(res.head_hires["nose"])
    patch[780:900, 590:720] = (150, 125, 115, 235)                        # tan, nearly opaque, on the cheek/nose area
    res.head_hires["nose"] = patch
    removed = refine_head(res)
    assert removed["nose"] > 0.8, removed
    assert int((res.head_hires["nose"][..., 3] > 16).sum()) < 0.2 * 120 * 130


def test_decontaminate_replaces_the_dark_fringe_but_not_thin_strokes():
    n = 80
    yy, xx = np.mgrid[:n, :n]
    r = np.hypot(yy - 40, xx - 40)
    img = np.zeros((n, n, 4), np.uint8)
    img[r < 20] = (205, 160, 140, 255)                                    # skin interior
    ring = (r >= 20) & (r < 24)
    img[ring] = (35, 30, 30, 110)                                         # semi-transparent edge with a dark colour
    img[10:12, 5:30] = (20, 10, 10, 120)                                  # a thin stroke that never becomes opaque
    out = decontaminate(img, reach=6)
    assert (out[..., 3] == img[..., 3]).all()                            # alpha is untouched
    assert np.abs(out[ring][:, :3].astype(int) - np.array([205, 160, 140])).max() < 3
    assert (out[10:12, 5:30] == img[10:12, 5:30]).all()                   # too far from any opaque pixel: keeps its colour


def test_a_band_the_source_does_not_have_is_removed_from_a_body_layer():
    """The real failure: the model's topwear layer carried a cardigan hem drawn right across the jeans."""
    res = _result()
    band = res.layers["topwear"].copy()
    band[640:665, 530:750] = (230, 90, 120, 255)                          # over the skirt: the source shows the skirt there
    res.layers["topwear"] = band
    kept_before = int((res.layers["topwear"][..., 3] > 16).sum())
    removed = refine_canvas(res)
    assert removed["topwear"] > 0.1, removed
    assert int((res.layers["topwear"][640:665, 540:740, 3] > 16).sum()) < 0.1 * 25 * 200   # the band is gone ...
    assert int((res.layers["topwear"][..., 3] > 16).sum()) > 0.6 * (kept_before - 25 * 220)  # ... the real garment stays


def test_a_faithful_body_is_left_alone_by_the_canvas_pass():
    res = _result()
    assert all(v < 0.03 for v in refine_canvas(res).values())
