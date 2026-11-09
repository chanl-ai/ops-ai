"""Page images a read may show the model: a whole page for a page read through OCR, and a crop around one
field for its re-read. The image leaves for the model provider, so the caller decides whether any is sent; this module
only draws them."""

from __future__ import annotations

import base64
import io
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pdfplumber
from PIL import Image, ImageOps

from ops_ingest.reading import MAX_RENDER_PIXELS
from ops_ingest.reading.images import MAX_IMAGE_PIXELS

# The resolution a page is drawn at, and the longest side it is sent at: enough for the model to read small print, a
# fraction of the bytes of the 200 dpi OCR render. Providers scale a larger image down before reading it anyway.
RESOLUTION = 150
MAX_SIDE = 1600
# The most pages one read sends whole; a longer scan's later pages go as text only.
MAX_PAGES = 4
# The margin around a field's box, as fractions of the page: wide enough to take in its label on the line, so the
# model sees which value it is looking at.
CROP_X = 0.12
CROP_Y = 0.02
IMAGE_MIMES = ("image/png", "image/jpeg", "image/tiff", "image/webp")


@dataclass(frozen=True)
class PageImage:
    page: int
    png: bytes

    def part(self) -> dict[str, Any]:
        """The OpenAI chat content part carrying the image, as models-service forwards it."""
        url = "data:image/png;base64," + base64.b64encode(self.png).decode()
        return {"type": "image_url", "image_url": {"url": url}}


def render(data: bytes, mime: str, pages: Iterable[int]) -> dict[int, Image.Image]:
    """The asked pages (1-based) drawn in grey; a page the file lacks is left out, as is an image too large to decode.
    An image file is its own page 1."""
    wanted = sorted(set(pages))
    if mime in IMAGE_MIMES:
        if 1 not in wanted:
            return {}
        # Opening reads only the header, so a frame past the reader's limit is refused before it is decoded; Pillow
        # refuses one past twice its own limit as it opens it.
        try:
            image = Image.open(io.BytesIO(data))
        except Image.DecompressionBombError:
            return {}
        return {} if image.width * image.height > MAX_IMAGE_PIXELS else {1: ImageOps.grayscale(image)}
    out: dict[int, Image.Image] = {}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for n in wanted:
            if 1 <= n <= len(pdf.pages):
                page = pdf.pages[n - 1]
                drawn = page.to_image(resolution=_resolution(float(page.width), float(page.height))).original
                out[n] = ImageOps.grayscale(drawn)
    return out


def _resolution(width_pt: float, height_pt: float) -> int:
    """`RESOLUTION`, or lower for a page so large that it would pass `MAX_RENDER_PIXELS` (the reader's own limit), so
    a poster-sized page cannot exhaust memory; the image is scaled to `MAX_SIDE` afterwards either way."""
    inches = width_pt * height_pt / (72 * 72)
    return math.floor(min(float(RESOLUTION), math.sqrt(MAX_RENDER_PIXELS / inches))) if inches > 0 else RESOLUTION


def whole(page: int, image: Image.Image) -> PageImage:
    return PageImage(page, _png(image))


def crop(page: int, image: Image.Image, boxes: list[dict[str, Any]]) -> PageImage:
    """The part of the page around a field's boxes (`{x, y, w, h}` fractions of the page), with a margin."""
    x0 = max(0.0, min(float(b["x"]) for b in boxes) - CROP_X)
    y0 = max(0.0, min(float(b["y"]) for b in boxes) - CROP_Y)
    x1 = min(1.0, max(float(b["x"]) + float(b["w"]) for b in boxes) + CROP_X)
    y1 = min(1.0, max(float(b["y"]) + float(b["h"]) for b in boxes) + CROP_Y)
    w, h = image.size
    return PageImage(page, _png(image.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))))


def _png(image: Image.Image) -> bytes:
    if max(image.size) > MAX_SIDE:
        image = image.copy()
        image.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
