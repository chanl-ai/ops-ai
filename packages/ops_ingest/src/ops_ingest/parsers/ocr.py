# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""OCR for pages with no text layer, through Tesseract. Installed with the `ocr` extra."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from PIL import Image, ImageFilter, ImageOps


class OcrUnavailableError(RuntimeError):
    """OCR was requested but the engine is not installed. The item fails rather than indexing empty."""


class OcrEngine(Protocol):
    def image_to_text(self, image: object) -> str: ...


@dataclass(frozen=True)
class OcrWord:
    text: str
    # left, top, width, height in the image's pixels
    box: tuple[int, int, int, int]
    confidence: float
    # Tesseract's block, paragraph and line numbers: words sharing them sit on one line
    line: tuple[int, int, int]


class TesseractEngine:
    def __init__(self, lang: str = "eng") -> None:
        try:
            import pytesseract  # pyright: ignore[reportMissingTypeStubs]  # noqa: PLC0415
        except ImportError as exc:
            raise OcrUnavailableError("OCR needs the `ocr` extra: uv sync --extra ocr") from exc
        try:
            pytesseract.get_tesseract_version()  # pyright: ignore[reportUnknownMemberType]
        except pytesseract.TesseractNotFoundError as exc:  # pyright: ignore[reportUnknownMemberType]
            raise OcrUnavailableError("OCR needs the tesseract binary on PATH") from exc
        self._tess = pytesseract
        self._lang = lang

    def image_to_text(self, image: object) -> str:
        text: object = self._tess.image_to_string(self.prepared(image), lang=self._lang)  # pyright: ignore[reportUnknownMemberType]
        return str(text)

    def image_to_words(self, image: object) -> list[OcrWord]:
        """Each recognised word with its box in the given image's pixels, Tesseract's confidence as 0 to 1, and the
        line it sits on, so a reader can score a value by the words under it rather than one factor for every OCR'd
        page. Words are read off the prepared page and their boxes mapped back through its turns, so a box lands where
        the word is printed on the page as scanned, sideways or not."""
        prepared, back = self._prepared(image)
        data = cast(
            dict[str, list[Any]],
            self._tess.image_to_data(  # pyright: ignore[reportUnknownMemberType]
                prepared, lang=self._lang, output_type=self._tess.Output.DICT
            ),
        )
        words: list[OcrWord] = []
        for i, text in enumerate(data["text"]):
            conf = float(data["conf"][i])
            if not str(text).strip() or conf < 0:
                continue
            line = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
            left, top, width, height = (int(data[k][i]) for k in ("left", "top", "width", "height"))
            words.append(OcrWord(str(text), back((left, top, width, height)), round(conf / 100, 3), line))
        return words

    def prepared(self, image: object) -> object:
        """The page as Tesseract reads it best (c-294): turned upright, straightened, despeckled. No contrast step:
        Tesseract's own thresholding read a uniformly faint page at every level tried, down to five grey levels."""
        return self._prepared(image)[0]

    def _prepared(self, image: object) -> tuple[object, Callable[[Box], Box]]:
        """The prepared page, and the map from a box on it back to the same words on the page as given."""
        if not isinstance(image, Image.Image):
            return image, _same
        grey = ImageOps.grayscale(image)
        upright, turn = self._upright(grey)
        angle = skew(upright)
        straight = upright if abs(angle) < MIN_SKEW else _turned(upright, angle)
        turns = [(angle, upright.size, upright.size)] if straight is not upright else []
        if upright is not grey:
            turns.append((-turn, grey.size, upright.size))

        def back(box: Box) -> Box:
            for degrees, source, out in turns:
                box = _unturned(box, degrees, source, out)
            return box

        return _despeckled(straight), back

    def _upright(self, image: Image.Image) -> tuple[Image.Image, int]:
        """A page scanned sideways or upside down, turned by Tesseract's orientation detection (psm 0) when it is sure,
        and the clockwise turn made; a page with too little text for it to judge is left as scanned."""
        try:
            osd = cast(
                dict[str, Any],
                self._tess.image_to_osd(image, output_type=self._tess.Output.DICT),  # pyright: ignore[reportUnknownMemberType]
            )
        except Exception:
            return image, 0
        turn = int(osd.get("rotate") or 0)
        if turn % 360 == 0 or float(osd.get("orientation_conf") or 0) < ORIENTATION_CONFIDENCE:
            return image, 0
        # Tesseract's `rotate` is the clockwise turn that makes the page upright; PIL turns counter-clockwise.
        return image.rotate(-turn, expand=True, fillcolor=255), turn


# left, top, width, height in pixels
Box = tuple[int, int, int, int]


def _same(box: Box) -> Box:
    return box


def _unturned(box: Box, degrees: float, source: tuple[int, int], out: tuple[int, int]) -> Box:
    """A box on an image that PIL turned `degrees` counter-clockwise (from a `source`-sized image to an `out`-sized
    one, centre to centre), as the box around the same pixels before the turn: PIL's own inverse mapping."""
    a = -math.radians(degrees)
    cos, sin = math.cos(a), math.sin(a)
    left, top, width, height = box
    xs: list[float] = []
    ys: list[float] = []
    for x, y in ((left, top), (left + width, top), (left, top + height), (left + width, top + height)):
        dx, dy = x - out[0] / 2, y - out[1] / 2
        xs.append(cos * dx + sin * dy + source[0] / 2)
        ys.append(-sin * dx + cos * dy + source[1] / 2)
    x0, y0 = max(0, math.floor(min(xs))), max(0, math.floor(min(ys)))
    x1, y1 = min(source[0], math.ceil(max(xs))), min(source[1], math.ceil(max(ys)))
    return (x0, y0, x1 - x0, y1 - y0)


# Tesseract's orientation confidence below which a quarter turn is not applied; the skew searched either way, in
# degrees, and the step of the search.
ORIENTATION_CONFIDENCE = 2.0
# The smallest skew corrected. Tesseract reads a page up to about 1.5 degrees off by itself, and turning a
# low-resolution scan softens its characters: on the levy scans made 1.4 degrees off a correction lost a digit
# string Tesseract read without it, while the invoice made 2 degrees off read its due date only once straightened.
MIN_SKEW = 1.75
MAX_SKEW = 5.0
SKEW_STEP = 0.25
# The width the angle search works at: big enough that lines of text stay apart, small enough to be fast.
SEARCH_WIDTH = 800
# A grey darker than this is ink when the angle search looks for lines of text.
INK_LEVEL = 160


def skew(image: Image.Image) -> float:
    """The counter-clockwise turn, in degrees, that straightens a page scanned a little off: the rotation of a reduced
    copy whose rows of text are sharpest (the variance of row darkness is highest when every line of text lies flat)."""
    small = ImageOps.grayscale(image)
    if small.width > SEARCH_WIDTH:
        size = (SEARCH_WIDTH, max(1, round(small.height * SEARCH_WIDTH / small.width)))
        small = small.resize(size)  # pyright: ignore[reportUnknownMemberType]
    # Ink white on black, so the empty corners a rotation leaves count as no ink.
    ink = small.point([255 if v < INK_LEVEL else 0 for v in range(256)])  # pyright: ignore[reportUnknownMemberType]

    def sharpness(angle: float) -> float:
        turned = ink.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=0)
        rows = turned.resize((1, ink.height), Image.Resampling.BOX)  # pyright: ignore[reportUnknownMemberType]
        values = [float(v) for v in rows.tobytes()]
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values)

    steps = round(MAX_SKEW / SKEW_STEP)
    return max((i * SKEW_STEP for i in range(-steps, steps + 1)), key=lambda a: (sharpness(a), -abs(a)))


def straightened(image: Image.Image) -> Image.Image:
    """The page turned back by its skew; a page within MIN_SKEW of straight is returned as it is."""
    angle = skew(image)
    if abs(angle) < MIN_SKEW:
        return image
    return _turned(image, angle)


def _turned(image: Image.Image, angle: float) -> Image.Image:
    return image.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)


def _despeckled(image: object) -> object:
    """Grayscale and a 3 px median filter. Scanner speckle made Tesseract misread characters next to it (a postcode's
    "M8V" as "Mav" on the levy notice scan); a higher resolution or another page mode only moved the misread or added
    noise, while the filter read every field of that scan (triage/c-233/capture.md)."""
    if not isinstance(image, Image.Image):
        return image
    return ImageOps.grayscale(image).filter(ImageFilter.MedianFilter(3))
