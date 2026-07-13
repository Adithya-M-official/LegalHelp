"""
document_pages.py

Support for multi-page / multi-image legal document uploads.

Gemini's multimodal API can accept multiple image parts in a single
request, so "multi-page support" here means: validate each uploaded
page individually (size, format, quality), then hand the full ordered
list of image bytes to ai_logic.py to include as separate parts in one
request. No merging/stitching of images is performed -- Gemini reads
each page as its own image, which preserves quality and avoids extra
image-processing complexity.

Everything here operates on in-memory bytes only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional

from PIL import Image, UnidentifiedImageError

from image_quality import ImageQualityReport, assess_image_quality

logger = logging.getLogger(__name__)

# Hard ceiling on the number of pages accepted per request. Keeps
# request size and Gemini latency predictable, and matches the kind
# of document this app targets (leases, contracts, notices) rather
# than entire books.
MAX_PAGES = 10


@dataclass
class PageValidationResult:
    """Per-page validation/quality outcome."""

    index: int
    filename: str
    image_bytes: bytes
    mime_type: str
    quality_report: ImageQualityReport
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None


def validate_pages(
    uploaded_files: List,
    max_size_mb: float,
    default_mime_type: str,
) -> List[PageValidationResult]:
    """
    Validate and quality-check a list of uploaded page images.

    Args:
        uploaded_files: A list of Streamlit UploadedFile objects (or any
            object exposing `.getvalue()`, `.type`, and `.name`).
        max_size_mb: Maximum accepted size per page, in megabytes.
        default_mime_type: MIME type to use if one can't be determined.

    Returns:
        list[PageValidationResult]: One result per uploaded file, in
        the original order. Files that fail validation have `.error`
        set and should be surfaced to the user rather than sent on to
        Gemini.
    """
    results: List[PageValidationResult] = []

    for index, uploaded_file in enumerate(uploaded_files):
        filename = getattr(uploaded_file, "name", f"page_{index + 1}")
        try:
            raw_bytes = uploaded_file.getvalue()
            size_mb = len(raw_bytes) / (1024 * 1024)

            if size_mb > max_size_mb:
                results.append(
                    PageValidationResult(
                        index=index,
                        filename=filename,
                        image_bytes=raw_bytes,
                        mime_type=default_mime_type,
                        quality_report=ImageQualityReport(),
                        error=(
                            f"'{filename}' is larger than the {max_size_mb} MB "
                            "limit."
                        ),
                    )
                )
                continue

            image = Image.open(BytesIO(raw_bytes))
            image.verify()
            # verify() invalidates the file handle for further use, so
            # re-open for the quality checks below.
            image = Image.open(BytesIO(raw_bytes))

            quality_report = assess_image_quality(image)
            mime_type = getattr(uploaded_file, "type", None) or default_mime_type

            results.append(
                PageValidationResult(
                    index=index,
                    filename=filename,
                    image_bytes=raw_bytes,
                    mime_type=mime_type,
                    quality_report=quality_report,
                )
            )

        except UnidentifiedImageError:
            results.append(
                PageValidationResult(
                    index=index,
                    filename=filename,
                    image_bytes=b"",
                    mime_type=default_mime_type,
                    quality_report=ImageQualityReport(),
                    error=(
                        f"'{filename}' doesn't look like a valid image file."
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error validating page '%s'", filename)
            results.append(
                PageValidationResult(
                    index=index,
                    filename=filename,
                    image_bytes=b"",
                    mime_type=default_mime_type,
                    quality_report=ImageQualityReport(),
                    error=f"Could not process '{filename}': {exc}",
                )
            )

    return results
