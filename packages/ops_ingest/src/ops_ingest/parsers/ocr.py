# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""OCR for pages with no text layer, through Tesseract. Installed with the `ocr` extra."""

from __future__ import annotations

from typing import Protocol


class OcrUnavailableError(RuntimeError):
    """OCR was requested but the engine is not installed. The item fails rather than indexing empty."""


class OcrEngine(Protocol):
    def image_to_text(self, image: object) -> str: ...


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
        text: object = self._tess.image_to_string(image, lang=self._lang)  # pyright: ignore[reportUnknownMemberType]
        return str(text)
