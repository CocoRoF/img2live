import numpy as np

from img2live.engine.matting import cutout_plain_background


def _disc_on(bg, size=200, hole=True):
    yy, xx = np.mgrid[:size, :size]
    img = np.zeros((size, size, 4), np.uint8)
    img[..., :3] = bg
    img[..., 3] = 255
    disc = (yy - 100) ** 2 + (xx - 100) ** 2 < 60 ** 2
    img[disc, :3] = (200, 120, 90)
    if hole:  # a pocket of background colour enclosed by the figure (e.g. between an arm and the body)
        pocket = (yy - 100) ** 2 + (xx - 100) ** 2 < 12 ** 2
        img[pocket, :3] = bg
    return img, disc


def test_flat_background_becomes_transparent_and_enclosed_pockets_stay():
    for bg in ((0, 0, 0), (249, 223, 217), (255, 255, 255)):
        img, disc = _disc_on(bg)
        out, info = cutout_plain_background(img)
        assert info["applied"], (bg, info)
        a = out[..., 3]
        assert a[0, 0] == 0 and a[-1, -1] == 0                     # the background is gone
        assert a[100, 60] == 255 and a[100, 150] > 200              # the figure stays
        assert a[100, 100] == 255                                   # the enclosed pocket is kept (not connected to the border)
        assert (out[..., :3][disc & (a > 0)] == img[..., :3][disc & (a > 0)]).all()  # colours are untouched


def test_untouched_when_the_image_already_has_transparency_or_a_busy_background():
    img, _ = _disc_on((0, 0, 0))
    img[:80, :, 3] = 0
    out, info = cutout_plain_background(img)
    assert not info["applied"] and (out == img).all()

    rng = np.random.default_rng(0)
    busy = rng.integers(0, 255, (200, 200, 4), dtype=np.uint8)
    busy[..., 3] = 255
    out, info = cutout_plain_background(busy)
    assert not info["applied"] and (out == busy).all()
