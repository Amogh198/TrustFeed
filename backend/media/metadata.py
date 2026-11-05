"""Input validation, image decoding and EXIF extraction."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from backend.media.config import MediaConfig
from backend.media.errors import MediaInputError
from backend.media.models import CheckStatus, MediaType, MetadataCheck

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_BASE_TAGS = {0x010F: "make", 0x0110: "model", 0x0131: "software", 0x0132: "modified_at"}
_EXIF_TAGS = {0x9003: "captured_at", 0x9004: "digitized_at"}
_MAX_FIELD_CHARS = 120

_EDITOR_MARKERS = ("photoshop", "lightroom", "gimp", "snapseed", "picsart", "faceapp")
_GENERATOR_MARKERS = ("stable diffusion", "midjourney", "dall-e", "dall·e", "firefly", "comfyui")
# PNG text chunks commonly written by image-generation tools. Their values may
# contain user prompts, so only the key names are ever inspected.
_GENERATOR_PNG_KEYS = {"parameters", "prompt", "workflow"}
_NON_VIDEO_BRANDS = {b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"avif", b"avis"}


@dataclass(frozen=True)
class InputInfo:
    media_type: MediaType
    container: str
    size_bytes: int
    sha256: str


def sniff_media_type(head: bytes) -> tuple[MediaType, str] | None:
    """Identify a file from its content so a misleading extension has no effect."""
    if head.startswith(b"\xff\xd8\xff"):
        return MediaType.IMAGE, "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaType.IMAGE, "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return MediaType.IMAGE, "webp"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return MediaType.VIDEO, "avi"
    if head[4:8] == b"ftyp" and head[8:12] not in _NON_VIDEO_BRANDS:
        return MediaType.VIDEO, "mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return MediaType.VIDEO, "webm"
    return None


def inspect_input(path: Path, config: MediaConfig) -> InputInfo:
    try:
        if not path.is_file():
            raise MediaInputError("not_found", "The media file was not found.")
        size = path.stat().st_size
        if size == 0:
            raise MediaInputError("empty_file", "The media file is empty.")
        with path.open("rb") as handle:
            head = handle.read(16)
            sniffed = sniff_media_type(head)
            if sniffed is None:
                raise MediaInputError(
                    "unsupported_type",
                    "Unsupported file content. Supported: JPEG, PNG, WebP, MP4, MOV, WebM, AVI.",
                )
            media_type, container = sniffed
            limit = config.max_image_bytes if media_type is MediaType.IMAGE else config.max_video_bytes
            if size > limit:
                raise MediaInputError("too_large", f"The file exceeds the {limit // (1024 * 1024)} MB limit.")
            digest = hashlib.sha256(head)
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise MediaInputError("unreadable", "The media file could not be read.") from exc
    return InputInfo(media_type, container, size, digest.hexdigest())


def _clean(value: object) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = "".join(ch for ch in str(value) if ch.isprintable()).strip()
    return text[:_MAX_FIELD_CHARS] or None


def _exif_fields(image) -> tuple[dict[str, str], bool, bool]:
    exif = image.getexif()
    fields: dict[str, str] = {}
    for tag, name in _BASE_TAGS.items():
        if (cleaned := _clean(exif.get(tag, ""))) is not None:
            fields[name] = cleaned
    sub_ifd = exif.get_ifd(_EXIF_IFD)
    for tag, name in _EXIF_TAGS.items():
        if (cleaned := _clean(sub_ifd.get(tag, ""))) is not None:
            fields[name] = cleaned
    has_gps = bool(exif.get_ifd(_GPS_IFD))
    return fields, has_gps, bool(exif) or bool(sub_ifd)


def _read_metadata(image, width: int, height: int) -> MetadataCheck:
    limitations = ["Metadata can be removed or edited, so it only supports or weakens other evidence."]
    indicators: list[str] = []
    generator_hint = False
    try:
        fields, has_gps, exif_present = _exif_fields(image)
    except Exception:  # Malformed EXIF must not stop the rest of the pipeline.
        fields, has_gps, exif_present = {}, None, None
        limitations.append("EXIF data could not be parsed.")

    software = fields.get("software", "").casefold()
    if any(marker in software for marker in _GENERATOR_MARKERS):
        generator_hint = True
        indicators.append(f"Software tag names an image generator: {fields['software']!r}.")
    elif any(marker in software for marker in _EDITOR_MARKERS):
        indicators.append(
            f"Software tag names an editing tool: {fields['software']!r}. Editing alone does not imply deception."
        )
    if image.format == "PNG" and _GENERATOR_PNG_KEYS & {str(key).casefold() for key in image.info}:
        generator_hint = True
        indicators.append("PNG text chunks use keys commonly written by image-generation tools.")
    if "captured_at" in fields:
        indicators.append(f"EXIF records a capture time of {fields['captured_at']}; this value can be edited.")
    if exif_present is False:
        indicators.append(
            "No EXIF metadata found. This is common after re-encoding or social media upload, "
            "and is not a sign of manipulation by itself."
        )
    return MetadataCheck(
        status=CheckStatus.COMPLETE,
        format=image.format,
        width=width,
        height=height,
        exif_present=exif_present,
        fields=fields,
        has_gps=has_gps,
        generator_hint=generator_hint,
        indicators=indicators,
        limitations=limitations,
    )


def read_image(path: Path, config: MediaConfig):
    """Decode an image and return ``(rgb_image, metadata_check, limitations)``."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    limitations: list[str] = []
    try:
        # Only these decoders run. Others, such as EPS, can start outside programs.
        with Image.open(path, formats=("JPEG", "PNG", "WEBP")) as image:
            width, height = image.size
            if width * height > config.max_image_pixels:
                raise MediaInputError("too_large", f"The image exceeds the {config.max_image_pixels:,} pixel limit.")
            metadata = _read_metadata(image, width, height)
            if getattr(image, "n_frames", 1) > 1:
                limitations.append("Animated image: only the first frame was analyzed.")
            image.load()
            rgb = ImageOps.exif_transpose(image).convert("RGB")
    except Image.DecompressionBombError as exc:
        raise MediaInputError("too_large", "The image has too many pixels to decode safely.") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise MediaInputError("corrupt_media", "The image is corrupt or could not be decoded.") from exc
    return rgb, metadata, limitations
