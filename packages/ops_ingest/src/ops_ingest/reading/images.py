# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Reading pictures by OCR: image files (PNG, JPEG, TIFF, one page per frame) and the OCR'd parts of PDF pages.

Tesseract's words come back with boxes in the picture's pixels; they are turned into fractions of the page and grouped
into paragraphs by Tesseract's own block and paragraph numbers, each paragraph keeping its lines.
"""

from __future__ import annotations

import io
import statistics
import struct
import time
import warnings

from PIL import Image, UnidentifiedImageError

from ops_ingest.parsers.ocr import OcrUnavailableError, OcrWord, TesseractEngine, WordOcr
from ops_ingest.reading.models import (
    Block,
    Box,
    FileFacts,
    Line,
    OcrQuality,
    Page,
    ReadingError,
    ReadingSettings,
    Word,
    page_text,
)

IMAGE_MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
#: A word Tesseract is less sure of than this counts towards a page's low-confidence share.
LOW_CONFIDENCE = 0.6
OCR_OFF = "no text layer and OCR is off"
NOTHING_FOUND = "no text found, even by OCR"
TOO_LARGE = "the image is too large to read"
UNDECODABLE = "the image could not be decoded"
#: The most pixels one image frame may hold before it is decoded: an A4 page at 600 DPI is about 35 million.
MAX_IMAGE_PIXELS = 50_000_000


class Engines:
    """The OCR engine, made on first use, so a file that needs no OCR reads on a server without Tesseract."""

    def __init__(self, settings: ReadingSettings, engine: WordOcr | None = None) -> None:
        self._settings = settings
        self._engine = engine

    def get(self) -> WordOcr:
        if self._engine is None:
            try:
                self._engine = TesseractEngine(lang=self._settings.language)
            except OcrUnavailableError as exc:
                raise ReadingError("ocr_unavailable", f"OCR not installed: {exc}") from exc
        return self._engine


def ocr_words(engine: WordOcr, picture: Image.Image, region: Box) -> list[tuple[OcrWord, Box]]:
    """Each word Tesseract reads in `picture`, with its box as fractions of the page. `region` is where the picture
    sits on the page, as fractions: `[0, 0, 1, 1]` for a whole page."""
    rx0, ry0, rx1, ry1 = region
    pw, ph = float(picture.width), float(picture.height)
    out: list[tuple[OcrWord, Box]] = []
    for word in engine.image_to_words(picture):
        left, top, width, height = word.box
        box = [
            round(rx0 + left / pw * (rx1 - rx0), 4),
            round(ry0 + top / ph * (ry1 - ry0), 4),
            round(rx0 + (left + width) / pw * (rx1 - rx0), 4),
            round(ry0 + (top + height) / ph * (ry1 - ry0), 4),
        ]
        out.append((word, box))
    return out


def _union(boxes: list[Box]) -> Box:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def ocr_blocks(page: int, words: list[tuple[OcrWord, Box]], *, first_id: int = 0) -> list[Block]:
    """OCR'd words as paragraph blocks, one per Tesseract paragraph, in the order Tesseract read them."""
    paragraphs: dict[tuple[int, int], dict[int, list[tuple[OcrWord, Box]]]] = {}
    for word, box in words:
        block, par, line = word.line
        paragraphs.setdefault((block, par), {}).setdefault(line, []).append((word, box))
    blocks: list[Block] = []
    for lines in paragraphs.values():
        read = [
            Line(text=" ".join(w.text for w, _ in members), box=_union([b for _, b in members]))
            for members in lines.values()
        ]
        boxes = [line.box for line in read if line.box is not None]
        blocks.append(
            Block(
                id=f"p{page}.b{first_id + len(blocks)}",
                kind="paragraph",
                text=" ".join(line.text for line in read),
                box=_union(boxes) if boxes else None,
                lines=read,
                read_by="ocr",
            )
        )
    return blocks


def quality(words: list[tuple[OcrWord, Box]]) -> OcrQuality | None:
    if not words:
        return None
    confidences = [w.confidence for w, _ in words]
    low = sum(1 for c in confidences if c < LOW_CONFIDENCE)
    return OcrQuality(
        mean=round(statistics.fmean(confidences), 3), low_share=round(low / len(confidences), 3), words=len(words)
    )


def as_words(words: list[tuple[OcrWord, Box]]) -> list[Word]:
    return [Word(text=w.text, box=box, confidence=w.confidence) for w, box in words]


def ocr_page(number: int, picture: Image.Image, engine: WordOcr, *, width: float, height: float) -> Page:
    """A whole page read by OCR; a page where OCR finds nothing is listed as unread with the reason."""
    words = ocr_words(engine, picture, [0.0, 0.0, 1.0, 1.0])
    if not words:
        return Page(number=number, width=width, height=height, source="none", unread_reason=NOTHING_FOUND)
    blocks = ocr_blocks(number, words)
    for i, block in enumerate(blocks):
        block.order = i
    return Page(
        number=number,
        width=width,
        height=height,
        source="ocr",
        text=page_text(blocks),
        blocks=blocks,
        words=as_words(words),
        ocr=quality(words),
    )


class ImageFile:
    """A PNG, JPEG or TIFF: each frame one page, read only by OCR.

    Only the header is read when the file is opened. Each frame's size is checked against `MAX_IMAGE_PIXELS` before
    it is decoded, so a small file that claims billions of pixels is refused instead of filling memory, and a frame
    that fails to decode fails its own page with the reason."""

    def __init__(
        self, data: bytes, *, filename: str, mime_type: str, settings: ReadingSettings, engines: Engines
    ) -> None:
        self._settings = settings
        self._engines = engines
        self._image: Image.Image | None = None
        self._refused: str | None = None
        count = 1
        try:
            with warnings.catch_warnings():
                # Pillow warns, then refuses, past its own limit; the size is checked here against ours instead.
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                self._image = Image.open(io.BytesIO(data))
            count = int(getattr(self._image, "n_frames", 1))
        except UnidentifiedImageError as exc:
            raise ReadingError("unreadable_file", f"{filename} is not a readable image: {exc}") from exc
        except Image.DecompressionBombError:
            self._refused = TOO_LARGE
        except (OSError, ValueError, SyntaxError, struct.error) as exc:
            if self._image is None:
                raise ReadingError("unreadable_file", f"{filename} is not a readable image: {exc}") from exc
            self._refused = f"{UNDECODABLE}: {exc}"
        self.facts = FileFacts(filename=filename, mime_type=mime_type, size_bytes=len(data), page_count=max(count, 1))

    def needs_ocr(self, number: int) -> bool:
        del number
        return self._settings.ocr != "off" and self._refused is None

    def page(self, number: int) -> Page:
        started = time.perf_counter()
        page = self._read(number)
        page.duration_ms = round((time.perf_counter() - started) * 1000)
        return page

    def _read(self, number: int) -> Page:
        if self._image is None or self._refused:
            return Page(number=number, source="none", unread_reason=self._refused or TOO_LARGE)
        try:
            self._image.seek(number - 1)
        except (EOFError, OSError, ValueError, struct.error) as exc:
            return Page(number=number, source="none", unread_reason=f"{UNDECODABLE}: {exc}")
        width, height = self._image.size
        if width * height > MAX_IMAGE_PIXELS:
            return Page(
                number=number,
                width=float(width),
                height=float(height),
                source="none",
                unread_reason=f"{TOO_LARGE} ({width} x {height} pixels; the limit is {MAX_IMAGE_PIXELS:,})",
            )
        if self._settings.ocr == "off":
            return Page(number=number, width=float(width), height=float(height), source="none", unread_reason=OCR_OFF)
        try:
            frame = self._image.copy()
        except (OSError, ValueError, SyntaxError, struct.error) as exc:
            return Page(
                number=number,
                width=float(width),
                height=float(height),
                source="none",
                unread_reason=f"{UNDECODABLE}: {exc}",
            )
        return ocr_page(number, frame, self._engines.get(), width=float(width), height=float(height))

    def close(self) -> None:
        if self._image is not None:
            self._image.close()
