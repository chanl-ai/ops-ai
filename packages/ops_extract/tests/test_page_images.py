"""Page images, by failure mode: a page drawn at full resolution whatever its size, so one poster-sized page in an
uploaded PDF or one huge image, asked for by any viewer, exhausts the service's memory."""

from __future__ import annotations

import io

import pytest
from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from ops_extract import page_images
from ops_ingest.reading import MAX_RENDER_PIXELS


def _pdf(width_pt: float, height_pt: float) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(width_pt, height_pt))
    c.drawString(72, 72, "Site plan, sheet 1")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_a_poster_sized_page_is_drawn_within_the_pixel_limit() -> None:
    # 48 x 48 inches: 7,200 x 7,200 pixels at 150 dpi, three times the limit.
    image = page_images.render(_pdf(3456, 3456), "application/pdf", [1])[1]
    width, height = image.size
    assert width * height <= MAX_RENDER_PIXELS, image.size


def test_a_letter_page_keeps_its_resolution() -> None:
    image = page_images.render(_pdf(612, 792), "application/pdf", [1])[1]
    assert image.size[0] == 1275, image.size  # 8.5 inches at 150 dpi


def test_an_image_past_the_readers_pixel_limit_is_not_decoded() -> None:
    buf = io.BytesIO()
    Image.new("1", (8000, 7000)).save(buf, format="PNG")  # 56 million pixels, a few kilobytes as a file
    assert page_images.render(buf.getvalue(), "image/png", [1]) == {}


def test_an_image_past_pillows_own_limit_is_refused_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pillow refuses a frame over twice its limit as it opens it, before the reader's limit is read: a 404, not a 500.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1_000_000)
    buf = io.BytesIO()
    Image.new("1", (2000, 1500)).save(buf, format="PNG")
    assert page_images.render(buf.getvalue(), "image/png", [1]) == {}
