"""Draw a simple app icon and turn it into assets/AppIcon.icns (macOS only)."""

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "AppIcon.icns"


def draw(size: int) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = size // 10
    d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=size // 6,
                        fill=(32, 36, 48, 255))
    # vinyl record
    c, r = size // 2, int(size * 0.32)
    d.ellipse((c - r, c - r, c + r, c + r), fill=(15, 15, 18, 255))
    for k in (0.85, 0.7, 0.55):
        rr = int(r * k)
        d.ellipse((c - rr, c - rr, c + rr, c + rr), outline=(60, 60, 70, 255),
                  width=max(1, size // 256))
    rl = int(r * 0.35)
    d.ellipse((c - rl, c - rl, c + rl, c + rl), fill=(230, 140, 40, 255))
    rh = max(2, size // 64)
    d.ellipse((c - rh, c - rh, c + rh, c + rh), fill=(32, 36, 48, 255))
    return im


def main() -> int:
    if sys.platform != "darwin" or not shutil.which("iconutil"):
        return 0
    iconset = ROOT / "assets" / "AppIcon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        draw(base).save(iconset / f"icon_{base}x{base}.png")
        draw(base * 2).save(iconset / f"icon_{base}x{base}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT)], check=True)
    shutil.rmtree(iconset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
