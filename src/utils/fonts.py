"""Cross-platform fonts for Pillow-rendered charts and exports."""

from __future__ import annotations

from PIL import ImageFont


def load_image_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Load an Arial-compatible font at the requested size on macOS/Linux/Windows."""
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow versions before scalable default-font support.
        return ImageFont.load_default()
