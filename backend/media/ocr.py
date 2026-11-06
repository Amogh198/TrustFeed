"""Read on-screen text with Tesseract. Tesseract is chosen because EasyOCR's weights are pickle files.

Text found in media is untrusted: it is cleaned, kept as data, and never logged or acted on.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from backend.media.config import MediaConfig
from backend.media.models import CheckStatus, OcrCheck, OcrLine

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 40.0
MAX_LINES = 200
MAX_LINE_CHARS = 300
OCR_LIMITATIONS = (
    "Text read from media can be wrong, and may have been placed there to mislead. It is not proof of anything.",
    "Accuracy has not been measured. Stylised, small or moving text is often missed.",
)
NOT_INSTALLED = (
    "Reading text needs the Tesseract program, which isn't installed or wasn't found. Install it, or set "
    "MEDIA_TESSERACT_CMD to where it is."
)
Reader = Callable[[Any, MediaConfig, float], list[tuple[str, float]]]


class OcrUnavailable(Exception):
    """Text can't be read at all. The message is safe to show."""


def clean_line(text: str) -> str:
    return " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())[:MAX_LINE_CHARS]


def _tesseract_lines(image: Any, config: MediaConfig, timeout_s: float) -> list[tuple[str, float]]:
    """Return (text, mean word confidence) per line."""
    try:
        import pytesseract
    except ImportError as exc:
        raise OcrUnavailable("Reading text needs pytesseract, which isn't installed.") from exc
    if config.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = config.tesseract_cmd
    try:
        data = pytesseract.image_to_data(
            image.convert("RGB"),
            lang=config.ocr_languages,
            output_type=pytesseract.Output.DICT,
            timeout=max(1, int(timeout_s)),
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailable(NOT_INSTALLED) from exc
    lines: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
    for index, word in enumerate(data["text"]):
        confidence = float(data["conf"][index])
        if word.strip() and confidence >= 0:
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            lines.setdefault(key, []).append((word, confidence))
    return [
        (" ".join(word for word, _ in words), sum(value for _, value in words) / len(words)) for words in lines.values()
    ]


def _usable(text: str, confidence: float) -> bool:
    return confidence >= MIN_CONFIDENCE and sum(ch.isalnum() for ch in text) >= 2


def read_text(
    frames: Sequence[tuple[float | None, Any]], config: MediaConfig, *, reader: Reader = _tesseract_lines
) -> OcrCheck:
    """Read each (timestamp, image). The same line in consecutive frames is kept once, with when it was last seen."""
    limitations = list(OCR_LIMITATIONS)
    started = time.monotonic()
    found: list[OcrLine] = []
    last_seen: dict[str, OcrLine] = {}
    examined = 0
    for timestamp, image in frames:
        remaining = config.ocr_time_limit_s - (time.monotonic() - started)
        if remaining <= 0:
            limitations.append(f"Stopped at the {config.ocr_time_limit_s:.0f}-second limit, so some frames weren't read.")
            break
        try:
            lines = reader(image, config, remaining)
        except OcrUnavailable as exc:
            return OcrCheck(status=CheckStatus.UNAVAILABLE, limitations=[str(exc)])
        except Exception as exc:  # noqa: BLE001 - one bad frame never stops the rest.
            logger.warning("Text reading failed: %s", type(exc).__name__)
            limitations.append("Text could not be read from part of this media.")
            continue
        examined += 1
        for raw, confidence in lines:
            text = clean_line(raw)
            if not _usable(text, confidence):
                continue
            key = text.casefold()
            if key in last_seen and timestamp is not None:
                last_seen[key].last_seen_s = timestamp
                continue
            if len(found) >= MAX_LINES:
                limitations.append(f"Only the first {MAX_LINES} lines were kept.")
                break
            line = OcrLine(text=text, confidence=round(confidence, 1), timestamp_s=timestamp, last_seen_s=timestamp)
            found.append(line)
            last_seen[key] = line
    if not examined:
        return OcrCheck(status=CheckStatus.UNAVAILABLE, limitations=list(dict.fromkeys(limitations)))
    return OcrCheck(
        status=CheckStatus.COMPLETE, frames_read=examined, lines=found, limitations=list(dict.fromkeys(limitations))
    )
