"""Small preview of a finished job (the composite cropped to the character), shared by the API and the worker."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image

THUMB = "thumb.png"


def make_thumb(jdir: Path, size: int = 320) -> Optional[Path]:
    """Create ``thumb.png`` next to ``composite.png`` (cached); None when there is nothing to preview."""
    thumb, comp = jdir / THUMB, jdir / "composite.png"
    if thumb.exists() and (not comp.exists() or thumb.stat().st_mtime >= comp.stat().st_mtime):
        return thumb
    if not comp.exists():
        return None
    im = Image.open(comp).convert("RGBA")
    box = im.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    if box:
        im = im.crop(box)
    im.thumbnail((size, size), Image.LANCZOS)
    tmp = thumb.with_suffix(".tmp.png")
    im.save(tmp, compress_level=6)
    tmp.replace(thumb)
    return thumb
