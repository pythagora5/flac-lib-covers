"""Image inspection and conversion to an Eversolo-friendly cover.jpg."""

from __future__ import annotations

import errno
import io
import os

from PIL import Image, ImageFile, ImageOps

from .models import ImageInfo

ImageFile.LOAD_TRUNCATED_IMAGES = False
Image.MAX_IMAGE_PIXELS = 80_000_000  # guard against decompression bombs


def inspect(path: str, size_bytes: int | None = None) -> ImageInfo:
    """Read only the image header (fast: no pixel decoding)."""
    if size_bytes is None:
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            size_bytes = 0
    info = ImageInfo(path=path, size_bytes=size_bytes)
    try:
        with Image.open(path) as im:
            info.width, info.height = im.size
            info.fmt = im.format or ""
            info.progressive = bool(im.info.get("progressive") or im.info.get("progression"))
    except OSError as exc:
        if exc.errno is not None and exc.errno != errno.ENOENT:
            # A system error (too many open files, drive unplugged, I/O error)
            # says nothing about the image; never report it as damaged.
            raise
        info.readable = False  # Pillow decode errors have no errno
    except Exception:
        info.readable = False
    return info


def probe_bytes(data: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return (0, 0)


def to_cover_jpeg(data: bytes, target: int, quality: int, max_kb: int) -> bytes:
    """Convert any image to a square-ish, baseline (non-progressive) sRGB JPEG.

    * no upscaling; images larger than ``target`` are shrunk to ``target``
    * near-square images (within 3%) are centre-cropped to exactly square
    * transparency is flattened onto white
    * metadata is stripped (some streamers choke on large EXIF/ICC blocks)
    """
    with Image.open(io.BytesIO(data)) as src:
        src.load()
        im = ImageOps.exif_transpose(src)

    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")

    w, h = im.size
    if w != h and abs(w - h) <= 0.03 * max(w, h):
        side = min(w, h)
        left, top = (w - side) // 2, (h - side) // 2
        im = im.crop((left, top, left + side, top + side))

    if max(im.size) > target:
        im.thumbnail((target, target), Image.LANCZOS)

    q = quality
    while True:
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True, progressive=False)
        out = buf.getvalue()
        if len(out) <= max_kb * 1024 or q <= 60:
            return out
        q -= 5
